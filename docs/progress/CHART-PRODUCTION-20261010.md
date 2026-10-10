# 图表治理生产执行记录（2026-10-10）

## 授权与固定输入

用户在独立验收后要求“继续吧，开发完了就开始部署和后续任务”。本次发布已验收源码 `6679872c532d78161035f4af643329252a3f8738`，不再重复索要该次发布许可。部署执行由 Codex 负责；Luna 只编制只读盘点工具，没有访问生产或外发资料。

范围：从旧镜像 `obsidian-sync:9d1b04f` 构建 `obsidian-sync:6679872`，更新 library、knowledge-api、knowledge-worker；原 Syncthing、采集器、原始资料和历史 OCR 容器保留。模型与提供者外发开关继续关闭。本批使用绑定真实生产 extraction/block/hash 的 8 页清单和 26 张原图资产；另外 2 页为独立本地提取样本，未混入生产切换。

## 恢复入口

- 服务器 operation：`/vol2/1000/10.Develop/obsidian-sync/operations/chart-release-6679872-20261010/`。
- 本地检查点：`runtime/chart-release-6679872-20261010/`（Git 忽略）。
- 新源码及 compose：`/vol2/1000/10.Develop/obsidian-sync/releases/6679872/`。
- 旧 compose：`/vol2/1000/10.Develop/obsidian-sync/releases/9d1b04f/deploy/production-compose.json`。

`prepare-status.json` / `isolated-result.json` / `supervisor-status.json` / `cutover-status.json` / `production-result.json` 是阶段入口。不要重新执行已启动的 prepare/supervise/cutover，也不要根据旧 PID 停进程。容器身份重新 inspect，源码与脚本 hash 绑定在私有检查点。

## 执行检查点

2026-10-10 10:10（北京时间）：新镜像已构建；34,233,925,632 字节知识库一致性副本已写完，正在运行完整 `integrity_check`，生产 API 与 worker 仍运行旧版本。服务器监督进程已脱离 SSH 启动，等待备份恢复及隔离小批验收全部通过，再在 worker 空闲时自动切换。此时尚不能称发布完成。

准备步骤：SQLite backup API → 完整性检查与 SHA → Vault/快照/配置保全 → 隔离恢复 → 8 页激活、索引、正文发布、三连跑幂等、原文保留、回退及重建。隔离容器禁网，限 CPU/内存，不调用模型。

切换步骤：重新确认精确写者 → 暂停知识 API/worker → 冻结一致性备份与 Vault 文件 hash → 同一清单应用到生产 → 更新 library/API → 原始证据、投影证据、26 图片 hash、原 PDF HEAD 检查 → 恢复增量 worker → Windows 对账。普通资料读取在冻结知识写者期间继续可用。

## 回退方式

优先回退派生指针，保留新文件、原文和人工修改。`recover.py` 只处理本次 8 个 block，要求当前投影仍等于本次预期，否则停止；随后使用已验收的索引重建及阅读发布器恢复入口。运行前重新冻结准确写者，使用新镜像、禁网、精确挂载 state/vault/operation。脚本不会自动执行。

冻结副本在 `frozen-backup/`，预备副本在 `backup/`，隔离恢复在 `isolated/`；各自有 hash/清单。若需要数据库级恢复，先保护切换后新增数据并单独对账，不能把旧 DB 直接覆盖当前 DB。旧镜像和旧 compose 保留；停止的历史 research-kb / GLM OCR 容器不重启。

## 后续验收面

1. 核对真实运行镜像、健康、worker 增量周期、未启用模型；核对源 block/提取/使用账本未被小批改变。
2. 核对新阅读文件与图表资产到 Windows 的 hash，旧证据和原文继续可达。
3. 只读全库候选盘点，不将规则命中当已确认图表。先开启有界候选发现，候选整体暂缓仍为关闭；开启前量化表格/混合页误报与受影响分析范围。
4. 旧副本仅对已登记 owner、hash 一致、非当前入口且无人工引用的精确文件准备搜索排除；不删除/移动。当前本地 Obsidian CLI 未开启，文件/config 检查不能冒充实际默认搜索验收。
5. 未确认区域、数字/表格的真实语义核对、已有研究结果重算不在本次 8 页上线完成的声明内。

最终结果随实测检查点更新；本记录不代替 [独立验收报告](CHART-CONTENT-ACCEPTANCE-20261010.md) 或 [操作手册](../42-chart-governance-operations.md)。

## 10:42 检查点与持续跟进

服务器仍处于 `backup_integrity_check`，发布监督器等待隔离验收；尚未停写或切换生产。备份检查进程运行约 41 分钟，CPU 累计约 21 分钟，磁盘读取继续增加；library 和 knowledge API 健康均为 HTTP 200。备份中有 1 个活动、28 个退役索引世代，记录的 postings 总数 108,943,090；这一全库物理校验规模不等于本次只处理的 8 页。没有可靠剩余时间百分比。

沿用现有 `glm-research-kb` 会话自动跟进，已改名为“图表发布与同步验收”并恢复每半小时运行；旧 OCR 汇报任务不再执行。后续固定为：核对服务器阶段与服务 → 上线后只读 `postcheck.py`/schema 3 `audit.py` → 下载元数据 → Windows 文件 hash 对账 → 精确旧副本搜索排除 → 应用实际搜索验证 → 更新记录和推送后暂停跟进。不要启动第二个发布监督器。

本地 `windows-verify.py` 在应用搜索排除前还会检查 Windows 尚未同步的人工引用、文件 hash、当前入口，并保留 `.obsidian/app.json` 原配置与备份；遇到人工引用则保护，不按服务器旧快照覆盖。当前该脚本只完成准备，没有改真实 Obsidian 配置。真实 Obsidian 搜索验证尚待用户开启 CLI，已发送请求；该项不阻断服务器发布。

服务器的准备/发布监督进程独立于 SSH 和本机。会话自动跟进与 Windows 验收需要本机和 Codex 应用可用，关机期间服务器流程继续，后续回来读取检查点续验；参见 [官方计划任务说明](https://learn.chatgpt.com/docs/automations?surface=app)。

另列后置运维项：评估历史索引世代保留与备份时长。这里只记录事实，不清理索引、不 VACUUM、不因此改变本次发布源码或重新开启开发返工。
