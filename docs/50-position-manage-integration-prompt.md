# position-manage 对接提示词（KB 2026-10-21 版本之后）

> 用途：交给 position-manage（Codex）侧 agent 的对接任务提示词。知识库（obsidian-sync）已于 2026-10-21 发布 `kb-normalize-20261021-f697f30`，以下能力已上线，接口文档与建议修改点如下。本文件只是对接说明，不包含对 position-manage 仓库的任何直接修改。

---

## 提示词正文（复制以下内容给 position-manage agent）

你在 position-manage 项目上工作。上游知识库（obsidian-sync，`/api/kb/v1`）刚完成一次发布（镜像 `obsidian-sync:kb-normalize-20261021-f697f30`，commit `f697f30`），新增/修复了四项能力。请在 position-manage 侧完成对接，逐项独立提交并附测试。

### 一、上游已上线的能力（KB 侧已完成，直接用）

1. **检索简繁/全半角归一化**：`资产负债`（简体）与 `資產負債`（繁体）互相命中，`ＡＳＭＬ`（全角）命中 `ASML`。索引与查询两侧同一归一化。研究端**不再需要**做查询侧简繁改写或全半角折叠——直接发原始查询即可。
2. **文档目录 API**（新端点）：`GET /api/kb/v1/documents?symbol=01810&doc_type=earnings&date_from=...&available=true&limit=50&cursor=...`
   - 响应 `{documents, total, limit, offset, next_cursor}`；每条含文档级元数据、`report_period`、`version_count`、`current_version_id`、`document_url`、`metadata_flags`。
   - 游标绑定过滤集摘要 + 元数据 epoch，变化返回 409 `cursor_expired`（重启分页即可）。
   - 用途：公司基线/财报文档**按 symbol 枚举**，替代关键词召回。「没搜到 ≠ 库里没有」由目录兜底。
3. **元数据质量标志**：documents 响应（单查与列表都）带 `metadata_flags`（建议性）：`period_invalid`（期间非 YYYY-MM-DD）、`period_suspect`（期间与发布日相差 >400 天，例如 FY2023 年报期间写成上一财年末）、`period_missing` / `symbol_missing`（财报类缺期间/代码）。**消费规则：被标记字段的 `report_period` 视为未核验，不得直接用作期间对齐键**；应回退到从正文/表头解析期间，或跳过该文档的期间绑定并把 flag 透传到报告缺口。
4. **表格结构化证据**：`GET /api/kb/v1/evidence/{block_id}` 对 `block_type=table` 的块额外返回兄弟级 `table` 节：`{rows, header_rows, normalized_cells}`。`normalized_cells` 每格含 `{row, col, raw_text, is_header, number}`，`number` 为读时解释 `{value, is_percent, negative_style, currency, issues}`（千分位、括号负数、币种符号、百分号；歧义保守 `value=null` + `issues` 原因）。注意：仅对**新提取**的 HTML 文档生效（提取配方 `evidence-block-v2`）；历史语料在显式重提取 pass 之前没有 table 节，代码需容忍缺失。

**接口文档**：`obsidian-sync/docs/04-api-contract.md`（「检索归一化」「文档目录列表」「表格证据」三节）与 `obsidian-sync/docs/39-knowledge-api-usage.md`（调用示例、token、隧道）。

### 二、position-manage 侧建议修改点（按优先级，均不需重构架构）

**P0-1 公司车道强制 symbol 过滤（小米污染事故的最短修复）**
- 位置：`backend/app/services/knowledge_research/prompts.py` `_parse_query`（约 3293-3303 行）。现状：模型扩展查询时 `filters` 只有模型自带 `symbols` 且首项等于 canonical 时才保留；模型不带就没有过滤。
- 改法：车道 ∈ `SYMBOL_FILTERED_LANES`（contracts.py:585，公司财报/研报/产品/风险四车道）且 `canonical_symbol` 已知时，**无条件注入** `filters["symbols"] = [canonical_symbol]`，模型输出只允许提供、无权省略。行业/同业车道维持不带。
- 测试：构造模型不带 symbols 的公司车道扩展查询，断言最终 PlannedQuery.filters 含 symbols。

