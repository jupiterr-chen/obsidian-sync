# 基础迁移恢复点（2026-10-04）

## M1：只读盘点完成

- 当前源码评审基线7ded572；310项回归OK/2 skip。
- 用户要求降低非核心缺陷对交付的阻碍，按docs/23的M1–M6推进；V01–V04进入对应功能启用前的fix清单。
- 旧research-kb三容器运行，library/syncthing healthy；新目录已有knowledge DB/snapshots，尚无catalog/vault/deploy/config。
- 新宿主配置仍引用旧catalog；未发现独立knowledge/shadow处理进程。后续冻结前必须再检查，不能使用本次PID或假定持续无写者。
- 本阶段仅SSH只读，未停机、未复制或覆盖生产文件。
- 详细私有盘点：本地runtime/review-fifth-20261004/migration-preflight.json（忽略不入Git）。

## 当前下一动作

M2备份与隔离恢复、M3新配置及能力边界。尚未达到可直接停机状态；所缺是迁移准备，不是增强功能修复或重复授权。
