# 任务台账

> **最新独立复核：第四轮（2026-10-03，cd3bb5d）NEEDS_CHANGES。** 301 tests OK/2 skip，但U01–U05未闭环，见[结果](FOURTH-REVIEW-20261003.md)、[任务书](../21-cutover-blockers-taskbook.md)、[提示词](../22-cutover-blockers-prompt.md)。用户条件式迁移/停机授权已获得；本次因缺陷和G2证据不足未停旧栈。GLM修改已结束，影子提取仍运行。以下完成声明为历史记录。

> **最新独立复核：第三轮（2026-10-03，源码 cb254df）NEEDS_CHANGES。** 287 tests OK / 2 skipped；T01–T07 共4 P1、3 P2待修复。先读[第三轮报告](THIRD-REVIEW-20261003.md)、[下一步任务书](../19-release-readiness-taskbook.md)与[提示词](../20-release-readiness-prompt.md)。先过G1再做小批影子验收，暂不启动全量重提取或生产切换。以下完成声明为历史记录，以最新独立验收为准。

> **最新独立复核：2026-10-03，基线 4949dcd，NEEDS_CHANGES。** 268 回归 OK（2 skipped），新增反例确认 S01–S10 尚待处理（6 P1 / 4 P2）。此前 R01–R15 全 fixed/RF7 闭环是提交者历史声明，未获本轮独立验收。先读[第二轮报告](RE-REVIEW-20261003.md)、[SR 任务书](../17-second-review-taskbook.md)及[执行提示词](../18-second-review-fix-prompt.md)。真实 NOT_RUN/BLOCKED 不变；本次未操作生产。以下历史记录保留。

字段：任务ID | 状态（todo/in_progress/blocked/accepted）| 负责人 | 依赖 | 变更commit | 验收报告 | 阻塞条件 | 下一动作。
完成度口径：源码实现 / 离线验证 / 全量数据验收 / 生产部署 四类分开记录。

