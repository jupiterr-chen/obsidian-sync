# 评审指南（给独立评审者 / Codex）

> **2026-10-06独立续验0f9cb27：原23探针通过、420回归通过/2跳过，干净源码F1/S4另4项通过。S4/F1代码交付通过；S1/S2/S3/F3原任务组合条件未闭环，按原docs/34补齐SF01–SF06，不扩展范围，F4仍后置。** [续验报告](S1234-ACCEPTANCE-20261006.md)、[原任务书](../34-tqma-followup-taskbook.md)、[续验提示词](../35-tqma-followup-prompt.md)。未部署；现网67c6985r2、旧服务仍停止。生产与数据批次授权边界不变。下方为历史记录。

> **2026-10-06 最新独立验收：fbc24bd的原16反例通过，410回归通过/2跳过。新增边界归并S1模型范围、S2有效入口与引用、S3冻结批次、S4真正只读四组，按功能限制启用；不重做已通过修复/迁移，不停现网。** [验收报告](TQMA-REVIEW-20261006.md)、[集中任务书](../34-tqma-followup-taskbook.md)、[下一位agent提示词](../35-tqma-followup-prompt.md)。样本工具未入Git等列fix清单；本次无生产变更/真实模型调用/历史重处理。生产仍67c6985r2；任何发布均须先Codex验收再获用户对具体commit/范围授权。下方开发声明为历史记录。

> **2026-10-06用户追加：正文质量TQ0–TQ4并入现有开发批次并前置于LLM。** [详细任务](../33-text-quality-repair-taskbook.md)、[统一任务](../31-maintenance-and-model-activation.md)、[更新后提示词](../32-model-activation-prompt.md)。只读核对发现当前523项提取中458项为旧stdlib-pdf；需全库质量清单、原生重提取优先、必要页OCR，不强制全库OCR。旧副本只做治理dry-run；生产重处理/归档/部署须另获具体授权。此前链接可打开的验收不代表正文内容正确，历史质量尚未修复。


> **2026-10-06 AC1续验最新结论：50cf6c1模型关闭维护范围限定通过。** [报告](AC1-FOLLOWUP-20261006.md)：原探针6/6、AC1探针7/7、全回归382通过/2跳过；旧库升级阻断解除，可进入维护发布准备，仍须用户授权。B/C启用前集中修MA01–MA03，不阻挡维护范围、不重做迁移。见[双轨任务书](../31-maintenance-and-model-activation.md)与[提示词](../32-model-activation-prompt.md)。未部署、未调用真实模型。下方历史声明不代表最新状态。


> **2026-10-06 AC1独立验收：原Q01–Q05六反例通过；整批发布暂不通过。** [报告](AC1-REVIEW-20261006.md)：基线d58119e，366项回归（364通过、2跳过）；现网仍67c6985r2。旧库升级、B→C有效证据、长文覆盖尚有核心缺口，发布/恢复及D当前选版为同批小修。见[续验任务书](../29-ac1-followup-taskbook.md)、[提示词](../30-ac1-followup-prompt.md)。不重做迁移、不停阅读；仍须Codex验收通过及用户明确授权具体发布。下方为历史记录，不代表最新验收状态。


> **2026-10-05 最新独立验收：部分可用，整体未完成。** [验收报告](ABCDE-ACCEPTANCE-20261005.md)：336项回归（334通过、2 skipped）；正文worker运行，服务器/Windows 523链接0断链；B/C缺执行与发布闭环，D历史背景as_of未生效。Q01–Q05按功能修复，不重做迁移/不停阅读。见[任务书](../27-abcde-acceptance-taskbook.md)和[提示词](../28-abcde-next-agent-prompt.md)。后续必须先接收Codex独立验收任务并验收通过，再取得用户明确生产部署授权；开发/self-test/push不授权部署。

以下为历史过程与提交者声明；与最新独立验收冲突时，以最新验收为准。

> **基础迁移已完成（2026-10-04）：** 旧三容器停止，新四容器运行；数据、恢复、原文、旧证据、增量三连跑和Windows同步已验证。见[迁移报告](MIGRATION-20261004.md)。第一层小时同步正常；知识自动worker/远程模型/自动候选暂未启用，fix清单后置。不要重做迁移。

