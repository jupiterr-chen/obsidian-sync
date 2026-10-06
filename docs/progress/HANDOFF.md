# 会话检查点 / HANDOFF

> **2026-10-06终轮验收通过：最终源码9d1b04f（含Codex补齐缺页/质量及claim资料范围）。29探针通过，431回归通过/2跳过，干净源码15项通过。S1–S4/F1–F3开发续验结束，不再下发SF返工，F4仍后置。** [最终报告](SF-ACCEPTANCE-20261006.md)、[发布与正文修复计划](../36-validated-release-and-text-repair.md)。本次未部署、未真实模型调用、未历史重处理/归档；生产仍67c6985r2。发布、真实样本/批次及模型范围/预算须分别授权。下方为历史记录。

> **当前状态（2026-10-06 第五批）：SF01–SF06 六条续验条件全部闭合并推送（db61484），停在"待 Codex 独立续验"**。见[开发报告](SF-DEV-20261006.md)：五份探针全绿（SF 6/6、TQMA 7/7、MA 3/3、AC1 7/7、原 6/6），全回归 426 OK；零生产变更/零模型调用。主题分类不再扩大 C 资料发送范围（文档级过滤）；新提取必须"全可用"才赢得入口（部分损坏不压完整旧稿，仅降级回退）；治理保护全 Vault wikilink/片段引用；JobRunner 拒绝冻结 recipe 不符的 job 且可恢复；批次冻结原子化（中断恢复完整批次）；预算等待退还 attempt 不耗尽故障重试。部署与数据批次均需 Codex 验收 + 用户对具体 commit/范围授权。

> **2026-10-06独立续验0f9cb27：原23探针通过、420回归通过/2跳过，干净源码F1/S4另4项通过。S4/F1代码交付通过；S1/S2/S3/F3原任务组合条件未闭环，按原docs/34补齐SF01–SF06，不扩展范围，F4仍后置。** [续验报告](S1234-ACCEPTANCE-20261006.md)、[原任务书](../34-tqma-followup-taskbook.md)、[续验提示词](../35-tqma-followup-prompt.md)。未部署；现网67c6985r2、旧服务仍停止。生产与数据批次授权边界不变。下方为历史记录。

> **当前状态（2026-10-06 第四批）：S1–S4 执行边界 + F1–F3 已完成并推送（25a89d6），停在"待 Codex 独立续验"**。见[开发报告](S1234-DEV-20261006.md)：TQMA 探针 7/7、MA 3/3、AC1 7/7、原 6/6 全绿，全回归 420 OK；零生产变更/零模型调用。执行范围覆盖 B 领取/partial/C 发送（空范围零调用）；阅读/检索/治理统一有效提取选择（坏新稿不压旧正文，被引用文件必留）；批次成员/recipe 冻结；三个预检 CLI 真正只读（外来库拒绝不初始化）；样本 harness 入 Git 并以合成含数字 PDF 实测。部署与数据批次均需 Codex 验收 + 用户对具体 commit/范围授权。

> **2026-10-06 最新独立验收：fbc24bd的原16反例通过，410回归通过/2跳过。新增边界归并S1模型范围、S2有效入口与引用、S3冻结批次、S4真正只读四组，按功能限制启用；不重做已通过修复/迁移，不停现网。** [验收报告](TQMA-REVIEW-20261006.md)、[集中任务书](../34-tqma-followup-taskbook.md)、[下一位agent提示词](../35-tqma-followup-prompt.md)。样本工具未入Git等列fix清单；本次无生产变更/真实模型调用/历史重处理。生产仍67c6985r2；任何发布均须先Codex验收再获用户对具体commit/范围授权。下方开发声明为历史记录。