|任务|状态|负责人|依赖|commit|验收报告|阻塞|下一动作|
|---|---|---|---|---|---|---|---|
|M0 源工程整合|accepted（源码+离线验证）|main-agent|P0|0f3a19f|docs/progress/m0-report.md|无|无，已完成|
|P0 设计基线|accepted|前序会话|无|a26f8f2/7cf9578|docs/10-p0-validation.md|无|无|
|P1-01 library接口核对|accepted（离线审计）|main-agent|M0|2889a12|docs/progress/p1-01-interface-audit.md|真实A01需源访问|已完成|
|P1-02 游标/版本幂等/不可变快照|accepted（源码+离线验证）|main-agent|P1-01|2889a12|docs/progress/p1-report.md|无|已完成|
|P1-03 分层30样本|accepted（工具+合成契约）/真实BLOCKED|main-agent|P1-01|2889a12|docs/progress/p1-report.md|真实源访问|源访问后执行真实抽样与标注|
|P1-04 页数/正文/tokenizer测量|accepted（工具+合成）/真实BLOCKED|main-agent|P1-03|2889a12|docs/progress/p1-report.md|真实源+tokenizer|源与tokenizer具备后真实测量|
|P2-01 PDF文字层与布局位置|accepted（源码+合成）/真实盲测BLOCKED|main-agent|P1-02|1fd8d78|docs/progress/p2-report.md|解析器选型+真实样本|注册真实解析器后实测|
|P2-02 按页质量判断与OCR路由|accepted（接口+合成路由）/真实OCR BLOCKED|main-agent|P2-01|1fd8d78|docs/progress/p2-report.md|本地OCR引擎未选型|引擎选定后注册|
|P2-03 HTML/图片/文本解析|accepted（源码+合成）|main-agent|P1-02|1fd8d78|docs/progress/p2-report.md|无|XBRL适配器P3+|
|P2-04 表格和数值口径|accepted（基线+单测）/A09真实门禁BLOCKED|main-agent|P2-01|1fd8d78|docs/progress/p2-report.md|真实标注样本|样本后迭代|
|P2-05 不可变提取产物、块与配置版本|accepted（源码+合成）|main-agent|P2-01/02/03|1fd8d78|docs/progress/p2-report.md|无|已完成|
|P3-01 中英文词法及筛选|accepted（源码+合成）/A10真实基准NOT_RUN|main-agent|P2-05|9eacef3|docs/progress/p3-report.md|真实语料|真实50查询基准待源访问|
|P3-02 HTTP服务、鉴权、分页、事件|accepted（源码+合成）|main-agent|P3-01|9eacef3|docs/progress/p3-report.md|生产部署|部署后A21性能实测|
|P3-03 影子全量回填与原子发布|accepted（工具）/生产BLOCKED|main-agent|P2/P3-01|9eacef3|docs/progress/p3-report.md|服务器+真实523基线|源访问后执行A14对账|
|P3-04 卡片证据链接集成|accepted（源码+合成，不写Vault）|main-agent|P3-02/03|9eacef3|docs/progress/p3-report.md|真实Vault写回授权|P5/P6决定写回路径|
|P4-01 embedding选型及预算|accepted（抽象+账本+mock）/真实BLOCKED|main-agent|P1-04/P3|240b4dd|docs/progress/p4-report.md|供应商与预算未定|用户给定后接入真实适配器|
|P4-02 混合召回及可选重排|accepted（RRF+缓存）/真实基准NOT_RUN|main-agent|P4-01|240b4dd|docs/progress/p4-report.md|同上|rerank真实评测后决定|
|P4-03 分析、引用验证、成本账本|accepted（源码+mock）/真实评测BLOCKED|main-agent|P4-02|240b4dd|docs/progress/p4-report.md|同上|真实化后执行A17|
|P5-01 claim/decision版本与review|accepted（源码+离线）|main-agent|P4-03|c4abc89|docs/progress/p5-report.md|无|已完成|
|P5-02 更新影响与反证候选|accepted（离线）/A20真实评测BLOCKED|main-agent|P5-01|c4abc89|docs/progress/p5-report.md|真实新旧版本语料|真实化后评测|
|P5-03 Obsidian安全成果写回|accepted（机制+离线）/真实Vault BLOCKED|main-agent|P5-01|c4abc89|docs/progress/p5-report.md|写回路径授权与目录登记|用户登记后启用|
|P6-01 生产调度、监控与资源限制|accepted（源码+离线+compose准备）/A21生产NOT_RUN|main-agent|P3|9a20156|docs/progress/p6-report.md|生产主机|部署后7天记录与性能实测|
|P6-02 备份、恢复及回滚|accepted（工具+离线演练）/A22真实演练BLOCKED|main-agent|P3|9a20156|docs/progress/p6-report.md|同上|生产后真实RPO/RTO演练|
|P6-03 研发与资金应用接入|accepted（接入上下文清单+示例）/真实客户端BLOCKED|main-agent|P3|9a20156|docs/progress/p6-report.md|客户端与生产|接入验收A13/A19|

## 评审修复（2026-10-03，独立评审 R01-R15）

|问题|状态|修复提交|回归|
|---|---|---|---|
|R01 预算/账本|fixed|4b90a75|test_review_regressions.R01BudgetTest|
|R03 provider 装配|fixed|4b90a75|R03ProviderWiringTest|
|R04 快照消费校验|fixed|310cad4|test_review_rf2.R04|
|R02 配置身份|fixed|310cad4|test_review_rf2.R02|
|R05 PDF 页序/引擎|fixed|310cad4|test_review_rf2.R05|
|R06 HTML 偏移|fixed|310cad4|test_review_rf2.R06|
|R08 选版/as_of|fixed（ADR0007）|1686d7d|test_review_rf3.R08|
|R07 索引恢复|fixed|1686d7d|test_review_rf3.R07|
|R09 混合先过滤|fixed|93e8298|test_review_rf4.R09|
|R11 固定 URL/快照|fixed|93e8298|test_review_rf4.R11|
|R12 分页|fixed|93e8298|test_review_rf4.R12|
|R10 写回唯一性|fixed|29590dd|test_review_rf5.R10|
|R15 影响 outbox|fixed|29590dd|test_review_rf5.R15|
|R13 部署可执行|fixed（服务器 compose config + 镜像冒烟通过）|36c84b5..6ffb0d6|test_review_rf6.R13|
|R14 恢复严格化|fixed|36c84b5|test_review_rf6.R14|