> **最新独立复核及用户取舍（2026-10-04，7ded572）：基础迁移优先。** 310 tests OK/2 skip；V01–V04保留为fix清单，关闭/暂缓相应增强功能。迁移独立核验数据、恢复、同步与回滚后可推进，不等待全部增强修复或人工质量标注。见[报告](FIFTH-REVIEW-20261004.md)、[任务书](../23-fifth-review-taskbook.md)、[交接提示词](../24-fifth-review-prompt.md)。旧栈在本次检查时仍运行；以下较早结论为历史记录。

> **最新独立复核：第四轮（2026-10-03，cd3bb5d）NEEDS_CHANGES。** 301 tests OK/2 skip，但U01–U05未闭环，见[结果](FOURTH-REVIEW-20261003.md)、[任务书](../21-cutover-blockers-taskbook.md)、[提示词](../22-cutover-blockers-prompt.md)。用户条件式迁移/停机授权已获得；本次因缺陷和G2证据不足未停旧栈。GLM修改已结束，影子提取仍运行。以下完成声明为历史记录。

> **最新独立复核：第三轮（2026-10-03，源码 cb254df）NEEDS_CHANGES。** 287 tests OK / 2 skipped；T01–T07 共4 P1、3 P2待修复。先读[第三轮报告](THIRD-REVIEW-20261003.md)、[下一步任务书](../19-release-readiness-taskbook.md)与[提示词](../20-release-readiness-prompt.md)。先过G1再做小批影子验收，暂不启动全量重提取或生产切换。以下完成声明为历史记录，以最新独立验收为准。

> **第二轮复核（基线 4949dcd）：NEEDS_CHANGES，S01-S10**，见 [RE-REVIEW-20261003.md](RE-REVIEW-20261003.md)。
> **S01-S10 已全部修复（2026-10-03）**：RED/GREEN 矩阵与隔离启动验收见 [second-remediation-log.md](second-remediation-log.md)；回归载体 `app/tests/test_second_review*.py`。复验以 ≥ `e369d32` 重跑探针与回归。

> **最新独立复核：2026-10-03，基线 4949dcd，NEEDS_CHANGES。** 268 回归 OK（2 skipped），新增反例确认 S01–S10 尚待处理（6 P1 / 4 P2）。此前 R01–R15 全 fixed/RF7 闭环是提交者历史声明，未获本轮独立验收。先读[第二轮报告](RE-REVIEW-20261003.md)、[SR 任务书](../17-second-review-taskbook.md)及[执行提示词](../18-second-review-fix-prompt.md)。真实 NOT_RUN/BLOCKED 不变；本次未操作生产。以下历史记录保留。

> **首轮独立复核（基线 534014a）：整体 NEEDS_CHANGES**，见[2026-10-02 评审报告](INDEPENDENT-REVIEW-20261002.md)及[修复任务书](../15-review-remediation-taskbook.md)。
> **R01-R15 已全部修复（2026-10-03）**：逐项 RED/GREEN 证据与提交见 [remediation-log.md](remediation-log.md)；回归载体为 `app/tests/test_review_*`。复验请以修复后基线（≥ `3cd2913`）重跑评审反例，并注意：未重做 M0、未降低任何验收标准、真实 NOT_RUN/BLOCKED 项保持原状。以下保留原提交者说明。

更新：2026-10-03。本文件是外部评审的入口：先读什么、每个声明去哪里核、哪些没做、重点审哪里。

## 评审范围与诚实边界

本工程分两层交付，评审时请区分：

1. **离线层（M0-P6 源码）**：全部实现并有自动化测试（`222 tests OK, 2 skipped`，skip 为依赖装没装的分支跳过）。
2. **真实数据层（2026-10-02 起）**：在服务器真实语料（538 文档/528 版本）上执行了快照/提取/索引/检索/分析/OCR 冒烟；**A06-A22 的真实验收大部分 NOT_RUN/BLOCKED**（见各报告），没有任何一项被谎报为通过。
3. 所有阶段报告均为**单一 agent self-reviewed**（docs/12 允许但要求标注）——你的独立复核正是缺失的那一环。

## 快速验证命令

