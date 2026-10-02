# 独立评审结果：NEEDS_CHANGES

评审日期：2026-10-02（用户时区 Asia/Shanghai）。评审基线：`534014a`。范围：迁移源码保真、知识层关键路径、离线测试与部署/恢复方案。本次未访问服务器、未调用真实模型、未执行生产回填或切换；仅新增评审文档和合成证据。

## 结果

- 复跑全套：222 tests，OK，2 skipped，用时39.023秒。通过已有测试不能覆盖下述反例。
- M0：49个导入映射的源Git blob SHA256全部匹配；目标在M0提交`0f3a19f`的46个hash匹配，另外3项（config/.env.example、config/stignore、scripts/install-windows.ps1）是已记录的CRLF/LF规范化，规范化后内容相等。另3个根规则文件为合并处理。因此没有发现迁移代码丢失/篡改证据。
- 15组需修复问题：10组P1、5组P2。离线实现整体尚不能独立验收；不建议按当前CUTOVER进行生产切换。
- 已明确NOT_RUN/BLOCKED的真实标注、Recall、7天运行、供应商embedding不可用等未重复列为缺陷。发现的是可复现代码错误或部署文件自身不可执行的问题。
- 合成反例及输出保留在本地忽略目录`runtime/review-20261002/`；可发布聚合证据见[review-evidence.json](review-evidence.json)。修复任务见[修复任务书](../15-review-remediation-taskbook.md)。

## 需修复问题

### R01 [P1] 预算配置失效，视觉OCR绕过用量与预算闭环

位置：`app/knowledge/__main__.py:183`、`analysis.py:182`、`ocr.py:134`。

模板预算位于顶层budget，serve-kb却读取providers.budget；设置顶层总额度1后实际加载为None。即使直接传入正确Budget，也仅比较已消耗是否超过总额，不预留本次输入：合成实验限额10、已用9，仍调用模型并累计至72，状态done。len(prompt)//4不是中文真实token上界。VisionApiOcr得到usage后直接丢弃，页级调用没有预算门禁/账本；fallback可按页重复产生费用。embedding也未统一受Budget控制。

影响：配置上限不能作为无人值守成本保护。修复需统一chat/embedding/vision预算入口、配置验证、调用前预留、并发原子额度、调用后结算、失败/重试记账和未知usage状态。未配置价格时至少强制token/请求/页预算，不伪报美元成本。

### R02 [P1] OCR有效配置不参与提取任务身份

位置：`app/knowledge/jobs.py:40`、`extract.py:40`。

extract_digest只hash静态EXTRACT_CONFIG，与ocr.engine、DPI、语言、阈值、fallback/provider/model及依赖版本无关。实测off与local+DPI300的digest完全相同。完成后改配置不产生新任务，或重跑时新结果被已有extraction_id吞掉。还在检查has_extraction之前完成提取，重复任务可能再次付费再丢弃结果。

修复：对实际解析/OCR/质量/分块配置和工具模型版本建立不含密钥的确定性配置摘要；任务登记与执行校验一致；昂贵处理前先检查已验证产物。改配置必须新身份，重复配置不能重复模型调用。

### R03 [P2] 主vision-api路由未装配provider

位置：`app/knowledge/jobs.py:224`附近的ocr_engine；`ocr.py:140`之后build_ocr_engine。

JobRunner.ocr_engine只传provider_specs，没有传providers。选择vision-api时构建的VisionApiOcr.chat_provider仍是None，实际调用报未配置；fallback路径反而传了providers。静态及mock参数检查确认。serve-kb另按hasattr遍历选第一个complete对象，只有vision配置时会把vision当普通chat。

修复：显式按角色绑定chat/embedding/vision_ocr；主路由与fallback均校验配置；未启用chat不因vision配置自动启用分析。

### R04 [P1] 已损坏快照仍被提取并作为原哈希证据发布

位置：`app/knowledge/jobs.py:178-190`。

入库快照会校验，但_execute_extract直接读取blob，没有核对实际字节hash和大小。合成实验先登记合法sha，再在本次测试私有目录放入不同字节，提取正常成功，证据仍携带合法原sha而正文为CORRUPTED内容。已绑定快照的_execute_snapshot也直接跳过。

修复：消费快照前验证同一读取内容的hash/大小；异常标记损坏、拒绝生成证据并保留旧已验证版本。物理落位应采用不覆盖的原子创建，补并发冲突及同大小损坏测试。不能把入库时校验视为永久磁盘完整性证明。

### R05 [P1] PDF页序错误，且漏页可标ready

位置：`app/knowledge/extract.py:469`、`:479`、`:547`。

页面按对象编号sorted(objects)枚举，而PDF实际顺序由Pages/Kids决定。合成结构Kids=[9,3]时，输出page1=SECOND、page2=FIRST；同一错误page_index又用于OCR渲染，可能混合两页证据。per_page_chars初始化后从未填充，缺页/稀疏检测失效。合成两页一页可读一页空白，结果status=ready且issues仍含page_2_needs_ocr，块质量也ready。

