# P5 验收报告：长期研究记忆与受控写回

日期：2026-10-01。执行：main-agent（self-reviewed）。完成度：**源码实现 + 离线验证**；真实 Vault 写回与 A20 真实评测 BLOCKED。

## 交付内容

### 研究记忆状态机（`memory.py`，docs/05 三种记忆）

- **claims**：`(claim_id 内容寻址, current_revision, statement, status, evidence_refs, counterevidence)`；claim_revisions 为**追加式历史**（自增 seq；每个 review 动作新增一行，永不改写旧行）。
- 状态：proposed/accepted/challenged/superseded/rejected；动作 accept/reject/challenge/revise/supersede 均留历史（reviewer/reviewed_at/review_note/新内容）。内容寻址 claim_id 使重复创建幂等。
- **决策冻结（decisions）**：记录时解析并冻结 claim revision + 当时刻陈述；后续 claim 修订不改写旧决策引用（测试覆盖）。
- **影响分析（A20）**：`impact_analysis(source, doc_id, new_version_id)` → 引用该文档证据的 claim 列表 → review_proposals（原因+详情，proposal_id 内容寻址幂等）；**接受中的 claim 状态与 revision 不被触碰**，仅生成人工复核候选；事件 review.proposed 入 kb_events。

### 受控写回（`writeback.py`）

- 写入仅限显式登记的生成目录；目标文件仅在「内容哈希 == 本模块上次写入哈希」或不存在时原子替换（temp+rename）；**人工编辑后哈希不符 → 不覆盖**，原文保留 + 另存带时间戳候选文件；sync-conflict/隐藏/路径穿越文件名直接拒绝。
- `render_claim_candidate`：候选稿含状态（待审核）、claim/revision、作者/提示词版本、陈述、证据引用（块 id + 原文摘录）与反证；`export_claim_candidates` 按状态批量导出（幂等，二次导出 unchanged）。
- 生成目录清单 `.knowledge-writeback.json` 记录 owner/last_hash/written_at。

### API

`GET /api/kb/v1/claims[?status=]`、`GET /claims/{id}`（含 history，research.read）；`POST /claims/{id}/review`、`POST /memory-proposals/{id}/review`（memory.review 写权限，契约路径）。

## 验收场景对照

| 场景 | 结果 |
|---|---|
| A19 记忆与决策 | PASS（离线）：确认/拒绝/质疑/替代全留历史（reviewer/note/新内容）；旧决策证据清单冻结不随新 revision 变化；claim 创建幂等 |
| A20 更新影响 | PASS（离线）：新版本→受影响 claim 召回 100%（合成）、建议以 proposal 呈现、接受版本零自动覆盖、重复分析幂等。**真实 ≥20 组标注评测 BLOCKED**（需真实新旧版本语料） |
| A15 人工区 | PASS（离线等效）：生成目录写回哈希门禁 + 人工编辑保留 + 冲突候选另存；**真实 ResearchVault 写回 BLOCKED**（需用户登记允许路径与授权，目录尚未创建） |
| P5-03 Obsidian 写回 | 候选生成与安全写回机制就绪；真实 Vault 路径授权后即可启用 |

## 测试

**196 OK (1 skipped)** = 185 + 11 P5（状态机全路径、决策冻结、影响分析幂等、写回三态、冲突拒绝、候选渲染/导出、API 路由与权限 scope 模型）。

## 已知限制

1. 影响分析按 evidence_refs 精确匹配文档版本；「同文档新旧版本内容差异」级的影响（diff 语义）需 P2 真实提取质量后增强。
2. 自动确认仅适用于客观字段的配置（docs/05）未启用——投资判断默认人工，符合要求。
3. 真实 Vault 的 `自动研究候选/`、`证据索引/` 目录登记与写回授权待用户提供。
