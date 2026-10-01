# P4 验收报告：语义检索与分析（provider 抽象、默认关闭）

日期：2026-10-01。执行：main-agent（self-reviewed）。完成度：**源码实现 + 离线（mock 协议）验证**；真实模型质量与成本 NOT_RUN/BLOCKED。

## 交付内容（ADR0006）

### Provider 抽象（`providers.py`）

- `EmbeddingProvider` / `ChatProvider` 协议（embed→向量+Usage；complete→文本+Usage）；真实供应商适配器**未实现、未注册**——配置中出现未实现 kind 直接 `ProviderNotConfigured`，不静默降级。
- Mock（`MockEmbedder` 确定性哈希向量、`ScriptedChat` 脚本回复）仅验协议，报告与代码注释明示不得作为质量/成本证据。
- `load_providers`：默认空；`serve-kb` 仅装配已实现 provider。

### 混合召回（`analysis.hybrid_search`）

- 关键词 + 向量并行召回 → RRF（k=60）融合；向量按 `(model, block_id)` 缓存（`block_embeddings` 表），二次查询只嵌入 query；关键词空结果时回退全池向量排序。
- `/api/kb/v1/search` mode=hybrid：无 embedder → 422 mode_unavailable（保持 P3 行为）；有 → 融合结果（score_kind=rrf_hybrid）。

### 分析运行（`analysis.execute_analysis_run`）

- 状态机 pending→running→done/failed；检索→编号证据 prompt（要求逐条引用、未知数值不许猜）→模型→**引用验证**（每条 [n] 必须命中本次检索到的可访问块，越界进 invalid，all_valid 如实呈现）→落库 draft/citations/verification。
- done 幂等重跑 no-op，不产生新用量。
- A18 故障路径：ProviderCallError（可重试）→ failed 无 draft 不发布部分结果；预算门禁（每 run 输入上限 + 总输入累计上限）在**任何 provider 调用前**拒绝，`chat.calls == 0` 由测试保证。
- `/api/kb/v1/analysis-runs` POST（analysis.run 权限；无 provider 422 task_disabled）+ GET run 详情（含 usage）。

### 用量账本（`usage_events`）

逐调用记录 provider/model/kind/input/output/cost_basis/run_id/时间；`usage_totals`（支持 since）/`usage_for_run` 聚合。真实价格表待供应商确定后接入（成本字段口径已留）。

## 验收场景对照

| 场景 | 结果 |
|---|---|
| A16 embedding 成本 | 协议/账本 PASS（mock）；**真实 provider/model/tokenizer/维度/账单 BLOCKED**（供应商与预算未定） |
| A17 分析引用 | PASS（mock）：引用越界被标记 invalid 不隐藏；有效引用绑定 block_id+evidence_url。**真实 ≥30 问人工核验 BLOCKED** |
| A18 LLM 故障 | PASS（mock）：429/预算超限不发布 draft、不重复投递、不无限重试；未知输出路径（验证失败标记）存在 |
| A10 hybrid | 融合机制 PASS（mock）；**真实 Recall@10 ≥0.90 NOT_RUN** |
| V4 计费门禁 | PASS：默认无 provider；工程订阅未被当作 API 授权；mock 用量标注 `mock:none` |

## 测试

**185 OK (1 skipped)** = 171 + 14 P4（provider 注册表、混合召回与缓存、分析状态机、引用验证、预算门禁、API 网关）。

## 已知限制

1. rerank 接口未实现（doc/03 列为可选项，真实评测后决定）。
2. unsupported_numeric_claims 目前为空占位——数值级「无依据不输出」的自动检查需真实模型输出结构（P4 真实化后启用）。
3. 真实接入清单：供应商+凭据注入方式+外发范围+价格表 → 适配器 + 真实 tokenizer 计数 + A16/A17/A10 真实评测。