修复：生产PDF路由采用成熟解析器与真实页树/字体映射，标准库简化器限定为测试/明确降级。填充页级统计并传播OCR失败、低置信度和未处理页面状态；不能只因剩余正文长度够就整文ready。验收包括乱序对象、对象流、Contents数组、中文ToUnicode、多栏、缺页、OCR截断和混合扫描。

### R06 [P2] HTML重复段落定位到第一次出现的位置

位置：`app/knowledge/extract.py:300-308`。

_finalize_blocks通过full_text.find(段落前60字符)求偏移。两段相同文字分别在不同DOM节点时，实测两个locator都为[0,23]，第二段位置应从23开始。前60字符相同但后文不同也会错误。规范化字符流目前没有稳定的完整持久化位置映射。

修复：使用解析时追踪的原位置与明确版本化规范化映射，完整正文与locator一起持久化；重复段落、空白变化、嵌套节点、void标签及SEC隐藏内容有测试。

### R07 [P1] 索引中断重跑会发布空或不完整generation

位置：`app/knowledge/indexing.py:115-120`。

首次构建create_generation提交后、write_postings前崩溃，会残留building。重跑发现generation已存在即activate，没有重新构建或数量验证。已实测：故障注入后重跑ok=true，active blocks=0，搜索命中=0，尽管存在证据块。还可能替换此前健康索引。

修复：区分building/verified/active/retired及完整manifest；只允许验证过的generation激活；从中断点重建或恢复，失败保留旧active。测试必须覆盖每个事务边界及已有健康索引情形。

### R08 [P1] 搜索混入历史提取和未来版本，as_of不满足历史可知语义

位置：`app/knowledge/indexing.py:75-79`、`:136-150`，`store.py`版本时间字段。

build_generation包含所有非failed的历史extraction，没有选择当前源版本/有效提取版本。system as_of只看document.first_seen_at，后来版本也以旧文档首次时间通过；public优先report_date并回退first_seen，不能证明公开时间。反例：文档1月首次出现、10月写入v2，2月system查询仍返回v2；默认查询同时返回v1/v2；available=false后仍有命中。

修复：明确默认/current与历史模式；每个版本保存不可变first_observed/公开时间依据，并按as_of选当时可用源版本和有效提取。区分暂时源失联（可用已验证快照）与明确撤回/撤权（排除/禁止），不能简单available=false全部物理删除。未知公开时间不伪造；索引manifest包含选版及策略版本。

### R09 [P1] 混合检索无关键词命中时绕过筛选

位置：`app/knowledge/analysis.py:77-85`。

无关键词命中时直接从整个active generation选前200块，没有sources/symbols/date/as_of/collections过滤，然后embedding并返回。实测symbols=NO_SUCH_SYMBOL仍返回6块。未来外发范围/权限过滤复用此路径时还会将不允许的正文送到provider。正常有关键词命中时只对词法候选算向量，也不是真正独立语义召回。

修复：用统一受控候选集合先过滤再做任何embedding/召回；语义与词法分别从允许集合召回并融合。embedding缓存身份含provider/model/维度/文本与规范化配置，校验向量数量与维度。当前用户关闭embedding，修复和回归可完全本地mock验证，无需重新启用真实provider。

### R10 [P1] 同秒候选覆盖和检查后覆盖窗口破坏人工保护

位置：`app/knowledge/writeback.py:75-87`。

人工修改目标后，候选名只精确到秒，open(...,'w')会覆写同秒候选。实测第一次候选被人工改成human edits candidate，第二次相同秒导出将它覆盖为candidate2。主文件读取hash与os.replace之间也有用户/Syncthing更新窗口；写回manifest无多进程一致性保护。

修复：候选用唯一身份且独占创建；机器生成文件与人工可编辑文件明确所有权，优先追加不可变候选；若保留覆盖路径需定义能成立的并发协议，普通进程锁不能锁住外部编辑器。补目标/候选/manifest并发与冲突测试；任何失败都保留用户字节。

### R11 [P2] 固定版本链接全部404，且没有可读快照入口

位置：`app/knowledge/kbapi.py:469-471`、document_version及evidence响应。

生成的路径为documents/{source}/{doc_id}/versions/{version_id}，route长度5；dispatcher却要求6并取route[5]。本地真实HTTP请求实测404。即使修正路由，目前该函数只返回元数据JSON，没有不可变快照字节/HTML证据视图；还不能完成“旧原文位置可打开”的使用目标。

修复：统一路由并对API返回URL做真实HTTP回访；补授权的固定快照读取/安全阅读入口，包含页/段落定位与浏览器认证方案，不能只返回指向上游current原文的链接。

### R12 [P2] 搜索分页提前结束

位置：`app/knowledge/kbapi.py:137-153`、indexing.search limit上限。

