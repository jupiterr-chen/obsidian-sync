# 旧 research-kb 编排切换到 obsidian-sync 全栈（待用户明确确认后执行）

目标：一个项目目录、一套编排（`deploy/docker-compose.full.yml`：library + syncthing + status-collector + knowledge-worker + knowledge-api），数据家目录 `/vol2/1000/10.Develop/obsidian-sync`。**Windows 端零改动**：迁移 Syncthing 的设备身份与文件夹 ID，`ResearchVault` 文件夹对自动重连。

## 为什么目前仍在旧目录生成内容

旧栈还在生产服役（库服务、Vault 同步都由它承担）；在切换确认前我不动它的容器、配置和数据。过渡期知识层的 `自动研究候选/` 写入旧 vault 目录只是搭现有 Syncthing 文件夹对的便车——切换后写回目标改到新 vault，旧目录整体退役。

## 前置条件（全部满足才能执行）

1. 用户明确确认下线旧编排（本工程记录的硬性门槛）。
2. 知识层在真实数据上的核心验收完成：快照/提取/索引全绿 + OCR 回填完成 + `/api/v1` 行为回归通过。
3. 新目录就绪：`config/config.json`（容器内路径版）、`config/knowledge.json`、`.env`。

## 切换步骤（服务器；全程不删任何旧文件，旧目录即回滚方案）

```sh
# 0) 变量
OLD=/vol2/1000/10.Develop/research-kb
NEW=/vol2/1000/10.Develop/obsidian-sync
cd $NEW/repo/deploy

# 1) 停旧栈（保留容器与数据，可随时 up -d 回滚）
cd $OLD/repo && docker compose stop

# 2) 迁移数据到新目录（在线备份 catalog；复制 vault 与 syncthing 身份）
mkdir -p $NEW/catalog $NEW/vault
python3 - <<'PY'
import sqlite3
src = sqlite3.connect("OLD_CATALOG"); dst = sqlite3.connect("NEW_CATALOG")
src.backup(dst); dst.close(); src.close()
PY
cp -a $OLD/vault/. $NEW/vault/            # 含人工区与自动研究候选/
cp -a $OLD/state/syncthing $NEW/state/    # 设备身份/密钥/文件夹ID → Windows 无感重连

# 3) 容器路径版配置（config/config.json 的 root 用 /archive、/discord，catalog_db 用 /data/catalog/catalog.sqlite3 —— 与旧栈相同挂载布局）
#    knowledge.json 的 catalog_db 指向容器内 /catalog/catalog.sqlite3（只读挂载）

# 4) 起新栈
cd $NEW/repo/deploy && docker compose -f docker-compose.full.yml up -d --build

# 5) 验收
#    - curl http://192.168.1.150:8765/healthz 与旧版行为一致
#    - Windows ResearchVault 显示已连接（同一文件夹 ID）
#    - /api/kb/v1/health 正常；worker 心跳新鲜
#    - knowledge.json 的 writeback.analysis_dir 改为 $NEW/vault/自动研究候选
```

## 回滚

`docker compose -f docker-compose.full.yml down`（不带 -v）→ `cd $OLD/repo && docker compose up -d`。旧目录未被修改，双向同步停摆窗口内 Windows 端的改动会在旧栈回来后继续同步（Syncthing 自身处理）。

## 注意

- 旧目录退役清理（删除）是**另一次**明确授权，不在本切换内。
- Syncthing 全局发现/中继保持旧栈的关闭配置（LAN 本地发现 + 显式地址）。
- 切换窗口选在没有人工编辑 Vault 的时段，避免两端并发写。