```powershell
# 本地全量测试（Windows，原生 PowerShell）
cd D:\2.Develop\8.Obsidian\obsidian-sync
$env:PYTHONPATH="app"; python -m unittest discover -s app/tests

# 文档链接与 JSON 有效性（评审自带的检查脚本不存在，用报告里的历史输出核对）
git log --oneline   # 提交历史：0f3a19f(M0) → 2889a12 → 1fd8d78 → 9eacef3 → 240b4dd → c4abc89 → 9a20156 → 真实数据阶段系列
```

服务器侧验证（需要 SSH 访问，路径见 HANDOFF）：`pgrep -f run-extracts`（OCR 回填）、`state/knowledge.sqlite3` 只读查询、`http://192.168.1.150:8765/healthz`（旧栈未动）。

## 声明 → 证据 对照表

| 声明 | 代码位置 | 测试 | 报告 |
|---|---|---|---|
| M0 迁移保真（52 跟踪文件，40 字节一致） | manifest | test_knowledge.py（回归 113 项原样） | m0-report + m0-import-manifest.json |
| 不可变快照（同 fd 哈希+复验+原子落位，绝不覆盖） | snapshot.py | test_knowledge.py 6 个场景 | p1-report |
| 幂等（A02：三连跑无重复） | sync/store/jobs | test_knowledge.py | p1/p2-report |
| 提取与证据块（契约对齐） | extract/schema.py | test_knowledge_extract.py（含契约示例） | p2-report |
| 检索与 /api/kb/v1（游标 409/鉴权/事件） | indexing/kbapi.py | test_knowledge_index_api.py（真实 socket） | p3-report |
| provider 抽象+默认关+外发门禁 | providers/ocr.py | test_knowledge_analysis/test_knowledge_ocr/test_knowledge_providers_http | p4-report |
| 研究记忆不可变历史+决策冻结+影响分析不越权 | memory.py | test_knowledge_memory.py | p5-report |
| 写回哈希门禁（人工编辑永不被覆盖） | writeback.py | test_knowledge_memory.py WriteBackTest | p5-report |
| worker 闭环+在线备份+恢复演练 | worker.py, scripts/backup-knowledge.py | test_knowledge_worker.py | p6-report |
| OCR 本地+低置信度回退 flash | ocr/extract.py | test_knowledge_ocr.py FallbackRouteTest | HANDOFF 10-02 节 |

## 重点复核建议（风险最高的六个决定）

1. **快照不可变性与 fail-closed**（snapshot.py）：同 fd 哈希、复验、身份重写拒绝——请尝试构造反例（如同哈希不同源、并发写、临时文件残留）。
2. **外发门禁是否真的先于任何网络调用**（providers.py `_require_egress` 在 `_post` 首行；测试断言零请求落网）。
3. **写回门禁**（writeback.py）：人工编辑后哈希不符 → 候选另存；sync-conflict 文件名拒绝。
4. **幂等键唯一性**（store.py jobs UNIQUE 约束 + extraction_id 构造）：换任何输入维度是否必然换身份。
5. **M0 迁移保真**：manifest 的 sha256 可用 `git -C <旧工程> cat-file` 复算。
6. **检索正确性**（indexing.py）：CJK bigram+unigram、BM25 长度归一、as_of 双模式过滤——p3 报告的 A11 合成用例可扩展。

## 已知未完成（评审时不要当缺陷误报，但欢迎指出遗漏）

- A04/A05/A10/A16/A17/A21/A22 真实部分：NOT_RUN（无标注样本/真实基准/生产 7 天窗口）；A08 真实门禁待 OCR 回填完成后盲测。
- embedding 不可用（用户已关）；混合检索 keyword-only。
- rerank、事件保留期、unsupported_numeric_claims 自动检查：未实现（报告有记录）。
- 旧 research-kb 生产栈仍在运行（切换需用户确认，CUTOVER.md 就绪）；OCR v3 全量回填后台进行中。

## 敏感性提醒

`docs/progress/HANDOFF.md` 含内网地址、SSH 用户与服务器路径（运维连续性需要）。**本仓库必须保持私有**；若要公开需先脱敏 HANDOFF 与 CUTOVER 文档。
