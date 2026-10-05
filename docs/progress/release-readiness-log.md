# 发布前修复与影子验收日志（T01-T07 / G1 / G2）

> **2026-10-05 最新独立验收：部分可用，整体未完成。** [验收报告](ABCDE-ACCEPTANCE-20261005.md)：336项回归（334通过、2 skipped）；正文worker运行，服务器/Windows 523链接0断链；B/C缺执行与发布闭环，D历史背景as_of未生效。Q01–Q05按功能修复，不重做迁移/不停阅读。见[任务书](../27-abcde-acceptance-taskbook.md)和[提示词](../28-abcde-next-agent-prompt.md)。后续必须先接收Codex独立验收任务并验收通过，再取得用户明确生产部署授权；开发/self-test/push不授权部署。

以下为历史过程与提交者声明；与最新独立验收冲突时，以最新验收为准。

> 2026-10-04 已补 Obsidian `解析正文/开始阅读.md`：512份已有正文及15份缺正文清单，见[阅读交付](TEXT-READING-20261004.md)。本次仅导出已有数据，未启动全文增量worker。

> **基础迁移已完成（2026-10-04）：** 旧三容器停止，新四容器运行；数据、恢复、原文、旧证据、增量三连跑和Windows同步已验证。见[迁移报告](MIGRATION-20261004.md)。第一层小时同步正常；知识自动worker/远程模型/自动候选暂未启用，fix清单后置。不要重做迁移。

> **最新独立复核及用户取舍（2026-10-04，7ded572）：基础迁移优先。** 310 tests OK/2 skip；V01–V04保留为fix清单，关闭/暂缓相应增强功能。迁移独立核验数据、恢复、同步与回滚后可推进，不等待全部增强修复或人工质量标注。见[报告](FIFTH-REVIEW-20261004.md)、[任务书](../23-fifth-review-taskbook.md)、[交接提示词](../24-fifth-review-prompt.md)。旧栈在本次检查时仍运行；以下较早结论为历史记录。

基线：第三轮评审 `4036a2b`（评审源码基线 `cb254df`，NEEDS_CHANGES，7 组问题 4P1/3P2）。
回归命令（PowerShell）：`$env:PYTHONPATH="app"; python -m unittest discover -s app/tests`

## N0 基线（2026-10-03）

- Git：HEAD `4036a2b`，clean；评审证据 `third-review-evidence-20261003.json` + 探针 `third-review-probe-20261003.py`。
- 回归基线：287 OK / 2 skipped（与评审一致）。
- T01-T07 断言式回归载体：`app/tests/test_third_review.py`（含旧 schema fixture 构建：用 git 基线 `0a473d9` 的 SCHEMA 建带数据旧库，验证升级而非新库冒烟）。

## RED/GREEN 记录

| 任务 | RED（基线复现） | GREEN | 提交 |
|---|---|---|---|
| T01 旧库升级 | 旧 schema（0a473d9 fixture）打开即报 no such column | 依赖列的索引移出 SCHEMA 到 POST_MIGRATION_INDEXES（列存在后才建）；版本化迁移（user_version=2）；带数据旧库升级+重开+半迁移容忍全部通过 | c99f159 |
| T02 预算状态机 | 结算中断额度复活；unknown 重放双记账；付费坏向量 release；HTTP 重试逃逸门禁 | fail_unknown 状态+usage 同事务（reservation_id UNIQUE 幂等）；坏 shape settle 真实用量不 release；attempt_ledger 门禁每次物理尝试（含重试）；counts_request 贯穿预留/usage/汇总 | c99f159/4109655 |
| T03 版本公开时间 | v2 继承 v1 的公开日期（1月→8月版本 7月查询命中） | 绑定用 STORED first_observed_at（新行用 upsert 的 synced_at 参数兜底）；早于首观察的文档日期对版本=unknown | c99f159/4109655 |
| T04 元数据纪元 | 同长度 symbol 修改 epoch 不变（只哈希长度和） | epoch 改为全部过滤相关字段值的规范化哈希（available/symbol/doc_type/日期/版本公开时间） | c99f159 |
| T05 漏页+recipe | 空 OCR 页+回退失败仍 ready；质量逻辑变化 digest 不变 | 空 OCR/回退失败页状态化（needs_ocr_unmet/ocr_empty_after_fallback/ocr_fallback_failed）并降级文档；EXTRACT_CONFIG v5 + QUALITY_CONFIG 深拷贝进 digest | c99f159 |
| T06 召回/缓存 | 前 200 截断（第 205 强语义目标永不召回）；同名同维度跨 provider 复用缓存 | 向量腿嵌入/打分完整允许集合（embed_top 只限融合 top-k）；缓存键=embedding_cache_key(provider+model+dims+host) | c99f159 |
| T07 幂等候选 | 同一 v2 三次导出=3 份重复文件 | 候选带确定性身份（name+content hash）进 manifest；重复投递返回既有文件（unchanged） | c99f159 |

