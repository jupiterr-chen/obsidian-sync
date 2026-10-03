# 任务台账

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
