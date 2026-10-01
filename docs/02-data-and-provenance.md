# 数据、身份与证据版本

## 身份规则

沿用 `(source, doc_id)` 作为 document key。不能仅用标题、股票代码或哈希代替文档身份。跨来源同一哈希可共享物理文件，仍保存不同来源元数据和权限。

`source_version` 沿用 library version_id，并验证 sha256；若来源相同版本却哈希改变，报一致性错误，不静默更新。原文哈希计算完整字节。`extraction_id` 对源版本、解析器版本、OCR 模型/语言、规范化规则及配置摘要构造确定性摘要。块身份由 extraction_id 和块路径确定。分块策略变化产生新的派生产物，不覆盖旧证据。

## 逻辑实体（实际迁移在 P1 实现）

|实体|关键字段|约束|
|---|---|---|
|documents|source, doc_id, title, market, symbol|source+doc_id 唯一|
|source_versions|document_key, version_id, sha256, bytes, media_type, source_uri|document+version 唯一、不可变|
|availability|published_at, filing_date, first_seen_at, ingested_at, availability_basis|未知时间显式 null|
|extractions|extraction_id, source_version, parser/config hashes, status, quality|派生配置可复现|
|blocks|block_id, extraction_id, type, text, locator, section_path|绑定不可变提取版本|
|tables|table_id, cells, header_links, unit, period, currency, locator|保留原始显示和规范化值|
|jobs|stage, idempotency_key, attempts, lease_until, status|同幂等键唯一|
|index_generations|generation_id, manifest_hash, status|active 指针原子更新|
|claims|claim_id, revision, statement, status, evidence, counterevidence|版本及审核记录|
|decisions|decision_id, recorded_at, context, claim_revisions|决策引用固定版本|
|usage_events|provider, model, prompt_version, input/output/reasoning, cost_basis|账单类别分开|

## 位置与引用

PDF locator 包含实际文件页序（1 起）、可选印刷页码、bbox、坐标单位及坐标系。HTML locator 包含源快照版本、DOM 路径、可选原始锚点、规范化正文字符偏移。图片含帧/图序和 bbox。纯文本保存字符偏移。所有偏移明确针对哪份正文，不能混用字节与字符。

引用 URI 由知识服务生成，例如 `/api/kb/v1/evidence/{block_id}`，返回固定版本上下文及源文件跳转。PDF `#page=N` 可作为阅读器提示，实际支持程度在目标阅读器验收。HTML 由服务托管净化后的固定快照/证据视图，不运行原站脚本。

## 表格和数值

单元格保留 raw_text、row/column、合并关系、关联表头、期间、币种、单位、原文位置及提取状态。规范化金额不能脱离币种/单位；负数括号、百分号、脚注和缺失值分别表示。财务事实额外标记实际/预测、GAAP/非 GAAP、合并范围及重述版本。未知字段不能由模型无依据补齐。

## 时间与历史研究

report_period 表示经营期间；filing_date/published_at 表示公开日期；first_seen_at 表示接入层首次观察；ingested_at 表示本系统落库。统一 UTC 存储，日期字段保留源精度，界面按 Asia/Shanghai 展示。

`as_of` 必须同时说明模式：public（按可信公开时间）或 system（按首次观察/接入时间）。未知公开日期的文档不能伪造历史可用时间。system 模式保证资料在当时系统中已经可用，不能声称恢复了接入系统建立前的完整历史知识。

## 保留和删除

默认保留原文、证据及研究历史。来源暂时失联只标记不可用，不删除索引历史。文档撤回后当前搜索排除，历史引用显示撤回状态；权限失效立即阻断内容访问。保留期限与任何物理清理必须单独制定，当前交付不包含删除任务。