受影响的 P1-P6 离线 accepted 状态按任务书重开为 NEEDS_CHANGES → 现 fixed，待独立复验（RF7）。真实 NOT_RUN/BLOCKED 项不变。最终回归 268 OK。

## 第二轮评审修复（2026-10-03，RE-REVIEW-20261003 S01-S10）

|问题|状态|修复提交|回归载体|
|---|---|---|---|
|S01 预算原子性|fixed|01c02d7|test_second_review.S01BudgetAtomicityTest|
|S02 写回覆盖窗口|fixed|a7640fd|S02WritebackAppendOnlyTest|
|S03 public 时间泄漏|fixed|a7640fd|S03PublicAsOfTest|
|S04 快照字节一致性|fixed|a7640fd|S04SnapshotBytesTest|
|S05 OCR 置信度门禁|fixed|a7640fd|S05OcrConfidenceGateTest|
|S06 图片重复 OCR|fixed|a7640fd|S06ImageDuplicateOcrTest|
|S07 outbox 事务间隙|fixed|01c02d7|S07OutboxAtomicTest|
|S08 游标元数据一致性|fixed|a7640fd|S08CursorMetadataTest|
|S09 部署启动/构建/路径|fixed（隔离目录实测启动）|e369d32|test_second_review_s09|
|S10 独立召回/缓存隔离|fixed|a7640fd|S10IndependentRecallTest|

最终回归 287 OK。逐项 RED/GREEN、隔离启动验收记录见 `second-remediation-log.md`。真实 NOT_RUN/BLOCKED 项不变。

## 第三轮评审修复 + 发布准备（2026-10-03，THIRD-REVIEW S/T01-T07）

|问题|状态|修复提交|回归载体|
|---|---|---|---|
|T01 旧库升级|fixed|c99f159|test_third_review.T01（旧 schema fixture）|
|T02 预算状态机|fixed|c99f159/4109655|T02BudgetStateMachineTest|
|T03 版本公开时间|fixed|c99f159/4109655|T03VersionPublicTimeTest|
|T04 元数据纪元|fixed|c99f159|T04MetadataEpochTest|
|T05 漏页/recipe|fixed|c99f159|T05MixedPdfAndRecipeTest|
|T06 召回/缓存|fixed|c99f159|T06FullRecallAndCacheTest|
|T07 幂等候选|fixed|c99f159|T07IdempotentCandidatesTest|

**G1 通过**：探针 14/14 + 301 tests。N5 影子小批进行中（服务器隔离目录）；N6 全量 dry-run 完成（524 重提取/14,751 页/OCR 2,792 页；旧产物全保留）。详见 `release-readiness-log.md`。

## 记录