（逐项随修复填充。）

## N4 G1 复验（2026-10-03）：**G1 通过**

- 逐字重跑评审探针 `third-review-probe-20261003.py`：**14/14 场景全部呈现修复后行为**（旧库打开、并发预留恰一个、页上限 1 拒 2、结算中断不复活、重放单次记账、付费坏向量不释放、重试尝试==记账、公开修订 unknown+0 命中、纪元翻转+409、混合 PDF review、recipe digest 变化、跨 provider 重嵌入、第 205 位召回、重复导出单份）。
- 全量回归：**301 tests OK (2 skipped)**（287 基线 + 12 T 回归 + S09 部署 + rf6 修正）。
- 旧库升级 fixture（git 基线 0a473d9 SCHEMA + 数据）在 T01 回归中持续验证。

## N5 影子验收（进行中，2026-10-03）

- 工具链（tools/shadow-acceptance/，已入 Git）：采样（30 份分层=20/10，身份从只读 catalog 固定）→ dry-run → 隔离执行（独立 state，任务剪枝到样本集）→ 对账报告；标注模板 30 份已生成在服务器 shadow/annotations/。
- **已在服务器启动隔离小批**：独立 knowledge DB + 快照根（shadow/state，与生产完全隔离）；快照阶段 61 done 0 failed；提取阶段进行中（OCR 密集文档约 27s/页，预计 1-2 小时完成）。进度查看：`ssh chen@192.168.1.150 'python3 -c "...jobs GROUP BY status..."'`（见 SHADOW-RUNBOOK）。
- 完成后按 RUNBOOK 执行：对账（A01/A14）→ 连跑两次验证幂等（A02）→ 人工标注（A04/A06/A08/A09 金标准，盲测集隔离）→ measure（A05）。**人工标注未完成前相关验收保持 NOT_RUN。**

### 影子小批结果（2026-10-04 凌晨，隔离目录实测）

- 处理完成：样本 30/30 快照全部就绪、提取 30/30 全部成功（另含此前试跑的 31 份非样本，共 61 份任务 0 失败）。
- A02 幂等（连跑三次）：第二、三轮快照/提取均 0 新增（61 补齐后归零）；无重复行/块/候选。
- 质量分布（隔离库全部 122 次提取，含历史波次）：ready 62 / review 50 / failed 10——均为旧 recipe 产物，新 recipe 重跑后待对比。
- OCR：27 文档应用 OCR 共 191 页；低置信度页 0（全部达到 0.6 阈值）。
- A05 测量：30 份中 24 测得正文（启发式约 563,632 token，仅数量级）、6 份未提取（待新 recipe 重跑后复测）；真实 tokenizer 仍 BLOCKED。
- 待人工：30 份标注模板已在 shadow/annotations/；A04/A06/A08/A09 金标准未开始，保持 NOT_RUN。

## N6 全量 dry-run（只读，已完成）

