# 查询与集成 API 契约（设计稿）

**实际调用请先读 [知识库 API 使用说明](39-knowledge-api-usage.md)**：含当前地址、Windows 连接、认证、检索/正文/证据/背景包完整示例，以及 2026-10-07 现网只读验证。本文保留设计范围，尚未实现的保证不应当作已交付能力。

新服务前缀 `/api/kb/v1`。现有 library 路由保持原有含义。2026-10-04已有知识API部署在服务器loopback，普通检索/证据/固定快照验证通过；模型调用关闭，目标投资应用尚未接入。以下为契约与设计范围，实际支持和验收以实现、迁移报告及[最新交付链](25-target-workflow-delivery.md)为准。

|方法与路径|用途|
|---|---|
|GET /health|仅存活，不返回敏感配置|
|GET /ready|数据库和 active generation 就绪|
|POST /search|关键词/混合检索，日期/公司/权限筛选|
|GET /documents|文档目录列表：按 symbol/doc_type/source/日期/可用性枚举文档（身份驱动，非文本召回）|
|GET /documents/{source}/{doc_id}|元数据、可访问版本和正文状态|
|GET /documents/{source}/{doc_id}/versions/{version_id}|固定源版本|
|GET /evidence/{block_id}|不可变证据及上下文；表格块附带结构化 table 节|
|GET /extractions/{extraction_id}/blocks|游标分页正文块|
|GET /changes?cursor=...|新增/修订/撤回事件，供客户端增量消费|
|POST /analysis-runs|后续带引用分析任务，默认未启用|
|GET /analysis-runs/{run_id}|状态、草稿、用量和验证结果|
|POST /memory-proposals/{id}/review|后续确认/拒绝，要求写权限|

## 检索归一化

检索词空间在索引侧与查询侧做同一确定性归一化：NFKC（全角折叠为半角，兼容形式归一）+ 繁→简转换。简体查询「资产负债」与繁体「資產負債」互相命中；存储的块原文永不改写，归一化只存在于可重建的词项层。分词器任何行为变化都会 bump `TOKENIZER_VERSION` 并进入 generation manifest，强制整代重建，杜绝新旧归一化混用同一索引。

## 文档目录列表

`GET /documents?symbol=01810&doc_type=earnings&source=reports&date_from=2025-01-01&available=true&limit=50&cursor=...`。稳定顺序（source, doc_id）；limit 默认 50、上限 100；分页窗口上限 1000（超出 422 result_window_exceeded）。响应为 `{documents, total, limit, offset, next_cursor}`，每条含文档级元数据、`version_count`、`current_version_id`、`document_url` 与 `metadata_flags`；版本明细需读取单文档接口。游标绑定过滤集摘要与元数据 epoch（变化即 409 cursor_expired）。

`metadata_flags` 为**建议性**读时质量标志，不改动、不拒绝存储值：`period_invalid`（期间非 YYYY-MM-DD）、`period_suspect`（期间与发布日相差超 400 天，如 FY2023 年报期间写成上一财年末）、`period_missing`/`symbol_missing`（财报类文档缺期间/代码）。消费端应把被标记字段视为未核验。

## 表格证据

HTML 表格块（block_type=table）在可检索平铺文本（全表头逐行拼接）之外，持久化结构化 `rows`/`header_rows`（写入时有界：≤200 行、≤40 列、单元格 ≤200 字符）。`GET /evidence/{block_id}` 对表格块返回兄弟级 `table` 节：`{rows, header_rows, normalized_cells}`；数字解释为**读时**派生（千分位、括号负数、币种符号、百分号；歧义分组保守置空并给原因），evidence-block v1 契约本身不变。

## 搜索请求

```json
{"query":"毛利率 下滑","mode":"keyword","filters":{"symbols":["EXAMPLE"],"sources":["reports"],"collections":["source_documents"],"as_of":"2026-09-30T15:59:59Z","as_of_mode":"system"},"limit":20,"cursor":null}
```

响应包含 request_id、generation_id、normalized_filters、hits、next_cursor。实际 hit 包含 source/doc_id、source_version/source_sha256、extraction_id、block_id、text/snippet、locator、quality、evidence_url、source_version_url、score_kind 和 score。标题及 published/first_seen 等元数据需读取 document 接口。contracts/examples/search-response.json 为合成契约样例，实际响应以使用说明和实现为准。

分页游标绑定查询摘要、generation 和元数据 epoch；实际实现中索引换代或元数据变化返回 409 cursor_expired，需重新分页。limit 默认 20，上限 100；query 最多 2000 字符。混合模式未启用返回 422 mode_unavailable。

## 错误及兼容

400 无效参数；401 未认证；403 无权限；404 不存在/不可披露对象；409 游标过期或版本冲突；422 模式/解析状态不支持；429 配额耗尽；503 服务未就绪。错误体包含 code、message、request_id、retryable，不暴露路径或堆栈。契约破坏升级 API 主版本。

## 变化事件

事件包含 event_id、sequence、event_type、document identity、version_id、occurred_at、payload_version。客户端按 event_id 幂等。设计中的“事件保留期配置化、过期游标返回 410”当前未实现；尾页游标与轮询处理见使用说明。解析完成与源变化是不同事件，避免客户端对尚未处理的源版本误判可搜索。

## 权限

除 health/ready 外，业务接口需要认证；客户端 token 从环境/密钥存储注入。research.read、analysis.run、memory.review、admin.jobs 分离。个人笔记集合默认关闭；授权必须在召回前过滤。修改与管理接口独立权限。历史证据保留不等于绕过当前授权。当前部署为服务器 loopback，通过 SSH 隧道访问；后续如需开放远程服务，应使用 TLS 或受控反向代理。
