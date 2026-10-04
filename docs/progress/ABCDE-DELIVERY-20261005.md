# A–E 交付链上线（2026-10-04/05）

依据 [docs/25](../25-target-workflow-delivery.md) 的交付次序 F0→A→B→C→D（E 并行），F0 之后本轮完成 A–E 的实现、部署与生产验证。基线 `a2407d1`（F0）；本批最终提交 `5b3fb75`。回归 **334 tests OK（2 skipped）**（F0 后为 324）。

## 部署形态

- 服务器五容器全部运行（compose 项目 `obsidian-sync`，release `releases/67c6985r2`）：library / syncthing（镜像保持 pinned sha256:82828dde…）/ status-collector / **knowledge-api** / **knowledge-worker（新）**。
- 镜像 `obsidian-sync:67c6985r2` 由 `Dockerfile.knowledge` 构建（pypdfium2 5.13.0 / rapidocr-onnxruntime 1.4.4 / Pillow 12.3.0，与迁移 venv 版本逐项一致 → recipe 摘要一致，不产生降级提取身份）。
- worker 配置新增 `vault_dir=/vault`、`public_base_url=http://192.168.1.150:8765`；间隔 1800s；资源 1.5 CPU / 1GB；catalog/archive/discord 只读挂载。API 保持 127.0.0.1:8766 loopback。
- 部署事故与修复（如实记录）：① 首次 compose 生成把 syncthing 的 pinned 镜像误写为应用镜像 → syncthing 崩溃循环 9 次，已恢复 pinned 镜像并健康；② 首个 worker 周期在阅读发布段 SELECT 不存在的 `jobs.extraction_id` 列崩溃 → 改为对账式入队并加周期内回归；③ 派生索引页受 S02 只写一次规则冻结 → 增加 `refreshable` 刷新路径（见下）。三者均已有回归测试。

## A：新增研报到 Obsidian（已上线，无生成式 LLM）

- **A1 增量**：`snapshots_missing_extract_jobs(new_only=True)`——只在任何 digest 下都没有提取作业的快照才入队；recipe 变更不隐式重排历史（回归证明）；历史重提取仍需显式 `historical=True`（保持未授权不跑）。worker 强制注册 extract 阶段；双周期幂等（回归+生产：第二周期 processed 0）。
- **A2 有界修复**：`repair.py` 队列针对当前版本缺正文/空正文/失败（生产实测 20 项：7 discord 图帖 + 13 报告 PDF），每周期注册 ≤10、先注册后提取。**生产结果：缺正文 15 → 4**。剩余 4 份中至少 1 份（reports/af1746654c423875a9b8）为快照缺失（原始文件不在归档），属诚实失败并计入 `failed_extractions_24h`，非静默丢失。
- **A3 自动阅读发布**：`publish_outbox` + `ReadingPublisher`。生产已收敛：**526 条消费、0 待处理、盘上 530 份 -readable.md**。入队为对账式（当前版本×最新提取×无 outbox 行），唯一身份索引去重；worker 崩溃/重启不丢发布（回归：清空 outbox 后下周期补齐）。人工编辑保护保持（主文件只写一次；候选隔离）。
- **派生索引刷新**：`开始阅读.md`/`处理状态.md` 为全派生页面，走 `refreshable=True` 原子刷新——仅当盘上文件仍等于账本记录的系统写入哈希（证明无人改过）才原地替换；人工编辑哈希不匹配自动退回候选路径。本次用它完成一次性导出器（owner=existing-text-export）到 publisher 的**哈希证明接管**，入口已切换（Windows 端 2026-10-05 01:21 收到 97,242 字节新版索引）。
- **A4 入口**：`处理状态.md` 状态页列出全部当前版本阶段（未提取/无正文/ready/review/failed）；`开始阅读.md` 索引正文 **523 份、缺正文 4 份**。标题可读，不依赖 hash 文件名。Syncthing→Windows 同步已核验（处理状态/开始阅读/新正文均到达本机）。

