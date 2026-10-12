# 图表治理：只读验收与每小时跟踪任务书

## 1. 本次职责与授权边界（2026-10-12最新）

用户将验收和跟踪交给其他agent：只验证现有数据、进度和服务执行情况，发现问题记录并报告，每小时运行一次。本任务不包含开发、生产修复、批次启动或部署。此前“继续治理、自动接续、可恢复异常主动修复”等授权，不得被本验收agent沿用为写入权限。

**异常时中断的是本轮常规验收、成功判定和放行建议；不得为了“中断排查”停止生产进程或容器。** 先做有界只读排查并通知用户。停服、重启、回滚、修改数据或重新执行批次均须另行交给获得明确授权的执行者。本任务绝不自动执行这些动作。

允许写入的只有本机验收记录：`runtime/readonly-acceptance-watch/`中的脱敏JSON/Markdown，以及本机`docs/progress/READONLY-ACCEPTANCE-LOG.md`的脱敏追加记录。不得改源代码、部署文件、其他任务的检查点、业务正文、审批清单、Vault配置或人工笔记；不得自行git add/commit/push。首次交付这些任务文档的提交不代表以后监控agent有代码提交权限。

## 2. 工作区、入口及交接基线

| 项目 | 固定入口 |
| --- | --- |
| 本地仓库 | `D:\2.Develop\8.Obsidian\obsidian-sync` |
| Windows Vault | `D:\2.Develop\8.Obsidian\ResearchVault` |
| 只读SSH | `chen@192.168.1.150` |
| 服务端根目录 | `/vol2/1000/10.Develop/obsidian-sync` |
| 当前治理operation | `operations/chart-governance-remaining-20261012` |
| 最近已完成批次 | 上述operation下`release-native-01` |
| 合并工具安装记录 | `operations/chart-merged-release-tools-20261012/08fc6fe/installation-result.json` |
| 范围身份 | `operations/glm-chart-batch-20261010/frozen/candidates.json`，862个固定候选 |
| 恢复入口 | 本文及`docs/progress/HANDOFF.md`最新条；旧内容仅供查证 |

最后一次现场只读检查时间为**北京时间2026-10-12 15:50**：最近29页/98图批次已published，接口29 raw/29 projected/98 assets/29 PDF通过；library和knowledge-api健康，worker运行，Syncthing健康，四服务restart_count均为0。生产业务应用仍6679872；合并工具08fc6fe已安装，但下一合并数据批次尚未启动。

截至这一检查点，冻结范围累计**40/862已验证发布，822未完成**；另外8个历史head不在冻结范围，不能计入分母。Windows107/107文件bytes/SHA匹配的实测时间是15:29，不是15:50重新验过。Obsidian真实UI搜索尚未验。

后续118项材料位于`followup-reviews/next-review-01..04/review/index.json`，尚未完成视觉/精确映射验收。19页坐标OCR结果均为partial，只有976精确片段/3026行，不能计为完成。**当前“等待后续验收/执行”是明确状态，不能声称有治理runner在后台处理822项。** 常驻增量worker运行也不代表图表治理批次正在运行。

以上只是带时间的交接基线。每次报告必须重新读取现场；SSH失败不得用基线充当最新结果。发现其他执行者创建了新批次，只能沿有证据的launch/状态引用读取它，不能凭目录修改时间或同名容器猜测当前任务。

## 3. 明确允许与禁止的操作

| 允许的只读检查 | 禁止事项 |
| --- | --- |
| SSH读取已知状态/launch/结果文件，限量读取脱敏错误摘要 | 写入任何服务器文件，包括operation状态、日志、检查点和配置 |
| `docker inspect`仅提取需要的字段；`docker stats --no-stream`；限量过滤日志 | `docker run/exec/start/stop/restart/kill/rm`、compose变更、镜像切换、进程信号 |
| 使用已存在只读接口的GET/HEAD检查；复用既有只读认证，仅在内存中使用 | POST/PUT/PATCH/DELETE；创建analysis任务、执行模型/OCR、重试未知请求 |
| SQLite URI `mode=ro`、`PRAGMA query_only=ON`，按本批ID做有限SELECT | 使用`KnowledgeStore`等可能迁移/写库的业务对象；写SQL、VACUUM、checkpoint、重建索引、全库integrity_check |
| 读取已存在清单，核对固定版本、hash、已生成图片/正文及发布文件 | 执行prepare/checker/merge/sequence/supervise/recover/publish脚本，即使名称含check、dry-run或isolated |
| 把必要元数据下载到本地忽略目录，再计算hash；查看已有审查图 | 生成或改写confirmed/activation审批、manifest、候选边界、原文、正文、索引或Vault设置 |
| 在本机允许目录保存验收证据与问题记录 | 删除/移动/权限修改、WSL或跨shell破坏操作、安装工具、修改服务器调度 |

