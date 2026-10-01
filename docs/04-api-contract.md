# 查询与集成 API 契约（设计稿）

新服务前缀 `/api/kb/v1`。现有 library 路由保持原有含义。当前没有可运行 API；本文件是 P3 实现的验收契约。

|方法与路径|用途|
|---|---|
|GET /health|仅存活，不返回敏感配置|
|GET /ready|数据库和 active generation 就绪|
|POST /search|关键词/混合检索，日期/公司/权限筛选|
|GET /documents/{source}/{doc_id}|元数据、可访问版本和正文状态|
|GET /documents/{source}/{doc_id}/versions/{version_id}|固定源版本|
|GET /evidence/{block_id}|不可变证据及上下文|
|GET /extractions/{extraction_id}/blocks|游标分页正文块|
|GET /changes?cursor=...|新增/修订/撤回事件，供客户端增量消费|
|POST /analysis-runs|后续带引用分析任务，默认未启用|
|GET /analysis-runs/{run_id}|状态、草稿、用量和验证结果|
|POST /memory-proposals/{id}/review|后续确认/拒绝，要求写权限|

## 搜索请求

```json
{"query":"毛利率 下滑","mode":"keyword","filters":{"symbols":["EXAMPLE"],"sources":["reports"],"collections":["source_documents"],"as_of":"2026-09-30T15:59:59Z","as_of_mode":"system"},"limit":20,"cursor":null}
```

响应包含 request_id、generation_id、normalized_filters、hits、next_cursor。hit 包含 document identity、source_version、extraction_id、block_id、text/snippet、locator、quality、published/first_seen 时间、evidence_url、source_version_url、score_kind 和 score。返回合成样例见 contracts/examples/search-response.json。

分页游标绑定查询摘要和 generation；发布新索引后旧游标仍指向可用旧版本或返回 409 cursor_expired，不能静默混页。limit 默认 20，上限 100；query 初定最多 2000 字符。混合模式未启用返回 422 mode_unavailable。

## 错误及兼容

400 无效参数；401 未认证；403 无权限；404 不存在/不可披露对象；409 游标过期或版本冲突；422 模式/解析状态不支持；429 配额耗尽；503 服务未就绪。错误体包含 code、message、request_id、retryable，不暴露路径或堆栈。契约破坏升级 API 主版本。

## 变化事件

事件包含 event_id、sequence、event_type、document identity、source_version、occurred_at、payload_version。至少一次投递，客户端按 event_id 幂等。事件保留期配置化，过期游标返回 410 并要求全量对账。解析完成与源变化是不同事件，避免客户端对尚未处理的源版本误判可搜索。

## 权限

所有知识接口认证；客户端 token 从环境/密钥存储注入。research.read、analysis.run、memory.review、admin.jobs 分离。个人笔记集合默认关闭；授权必须在召回前过滤。修改与管理接口独立权限。历史证据保留不等于绕过当前授权。生产 TLS 或受控反向代理，不将无鉴权局域网地址暴露公网。
