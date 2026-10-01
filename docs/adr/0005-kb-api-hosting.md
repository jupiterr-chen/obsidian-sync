# ADR 0005：/api/kb/v1 独立标准库 HTTP 服务

状态：已接受，2026-10-01（P3 实现）。

## 决定

知识 API 以**独立进程/端口**（默认 127.0.0.1:8766）的标准库 `ThreadingHTTPServer` 提供，不复用 library 的 `/api/v1` 进程，也不引入 FastAPI。理由：

1. 第一层 `/api/v1` 行为保持原样是硬约束；独立 handler 使两套 API 的鉴权、错误结构与发布节奏互不影响。
2. 部署上两者可同机不同端口（compose 各自服务），与"OCR/LLM 独立 worker"的方向一致。
3. FastAPI 迁移收益（校验/OpenAPI）不抵依赖引入与双框架维护成本；若 P4+ 需要异步或更大生态再评估（届时仅替换 handler 层， KbApi 逻辑类与存储无关）。

## 实现要点

- `KbApi` 逻辑类与传输解耦（单测直接调用方法）；HTTP Handler 仅做路由/鉴权/序列化。
- 鉴权：Bearer token + 权限 scope（research.read / analysis.run / admin.jobs）；token 来自配置文件或环境变量 `RESEARCHKB_KB_TOKEN`，仓库只放占位样例。无 token 一律 401，token 无权限 403。
- 错误结构统一 `{error: {code, message, request_id, retryable}}`，不泄路径/堆栈（docs/04）。
- 游标：opaque base64，绑定查询摘要与 generation；换 generation 或换查询 → 409 cursor_expired，不静默混页。
- 混合检索/分析任务默认 422 mode_unavailable / task_disabled（P4 前不开）。
- 事件：kb_events 表，sequence 单调，event_id 内容寻址幂等；`GET /changes?cursor=` 增量消费。

## 代价

- 两个端口/进程的运维面；标准库 HTTP 无连接池/异步（研究规模足够，A21 性能门禁实测后复查）。
