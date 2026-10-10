# GLM 图表批处理执行记录（2026-10-10）

## 当前状态

北京时间 14:03：固定工具源码 `34edf468d9aaba55e0fe652f3ab9cfd2bc10954d` 已推送，30 项真实 GLM 试点已在服务器启动。Luna 离线 5 项测试由 Codex 复跑通过；Codex 另 6 项独立反例通过。用户已确认本方案，明确 GLM 额度充足；任务边界见 [任务书](../43-glm-chart-batch-taskbook.md) 和 AGENTS.md 首部。

独立 operation：`/vol2/1000/10.Develop/obsidian-sync/operations/glm-chart-batch-20261010/`。恢复时先读 `preparation.json`、`freeze-launch.json`、`pilot-launch.json` 和 `pilot-run/`；不重复启动容器或请求。没有改生产数据库、Vault、配置或常驻服务。

14:02 禁网冻结退出 0：862 个候选全部通过当前有效版本、原文/快照 hash 和投影 head 核对，跳过 0。试点 30 个唯一候选来自 30 份不同文档，native/OCR/unknown 各 10，包含 1 张 PNG；其余为 PDF 页。`frozen/candidates.json` 和 `frozen/pilot.json` 保留完整私有身份。

14:03:10 启动独立容器 `obsidian-sync-glm-chart-pilot-20261010`，身份以 `pilot-launch.json` 为准。使用既有依赖镜像 `a3bab76c9e34`，候选源码另行只读挂载；state/snapshots 只读、现有 secret 只读、operation 可写。两轮、4 路并发，最多 60 次物理请求；没有生产投影写入。服务器进程脱离 SSH，本机关机不影响执行。

沿用现有 `glm-research-kb` heartbeat，已更新为“GLM图表批处理与验收”，每半小时简报并续验；旧发布/OCR流程不再执行。真实模型结果、双轮分歧和视觉验收状态以本记录后续检查点为准。Codex 本地自动跟进仍需要本机应用运行；回来后可按服务器检查点继续。

## 输入与执行边界

- 盘点时刻 2026-10-10 13:14，862 候选块、159 文档版本。209 原生、457 OCR、196 unknown；unknown 中有 1 个图片。候选不等于错误。
- 先核对当前有效 extraction、已有投影 head、原文和快照 hash，再冻结输入；变化项单独列原因，不偷偷替换或静默消失。
- 试点 30 项，三种来源各 10 项，尽量分散文档并纳入图片。两轮独立观察，仅返回区域类别/bbox/疑点。模型共识仍是 proposal。
- 固定既有 GLM-5.3-Flash 与 `https://open.bigmodel.cn/api/anthropic/v1/messages`，4 路并发。已只读证实现有配置的 model/endpoint 匹配且 api_key 存在，没有输出或复制凭据。
- 新工具使用已部署镜像的依赖，候选源码单独只读挂载；生产 state/snapshots 只读，无 Vault 写入。不得启动新常驻 worker 或重启旧 OCR。
- 已 dispatch 无结果的请求进入未知队列，不自动重复发送；只有验收通过后继续相同冻结范围。

## 验收与未完成

Luna 负责新的 `chart_batch.py`、独立 CLI 和 fake transport 测试。Codex 负责独立反例、固定源码、30 页真实结果和原图复核。独立 6 项已验证：旧正文 hash、过期版本、已有 head 拦截；调用前外发门禁；完整 run 的只读连接与重启缓存；并发重复页仅发一次物理请求。源码审查还核对固定 endpoint/model、禁代理和重定向、两轮输入独立、JSON 坐标校验、无 activate/生产写入。当前尚无本批真实分类质量结论，不以离线通过替代视觉验收。

后续仍需原生字符精确映射、OCR 区域定位例外处理、确认投影、按批索引/发布与 Windows 验证。既有小批的 8 页/26 图像已上线，不代表 862 候选全部治理完成；真实表格和正文必须保留。保护 docs/37 用户修改和所有源证据。

## 14:07 首批回复与格式诊断

14:06:29 只读快照：已 dispatch 15 次，收到 11 个回复，其中 2 个通过结构校验、9 个 `invalid_json_or_schema`；4 个仍在途，无 HTTP 错误或熔断。这是模型输出结构问题的信号，尚不能判断真实图表识别质量；原文及生产数据没有改变。

当前 runner 对格式失败只保存输出 hash，无法从旧失败记录恢复原始回复。已安排一个独立诊断：`supervise_diagnostic.py` 等准确试点容器退出 0 后，仅选同一 30 项中一条已知格式失败请求，额外调用一次并将原始回复保存在私有 `diagnostic-one/raw-response.json`，对外只输出格式/校验元数据。它与原 4 路试点串行，不重试未知 dispatch，不重启现有容器。恢复先看 `diagnostic-supervisor-launch.json`、`diagnostic-supervisor-status.json`、`diagnostic-launch.json`、`diagnostic-one/diagnosis.json`；禁止盲目重新排队。

需先根据真实诊断定位包装/schema问题，再决定有界兼容和已知失败项续跑；成功回复与旧证据保留。剩余 832 项尚未启动，不能因用户额度充足就跳过试点质量验收。