不输出配置全文、环境变量、Docker完整inspect、请求headers、token、报告标题或正文。错误可能夹带这些内容，应先提取错误代码、类型及可公开的阶段摘要再落盘。不要向其他agent、邮箱或聊天应用发消息；直接在本任务报告用户即可。

## 4. 每次执行流程

每轮独立结束，不用常驻sleep循环冒充定时器。建议普通轮总耗时控制在数分钟内；SSH连接超时10秒、HTTP单次最多10秒、SQLite忙等待最多5秒。失败不能申请扩大权限或安装依赖来绕过只读边界。

### A. 恢复与确定真实执行者

1. 读本文、本地上轮`latest.json`与HANDOFF最新条；没有变化时不重读完整历史、所有报告或代码。
2. 先读当前operation的`progress-latest.json`，再读其实际引用的sequence/supervisor/apply launch与最新stage。记录各文件自己的时间，不用本轮读取时间替代产物时间。
3. 当前已完成29页的证据：`sequence-result.json`、`release-native-01/{supervisor-status.json,apply-launch.json,data-release-production-result.json,server-verification.json,service-final-inspection.json}`。存在新发布时按新的准确引用核查同类证据。
4. 容器ID/名称/镜像以launch和现场inspect互相核对；PID必须现场重查。已退出的旧试验失败容器不属于当前故障。不要只凭running判断正常。
5. `supervisor=frozen_backup_ready`可能只是等待checker；必须结合生产stage判断是否已经应用，不能误报“还没有开始”。没有新launch且后续材料未验收，报告`WAITING_REVIEW`，不要启动任务。

### B. 进度、计数和运行活动

必须分开记录：`材料已生成`、`分类proposal`、`已审查`、`已应用head`、`已发布且服务器核验`、`Windows已核验`、`例外待处理`。阶段之间不能互相替代。

- 分母固定862，按候选/源版本/提取/块/page身份去重；不把资产数、模型调用数或同文档多页当成文档完成数。
- “已完成”需有本范围对应项及发布证据。数据库head存在不能单独作为交付成功，合并器已安装也不算数据发布。
- 比上轮新增数只比较同一范围、同一口径；上次失败或不可达时填`unknown`，不要虚构0增长或减少。
- 活跃任务核查stage变化、持久产物时间、准确进程的CPU累计时间/IO增量、容器退出码及OOMKilled等。`docker stats`是瞬时值；若需判断停滞，可在本轮做一次相隔10～30秒的只读复查，禁止长轮询。
- 网络等待、合法空闲、等待验收或正在索引的任务不能只因CPU低、状态文件旧而判死。只有证据足够时给阶段耗时范围，不把上批14.4分钟索引耗时当所有阶段的硬截止时间。

### C. 服务执行正确性

| 服务/项目 | 检查内容 | 不能据此推断 |
| --- | --- | --- |
| `obsidian-sync-library` | 准确ID/镜像、运行/health、restart_count变化；新发布时原文PDF HEAD | 容器running不代表PDF可达 |
| `obsidian-sync-knowledge-api` | 准确ID/镜像、health；GET `/api/kb/v1/health`和`/ready`的实际字段/状态码 | HTTP200不自动等于索引ready或数据正确 |
| `obsidian-sync-knowledge-worker` | 容器与`state/knowledge-worker.json`的state、阶段、最近成功/错误、实际活动 | idle可能正常；常驻worker不是治理runner |
| `obsidian-sync-syncthing` | 原容器身份/health、可读的连接/错误状态；本地文件核对 | healthy不代表指定文件已到Windows |
| 模型与配置 | 只核对已批准的镜像/配置hash和必要布尔开关；配置不一致记录差异 | 不读取或输出完整凭据/环境变量，不自动改回 |

