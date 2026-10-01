# P1-01 接口探测报告：library 第一层能力与知识层接入面

日期：2026-10-01。方法：通读 `app/library/`（M0 导入，与源基线 5442e39 字节一致），对照 docs/02/03 需求。离线代码审计；**未连接生产服务**，运行时行为以 113 项回归测试为准（全部通过）。

## 1. 身份与版本模型（可直接复用）

- 文档身份 `(source, doc_id)`，`versions` 主键 `(source, doc_id, version_id)`（`catalog.py` SCHEMA）。
- 版本身份不可变语义已在库内实现：持久化的 `sha256/bytes` 不被后续快照覆盖；`observed_sha256` 与持久化身份不一致 → `state=conflict`（`commit_snapshot` 中 effective 计算）。同一文档恰好一个 `is_current` 版本（UPDATE 强制归一）。
- 版本状态机：`ready` / `missing` / `conflict`（`models.py`）。文档 `available` = 存在唯一 current 且其状态 ready。
- `first_seen_at` 首次落库后保留，`last_seen_at` 每次刷新（`commit_snapshot`）。
- 快照缺席的文档**不删除**，标 `available=0, status='not_in_snapshot'`（保留历史）。

## 2. 对知识层有用的读取接口

| 接口 | 说明 | 知识层用法 |
|---|---|---|
| `existing_version_map(source)` | (doc_id,version_id)→{sha256,bytes,observed_sha256,mtime_ns} | 增量对账输入 |
| `get_document / all_versions / list_documents` | 完整版本枚举 | 每日全量对账 |
| `recent_changes(limit≤200)` / `changes_since(at)` | 变更账本读取 | 新版本任务发现（优化项） |
| `source_state / counts / source_breakdown` | 来源健康与计数 | 监控 |
| `resolve_version_path(config, source, version)` | 版本→源文件绝对路径（路径穿越防护） | 快照读取入口 |
| `hash_file_stable(path)` | 同文件读前后 stat 一致的稳定哈希（fail-closed） | 快照前验证 |
| `FileLock` | 跨进程文件锁（flock/msvcrt） | 知识任务互斥 |
| `models.is_valid_id / safe_relpath` | ID 与相对路径校验 | 输入校验 |

**注意**：`Catalog.__init__` 会执行建表脚本并启用 WAL——知识侧读取现有 catalog 数据库必须用 `sqlite3.connect(file:...?mode=ro, uri=True)` 只读连接，不得用 `Catalog` 类打开生产库。

## 3. 变更账本（changes.py）

事件种类齐全：`ledger_baseline / imported / metadata_updated / new_version / current_changed / became_unavailable / recovered / content_conflict`。语义比较只看稳定字段，no-op 扫描零事件。

**限制（doc/11 已知）**：无外部消费游标接口、无保留策略承诺。知识层采用**每日全量版本对账**为主（幂等 upsert），账本仅作加速线索，不承担完整性责任。

## 4. API 面（`/api/v1`，行为必须保持）

- `/`（中文面板，CSP sandbox）、`/assets/dashboard.css|js`、`/healthz`
- `/api/v1/search`：元数据 LIKE 检索 + source/market/symbol/doc_type/date 过滤 + available_only + 分页；响应带 `kind=metadata_search` 与"无全文"声明
- `/api/v1/sources`、`/api/v1/status`
- `/api/v1/documents/{source}/{doc_id}`（含 versions 数组与 file_url）
- `/api/v1/files/{source}/{doc_id}?version=&download=`：HEAD/Range(206/416)/强 ETag(304)/409 fail-closed/HTML sandbox CSP/UTF-8 文件名
- `/api/v1/versions/{source}/{doc_id}` = documents 别名

**限制**：无鉴权（LAN 绑定模型）。知识接口 `/api/kb/v1` 必须自带权限过滤（P3 A13），不继承此假设。

## 5. 原文服务验证语义（fileserve.py）

`open_validated` 在**同一文件描述符**上先哈希再服务，任何不匹配 fail-closed（409）。上游字节被覆盖 → `content_conflict` + 不可服务。

**缺口（doc/11 明示，P1-02 解决）**：无不可变快照存储——上游覆盖历史字节后旧证据永久丢失。知识层增加内容寻址快照库：`hash_file_stable` 验证 → 同 fd 流式复制到临时文件 → 复验哈希 → 原子 rename → 绑定 `(source,doc_id,version_id)→sha256`。同哈希跨来源共享物理文件（doc/02）。

## 6. 存储与运行时

- SQLite（WAL、busy_timeout 15s、单写者模型）；`ingest_runs`/`sources`/`meta` 表支撑状态页。
- 调度：进程内小时级（`__main__`/runtime），ingest+render 由 FileLock 互斥；来源失败按来源隔离并脱敏。
- 部署：docker-compose（library + syncthing sidecar + status-collector），源只读挂载。

## 7. 来源清单与权限（A01 前置）

| 来源 | 类型 | 身份来源 | 只读访问 |
|---|---|---|---|
| reports | SQLite 归档（manifest+artifacts，state='ready'）+ 文件根 | report_id + artifact sha256 | 服务器挂载（当前不可达） |
| discord | JSONL index（documents.jsonl + meta.json）+ 附件根 | doc_id + 声明 sha256 | 服务器挂载（当前不可达） |

**BLOCKED（真实清单核对 A01）**：无服务器访问。现有唯一清单参照为 `ResearchVault/资料目录/_catalog.csv`（523 条，docs/00 基线），为生成卡片而非服务端清单，不能替代 A01 的服务端对账。真实清单核对推迟到获得只读源访问后执行，届时用 `scripts/verify-api.py` + 新增对账工具完成。

## 8. 知识层设计决定（详见 ADR0003）

1. 独立 `state/knowledge.sqlite3`，不复用 catalog 库文件；通过只读连接消费 catalog。
2. 快照库 `snapshots/` 内容寻址（sha256 二级目录），去重共享，绝不覆盖已存在 blob。
3. 任务幂等键 `(source, doc_id, version_id, stage, config_digest)` 唯一约束（doc/02 jobs 表）。
4. 全量对账幂等 upsert 为主，变更账本为加速线索。

—— self-reviewed（单一 agent）；建议 P3 前由独立复核抽查第 4/5 节与实际 API 行为。
