# 评审指南（给独立评审者 / Codex）

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
