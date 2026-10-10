# 图表治理生产执行记录（2026-10-10）

## 授权与固定输入

用户在独立验收后要求“继续吧，开发完了就开始部署和后续任务”。本次发布已验收源码 `6679872c532d78161035f4af643329252a3f8738`，不再重复索要该次发布许可。部署执行由 Codex 负责；Luna 只编制只读盘点工具，没有访问生产或外发资料。

范围：从旧镜像 `obsidian-sync:9d1b04f` 构建 `obsidian-sync:6679872`，更新 library、knowledge-api、knowledge-worker；原 Syncthing、采集器、原始资料和历史 OCR 容器保留。模型与提供者外发开关继续关闭。本批使用绑定真实生产 extraction/block/hash 的 8 页清单和 26 张原图资产；另外 2 页为独立本地提取样本，未混入生产切换。

## 恢复入口

- 服务器 operation：`/vol2/1000/10.Develop/obsidian-sync/operations/chart-release-6679872-20261010/`。
- 本地检查点：`runtime/chart-release-6679872-20261010/`（Git 忽略）。
- 新源码及 compose：`/vol2/1000/10.Develop/obsidian-sync/releases/6679872/`。
- 旧 compose：`/vol2/1000/10.Develop/obsidian-sync/releases/9d1b04f/deploy/production-compose.json`。

当前续接入口为 `attempt-v2-launch.json` / `rebind-v2-result.json` / `isolated-result-v2.json` / `supervisor-v2-status.json` / `cutover-status.json` / `production-result.json`。首轮 `prepare-status.json` / `isolated-result.json` / `supervisor-status.json` 保留为历史证据，不能把首轮失败误当成 v2 最新状态。不要重新执行 prepare 或重复启动监督器，也不要根据旧 PID 停进程。容器身份重新 inspect，源码与脚本 hash 绑定在私有检查点。

## 执行检查点

2026-10-10 10:10（北京时间）：新镜像已构建；34,233,925,632 字节知识库一致性副本已写完，正在运行完整 `integrity_check`，生产 API 与 worker 仍运行旧版本。服务器监督进程已脱离 SSH 启动，等待备份恢复及隔离小批验收全部通过，再在 worker 空闲时自动切换。此时尚不能称发布完成。

准备步骤：SQLite backup API → 完整性检查与 SHA → Vault/快照/配置保全 → 隔离恢复 → 8 页激活、索引、正文发布、三连跑幂等、原文保留、回退及重建。隔离容器禁网，限 CPU/内存，不调用模型。

切换步骤：重新确认精确写者 → 暂停知识 API/worker → 冻结一致性备份与 Vault 文件 hash → 同一清单应用到生产 → 更新 library/API → 原始证据、投影证据、26 图片 hash、原 PDF HEAD 检查 → 恢复增量 worker → Windows 对账。普通资料读取在冻结知识写者期间继续可用。

## 回退方式

优先回退派生指针，保留新文件、原文和人工修改。当前版本为 `recover-v2.py`，使用 `manifests-v2/`，只处理本次 8 个 block，要求当前投影仍等于本次预期，否则停止；随后使用已验收的索引重建及阅读发布器恢复入口。运行前重新冻结准确写者，使用新镜像、禁网、精确挂载 state/vault/operation。脚本不会自动执行。首轮 `recover.py` 与 `manifests/` 仅留档，不用于本次 v2 的回退。

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

## 11:20 换行差异定位与第二次隔离验收

完整备份及恢复 hash 已通过。10:45 首轮隔离预检因 `stale block text` 退出，监督器正确停止，没有冻结生产写者或执行切换。11:12 后续检查发现本地样本曾由 Windows `write_text` 导出，再由 `read_text` 读取：原 CRLF 被扩成 CRCRLF，读取后成为两个 LF。8 页中 5 页因此清单 hash 不等于生产原始字节。此前“绑定生产 hash”的表述不够准确；身份和 PDF hash 正确，但没有在发布准备前复核数据库原始文本字节。这是本次清单准备遗漏，不是生产正文改变，也不需要重跑 OCR 或修改应用代码。

续验先将生产、备份、隔离副本的 8 页逐一只读比较，三者完全一致。再证明全部差异仅是原 CR 位置变成 LF、字符总数及所有其他位置不变；41 个已审查区间的原哈希全部匹配导出变换。用原始字节重算正文及区间哈希，范围下标、区域、图题、26 图像和 keep/exclude 意图不变，三份数据库的 `validate_manifest` 全部通过。新的 `manifests-v2/` 和 `rebind-v2-result.json` 保留完整元数据；原清单和失败结果不覆盖。未修改任何数据库原文。

11:19 服务器启动第二次禁网隔离容器 `obsidian-sync-chart-check-6679872-20261010-v2`，身份记录于 `attempt-v2-launch.json`；`check-v2.py` 已通过 8 页预检，正在构建隔离基线索引。11:20 实测 CPU 约 102%、内存 1.82 GiB、容器磁盘读 1.21 GB，属于实际计算阶段。此时生产 library/API 健康均为 HTTP 200，仍未切换。

`supervise-v2.py` 已脱离 SSH 运行，只有第二次隔离的激活/发布三连跑、原始证据保留及回退全部通过且容器退出 0、普通 worker 空闲时，才执行 `cutover-v2.py`。发布镜像仍是独立验收的 `6679872`，没有应用源码修改或模型调用。只读后验工具和 Windows 验证继续使用原 `postcheck.py`、`audit.py`、`windows-verify.py`；生产结果文件名不变。若监督器超时，先核查新容器实际活动和检查点，不重做已完成的备份或初始部署。

## 12:13 隔离全部通过，自动生产切换已开始

第二次隔离容器于 12:12:50 正常退出（0，无 OOM）。`isolated-result-v2.json` 为 `passed`：8 页/26 图像、三连跑幂等、原文 hash 保留、模型使用账本不变、8 页回退及恢复索引均通过。隔离前后 `blocks=231075`、`extractions=1624`、`usage_events=1` 一致；这条历史 usage 记录不是本轮模型调用。只读复核隔离库已回退到 0 个活动投影，发布 outbox 全部 1009 条 consumed。隔离发布时报告的 4 个待发布/4 个无正文属于全库状态，不能据此宣称所有历史资料均已修复。

12:12:54 监督器在普通 worker 空闲时开始 `cutover-v2.py`，阶段进入 `freezing_knowledge_writers`。12:13 检查时 library 和知识 API 仍返回 HTTP 200，停止请求尚在等待容器退出；此时尚未生成 `production-result.json` 或完成新版本切换。随后应依次核对冻结副本、生产小批应用、API/图像/原文可达和 worker 恢复，禁止并行重跑切换脚本。

Windows 12:13 再查 `Obsidian.com version` 返回无法找到正在运行的 Obsidian；当前无法确认 CLI 是否已被用户开启。后续真实默认搜索验收需要 Obsidian 运行并开启 CLI，仍不影响服务器自动发布和文件 hash 对账。不要把配置或文件检查记作应用内搜索已通过。