> **当前状态（2026-10-06 第三批）：TQ0–TQ4 正文质量防护/工具 + MA01–MA03/C主题 已完成并推送（721dde8→db7b967），停在"待 Codex 独立验收"**。见[开发报告](TQMA-DEV-20261006.md)：三探针全绿（6/6+7/7+3/3）、全回归 410 OK、零生产变更/零模型调用/零历史批量重提取。正文防护已进代码路径（损伤路由/替换不拼接/下游证据过滤/入口状态区分），生产清单与修复批次等待授权窗口。部署（含 50cf6c1 维护版）均需 Codex 验收 + 用户对具体 commit/范围授权。

> **2026-10-06用户追加：正文质量TQ0–TQ4并入现有开发批次并前置于LLM。** [详细任务](../33-text-quality-repair-taskbook.md)、[统一任务](../31-maintenance-and-model-activation.md)、[更新后提示词](../32-model-activation-prompt.md)。只读核对发现当前523项提取中458项为旧stdlib-pdf；需全库质量清单、原生重提取优先、必要页OCR，不强制全库OCR。旧副本只做治理dry-run；生产重处理/归档/部署须另获具体授权。此前链接可打开的验收不代表正文内容正确，历史质量尚未修复。


> **2026-10-06 AC1续验最新结论：50cf6c1模型关闭维护范围限定通过。** [报告](AC1-FOLLOWUP-20261006.md)：原探针6/6、AC1探针7/7、全回归382通过/2跳过；旧库升级阻断解除，可进入维护发布准备，仍须用户授权。B/C启用前集中修MA01–MA03，不阻挡维护范围、不重做迁移。见[双轨任务书](../31-maintenance-and-model-activation.md)与[提示词](../32-model-activation-prompt.md)。未部署、未调用真实模型。下方历史声明不代表最新状态。


> **当前状态（2026-10-06 第二批）：R1–R5 已完成并推送（e58e91b→8cca7de），停在"待 Codex AC1 续验"**。见[开发报告](R12345-DEV-20261006.md)：新探针 7/7、旧探针 6/6、全回归 382 OK、零生产变更/零模型调用。关键集成：旧版库起步+两篇冲突合成报告经标准服务入口（worker --once）到 B/C 页面。部署仍需 Codex 续验通过 + 用户对具体 commit/范围的授权。

> **2026-10-06 AC1独立验收：原Q01–Q05六反例通过；整批发布暂不通过。** [报告](AC1-REVIEW-20261006.md)：基线d58119e，366项回归（364通过、2跳过）；现网仍67c6985r2。旧库升级、B→C有效证据、长文覆盖尚有核心缺口，发布/恢复及D当前选版为同批小修。见[续验任务书](../29-ac1-followup-taskbook.md)、[提示词](../30-ac1-followup-prompt.md)。不重做迁移、不停阅读；仍须Codex验收通过及用户明确授权具体发布。下方为历史记录，不代表最新验收状态。


> **当前状态（2026-10-05 第二批）：N1–N5 已开发完成并推送（c9032a7→9fbf1ab），停在"待 Codex 独立验收（AC1）"**。见[开发报告](N12345-DEV-20261005.md)：探针 6/6 全绿、全回归 364 OK、零生产变更/零模型调用。B/C 为 fake-provider 离线闭环（真实质量待授权）；D 时间语义已实（真实应用未接入）；A 的 N5 断链修复已备但未部署。**部署需：Codex 验收通过 + 用户对该次 commit/范围的明确授权。**

> **2026-10-05 最新独立验收：部分可用，整体未完成。** [验收报告](ABCDE-ACCEPTANCE-20261005.md)：336项回归（334通过、2 skipped）；正文worker运行，服务器/Windows 523链接0断链；B/C缺执行与发布闭环，D历史背景as_of未生效。Q01–Q05按功能修复，不重做迁移/不停阅读。见[任务书](../27-abcde-acceptance-taskbook.md)和[提示词](../28-abcde-next-agent-prompt.md)。后续必须先接收Codex独立验收任务并验收通过，再取得用户明确生产部署授权；开发/self-test/push不授权部署。

以下为历史过程与提交者声明；与最新独立验收冲突时，以最新验收为准。

