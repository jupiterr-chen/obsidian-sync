# 基础迁移完成（2026-10-04）

**结果：基础迁移、旧栈停机与必要验证已完成。** 2026-10-04 13:53:58（Asia/Shanghai）新栈恢复健康，14:03完成收尾验证。旧目录、容器和备份均保留，未删除/递归移动、未改权限、未调用远程模型。

## 当前服务与入口

- 数据家目录：`/vol2/1000/10.Develop/obsidian-sync`。
- 部署源码：`releases/42d0dd4`；镜像 `obsidian-sync:42d0dd4`。由已有本地知识运行时加当前源码构建，离线依赖冒烟通过，未下载模型。
- **实际生产编排**：`/vol2/1000/10.Develop/obsidian-sync/releases/42d0dd4/deploy/migration-compose.json`；私有配置位于同目录 `config/`，不要打印/提交凭据。
- [资料服务](http://192.168.1.150:8765)、[健康检查](http://192.168.1.150:8765/healthz)：原入口保持。
- 知识 API：服务器 `127.0.0.1:8766/api/kb/v1`，仅本机可达、凭据仅 research.read；普通检索、原有证据与固定快照可用。
- 新四容器：`obsidian-sync-library`、`obsidian-sync-syncthing`、`obsidian-sync-status-collector`、`obsidian-sync-knowledge-api` 全部 running，配置了健康检查的三个均 healthy。
- 旧三个 `research-kb-*` 容器均 exited；全部新服务的数据挂载已切到新目录，没有继续引用旧项目的数据挂载。
- 第一层每小时检查/增量入库保持3600秒周期。**知识层自动 worker 暂未启动，故新增全文自动提取/重建索引尚未在本次上线**；保留现有知识数据和检索，避免新recipe触发未经计划的全量重提取。

## 数据和验收结果

|项目|实际结果|
|---|---|
|目录|538 documents / 528 versions；523份当前可用卡片；文档和版本业务字段全量一致，仅正常接入的 last_seen_at/observed_at 更新|
|知识库|1,123 extractions / 213,829 blocks；所有旧表共同字段逐行摘要全量一致，包含索引、历史任务、分析、账本、记忆/outbox|
|备份恢复|catalog/knowledge均使用SQLite backup API；独立恢复文件哈希一致、integrity_check=ok；新镜像升级恢复副本后共同字段逐行一致，普通检索成功|
|原文/快照|524份备份快照逐个SHA256/bytes一致；新服务挂载下524份ready原文逐个全量核验通过|
|兼容入口|两类来源的旧文件URL与固定snapshot URL均200且返回字节SHA一致；旧block evidence和版本链接解析成功|
|增量三连跑|每次ok=true、changes=0、cards_written=0、cards_unchanged=523、pages_written=0、human_initialized=0|
|服务端Vault|切换前后541文件，0缺失、0内容变化，人工区与已有研究稿保留|
|Windows Vault|切换前备份545文件；最终0缺失、0内容变化。原Syncthing程序先前未运行，本轮备份后启动恢复连接|
|同步|同设备身份、同research-vault文件夹；两端connected/idle，needFiles=0/needBytes=0/pullErrors=0|
|新目录写入|旧catalog保持84条ingest_runs，新catalog达到88条；新monitor/日志持续写入新目录；用户crontab未发现旧research-kb任务|

数据库初次机械对比发现catalog运行时间字段不同，进一步逐列证明仅last_seen_at/observed_at及接入运行记录/状态变化，业务身份与内容未变；知识库所有原有字段完全一致。未把正常运行元数据变动当作丢失，也未略过差异。

## 本次落地的部署处理

实际CLI未将配置snapshot_root传入API构造器，导致默认从`/app/state/snapshots`读取而404。将knowledge-api工作目录设为`/`，与`/state/snapshots`挂载对齐，随后真实固定快照HTTP哈希核验通过。仓库full compose同步此设置；CLI根治列入fix清单，不扩大本次交付。

模型egress全部false，OCR远程fallback关闭；新增自动候选导出未启用；知识API限制loopback/read scope，public-as-of未作为本轮验收能力。full compose为knowledge-worker增加`enhanced-worker`显式profile，避免默认启动引发全量重提取。现有shadow/shadow2、运行库和旧失败/待处理历史全部保留。

## 备份、回退与恢复点

主备份：`/vol2/1000/10.Develop/obsidian-sync/backups/migration-20261004T054637Z`。

- `catalog.sqlite3`、`knowledge.sqlite3`：在线备份；`restore/`：已经实际运行过的隔离恢复副本。
- `knowledge-snapshots/`：524份独立快照副本；`old-vault/`、`old-repo/`、`old-tools/`、`catalog-files/`：在线阶段文件备份。
- `final/`：旧写者停止后的catalog/knowledge一致备份、完整Vault、old-state（含Syncthing身份/索引）、原宿主配置和私有哈希清单。
- `cutover-identities.json`记录准确旧容器ID；`completion.json`、`post-cutover-check.json`、`post-cutover-db-check.json`、`originals-full-check.json`为实际证据。
- 旧目录`/vol2/1000/10.Develop/research-kb`完整保留；旧工具/历史备份/历史恢复目录另存新家目录`legacy-research-kb/`。
- 本机Vault备份：`runtime/review-fifth-20261004/windows-vault-before-sync/`，仅本地忽略目录。

需要回退时，先停止准确的新四容器，保全**切换后的新库/快照/人工修改**到新的私有备份目录，再按差异恢复人工内容，随后启动保留的旧三容器并验证入口及Windows重连。不能直接覆盖旧Vault，也不能同时启动同身份的新旧Syncthing。不要运行`down -v`或清理旧目录。本轮完成的是隔离恢复演练，未为了演示回滚而再次中断已恢复的生产服务。

## 后续（不阻断本次基础交付）

1. 增强功能V01–V04及CLI snapshot_root配置传递进入fix清单；按相应能力启用时修复，不重新整包迁移。
2. 设计并开启仅新增内容的知识worker；全量旧recipe升级作为独立可预算任务。当前小时自动化只保证第一层同步，不能宣称新增全文已自动处理。
3. OCR/分析金标准仍NOT_RUN，七天稳定观察尚未完成；不能将本次完整性验收写作内容质量验收。
4. 自动化`glm-research-kb`维持PAUSED，避免旧监控重复执行迁移。

[脱敏机器证据](migration-evidence-20261004.json)；[修复清单及任务指导](../23-fifth-review-taskbook.md)。