**P0-2 空 symbol 候选不再默认无冲突**
- 位置：`backend/app/services/knowledge_research/retrieval.py` `_entity_conflict`（约 930-937 行）。现状：候选 `symbol` 为 None 时表达式恒 False，无代码资料直接进入公司车道。
- 改法：公司车道候选 symbol 为 None 且 canonical 已知时返回冲突（或新增 `entity_unverified` 态进 deferred，复用 `relevance.py` `_same_entity` 用标题主体名兜底校验）。同时考虑把 `relevance.py:471` 处非门控车道的自动 `COMPANY_FACT` 改为经上述校验后才给。

**P0-3 会计口径词表两处补齐（阿里 15 条事实全缺绑定的一部分原因）**
- 位置：`backend/app/core/knowledge_research/validation.py`。
- 改法 1：`_STANDARD_FAMILIES["US-GAAP"]`（约 738-741 行）追加 `"美国公认会计准则", "美國公認會計準則", "公認會計原則"`——GAAP=Generally **Accepted**，港交所文件用「公认」，现词表只有「通用」。
- 改法 2：`_BASIS_PREPARATION_PHRASES`（约 756-761 行）追加 `"列報基礎", "列报基础", "呈列基礎"`。
- 测试：用「本中期報告未經審核，根據美國公認會計準則編製」与「列報基礎」样例断言能定位准则族。

**P0-4 报告终态门槛（零财务事实仍标「研究报告」）**
- 位置：`backend/app/services/knowledge_research/pipeline.py` 1212-1217 行。现状：有任意 1 条 claim + LLM OK 即 `OutputKind.RESEARCH_REPORT`。
- 改法：RESEARCH_REPORT 需量化门槛（如 ≥N 条 SUPPORTED 事实且含 ≥1 条财务指标事实、≥1 次计算）；只有「资料不足」型 claim 时降级 `EVIDENCE_PACKAGE`（或新增 INSUFFICIENT 枚举，注意 DB 枚举与前端展示联动）。「资料不足」说明应映射 INSUFFICIENT 而非完成态。

**P1-5 检索降级梯 + 目录兜底**
- 位置：`backend/app/providers/knowledge_base.py` `search()`（约 830-831 行硬拒非 keyword 模式）与 `services/knowledge_research/retrieval.py`。
- 改法：provider 放开 `mode="hybrid"`（KB 已支持，未配 embedding 时返回 422 `mode_unavailable` 可捕获降级）；provider 新增 `documents()` 方法封装 `GET /documents`。检索梯：keyword（带 symbol）→ hybrid → 目录枚举；空结果触发下一级而不是直接记 `QUERY_EMPTY`。目录枚举同时消掉 `DIRECTORY_COVERAGE_UNKNOWN` 常驻缺口（probe 已有该 gap 码）。

**P1-6 S06 表格按列取数 + 装配绑定**
- 位置：`services/knowledge_research/prompts.py` S06 输入规划（`_s06_input_plan`，`MAX_TEXT_CHARS=800` 窗口）。
- 改法：`block_type=table` 且 evidence 带 `table` 节的块，不再走平铺文本窗口，改按「表头行 + 目标行」结构化装配（列名→值的显式对应），声明块与数值块保同一窗口相邻发送。无 table 节的历史块维持现状。

**P1-7 展示层采用/摘录分区**
- 位置：`core/knowledge_research/render.py`。两份报告 82-84% 篇幅是来源摘录。改法：「已综合采用的结论」与「仅来源摘录」强制分区渲染并设篇幅比例上限；摘录区标注哪些来源未通过准入（relation UNKNOWN/UNRELATED 的可追溯候选不冒充已采用）。

### 三、验收基准（对照实测数据）

`.orchestra/kr-quality-review-20261020/kb-search-comparisons.json` 中的对照现已在 KB 侧修复：
- `xiaomi_balance_simplified`（原 0 命中）现在应与 `xiaomi_balance_traditional` 等价命中。
- 该 JSON 建议固化为 position-manage 回归测试基线（简繁等价、symbol 过滤不漏不串）。

检索行为变化提醒：所有查询词现在会被 KB 侧归一化（繁→简 + 全半角折叠），研究端如果之前做过查询侧简繁替换逻辑，应删除以避免双重转换开销；`snippet` 高亮可能匹配不到原文（匹配词是归一化形态，原文是繁体），属预期降级。
