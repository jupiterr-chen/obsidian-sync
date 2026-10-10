# 图表治理运行手册

适用：docs/41 的图表治理交付。**2026-10-10 固定源码 `6679872` 已独立验收，用户随后明确授权部署及后续任务，正在按本手册执行。** 当前真实阶段、备份及结果见 [生产执行记录](progress/CHART-PRODUCTION-20261010.md)。本次许可不重复询问；以后的新代码仍须固定 commit 独立验收和对应生产授权，不能复用旧 OCR 授权。递归移动/删除仍需对准确绝对路径单独批准。

## 数据与使用方式

原始 `blocks.text`、原始 PDF 和历史证据继续保留。新增 `content_projections` 保存不可变 manifest 和派生正文，`content_projection_heads` 指向当前版本，事件表记录切换与回退。数据库 schema 升到 3，已有数据不回填改写。

所有默认事实消费走 `consumer_blocks`：关键词索引及结果、向量生成/缓存/召回、通用分析（包括自定义 retriever）、单篇分析、公司/主题总结的正文与分析证据、投资背景包引用。向量缓存按受影响块的 projection_id 分开，避免全库重新调用 embedding。没有新增独立 rerank 服务；现有 hybrid 融合排序只接收通过门禁的候选。

历史分析 run、claim 修订、summary 修订的失效单独记录。旧版本仍能审计，新 claim 修订引用正确投影后可以重新使用；不自动调用模型重算。正在生成期间证据变化的结果不能发布成有效结论。

分析页的引用正文按生成该分析时绑定的 `projection_id` 读取，之后的切换或回退不会悄悄替换证据。找不到该投影时停止发布，不回落原始碎片。页面同时显示可复制的知识库证据路径（带投影参数），经已认证的知识库客户端读取；library 的原文服务地址不能拼接知识库 API 路由，见 [API 使用说明](39-knowledge-api-usage.md)。历史 raw 引用继续保留审计。

引用仅到文档/提取、没有准确 block 和投影身份的 claim，在该范围包含已投影或暂缓候选时不能进入当前总结或背景包；需补齐精确证据引用。开启候选暂缓后，含未确认候选页的既有单篇分析也暂缓进入总结，即使其最终引用只列出了另一页。关闭暂缓可恢复由该开关造成的消费限制，历史原始数据不被删除。

图表阅读页使用新的不可变文件名 `…-readable-chart-<revision>.md`，当前目录指向它；旧阅读页和人工编辑不被覆盖。图像使用 SHA-256 文件名，从数据库旁的 `chart-assets/` 复制到生成目录 `解析正文/图表资产/`。文件存在但 hash 不符时停止，不覆盖。图题按原文呈现，说明明确“未估算数值”；本批未实现自动图意推理或表格数值校验。

## 区域清单契约

每个 manifest 对应一个已有 block，包含：

- `policy: chart-content-v1`、`review_state: confirmed`、`reviewer`。
- `source/doc_id/version_id/extraction_id/block_id/snapshot_sha256/text_sha256`。
- `page`：从 1 起的物理页；`coordinate_system: normalized-top-left`。
- `mapping_method`：原生字符精确映射，或经过原图核对的准确文本范围。
- `regions`：独立 id、`kind`（chart/table/narrative/navigation/unknown）、`bbox`；原生映射可用较小的 `text_bbox` 分开图像裁切与文本区域。
- `spans`：Python Unicode 字符下标 `[start,end)`、该子串 SHA-256、keep/exclude、role。不能用 UTF-8 字节下标。exclude 只允许 confirmed chart 的 axis/legend/unassigned_value；不能覆盖 keep 范围或彼此重叠。
- 图表必须有原文中存在的 `caption` 以及 `asset.name/sha256`，名称严格为 `<sha256>.png`。

生产清单必须对数据库原始字符串计算 SHA 和区间，不能对经过 Windows 文本文件默认换行转换的副本直接计算。若需要导出文本，使用 UTF-8 字节写入或显式保持换行，并在进入隔离发布前只读复核数据库 hash。2026-10-10 本批续接使用 `manifests-v2/`：仅修正已证明等价的换行字节绑定，原区间下标、图像和文字内容不变；详细证明及新检查点见生产记录。

原生映射逐字核对去空白后的**完整**文字层，再用每个字符 bbox 匹配已确认区域；不同文字层、扫描 PDF、缺字、歧义字符均拒绝猜测。未归属字符保留。扫描页没有空间映射时，必须先看原图确认文本范围；多个子图被 OCR 交错时，可记录整体图组及独立子图资产，不假装已恢复每个数字的系列关系。

图表目录、真正的数据表可使用 all-keep manifest。这也用于解除候选误报；不能通过“数字多”直接删表。

## 命令（隔离副本先运行）

运行时设 `PYTHONPATH=app`。下列路径为调用者准备的隔离 DB、源 PDF 和私有 manifest；不要照抄到生产。清单、正文、图像和数据库存放 `runtime/` 或私有 operation，不提交 Git。

```text
python -m knowledge.chart_governance scan --db <isolated-db>
python -m knowledge.chart_governance prepare --spec <reviewed-spec.json> --pdf <source.pdf> --assets <db-directory>/chart-assets --output <new-manifest.json>
python -m knowledge.chart_governance prepare --spec <reviewed-boxes.json> --pdf <source.pdf> --db <isolated-db> --native-mapping --assets <db-directory>/chart-assets --output <new-manifest.json>
python -m knowledge.chart_governance plan --db <isolated-db> --manifest <manifest.json>
python -m knowledge.chart_governance activate --db <isolated-db> --manifest <manifest.json>
```

