# 旧 research-kb 编排切换到 obsidian-sync 全栈（待用户明确确认后执行）

目标：一个项目目录、一套编排（`deploy/docker-compose.full.yml`：library + syncthing + status-collector + knowledge-worker + knowledge-api，镜像 `Dockerfile.knowledge` 含锁定依赖与预置 OCR 模型），数据家目录 `/vol2/1000/10.Develop/obsidian-sync`。**Windows 端零改动**：迁移 Syncthing 设备身份与文件夹 ID，`ResearchVault` 文件夹对自动重连。

## 为什么目前仍在旧目录生成内容

旧栈还在生产服役；切换确认前不动它的容器、配置和数据。过渡期 `自动研究候选/` 写入旧 vault 是搭现有同步文件夹对的便车——切换后写回目标改到新 vault，旧目录整体退役。

## 前置条件（全部满足才执行）

1. 用户明确确认下线旧编排（硬性门槛，另需单独授权才清理旧目录）。
2. 真实数据核心验收完成：快照/提取/索引全绿 + OCR 回填完成 + `/api/v1` 行为回归 + 评审修复复验通过。
3. 新目录就绪：`deploy/config/config.json`（容器内路径版）、`deploy/config/knowledge.json`、`deploy/.env`（compose 变量）。

## 切换步骤（服务器；全程不删任何旧文件）

```sh
# 0) 变量与配置检查
OLD=/vol2/1000/10.Develop/research-kb
NEW=/vol2/1000/10.Develop/obsidian-sync
cd $NEW/repo/deploy
docker compose -f docker-compose.full.yml config >/dev/null && echo "compose config OK"

# 1) 冻结所有写者（R13：包括独立回填 worker，保证一致的切换点）
pkill -f "knowledge run-extracts" || true          # 后台 OCR 回填
pkill -f "knowledge worker" || true                # 周期 worker（如已部署）
cd $OLD/repo && docker compose stop                # 旧栈（保留容器与数据）

# 2) 在线备份 catalog（真实路径，非占位；SQLite backup API，不拷贝 WAL 文件）
mkdir -p $NEW/catalog $NEW/vault $NEW/state
python3 - <<'PY'
import sqlite3
src = sqlite3.connect("/vol2/1000/10.Develop/research-kb/catalog/catalog.sqlite3")
dst = sqlite3.connect("/vol2/1000/10.Develop/obsidian-sync/catalog/catalog.sqlite3")
src.backup(dst); dst.close(); src.close()
print("catalog online backup done")
PY

# 3) 复制 vault 与 Syncthing 身份（设备密钥/文件夹 ID → Windows 无感重连）
cp -a $OLD/vault/. $NEW/vault/            # 含人工区与自动研究候选/
cp -a $OLD/state/syncthing $NEW/state/

# 4) 容器路径版配置：config/config.json 的 root 用 /archive、/discord，
#    catalog_db=/data/catalog/catalog.sqlite3（与旧栈相同挂载布局）；
#    knowledge.json 的 catalog_db=/catalog/catalog.sqlite3（只读挂载），
#    writeback.analysis_dir=$NEW/vault/自动研究候选。

# 5) 起新栈并自检
docker compose -f docker-compose.full.yml up -d --build
curl -sS http://192.168.1.150:8765/healthz | python3 -m json.tool
curl -sS http://127.0.0.1:8766/api/kb/v1/health | python3 -m json.tool

# 6) 切换后写入对账（R13）：观察一个调度周期后的增量是否只落在新目录
grep -c "knowledge" $NEW/state/ingest.log || true
ls $NEW/state/knowledge.sqlite3-wal 2>/dev/null && echo "knowledge writers active"
```

Windows 端确认：Syncthing `ResearchVault` 文件夹显示已连接（同一文件夹 ID、同一设备身份）。

## 回滚（保护切换后产生的新写入，不是零丢失承诺）

1. `cd $NEW/repo/deploy && docker compose -f docker-compose.full.yml down`（不带 -v）。
2. **先收割切换后新写入**：`$NEW/state`（knowledge 库/快照）、`$NEW/vault/自动研究候选/` 与人工在新生成区的任何编辑——打包保存到回滚备份目录（不删除）。
3. 把 vault 中切换后的人工编辑按文件同步回旧目录（Syncthing 停摆窗口内的两端改动需要人工合并；冲突文件保留两份）。
4. `cd $OLD/repo && docker compose up -d`；验收 `/healthz` 与 Windows 重连。

## 注意

- 旧目录退役清理（删除）是**另一次**明确授权，不在本切换内。
- Syncthing 保持旧栈的关闭全局发现/中继配置（LAN 本地发现 + 显式地址）。
- 切换窗口选在没有人工编辑 Vault 的时段；切换前冻结写者（步骤 1）确保一致快照点。
- 回填如未跑完即切换：新栈的 knowledge worker 会按 outbox/任务表继续，幂等可续。