API服务地址为服务器本机`http://127.0.0.1:8766`，library为`http://192.168.1.150:8765`。证据/图像/原文URL应来自真实现有元数据或文档，不拼造ID。参考`docs/39-knowledge-api-usage.md`；检索POST即使业务语义只读，本监控也不调用。

发布阶段合法冻结写者时，必须有本次准确停止记录和仍活跃的监督器/checker，且与批准阶段对应，才能视为预期暂停。已经published后服务未恢复、无监督器却仍停服，属于异常。服务原本没有Docker health字段时记`not_configured`，不能编造healthy。

### D. 阶段完成后的增量数据验收

只对新完成/证据变化批次进行，避免每小时重复全库验收。已有通过项可复用，但须绑定operation、源码/镜像、manifest/asset集合hash及关键产物hash；变化后原结论失效。

1. 核对输入manifest集合、审批来源及asset字节hash；跨包无重复、版本或提取冲突。只核对现有审批，不生成新审批。
2. 核对真实隔离结果与本批绑定，包含原文保留、两次幂等及回退；结果文件中的passed只是证据的一部分，不把旧批结果套给新批。
3. 通过只读SQL按本批ID核查current/effective身份、源/原始文本hash、head/投影身份和本批发布outbox状态。不得使用会隐式迁移或新建库的业务初始化。SQLite结果有WAL时不可用`immutable=1`忽略WAL；拿不到一致视图就标未验证。
4. 检查API证据原始/投影视图、图像及PDF的实际可达性。返回内容只在内存中核对身份/hash/数量，不输出正文。图表区域、真表格、叙述正文的语义正确性仅凭hash不能判定；未实际视觉核查的项目标`NOT_VERIFIED`，不能自动升级confirmed。
5. 按`server-verification.json → api_verification.published_files`中的相对路径逐一核对Windows文件存在、bytes和SHA256；拒绝绝对路径、`..`、路径逃逸。仅读取，不修同步、不复制正文覆盖Vault、不改权限。区分missing、mismatch、matched。
6. 人工区/历史/原文不变，需有对应基线hash或已有冻结保护证据；没基线就写明不能独立证明。后续合法生成文件变化或人工主动编辑不能直接判为数据破坏，须核对版本/写入时段。
7. 常规时段只抽查最近完成批次少量文件并记录范围；一次完整批次验收必须核完其发布清单。文件一致不等于Obsidian UI搜索验收。
8. 多文件状态读取跨越发布变化时标记`SNAPSHOT_CHANGED`，不要把不同时刻拼成矛盾故障；本轮允许一次短复查。尚未完整完成的结果标`IN_PROGRESS/NOT_VERIFIED`。

## 5. 结论与异常中断规则

| 状态 | 判定及行动 |
| --- | --- |
| `RUNNING_CHECKED` | 有真实活动、阶段符合计划；报告阶段和证据，不宣称完成 |
| `WAITING_REVIEW` | 后续材料/处理未启动或等待执行者；如实报告，不自动补启动 |
| `VERIFIED_BATCH` | 本批服务器与本机可执行核验全部通过；仅本批通过，非全库完成 |
| `NOT_VERIFIED` | SSH/权限/文件不可达，或缺少基线、实际UI等证据；不沿用旧数作新结论 |
| `WATCH` | 比较慢、单次探针失败、同步尚未追平等；一次有界只读复查，再记录实际情况 |
| `INCIDENT_HOLD` | 下列明确异常出现，立即中断本轮常规验收/放行，进入只读排查并通知用户 |

直接进入`INCIDENT_HOLD`的例子：当前准确runner非预期非零退出、OOMKilled、显式failed/stopped_for_review；宣称published却服务未恢复或接口反复失败；确认的审批/原文/资产hash不匹配且不是读取跨阶段或合法版本更新；意外多写者或容器/镜像/配置漂移；超出本862范围的激活；未知请求被重复发送或出现未授权模型外发迹象。