> **提交者历史声明（2026-10-05，已由上方独立验收修正）：A–E 交付链已上线**，详见[交付报告](ABCDE-DELIVERY-20261005.md)与[readiness log](release-readiness-log.md)。五容器运行（含新 knowledge-worker，间隔 30 分钟增量周期）；缺正文 15→4；阅读入口自动发布并已同步 Windows；228 条分析任务 blocked(model_disabled)；0 新增模型调用。下一步可选：B/C 模型启用（需用户授权 provider/范围/预算）、D 目标应用接入、7 天观察累计。

> **F0 bug fix 已完成（2026-10-04，a2407d1）**，见[docs/26](../26-bugfix-first-taskbook.md)与[readiness log](release-readiness-log.md)。V01–V04 与 CLI snapshot_root 全部修复，探针 ALL-PASS。

> **目标交付链：** [docs/25](../25-target-workflow-delivery.md)：A自动解析与阅读（已上线）→ B单篇LLM分析（管线就绪、模型关闭）→ C知识总结（同）→ D投资框架接入（API+客户端就绪、待真实应用）→ E稳态运维（ops_status/心跳已上线）。

> 2026-10-04 已补 Obsidian `解析正文/开始阅读.md`：512份已有正文及15份缺正文清单，见[阅读交付](TEXT-READING-20261004.md)。本次仅导出已有数据，未启动全文增量worker。

> **基础迁移已完成（2026-10-04）：** 旧三容器停止，新四容器运行；数据、恢复、原文、旧证据、增量三连跑和Windows同步已验证。见[迁移报告](MIGRATION-20261004.md)。第一层小时同步正常；知识自动worker/远程模型/自动候选暂未启用，fix清单后置。不要重做迁移。

> **最新独立复核及用户取舍（2026-10-04，7ded572）：基础迁移优先。** 310 tests OK/2 skip；V01–V04保留为fix清单，关闭/暂缓相应增强功能。迁移独立核验数据、恢复、同步与回滚后可推进，不等待全部增强修复或人工质量标注。见[报告](FIFTH-REVIEW-20261004.md)、[任务书](../23-fifth-review-taskbook.md)、[交接提示词](../24-fifth-review-prompt.md)。旧栈在本次检查时仍运行；以下较早结论为历史记录。

> **最新独立复核：第四轮（2026-10-03，cd3bb5d）NEEDS_CHANGES。** 301 tests OK/2 skip，但U01–U05未闭环，见[结果](FOURTH-REVIEW-20261003.md)、[任务书](../21-cutover-blockers-taskbook.md)、[提示词](../22-cutover-blockers-prompt.md)。用户条件式迁移/停机授权已获得；本次因缺陷和G2证据不足未停旧栈。GLM修改已结束，影子提取仍运行。以下完成声明为历史记录。

> **最新独立复核：第三轮（2026-10-03，源码 cb254df）NEEDS_CHANGES。** 287 tests OK / 2 skipped；T01–T07 共4 P1、3 P2待修复。先读[第三轮报告](THIRD-REVIEW-20261003.md)、[下一步任务书](../19-release-readiness-taskbook.md)与[提示词](../20-release-readiness-prompt.md)。先过G1再做小批影子验收，暂不启动全量重提取或生产切换。以下完成声明为历史记录，以最新独立验收为准。

> **最新独立复核：2026-10-03，基线 4949dcd，NEEDS_CHANGES。** 268 回归 OK（2 skipped），新增反例确认 S01–S10 尚待处理（6 P1 / 4 P2）。此前 R01–R15 全 fixed/RF7 闭环是提交者历史声明，未获本轮独立验收。先读[第二轮报告](RE-REVIEW-20261003.md)、[SR 任务书](../17-second-review-taskbook.md)及[执行提示词](../18-second-review-fix-prompt.md)。真实 NOT_RUN/BLOCKED 不变；本次未操作生产。以下历史记录保留。

更新：2026-10-01（P6 离线部分完成后，本会话收尾）。

## 当前状态