新报告端到端说明：观察窗口内 reports-fetcher 无新报告入库（sync new_versions=0），本批用修复队列的真实提取（18 份文档经提取→发布→同步全链路）作为等价证据；新 PDF 走同一代码路径（sync→snapshot→extract→publish）。

## B：单篇分析（管线真实，模型保持关闭）

- `analysis_tasks` 注册表：仅 READY 当前提取（review/failed 排除，B4 口径）；身份=(source,version,extraction,model,prompt,template)；生产 **228 条全部 blocked(model_disabled)**——不静默排队付费调用。任务身份与预算/物理请求上限（V01 修复后）已就绪，启用需用户明确 provider/范围/额度。
- B4 质量小批验收 NOT_RUN（依赖模型启用）。B3 分析页面发布随 B 启用后接 A3 发布器。

## C：知识总结（管线真实，模型保持关闭）

- `summaries`/`summary_outbox` 版本化（revision 1..N 保留历史）；影响通道（claim subject）驱动，无关实体不更新。生产当前 0 条开放 review proposal → 0 条入队，符合"无新证据不更新"。生成侧 blocked(model_disabled)，同 B。

## D：投资框架背景包（API + 参考客户端已实测，真实目标应用待接入）

- `POST /api/kb/v1/background-package`（company 按代码 / topic 按标题）：sources（含提取状态+稳定证据引用）、claims（含 revision/counterevidence）、risks_and_counter、missing_information、as_of 语义、可重放 `result_digest`（sha256 规范化 JSON）。
- 修复了部署期发现的真 HTTP 500（Handler 误用 `self.kb`；单测直调 API 对象掩盖了该路径）——新增 ThreadingHTTPServer 线级回归。
- 参考客户端 `scripts/kb-background-client.py`：持久化 `researchkb.decision-context/1` 决策上下文包，客户端重算服务端摘要并校验一致（本地起 serve-kb 实测：摘要匹配、坏 token 拒绝）。目标投资框架的真实集成（查询→证据→决策记录→重放）待框架侧接入，服务器仅 loopback 的联通/鉴权配置随之进行。

## E：稳态运维（已上线）

- `tools/shadow-acceptance/ops_status.py` + CLI `knowledge ops-status`：jobs 分阶段/状态、24h 失败、三个 outbox、analysis_tasks、用量、活跃索引代、worker 心跳、第一层可达性。已留档 `state/ops-status-20261005T1736Z.json`（ready 187、pending 0、blocked 228、心跳 fresh、第一层 538 文档）。
- worker 心跳状态文件 `state/knowledge-worker.json` 每周期持久化（含 last_cycle 全量结果）。修复 `extractions_ready` 误将 TEXT extraction_id 与 MAX(rowid) 比较恒为 0 的问题。
- 用量账本：**0 新增模型调用**（usage_totals 为迁移前已授权运行的 26,602 token / 1 call 历史值）。

## 明确未完成（不虚构）

- B/C 的生成侧：模型启用、小批质量验收（B4）、分析/总结页面——全部等待用户授权 provider/范围/预算。
- D 的目标应用真实集成与外网/鉴权配置（服务器仍 loopback）。
- 7 天稳定观察：从 2026-10-05 起累计，不能以当天冒烟替代。
- 修复队列残余 4 份缺正文（其中快照缺失的 1 份不可修复，除非原始文件回归归档）。
- 早期一次性导出的原样稿/候选文件按规则保留，不清理。

## 提交清单（本批）

`b4fcde1`（A–E 主体）→ `b95f06d`（CLI+客户端+真 HTTP 500 修复）→ `d269730`（CLI 三处崩溃修复）→ `67c6985`（worker 崩溃+对账式发布）→ `c8b088a`（派生索引刷新路径）→ `5b3fb75`（ops_status ready 计数修复）。
