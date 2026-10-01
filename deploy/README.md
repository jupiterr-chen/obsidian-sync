# 部署交付边界

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

