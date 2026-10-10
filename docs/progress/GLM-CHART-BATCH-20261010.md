# GLM 图表批处理执行记录（2026-10-10）

## 当前状态

最新检查点见文末：原 30 项 v2 已结束，30 项真实视觉验收完成；剩余 832 项的 9 批 proposal 分类已在服务器启动，不批准按模型 bbox 激活投影。

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

## 14:34 试点返回完成，确认格式兼容问题

原试点 14:18:14 退出 0：60/60 请求全部有持久结果，24 valid、35 invalid_json_or_schema、1 truncated，无 OOM。累计记录 input_tokens=203800、output_tokens=182057。30 项中 4 项两轮都有效，但区域划分有分歧；其余 26 项至少一轮无有效结构。不能据此宣称图表识别质量通过。

串行诊断于 14:19:16 完成，仅额外 1 次请求；确认诊断回复为完整 Markdown JSON 围栏，去除围栏后 8 个区域通过原有严格 schema 校验。当前只证明这条诊断的失败原因，其余旧失败回复未保存原文，不能声称全部可以离线恢复。

已安排 Luna 对原三文件做最小兼容：只接受完整 JSON 围栏、保留私有原始回复、依据 source/image/text/prompt/recipe 身份复用旧 valid 和可恢复诊断，未知请求不重发；已知无可恢复失败才有界补调用。Codex 独立验证后在独立新目录续跑原 30 项，生产服务及数据不改。已启动禁网 `review-v1` 图片渲染，先核对 4 个两轮有效项，不重复请求这些成功结果。

Codex 已实际查看试点序号 13/16/25/30 的原图及两轮框选：四项均为真实表格或正文加表格，两轮均未分类为 chart。分歧主要是图题/脚注拆分和页脚框；序号 30 第一轮表格框漏到底部两行，不能拿模型 bbox 直接作精确裁切/删除依据。四项结论均为保留全部正文/表格、不创建图表排除投影；带图 hash 的私有复核记录在本地 `runtime/glm-chart-batch-20261010/visual-review-v1.json`。这不是剩余 26 项或全库质量结论。

围栏及续跑工具续修已独立验收：9 项离线回归通过；Codex 完整 run() 的 6 项检查通过（旧成功零请求复用、已知失败仅一次新请求、再次重启零请求、usage 来源区分、结果不激活、数据库不变）。成功缓存与诊断恢复必须重算旧输入/图片/文字/prompt/recipe身份，错误缓存隔离；认证/限流和错模型保持熔断。只接受完整 JSON 围栏，前后散文及不合法区域仍拒绝。下一步用该固定源码在禁网环境实际计算旧60结果可复用数量，再有界续跑；不替换常驻应用。

## 14:44 已验证复用并启动有界续跑

续修固定源码 `dd8180d9c9ff81e2e5a237d84e13400cfd4efb46` 已推送，服务器独立放在 `source-v2/`，原源码和结果都保留。14:43:56 禁网预检退出 0：25 个回复可准确复用（原成功 24 + 诊断恢复 1），35 个已知失败需补发，未知 0，预检真实调用 0。详细身份清单在 `resume-plan-v2.json`。

14:44:47 新容器 `obsidian-sync-glm-chart-pilot-v2-20261010` 已脱离 SSH 启动。身份/镜像/归档 hash 见 `pilot-v2-launch.json`，输出 `pilot-run-v2/`；使用原 `frozen/pilot.json`，固定 4 路并发，本轮最多 35 次物理请求。成功项走复用缓存、不创建新 dispatch；未知结果不得改目录重发。生产服务、数据库和 Vault 保持原样，常驻模型开关没有改变。

后续统计必须区分 `usage_provenance=reused_response` 与 `physical_response`，以 dispatch 配对结果计新增请求；`responses/` 中原始回复只作私有诊断。v2 完成后对其余 26 项真实图像续验，832 个后续候选仍未启动。旧原试点及串行诊断已经结束，不能重启。现有半小时 heartbeat 已更新此恢复分支。

## 15:04 起：v2 完成与 30 项真实视觉验收