在服务器以只读连接对生产知识库执行 `full_wave_dryrun.py`：
- ready 版本 524（discord 438 + reports 86）；快照全部就绪（0 需补）。
- **新 recipe（v5，含 T05 页级质量门禁）下需重提取 524 份**：预估 14,751 页、OCR 候选 2,792 页。
- 不可变性：既有 1,123 提取 / 213,829 块全部保留，新 recipe 产生全新身份行。
- 恢复：任务幂等（stage+config 唯一），中断即续。

## G2 状态：**未达成**（等影子人工标注 + 真实门禁）；全量/生产操作待授权。

## 第四轮评审修复（2026-10-04，U01-U05）

基线：`cd3bb5d` + 评审提交 `798c0d1`/`43018a9`；回归载体 `app/tests/test_fourth_review.py`（9 项断言，基线 7 RED）；探针 `fourth-review-probe-20261003.py` 逐字重跑全修复。

| 问题 | RED（基线） | GREEN | 提交 |
|---|---|---|---|
| U01 旧库 counts_request | 0a473d9 旧库升级后首次 reserve 报 no such column | 迁移列表补 usage_events.counts_request；升级副本实际运行 reserve/settle/unknown/重放（合计含旧行），重开幂等 | 6a2e57d |
| U02 三入口门禁 | chat/vision cap1 重试 2 次 transport、账本 1；embedding 成功后 http-attempt 永久 reserved | 三个真实入口（execute_analysis_run/VisionApiOcr/budgeted_embed）统一装配 attempt_ledger；每次物理尝试门禁+终态（成功 release、已派发失败 fail_unknown）；attempt-gated provider 的业务预留只计 token | 6a2e57d |
| U03 legacy NULL | 迁移旧 v2（first_observed=NULL）继承 1 月公开日期、7 月查询命中 | NULL=unknown 永不绑定；绑定需 row_known+row_first+日期不早于首观察；NULL 基线回填显式 'unknown' | 6a2e57d |
| U04 claim 导出 | 同 claim 三次不同秒导出=3 个 Markdown | 候选身份=claim_id/current_revision/模板版本（稳定业务身份，不依赖含时间的渲染哈希）；三次导出恰 1 份候选 | 6a2e57d |
| U05 影子链 | manifest 30/30 缺 sha256；runner 可写生产路径、继承外发配置；标注可被重写 | SELECT 含 sha256；manifest 自哈希；state-dir 命中生产路径在任何探测/写入前拒绝（exit 3）；chat/vision/embedding 全部强制 egress_allowed=false、OCR fallback=null；标注独占创建不重写 | 6a2e57d |

### 服务器实测（C6）

1. **生产库升级演练（U01 真实场景）**：在线备份 API 复制生产 knowledge.sqlite3（升级前 usage_events 无 counts_request——与评审观察一致）→ KnowledgeStore 打开（迁移）→ reserve/settle/unknown/重放全部执行 → **26,612 token（含旧 26,602+新 10）/ 3 requests**，重开一致；**1,123 提取 / 213,829 块零丢失**。
2. **shadow2 新独立 run（U05 封闭链）**：seed 20261004 选样 30 份（manifest_hash d25c541a…，30 份标注模板首次创建）；生产 state-dir 拒绝（exit 3）；隔离 state 处理 30/30 快照+提取全成（venv 解释器一致）；**usage_events=0（零模型调用证明）**；连跑三次第二/三轮 0 处理（幂等）；对账 ready 28/review 2/failed 0；A05 测量 26 份约 65.9 万 token（启发式）。此前 shadow1 保留未动。
3. 教训已固化：同一 state 必须用同一解释器（venv）跑——system python3 缺 pypdfium2 会产生不同 recipe 身份的降级产物（影子期间实际发生并已用独立 state 重做，成为 interpreter 一致性的实证）。

最终回归：**310 tests OK (2 skipped)**；第四轮探针 7 场景全修复（含 unchanged claim 3 导出→主文件+恰 1 候选）。

### G2 前剩余

- shadow2 的 30 份人工标注（A04/A06/A08/A09 金标准）未开始 → NOT_RUN。
- 全量/切换待上述+用户启动指令（停机授权已有，条件未满足前不动旧栈）。