- **M0、P1-P6 离线部分全部完成并验收**，提交已推送 obsidian-sync.git：
  `0f3a19f`(M0) → `2889a12`(P1) → `1fd8d78`(P2) → `9eacef3`(P3) → `240b4dd`(P4) → `c4abc89`(P5) → P6 提交见 git log。
- 测试基线：**202 OK (1 skipped)**（113 第一层回归 + 89 知识层）。
  命令（原生 PowerShell）：`$env:PYTHONPATH="app"; python -m unittest discover -s app/tests`
- 源工程 research-kb 未改动（基线 5442e397）；ResearchVault/ResearchTools 未触碰；无生产服务启动/重启；无真实模型调用；工作树干净。

## 已完成任务（摘要，详见各报告）

| 阶段 | 交付 | 报告 |
|---|---|---|
| M0 | 49 文件复制整合+manifest+根配置合并 | m0-report.md |
| P1 | 知识库存储/不可变快照/幂等同步/抽样与测量工具（ADR0003） | p1-report.md, p1-01-interface-audit.md |
| P2 | 提取器注册表（txt/html/pdf/img）+证据块+质量路由+OCR接口+数值规范化（ADR0004） | p2-report.md |
| P3 | 混合分词 BM25 索引+generation 原子发布+/api/kb/v1+事件流+证据链接（ADR0005） | p3-report.md |
| P4 | provider 抽象（默认关闭）+RRF 混合召回+引用验证分析+用量账本+预算门禁（ADR0006） | p4-report.md |
| P5 | claim/decision 追加式历史+决策冻结+影响分析 proposal+安全写回 | p5-report.md |
| P6 | worker 周期闭环+心跳监控+在线备份/恢复演练+compose 准备+接入示例 | p6-report.md |

## 失败测试 / 已知问题

- 无失败测试。各阶段已知限制见对应报告（标准库 PDF 解析器覆盖、事件保留期未配、rerank 未实现、unsupported_numeric_claims 占位等）。

## 2026-10-04（晚）F0 迁移后 Bug Fix 完成（V01-V04+CLI，探针 ALL-PASS）

- 第五轮 V01-V04 + CLI snapshot_root 全部修复（`a2407d1`，324 tests，探针 8/8）。**生产零改动**：只读审计确认 V03 误填从未发生（生产 528 版本 basis 全 null）、V01 无孤儿预留；新四容器 healthy、旧栈停止。修复代码未部署（随下次发布上线；knowledge-api 的 working_dir 规避继续有效）。
- 下一步：docs/25 的 A 阶段（自动解析/阅读）。F0/一次性导出≠自动解析上线。

## 2026-10-04 第四轮修复完成（U01-U05，探针+服务器实测）

- 第四轮复核 → 全部修复（`6a2e57d`）：旧库迁移在**生产库副本**上实际运行业务通过；三 provider 入口统一 attempt 门禁；legacy NULL 不绑定；claim 导出幂等；影子链封闭（manifest hash/生产路径拒绝/强制禁外发——shadow2 全程 usage_events=0）。
- 310 tests OK；shadow2（seed 20261004）30/30 处理+三连跑幂等+对账 ready 28/review 2/failed 0；shadow1 保留。
- 待人工：shadow2/annotations 30 份金标准（A04/A06/A08/A09）→ NOT_RUN。全量/停机条件见 release-readiness-log。

## 2026-10-03（深夜）第三轮修复 + G1 通过 + 影子验收进行中

- 第三轮复核（T01-T07）→ 全部修复（提交 c99f159 → 552a67b）；**G1 通过**：探针 14/14、301 tests。
- N5 影子小批**已在服务器隔离目录运行**（shadow/state，独立库+快照；快照 61 done 0 failed；提取进行中，OCR 密集约 27s/页）。完成后按 tools/shadow-acceptance/SHADOW-RUNBOOK.md：对账→幂等重跑→人工标注→measure。
- N6 全量 dry-run（只读）完成：新 recipe 需重提取 524 份（14,751 页 / OCR 2,792 页），旧产物全保留；**未启动全量**（待授权）。
- 全量/生产切换前置：影子人工标注（A04/A06/A08/A09 金标准）+ 用户明确授权。