v2 于 14:56:12 退出 0，无 OOM。35 个新增 dispatch 全部有结果、在途/未知 0；另复用 25 个回复。合计 59 valid、1 truncated，29 项两轮有效、1 项仅一轮有效；页级比较 4 agreement、25 disagreement、1 invalid。不要按 result 中不存在的 item_id 聚合页数，应以 proposals 的逐项双轮记录对账。截断项为试点序号 26，按既定有界策略保留例外，不追加第三轮。

15:05 在禁网、生产 state 只读容器生成 `review-v2/` 的 30 张原图与双轮框选，退出 0。Codex 实际查看余下 26 张；序号 13/16/25/30 与此前已目视验收的图片 SHA 完全相同，沿用其真实结论。逐项来源图/复核图 hash、判断、限制保存于私有 `visual-review-v2.json`。

真实观察：22 项包含图表（共 58 个图表面板），8 项仅表格/正文，应保留全部文字。8 项包含带数据条或迷你折线的真实表格，不能因含图形而整表屏蔽。本分层试点不是全库随机精度统计，不外推为全库准确率。

两轮分歧常来自图题、脚注、页眉页脚与正文段落拆分。已经发现实际边界风险：11 号第一轮图框混入上一段末行且多图被截短，20 号第一轮图框纳入表格脚注，29 号第二轮漏掉坐标及部分负值柱；多页还存在图题/坐标边缘过紧。两轮 agreement 也不能替代精确字符定位。上述风险纳入 B3 保护清单，不能以模型 bbox 或共识直接排除正文。

验收结论：B2 **仅作为候选分类、有例外保留的流程通过**，允许相同冻结清单剩余 832 项继续，4 并发、每批约 100、同一时间一个 runner；无需改代码或重跑已成功请求。B3 尚未验收，无 confirmed/activate，无生产 DB/Vault/常驻服务变化。批次监督器由 Luna 编制私有 operation helper，Codex 审查/离线验证后启动；不重用旧 OCR/部署监督器。

## 15:17 剩余 832 项已在服务器顺序执行

私有 `run_remaining_batches.py` 已完成审查，SHA256 `736f75b846186530be8a0de04d28ca834903654e4d79ad7607f8359e958a3857`。Luna 合成验证 9 批顺序执行及第 3 批异常停止；Codex 使用真实 `GLMChartRunner.run()` 的 fake provider 产物做 5 项独立集成检查，通过实际 report/cache 配对、已知截断保留、错误 endpoint 拒绝、意外 activation 拒绝、熔断拒绝。没有修改分类应用或常驻服务代码。

服务器 `--plan-only` 通过后，Codex 另行逐对象核对 `remaining/plan.json` 与冻结父清单：832 项分为 `[100,100,100,100,100,100,100,100,32]`，与试点 30 项完全不交叉，内容逐项相同、无重复/遗漏。随后执行一次 `--execute`，监督器已脱离 SSH；不要重新初始化或重跑启动命令。每批前后核查来源当前身份，模型调用使用独立输出目录，至多一个分类容器、4 个在途请求；未知、熔断、非 0 或来源变化停止，不自动重试已知格式/截断例外。

第一批 `obsidian-sync-glm-chart-rem-001-20261010` 于 **15:17:42** 启动，ID `ae162b20bdaf52d1f3595b5286674b89390459dd4ec51db86e977d6543e2a2eb`，以 `remaining/batch-001/launch.json` 为准。15:18:55 快照：第一批 100 项，7 次 dispatch、3 次返回且均 valid、4 次在途，双轮齐备项 0；这不是 7 项已完成。实际挂载 `/state`、`/candidate`、`/run/glm.json`、`/batch` 均只读，仅本批 `/operation` 可写，无 Vault 挂载。

恢复入口：`sequence-status.json`、`sequence-events.jsonl`、`remaining/plan.json`、各批 `launch.json` / `run/cache/` / `batch-result.json`，全部结束时 `sequence-result.json`。`sequence-started.json` 有内部 token，只读聚合元数据，勿全文输出；PID 不作停进程依据。原 pilot/诊断/review 容器均不重启。该私有 helper 和逐项视觉证据在本地同名 runtime 与服务器 operation 保留，不进入 Git。

现有半小时 heartbeat 已更新为本队列分支。检查时普通 worker 运行，library/knowledge API/Syncthing healthy；当前生产仍 `6679872`，既有 8 页投影不变。下一步是只读跟进 9 批候选分类及例外对账，结束后独立进入 B3；本轮不声称全库治理完成。