每页只召回limit+1条，然后按全局offset切片；第二页只能剩1条。实测6条、limit2：第一页2条、第二页1条且next_cursor=null，另3条永远取不到；limit100时底层最多100条也没有下一页。cursor摘要未绑定mode，metadata筛选变动未必换generation。

修复：实现稳定总排序和真实offset/keyset分页，游标绑定mode/筛选/索引与必要元数据版本；完整遍历超过100条不重不漏，切换generation明确409。

### R13 [P1] 部署编排不可解析，切换手册尚不可执行

位置：`deploy/docker-compose.full.yml:105`、`deploy/docker-compose.knowledge.yml:39`、`Dockerfile:1-10`、`deploy/CUTOVER.md:30`。

两份Compose healthcheck把多段双引号字符串写成Python式相邻拼接，YAML解析均报expected ',' or ']';因此无法启动。Dockerfile沿用python slim，仅COPY，没有安装实际回填使用的PDF渲染/OCR/模型依赖，切换容器将丢失当前宿主机能力。CUTOVER以字符串OLD_CATALOG/NEW_CATALOG连接SQLite，会在当前目录新建占位空库而非备份实际目录；full Compose从deploy/config取配置，另一Compose从../config，环境文件解析位置不统一。手册没有处理当前独立回填进程的停写一致性，也没有对切换后的新写入做回滚对账。

修复：统一部署根/配置路径、显式env-file、可复现知识镜像与依赖/模型版本；两份Compose先config验证再容器冒烟；用参数验证的只读源+在线备份代替占位；切换前冻结所有写者，验证快照、Vault和Syncthing身份；回滚纳入切换后写入，禁止无依据声称零丢失。仅制作和演练方案，不在本修复授权中切换生产。

### R14 [P1] 恢复演练缺快照仍返回成功

位置：`scripts/backup-knowledge.py:135-158`、`deploy/README.md:15`。

drill在未提供/不存在snapshots根时记录skipped，但ok将含skipped的问题排除，退出0。合成备份有1个blob记录、没有原文，结果ok=true、blobs_verified=0。部署示例又让drill使用生产state/snapshots，而非备份输出的blobs目录，会掩盖备份包原文缺失。

修复：按备份报告关联独立blob集合；引用存在但原文未验证必须失败。显式database-only模式只能宣称部分恢复，不能通过A22。脱离生产路径验证全部引用、计数/完整性和应用读取，再记录RPO/RTO。

### R15 [P2] 更新影响任务可能永久漏掉

位置：`app/knowledge/worker.py:78-88`、sync._commit_document。

有新增版本时，只选synced_at=max的一批且LIMIT25；synced_at是每个文档逐次更新的对账时间，并不代表“本次新增集合”。跨秒对账会遗漏早先新版本，超过25版本无续传；下轮new_versions=0也不会补处理。sync完成后worker崩溃同样会丢失后续影响分析。

修复：source-version事件与待处理影响任务在持久事务/outbox中绑定，使用消费游标/幂等键，分页直至清空；不能依赖max时间戳。测试>25版本、跨秒、同步后崩溃和无变化再启动。

## 方案与迁移改进（不冒充已复现缺陷）

1. 继续保留“一仓库、library与knowledge分服务”的选择；迁移代码基础可以复用，不建议重做第一层。
2. 生产PDF应选成熟引擎，复杂表格保留单元格/表头/单位/期间；当前tables.py是独立规范化工具，尚不等于财报结构化抽取流水线。A09保持待验，生成式模型不能补造财务事实。
3. 引用验证拆为引用存在、引文一致、事实支持三种状态；没有引用或unsupported_numeric_claims未运行时返回not_checked，不把空数组解释为已通过数值核验。这是现有已知限制的产品输出改进。
4. 索引、OCR、模型、质量、规范化和embedding缓存都使用统一派生配置清单；数据变更/处理配置变更分离，按需重建，保留旧引用。
5. 默认检索当前有效内容，历史证据通过显式时间模式读取；研发/投资调用存查询、筛选、源版本、提取版本和模型信息，防止历史研究使用后来材料。
6. 迁移manifest区分源Git blob hash、规范化目标blob hash与工作树字节hash，避免把换行转换误报为源改动；不需要重复制旧工程。
7. 部署凭据继续留私有配置，公开进度文档尽量用配置键和逻辑路径。此评审不确认GitHub仓库可见性，内网文档不应被当作可公开模板。
8. 旧报告日期与当前客户端日期有先后不一致，后续台账以实际commit、执行时间和报告版本对齐，不靠“完成”文字确定验收状态。

## 结论的适用范围

迁移保真基本通过；现有测试复跑通过；新增知识层关键数据正确性、计费控制、并发写回与部署恢复存在上述问题，整体NEEDS_CHANGES。服务端真实运行状态没有复核，本次不声称已经停用/修复线上行为。修复完成后按任务书独立复验，再补已知真实验收门禁。