## 2026-10-03（晚）第二轮评审修复完成（S01-S10 全部 fixed，待复验）

- 二轮复核（RE-REVIEW-20261003，基线 4949dcd，NEEDS_CHANGES，S01-S10）→ 全部修复。RED/GREEN 矩阵与隔离启动验收见 `second-remediation-log.md`；提交 01c02d7 → a7640fd → e369d32。
- 最终回归：**287 tests OK (2 skipped)**（二轮基线 268 + 19）。
- 隔离启动验收（S09）：服务器 /tmp 独立目录中 library 显式 serve（/healthz ok，100 文档）、knowledge API（/api/kb/v1/health ok）、worker 一次性闭环（90 版本→86 快照→索引发布）全部实测；生产栈与回填未动。
- 复验入口：以 ≥ e369d32 重跑 re-review-probe-20261003.py + test_second_review*。
- 待用户决定：第四轮全量重提取（采用修复后身份逻辑）；生产切换（CUTOVER）。

## 2026-10-03 独立评审修复完成（R01-R15 全部 fixed，待复验）

- 独立评审（基线 534014a，NEEDS_CHANGES，15 组问题）见 `INDEPENDENT-REVIEW-20261002.md`；修复任务书 `docs/15`。
- RF0-RF6 完成：预算账本/角色装配/快照校验/配置身份/PDF 页序引擎/HTML 偏移/选版 as_of/索引恢复/混合先过滤/固定 URL 快照服务/分页/写回唯一性/影响 outbox/部署可执行/恢复严格化。逐项 RED/GREEN 证据在 `remediation-log.md`，提交 4b90a75 → 6ffb0d6。
- 最终回归：**268 tests OK (2 skipped)**（基线 222 + 46 修复回归）。
- 服务器：两份 compose `docker compose config` 通过；knowledge 镜像 build + 容器内 pypdfium2/RapidOCR/模块冒烟通过；OCR v3 回填未停仍在跑（旧代码进程，完成后重启 worker 采用新逻辑）。
- 真实切换前置：评审方复验 R01-R15 + OCR 回填完成 + 用户明确确认旧栈下线（CUTOVER.md 已可执行）。

## 2026-10-02 真实数据阶段开启（用户已授权）

- **SSH 授权**：`chen@192.168.1.150`（密钥认证可用）；新工程目录 `/vol2/1000/10.Develop/obsidian-sync/`（与 research-kb 同级）已建立：`repo/`（代码，git archive 上传）、`config-knowledge.json`/`config-library.json`（主机路径版）、`state/`（2.2G）。
- **真实源路径**（来自旧工程 RUNBOOK）：reports `/vol2/1000/10.Develop/reports-fetcher/reports`；discord `/vol2/1000/10.Develop/discord_export`；现网 catalog 只读消费。
- **已执行（写入仅限新目录，未触碰任何现有容器/数据）**：
  1. 首次真实 sync：538 文档/528 版本镜像，524 快照任务（4 非 ready 如实跳过）——与旧工程验收记录一致（A01 对账通过）。
  2. 代表性样本 30 份全通过 → 影子全量回填：524/524 快照（18.5s）、提取（97s）、索引 104,723 块/140 万词项/14.3M 字符。
  3. 真实检索验证：两字中文词、英文、代码均可检索。
  4. **真实质量基线**：discord ready 1/review 315/failed 122；reports ready 32/review 43/failed 11；122 份纯扫描件（23%）、19% 页面需 OCR（2792/14751）、220 份 CID 字体（标准库解析器不支持，待 PyMuPDF 级解析器）、343 份 control_characters 标记。
  5. 分层 30 样本测量：23 份测得正文（启发式约 48.3 万 token，全库外推约 8.4M，仅数量级参考），7 份待 OCR。
