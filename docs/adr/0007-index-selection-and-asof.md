# ADR 0007：索引选版策略与 as_of 可见性语义

状态：已接受，2026-10-03（R08 修复）。

## 决定

1. **默认索引只含「当前版本」**：每文档取 `is_current=1` 的源版本，配合该版本**最新一次非 failed** 提取（`created_at DESC, extraction_id DESC` 确定性并列拆分）。历史版本/历史提取不进默认搜索索引，但仍可通过 evidence/blocks API 按固定 extraction_id 读取（证据不可变性不变）。
2. **选版策略进入 generation manifest**（`selection_policy` 前缀进哈希）：策略变化必然产生新 generation，不静默混索引。
3. **system as_of 按版本级 `first_observed_at` 判定**：新版本入库时记录；**旧库行保持 NULL=unknown**——unknown 在任何过去 as_of 下不可见（不倒填、不伪造可知性；迁移观测时间属于伪造）。文档级 first_seen 不再作为 system 可见性依据。
4. **public as_of 需要真实公开日期依据**（report_date/published_at/filing_date 三者之一）；全部为空 → 该文档在 public 模式下排除（原实现回退 first_seen 会把接入时间伪装成公开时间）。
5. **available=0 的文档默认过滤**：源失联/撤回的文档不进默认检索；其已验证快照与证据仍可按固定版本读取（失联≠销毁历史；明确撤权场景由权限层另行阻断——P3 A13 范畴）。
6. **历史研究模式**：需要「当时怎么看」的重放通过证据 API + 存档的 integration-context（generation_id/evidence_refs/result_digest，docs/05）完成，而不是让主索引同时服务多时间面。

## 代价

- 历史版本的全文检索需显式工具（后续如需可建 history generation，属独立决策）。
- 旧数据的 system-asof 查询保守（unknown 不可见）——符合「宁可少说，不可编造」。