## F0 迁移后 Bug Fix（2026-10-04，V01-V04 + CLI snapshot_root）

基线 `b38f333`（迁移后）；评审依据 `FIFTH-REVIEW-20261004.md`；回归载体 `app/tests/test_f0_fixes.py`（13 项断言，基线 9 RED）；探针 `fifth-review-probe-20261004.py` 逐字重跑 **ALL-PASS（8/8）**。提交 `a2407d1`。

| 问题 | RED | GREEN |
|---|---|---|
| V01 成功请求不计预算 | 三入口 cap=1 连续成功两次、requests=0 | 物理尝试=上限单位（重试需自有槽位）；业务预留 settle/unknown 持久化为请求记录；连续成功/跨重启/超时重试/坏响应/旧库升级全覆盖 |
| V02 manifest/对账不严 | sha256 30/30 缺失；空 state/缺 blob/错 hash/错 recipe 均 exit 0 | 选样 SELECT 带 sha256 且缺哈希拒绝出 manifest；manifest 锁定 expected_extraction_digest；reconcile 严格只读（mode=ro 不建库）逐份核验 blob 大小/哈希/recipe，问题=exit 1，缺数据=NOT_RUN exit 2 |
| V03 误填时间未修 | 误填库重同步保留 1 月日期、7 月命中 | sync 自愈（继承基线无版本证据→重算归 unknown，显式版本证据保留）；time_audit.py 只读审计+幂等修正（保留前值/原因/证据）。**生产只读审计：528 行 basis 全 null，0 误填——从未污染生产** |
| V04 写回首次重复+中断 | 同 revision 三导出 2 文件；中断重试 2 份 revision2 | 渲染时间取 claim 固定 updated_at（同 revision 字节稳定→重导出纯 no-op）；首次发布登记业务身份；人工编辑恰 1 候选；候选文件名含稳定标记（中断孤儿可被收养并登记） |
| CLI snapshot_root | serve-kb 未传配置路径（迁移时以 working_dir 规避） | 显式传 config.snapshot_root；任意 cwd 端到端快照哈希核验通过（既有容器 working_dir 规避继续有效） |

最终回归 **324 tests OK（2 skipped）**。生产状态：新四容器 healthy、旧栈停止；V01 无孤儿预留；无生产数据修改（本轮零部署变更，修复待下次发布随新镜像上线——见 F0-5 根治后仍保留 working_dir 设置至新发布验证）。

### F0 边界（按任务书）

- 一次性阅读副本导出的 CRLF/NUL 处理作为回归保持（test_fourth_review 阅读路径测试继续通过），未扩大重构。
- F0 通过≠自动解析/分析上线；下一步接 docs/25 的 A 阶段。

## A–E 交付链上线（2026-10-05，基线 a2407d1 → 5b3fb75）

按 docs/25 交付次序完成 A（自动解析+阅读发布）、B/C（管线真实、模型保持关闭、blocked 如实记录）、D（背景包 API+参考客户端）、E（ops 工具）。334 tests OK（2 skipped）。生产五容器（含新 knowledge-worker）运行；详见[交付报告](ABCDE-DELIVERY-20261005.md)。

- 生产实证：缺正文 15→4（A2 有界修复）；publish_outbox 526 消费 0 待处理；阅读索引/状态页经哈希证明原地刷新并同步到 Windows；228 条分析任务 blocked(model_disabled)；0 新增模型调用。
- 部署期发现并修复（各有回归）：真 HTTP background-package 500；CLI repair-queue/ops-status 崩溃；worker 阅读段 SELECT 不存在列；派生索引被 S02 规则冻结（新增 refreshable 刷新路径，人工编辑仍走候选保护）；syncthing pinned 镜像被误写后已恢复。
- 未完成不虚构：B/C 生成侧待模型授权；B4 质量验收 NOT_RUN；D 真实目标应用集成待接入；7 天观察自 2026-10-05 起累计。
