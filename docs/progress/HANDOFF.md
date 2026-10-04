# 会话检查点 / HANDOFF

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
