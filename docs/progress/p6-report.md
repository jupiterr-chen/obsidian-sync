# P6 验收报告：自动运行与运维（离线就绪）

日期：2026-10-01。执行：main-agent（self-reviewed）。完成度：**源码实现 + 离线验证 + 部署准备**；生产部署、7 天稳定性与真实恢复演练 NOT_RUN/BLOCKED。

## 交付内容

### P6-01 调度与监控（`worker.py` + `deploy/docker-compose.knowledge.yml`）

- **KnowledgeWorker**：周期（默认 1h，可配）执行完整闭环 sync → snapshots → extracts → rebuild-index → 影响分析（新版本→claim 复核候选）→ 计数快照；沿用第一层模式：持久化诚实状态文件 `state/knowledge-worker.json`（state/attempt/last_ok/last_error/next_check_at + **15s 心跳**），`worker_is_stale()` 供监控判定 worker 死亡而非旧成功绿灯常亮；与手工命令共用 knowledge 文件锁，互不竞态。
- CLI：`python -m knowledge worker [--once] [--interval N]`。
- **compose（部署准备，未部署）**：`deploy/docker-compose.knowledge.yml` 定义 knowledge-worker（CPU 1.5/1g，healthcheck 查 worker 心跳新鲜度）与 knowledge-api（CPU 0.5/512m，绑定 127.0.0.1:8766，healthcheck 打 /health）；catalog 以**只读**挂载给知识层（ADR0003）；日志轮转限制；OCR/分析 worker 明确缺席（引擎未选型，BLOCKED）。第一层 compose 不改动。

### P6-02 备份与恢复演练（`scripts/backup-knowledge.py`）

- **backup**：SQLite 在线备份 API（绝不拷贝运行中的 WAL 库文件——AGENTS 约束）+ 快照 blob 目录复制 + 表计数报告 + RPO 记录。
- **drill**：在**独立目录**恢复备份副本，验证 integrity_check、11 张表计数、全部 blob 的大小+sha256 与账本一致；损坏备份被检出（测试覆盖）；记录 RTO（恢复+校验墙钟）；生产库零接触。
- **BLOCKED（生产）**：A22 真实 RPO≤24h/RTO≤4h 演练与 7 天记录（A21）需生产主机；工具与流程已就绪。

### P6-03 应用接入（`scripts/kb-client-example.py`）

- 参考客户端演示 docs/05 通用接入上下文清单（purpose/query/filters/as_of_mode/generation_id/evidence_refs/claim_revisions/result_digest=sha256）的持久化构造——消费方保存后可重放定位同一批历史证据。
- token 走环境变量/参数，不落仓库。

## 验收场景对照

| 场景 | 结果 |
|---|---|
| A21 稳定性与延迟 | NOT_RUN（生产）；调度/心跳/互斥/幂等闭环离线验证（202 测试） |
| A22 恢复 | PASS（离线演练）：备份→独立目录恢复→表计数/blob 哈希全验通过；损坏备份检出。**真实 RPO/RTO BLOCKED** |
| P6-03 客户端 | 接入上下文清单机制 PASS（离线）；真实客户端验收 BLOCKED |
| 调度连续性 | 7 天记录 NOT_RUN；机制上：周期任务幂等（A02 测试覆盖三连跑）、锁互斥、心跳可监控 |

## 测试

**202 OK (1 skipped)** = 196 + 6 P6（worker 周期幂等+索引发布、新版本影响挂钩、心跳状态/陈旧判定、worker 线程生命周期、备份→演练全链路、损坏备份检出）。

## 生产启用前缺项（BLOCKED 清单）

1. 生产主机访问、目标目录、运行用户与回滚方案。
2. 真实源（reports/discord）只读路径或服务器地址。
3. `config/knowledge.json` 生产实例 + API token 生成注入。
4. OCR 引擎与模型供应商选型（worker 需 CPU/GPU 重新评估资源限额）。
5. 7 天稳定性与性能实测（A21）、真实恢复演练（A22）、523 基线全量对账（A14）。
