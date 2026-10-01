# 任务台账

字段：任务ID | 状态（todo/in_progress/blocked/accepted）| 负责人 | 依赖 | 变更commit | 验收报告 | 阻塞条件 | 下一动作。
完成度口径：源码实现 / 离线验证 / 全量数据验收 / 生产部署 四类分开记录。

|任务|状态|负责人|依赖|commit|验收报告|阻塞|下一动作|
|---|---|---|---|---|---|---|---|
|M0 源工程整合|accepted（源码+离线验证）|main-agent|P0|0f3a19f|docs/progress/m0-report.md|无|无，已完成|
|P0 设计基线|accepted|前序会话|无|a26f8f2/7cf9578|docs/10-p0-validation.md|无|无|
|P1-01 library接口核对|accepted（离线审计）|main-agent|M0|见P1提交|docs/progress/p1-01-interface-audit.md|真实A01需源访问|已完成|
|P1-02 游标/版本幂等/不可变快照|accepted（源码+离线验证）|main-agent|P1-01|见P1提交|docs/progress/p1-report.md|无|已完成|
|P1-03 分层30样本|accepted（工具+合成契约）/真实BLOCKED|main-agent|P1-01|见P1提交|docs/progress/p1-report.md|真实源访问|源访问后执行真实抽样与标注|
|P1-04 页数/正文/tokenizer测量|accepted（工具+合成）/真实BLOCKED|main-agent|P1-03|见P1提交|docs/progress/p1-report.md|真实源+tokenizer|源与tokenizer具备后真实测量|
|P2-01 PDF文字层与布局位置|accepted（源码+合成）/真实盲测BLOCKED|main-agent|P1-02|见P2提交|docs/progress/p2-report.md|解析器选型+真实样本|注册真实解析器后实测|
|P2-02 按页质量判断与OCR路由|accepted（接口+合成路由）/真实OCR BLOCKED|main-agent|P2-01|见P2提交|docs/progress/p2-report.md|本地OCR引擎未选型|引擎选定后注册|
|P2-03 HTML/图片/文本解析|accepted（源码+合成）|main-agent|P1-02|见P2提交|docs/progress/p2-report.md|无|XBRL适配器P3+|
|P2-04 表格和数值口径|accepted（基线+单测）/A09真实门禁BLOCKED|main-agent|P2-01|见P2提交|docs/progress/p2-report.md|真实标注样本|样本后迭代|
|P2-05 不可变提取产物、块与配置版本|accepted（源码+合成）|main-agent|P2-01/02/03|见P2提交|docs/progress/p2-report.md|无|已完成|
|P3-01..04 词法检索/API/影子回填/卡片链接|todo|main-agent|P2-05|—|—|生产全量验收需服务器|离线实现先行|
|P4-01..03 embedding/混合检索/分析|todo|main-agent|P3|—|—|供应商/凭据/预算未定|默认关闭，mock协议测试|
|P5-01..03 记忆/影响分析/写回|todo|main-agent|P4|—|—|真实写回授权|离线状态机先行|
|P6-01..03 调度监控/备份恢复/应用接入|todo|main-agent|P3|—|—|生产主机访问|部署配置与演练工具可先行|

## 记录

- 2026-10-01：M0 完成。源基线 commit 5442e397（52 跟踪文件，工作树干净），复制 49 个公开文件（40 字节一致 / 3 行尾规范化 / 6 文档加来源头），合并 3 个根配置，排除 7 类私有内容。源工程与目标工程测试同为 113 OK（1 skipped）。源目录、Vault、ResearchTools 未改动。
- 2026-10-01：P1 完成（离线）。app/knowledge（store/snapshot/sync/jobs/sampling/measure + CLI），ADR0003；134 测试全过（113 回归不变+21 新增）。A01/A04/A05 真实部分 BLOCKED：真实源访问、真实 tokenizer 未具备。
- 2026-10-01：P2 完成（离线）。ADR0004 + extract/quality/tables/schema 模块；提取器注册表（txt/html/pdf/img 标准库实现）；不可变 extractions/blocks 对齐 evidence-block 契约；153 测试全过。真实 A06-A09 盲测/OCR/财务门禁 BLOCKED（解析器选型、OCR 引擎、真实样本未具备）。