- 2026-10-01：M0 完成。源基线 commit 5442e397（52 跟踪文件，工作树干净），复制 49 个公开文件（40 字节一致 / 3 行尾规范化 / 6 文档加来源头），合并 3 个根配置，排除 7 类私有内容。源工程与目标工程测试同为 113 OK（1 skipped）。源目录、Vault、ResearchTools 未改动。
- 2026-10-01：P1 完成（离线）。app/knowledge（store/snapshot/sync/jobs/sampling/measure + CLI），ADR0003；134 测试全过（113 回归不变+21 新增）。A01/A04/A05 真实部分 BLOCKED：真实源访问、真实 tokenizer 未具备。
- 2026-10-01：P2 完成（离线）。ADR0004 + extract/quality/tables/schema 模块；提取器注册表（txt/html/pdf/img 标准库实现）；不可变 extractions/blocks 对齐 evidence-block 契约；153 测试全过。真实 A06-A09 盲测/OCR/财务门禁 BLOCKED（解析器选型、OCR 引擎、真实样本未具备）。
- 2026-10-01：P3 完成（离线）。indexing/kbapi/cards + 事件流；/api/kb/v1 全路由与鉴权（ADR0005，独立端口）；影子索引原子发布；171 测试全过。A10 真实基准/A14 生产对账/A21 性能 BLOCKED（真实语料与服务器未具备）。
- 2026-10-01：P4 完成（离线）。ADR0006 + providers/analysis；RRF 混合召回、引用验证、usage_events 账本、预算门禁；185 测试全过。真实 provider/质量/成本 BLOCKED（供应商、凭据、预算未定）。
- 2026-10-01：P5 完成（离线）。memory/writeback：追加式 claim 历史、决策冻结、影响分析 proposal（不自动覆盖）、哈希门禁写回；196 测试全过。真实 Vault 写回与 A20 真实评测 BLOCKED。
- 2026-10-01：P6 离线部分完成。worker（sync→快照→提取→索引→影响分析闭环+心跳）、在线备份/独立目录恢复演练、compose 准备、接入示例；202 测试全过。生产部署/A21/A22 BLOCKED。至此 M0+P1-P6 离线可完成部分全部完成；剩余工作均依赖外部条件（源访问/服务器/模型供应商/写回授权），见 HANDOFF。

## 独立复核追加（2026-10-02，基线534014a）

当前总体NEEDS_CHANGES。M0保真基本通过，222回归OK/2skip；R01-R15重新打开受影响的P1-P6源码验收，原accepted为历史self-review记录，不是独立验收结论。已明确的真实NOT_RUN/BLOCKED仍保留。修复入口为[RF任务书](../15-review-remediation-taskbook.md)，修复任务RF0-RF7当前均todo。

## 第二轮修复台账（独立复核，2026-10-03）

|任务|问题|状态|退出依据|
|---|---|---|---|
|SR0|基线与失败回归|todo（独立探针已提供）|转换为断言式 RED 回归|
|SR1|S01/S07|todo|预算与 outbox 原子性、中断恢复|
|SR2|S04/S05/S06|todo|返回字节、OCR质量、图片幂等|
|SR3|S02|todo|人工内容不覆盖|
|SR4|S03/S08/S10|todo|时间语义、游标、独立召回|
|SR5|S09|todo|服务正确启动、隔离切换演练|
|SR6|全部|todo|独立复验及真实缺项清单|

详见 docs/17；本表覆盖此前 RF7 闭环判断，不改写历史修复提交。

## 发布前与影子验收（第三轮独立复核，2026-10-03）

|任务|范围|状态|进入/退出条件|
|---|---|---|---|
|N0|基线与断言式反例|todo，独立探针已提供|T01–T07目标断言RED|
|N1|旧库升级与异常账本|todo|有数据升级、逐请求成本与故障恢复|
|N2|版本时间、逐页质量、recipe升级|todo|未知不伪造，漏页不ready，新旧产物独立|
|N3|游标、语义召回、缓存、候选幂等|todo|同长度变化、205块、同维provider、三连跑|
|N4/G1|独立复验|未通过|T01–T07及全回归GREEN，契约无虚假声明|
|N5|小批影子验收|待G1；脚本模板可先准备|docs/08真实证据，未运行保留NOT_RUN|
|N6/G2|全量/切换变更包|待影子结果|范围/预算/恢复明确，实际变更单独授权|

## 第四轮独立验收（2026-10-03）

|条目|状态|接续|
|---|---|---|
|U01 旧库账本迁移|OPEN/P1|C1|
|U02 三类provider请求门禁和attempt终态|OPEN/P1|C2|
|U03 旧版本unknown时间|OPEN/P1|C3|
|U04 真实claim导出幂等|OPEN/P2|C4|
|U05 影子身份/外发/范围/标注/对账|OPEN/P1|C5|
|G1/G2|未独立通过|C6及真实验收|
|条件式迁移/停旧栈授权|已获得|条件通过后执行；本轮未停服|