“慢”不自动等于失败。有明确超时配置时核对是否已经超时；没有时，至少组合两个相邻观测的阶段、CPU累计/IO、产物和实际等待原因。连续两轮一小时检查都无进展且确认任务本应运行、无可解释等待，并有活动停滞证据，进入`INCIDENT_HOLD`排查。无法取到活动证据时标`NOT_VERIFIED/WATCH`，不能编造卡死。

发生异常后：

1. 立即停止当前批“通过/完成”的判断，记录发现时间、operation、准确容器身份、阶段、错误类型和影响范围。
2. 只读获取当前launch、相关stage/result、退出状态、服务健康、必要脱敏日志末尾及有限数据库/文件对照；同一故障一次有界排查，建议不超过10分钟。
3. 形成问题单：已证实事实、仍不确定部分、可能原因、已排除项、下一步建议及**需要执行者另行授权的动作**。不提交修复、不重试apply、不改自动化来代替修复。
4. 在当前会话立即报告，不等待下个整点。说明生产是否仍运行、哪些服务受影响，不能声称“已停机”或“已修复”。
5. 下个小时只跟踪同一事件是否变化，避免反复重查整库或生成重复问题单。故障消失后先验证恢复证据再关闭事件；没有证据保持未解决。调度继续，不静默暂停。

即使怀疑数据持续受损，也只能明确建议执行者紧急暂停准确写者；本任务没有发送stop/kill等信号的权限。

## 6. 记录格式与每小时输出

本机记录目录：`runtime/readonly-acceptance-watch/`，进入Git前必须保持忽略。每轮保存不含私有正文的`checks/YYYYMMDD-HHMMSS.json`和同名`.md`，更新本任务自己的`latest.json`；问题按`issues/<稳定问题ID>.md`记录发现/最后观察/状态。不得覆盖其他operation的状态文件。

报告中的“模型调用0”指没有新增GLM/OCR/业务分析请求；承载监控agent本身的推理仍可能消耗其平台额度，不能称为零token成本。

最小记录字段：检查时刻和时区、数据产物时刻、operation/launch身份、各阶段计数、上轮差分及比较基线、退出码/活动证据、服务状态、API核验范围、Windows匹配范围、结论、问题ID、证据路径/hash、未验证项。本轮不可达的字段为null/unknown，不能默认为0或成功。可追加脱敏摘要到`docs/progress/READONLY-ACCEPTANCE-LOG.md`，不自动提交推送。

正常汇报不超过约5行，例如：

```text
北京时间 <时刻>｜结论 <RUNNING_CHECKED/WAITING_REVIEW/...>
冻结范围已验证发布 <n>/862；剩余 <n>；较上次 <增量或无法比较>。
当前 <operation与阶段>；活动证据 <阶段/CPU时间/IO/退出状态>。
服务 <实际状态>；本轮服务器核验 <范围>；Windows <已核范围>。
异常 <无/问题ID与事实>；待验证 <范围>。本轮生产变更0、模型调用0。
```

异常报告优先问题、影响、实际服务状态、证据入口和建议，不为了“五行”省略必要事实。每小时都报告一次，即使未增加完成数。全862只有逐项闭环或有经批准的明确保留处置，且发布/同步要求均核验，才可建议结项；不要为归零把例外标成通过。

## 7. 调度与交接

现有定时任务ID为`glm-research-kb`，每1小时，已改为本文只读职责。只保留一个调度所有者，不新建第二个同范围每小时任务。其他agent接管时应复用此调度；若其平台不能接管，先明确完成旧调度停用/移交，再启用新调度，不假称已经接管。

定时能力由运行平台提供；本任务不授权在生产服务器安装cron/systemd或部署新的监控程序。若其他agent没有调度能力，明确报告限制，不通过无限循环或再次唤醒主模型伪造每小时任务。

本地桌面调度需要电脑开机且应用运行；服务器既有任务是否继续与本地汇报能否执行是两件事。若需要关机后仍每小时验收，应由用户指定可常驻的执行平台接管，不能凭本提示词宣称已经实现。参见[官方定时任务说明](https://learn.chatgpt.com/docs/automations?surface=app)。

交接提示词：[46-readonly-acceptance-agent-prompt.md](46-readonly-acceptance-agent-prompt.md)。