- **待用户决定/授权**：① 模型配置填写（完整模板 `config/knowledge.example.json`，服务器实际配置只改 FILL-ME 项：base_url/api_key/model，egress_allowed 默认 false）；② OCR 路线已实现开关（`ocr.engine`: local/vision-api/off，默认 local=RapidOCR/PP-OCR）；③ **research-kb 旧容器编排下线需用户明确确认**（已记录为待确认事项，本工程完成全部验收前不动）；④ Vault 写回已授权（待登记生成目录后启用）。
- **2026-10-02 OCR 路线落地（本地引擎默认）**：`ocr.engine` 开关（local/vision-api/off）实现并测试（211 测试 OK）；服务器 venv 装入 rapidocr-onnxruntime + pypdfium2（清华镜像，PEP668 系统禁用 --user 后改 venv）。
- **真实 OCR 冒烟（纯扫描件 discord/1527272124073382069_0，6 页）**：3 页 / 80.5s（约 27s/页），置信度 0.96-0.98，中英混排质量好，质量检查 ready。全量估算：2792 页 ≈ 21 小时 CPU。
- **后台 OCR 回填已启动**（nohup，只写新目录，任务粒度可中断续跑）：日志 `/vol2/1000/10.Develop/obsidian-sync/state/ocr-backfill.log`，查看 `ssh chen@192.168.1.150 'pgrep -f run-extracts'`，停止 `pkill -f "knowledge run-extracts"`。EXTRACT_CONFIG 升 v2 → 全部 524 份产生新提取行（旧行保留，历史证据不变）。
- 完整配置模板：`config/knowledge.example.json`（全部默认值已填，仅 base_url/api_key/model 为 FILL-ME）；服务器实际配置已重写为同样形式。FILL-ME 未填时该 provider 自动视为关闭，不报错。
- **2026-10-02 真实 provider 接入与首次真实分析**：OpenAI 兼容适配器（chat/embedding/vision，urllib）+ 协议测试（218 OK）。
  - chat=GLM-5.3 打通：精确用量可得（含 reasoning_tokens 细分，印证 docs/09 推理计费提醒；小 max_tokens 会被 reasoning 耗尽导致空正文）。
  - embedding 报 429 丙码113 余额不足：coding 套餐端点无 embedding 资源包→ 混合检索保持 keyword 模式（422 按设计），需用户充值/换资源后开启。
  - vision_ocr 已配置 GLM-5.3-Flash 但 egress_allowed=false → 按门禁拒绝测试；待用户翻开开关后验证其图片输入支持。
  - **首次真实分析（A17 首个真实数据点）**：查询毛利率观点，6 个真实证据块→ GLM-5.3 引用全部有效；证据仅为笔记标题清单时模型诚实回答 unknown 拒绝编造（docs/05 要求的行为）；真实用量：输入 26,602 + 输出 852 tokens，已入 usage_events 账本。
- 后台 OCR 回填进度：extract v2 任务 done 568 / pending 479（总 1048，含旧一代），零失败；v2 提取行 44（OCR 慢速段）。
- **2026-10-02 晚：三模型实测与 Vault 写回打通**：
  - vision（GLM-5.3-Flash，egress 已开）：**确认支持图片输入**。真实扫描页对比：flash 21.4s/页、拼写与空格明显更好（本地 "Commodies/Sel-ff" 类错误），成本约 7.5K tokens/页；本地 RapidOCR 56.4s（同时背负 OCR 回填 CPU 竞争，中文两者相当）。结论：批量走本地，疑难页/图表用 flash 复核仍是合理路线（fallback 混合路由待实现）。
  - embedding（opencode.ai zen + deepseek/deepseek-v4.1-flash）：`/embeddings` 返回 **HTTP 403 error 1010**（网关拒绝该端点/模型不可 embedding）—— 需用户确认网关支持的 embedding 模型名或换回智谱 embedding-3；混合检索继续 keyword 模式（按设计 422）。
  - **分析产物 Vault 写回已打通**（零 Syncthing 配置变更）：`export-analysis` CLI → 服务器 `research-kb/vault/自动研究候选/`（新增生成子区，旧渲染器不碰）→ 现有 Syncthing 文件夹对 → Windows `ResearchVault/自动研究候选/` （实测 30 秒内到达，含引用验证与证据链接）。写回带哈希门禁：人工编辑后不被覆盖。注：文件以只读属性同步，标注请复制或改属性，哈希门禁保护两者。