`scan` 是线索，不是自动确认。`prepare` 只写新资产/新清单，校验源 PDF SHA，拒绝覆盖不同内容的输出。`plan` 和没有 `--apply` 的 `activate` 使用 SQLite `mode=ro` + `query_only`，不初始化数据库、不迁移 schema、不改索引。plan 检查身份/范围；资产存在、PNG 格式与 hash 在 activate 时再检查。

显式应用需要 plan 返回的 `expected_revision`，第一次无投影时为空字符串：

```text
python -m knowledge.chart_governance activate --db <isolated-db> --manifest <manifest.json> --apply --expected-revision <exact-value-from-plan>
python -m knowledge.chart_governance report --db <isolated-db> --reading-dir <isolated-vault>/解析正文
python -m knowledge.chart_governance rollback --db <isolated-db> --block-id <block-id> --expected-projection <projection-id>
python -m knowledge.chart_governance rollback --db <isolated-db> --block-id <block-id> --expected-projection <projection-id> --apply
```

激活/回退事务同时记录历史、失效依赖和正文发布 outbox。随后构建派生索引；标准 worker 的 publisher 消费正文发布。崩溃后可重跑索引与消费 pending outbox。回退只改派生指针，不删除原文、资产、历史投影或笔记。索引切换完成前，查询仍会对当前投影过滤，不能通过旧关键词/向量缓存送出已隔离内容。

若指针事务已提交、随后索引构建失败，先用只读 `report` 核对当前 `content_revision` 和切换记录，再在同一隔离库执行：

```text
python -m knowledge.chart_governance reindex --db <same-isolated-db>
```

`reindex` 是会写派生索引的显式恢复命令，可重复运行；不是 dry-run，不重新执行投影切换。原 `rollback --apply` 保持严格的当前投影比较，不能在指针已经回退后盲目重放。生产上的恢复同样只能在已批准的发布窗口及准确数据库范围内执行。

生产切换窗口须暂停准确的知识层/模型消费者写者，避免批次中途改投影；普通资料接入可继续。不要并发执行多个治理 CLI。原先进行中的 partial 分析标记失效后不会继续复用旧 section；授权重算时使用新分析任务身份，不能手改旧任务状态续跑。

## API

沿用 `research.read` 权限及原认证方式。

- 检索返回 `projection_id`、`chart_assets`，证据 URL 绑定投影。
- `GET /api/kb/v1/evidence/<block>?projection=<cp-id>` 返回该投影的 `evidence.text`、图表资产和原文入口。回退后历史 cp-id 仍可访问。
- 不带 `projection` 的旧证据 URL 保持原始文本协议；同时提供 `default_projection` 供客户端获知当前可用正文。事实型新客户端应使用检索/背景包给出的投影链接，不能自行丢掉参数。
- `GET /api/kb/v1/evidence/<block>/charts/<sha>.png?projection=<cp-id>` 返回此证据版本登记的 PNG，校验 hash；未授权、错引用或损坏文件不返回图片。
- 背景包携带 `content_revision`，只引用通过门禁的正文；历史来源的时间过滤仍执行，同时应用当前安全策略，不能将其宣称为过去某天完全未经后续修订的系统快照。

## 新增文件防复发

生产默认不开启候选暂缓。经验收及配置授权后可加入：

```json
{"chart_governance":{"enabled":true,"hold_candidates":true,"scan_limit":500}}
```

worker 有界扫描进入 review 队列；消费入口还会同步检查未扫描的新块，因此不依赖扫描恰好跑到该页。明确的已确认投影优先使用；尚未确认且满足候选规则的页面暂缓进入事实型检索/模型，原始证据与阅读材料保留。all-keep 确认可释放真正的表格；关闭配置会解除此暂缓策略。

这是保守的候选暂缓，**会暂时影响混合页/表格召回，规则也可能漏掉图表**。它不是所有新增图表自动理解完成的承诺。扩展处理先做区域确认；未知区域不自动改写，不能为了消除待处理数量把规则候选统一确认。

## 生产与 Obsidian 收尾门槛

1. 固定源码独立验收：运行新反例、全回归、真实 8 页 + 追加 2 页；验证 API 图片访问、旧证据和回退。
2. 明确发布 commit、模型仍关闭、小批清单和资产清单，取得具体发布/切换授权；一致性备份并隔离恢复验证。
3. 重新核对当时的活动索引、源 hash、写者、新人工内容。先在已确认小批启用、发布、Windows 对账，再逐批扩展；本轮 178 份候选不能直接整体激活。
4. 对旧副本生成准确路径及 hash 的操作清单。登记 hash 不符、未知所有者、人工链接的文件保留。归档到 Vault 外或设置 Obsidian 搜索排除，必须分别取得适用授权并验证实际 Obsidian 默认搜索；不能用折叠、提示文字或改索引目录冒充搜索隔离。
5. API 默认检索和 Obsidian 全库搜索是两个独立验收面。旧副本还在且未排除时，Obsidian 仍可能搜到碎片；本地开发通过不代表这一步完成。
6. 新增候选暂缓开关单独小批确认误报/漏报影响，观察正常增量；恢复记录中列出未确认区域、待重算分析和人工冲突。

没有任何命令在本轮递归删除、移动或改权限；未调用真实模型。真正的图表语义分析、精确数值/单位/期间结构化及模型重算需另按具体范围和质量标准开展。
