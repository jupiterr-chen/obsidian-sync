# 部署交付边界

> **2026-10-06更新**：生产现为67c6985r2；新代码9d1b04f已通过开发续验、尚未部署。后续按[发布与正文修复计划](../docs/36-validated-release-and-text-repair.md)准备并取得具体授权。下方2026-10-01状态与流程保留为历史背景，不代表最新线上状态。

**当前状态（2026-10-01）**：知识层代码与离线验证完成（P1-P6 离线部分），但**未部署任何生产服务**。第一层部署沿用根目录 `docker-compose.yml`（未改动）；知识层部署准备见 [docker-compose.knowledge.yml](docker-compose.knowledge.yml)（worker + 独立 API 端口 + 资源限制 + 只读 catalog 挂载），生产启用前置条件见 [P6 报告](../docs/progress/p6-report.md) 的 BLOCKED 清单。

部署顺序：检查原文可达与凭据 -> 独立runtime -> 样本 -> 影子回填 -> 检索验收 -> 受控客户端切换 -> 增量调度。生产环境、Vault路径和允许写入列表由配置指定。详细恢复及资源策略见 docs/06-operations.md。

## 知识层运维命令（部署后）

```sh
# 周期闭环（sync→快照→提取→索引→影响分析），幂等可重入
python -m knowledge worker --config config/knowledge.json --once

# 备份（SQLite 在线备份 API）与独立目录恢复演练
python scripts/backup-knowledge.py backup --db state/knowledge.sqlite3 --out backups --snapshots state/snapshots
python scripts/backup-knowledge.py drill --backup backups/<stamp>.db --snapshots state/snapshots

# 监控判定（心跳超时即告警）
#   state/knowledge-worker.json 的 updated_at 超过阈值 -> worker 异常
```