- **2026-10-02 深夜：fallback OCR + 全栈编排 + embedding 关闭**：
  - `ocr.fallback=vision-api` 实现并上线（EXTRACT_CONFIG v3）：本地页置信度 < fallback_min_confidence(0.6) 或空文本时才升级问 flash（每页记录双置信度）；回退失败不伤主流程。后台 v3 全量回填已重启（446 个被取代的 v2 pending 任务已标记 superseded）；至今 fallback 触发 0 次（本地置信度普遍 0.96+）。
  - embedding egress 已改 false（用户决定后续再开）；chat/vision 不变。
  - **`deploy/docker-compose.full.yml`：全栈切换目标编排**（library+syncthing+status-collector+knowledge-worker+knowledge-api，容器名 obsidian-sync-*，资源限制+健康检查，catalog 只读挂载）；**`deploy/CUTOVER.md`：切换手册**——回答“为何现在还写旧目录”（旧栈仍在服役，过渡期搭便车）；切换时迁移 Syncthing 设备身份+文件夹 ID → **Windows 端零改动**；回滚=启动旧栈；旧目录清理是另一次单独授权。旧栈下线仍需用户明确确认 + 真实验收完成。
  - 测试基线 **222 OK**（+3 fallback 路由/门禁）。
- 修复：CLI rebuild-index 分发 bug（真机首跑发现，已修+回归测试，203 测试 OK，提交 f7f0e45）。

## 剩余工作 = 外部条件依赖（合并缺项清单）

1. ~~真实源访问~~ 已解决（2026-10-02）；后续：真实 tokenizer 接入（A05 精确计数）、A10 真实 50 查询基准、A04 人工标注。
2. **生产部署**（compose 已备 `deploy/docker-compose.knowledge.yml`）：A21 性能与 7 天记录、A22 真实恢复演练；旧 research-kb 容器下线待明确确认。
3. **模型供应商+凭据方式+外发范围+预算**：P4 真实适配器（providers.py 预留 + providers.example.json 模板）、A16 成本、A17 分析评测、真实 tokenizer。
4. **OCR 引擎选型**：真实需求数据已测得（122 全扫描件/19% 页面）；本地引擎 vs 多模态 LLM 待用户定。
5. **真实 Vault 写回**：已授权；待在 ResearchVault 登记 `自动研究候选/` 等生成目录后启用（P5-03）。

## 准确续跑起点

- 读本文件 → docs/progress/task-status.md（状态表）→ 对应阶段报告的「BLOCKED/已知限制」节。
- 任何新会话先跑全量测试确认基线，再从上述缺项中已具备的条件切入；无需重做 M0-P6 离线部分。
- 约束提醒：不修改源工程/原始归档；不 force-push；不猜凭据；OCR/LLM 独立 worker；`/api/v1` 行为保持；人工笔记零覆盖。

## 会话执行说明

本会话为普通交互会话，无自动唤醒能力：会话结束后不会后台继续。所有已声明完成的工作均已在本会话内执行、测试并推送；未执行事项均如实标注 NOT_RUN/BLOCKED，无虚构。

## 独立评审接续（2026-10-02）

基线534014a已复核：整体NEEDS_CHANGES。未改业务代码或生产服务；下一执行从docs/15-review-remediation-taskbook.md的RF0开始，提示词在docs/16-review-fix-prompt.md。15组问题及合成证据见INDEPENDENT-REVIEW-20261002.md/review-evidence.json。当前不应执行CUTOVER；源迁移无需重做。原真实验收缺项继续保留，源码修复有独立可执行任务。
