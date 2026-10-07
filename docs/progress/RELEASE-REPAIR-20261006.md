# 生产发布及正文修复运行记录

## 2026-10-07：Obsidian 保存 EPERM 已修复

用户截图报错为 Markdown **保存失败**：`EPERM: operation not permitted, open`。不是 OCR 批次整体失败。本地复现同一文件只读打开成功、可写打开被拒绝；盘点 ResearchVault 的 2,049 个 Markdown 带 Windows ReadOnly 属性，两端 Syncthing 的 `research-vault` 均为 `ignorePerms=false`。服务器对应文件也缺写权限位。

用户明确回复“修复把”后，执行了此项有限授权：

- 备份两端私有 Syncthing 配置，经 REST PATCH **只改 `research-vault.ignorePerms=true`**；确认其他字段未变、无需重启。
- 原生 PowerShell 按既定清单清除本地 2,049 个 Markdown 的 ReadOnly 位；未改正文、NTFS ACL、目录权限或服务器 chmod/chown，未移动/删除文件。
- 逐文件校验 2,049/2,049 内容 SHA256 和 NTFS SDDL 未变；剩余只读 Markdown 为 0。原报错文件、开始阅读、研究区 README 均可用读写模式打开，验证未写入任何内容。
- 最终两端同步均为 idle、needTotalItems=0、needBytes=0、pullErrors=0；正式 OCR 容器持续运行，已进入第 212/458 份，已发布批次仍为 200 份。

本地恢复依据：`runtime/obsidian-readonly-20261007/plan.json`、`attributes-before-20261007T110717Z.json`、`attributes-result-20261007T110717Z.json`。Windows 配置备份在同目录 `windows-/20261007T110632Z/`；服务器配置备份在 `/vol2/1000/10.Develop/obsidian-sync/operations/readonly-fix-20261007/server-/20261007T110639Z/`。这些私有文件不提交，包含配置的备份不得打印或外发。后续部署保留两端此 folder 的 ignorePerms 设置，避免旧配置覆盖。

本修复仅解决 Obsidian 保存权限。此前字形映射问题仍在独立 fix 清单；本次未修改应用源码、重启 OCR 或重新登记识别批次。

## 最新执行状态：正式自动批次已启动

用户再次明确要求立即使用既有验收版本开始服务器重识别，新增错误另列 fix，不再扩大代码修改或等待用户回来。**应用源码仍为 `9d1b04f`，没有为新发现的问题修改应用代码。** 先前“样本结束停在人工检查点”的后续安排已被本段取代。

服务器独立监督进程已启动 `ops_cutover_repair_20261006.py`（首次 PID 278018，仅作历史线索）。它自动冻结准确旧 worker/API 写者，保存最终数据库/Vault 回退副本，启动既有验收镜像的 library/API，再启动 `obsidian-sync-repair-9d1b04f-20261006` 正式处理冻结的 **458** 份候选。每 20 份重建索引和发布阅读正文，完成后自动恢复新版增量 worker；无需再点头或回来触发。异常自动停止并保留结果，服务和数据不被盲目恢复覆盖。

正式状态入口：服务器 operation 下 `production/supervisor-status.json`、`production/repair-status.json`；日志 `cutover.log`、`production/commands.log`。正式回退副本：`production/cutover-backup/`，原文备份仍在 `backup/snapshots/`。本地电脑关机不影响服务器独立进程/Docker；Windows 同步在下次开机后继续。

### 单独后置 fix（不阻塞本次任务，不声称已修复）

真实样本 13（415 页长报告）发现：PDF 字形映射错误可产出合法 Unicode 汉字乱码；现有控制字符检测未覆盖，native 提取可能误标 ready。原文 p2 与解析结果不一致，私有证据为 `sample-item-0013.json`、`verify-13-p2.png`。该问题独立登记；本次重处理不能据 ready 声称全部内容已人工验真，LLM 仍关闭。其余已对照样本中，原生样本关键数值 194.01/194.08/13.2%/7.0% 和混合 OCR 页 671.83 与原文相符。本次不扩大到该问题的代码开发。

## 用户授权与固定输入

2026-10-06 用户明确要求 Codex 直接完成本次生产发布与正文修复，不交其他 agent；要求先完成本地工作，确认服务器任务独立运行后通知可退出。本次操作不再请求重复授权。真实模型、付费调用、远程 OCR、资料外发保持关闭；不删除或归档旧 Vault 文件。

- 应用源码：`9d1b04fc1ae7fa8a6e067af46f65b842773a523e`，代码验收见 [SF 报告](SF-ACCEPTANCE-20261006.md)。
- 源码 tar SHA256：`d92a8e8426e04a40f9fc6d0229e5af27cf37860e82e61129300944b15f25ca30`。
- 基础运行环境：生产现用镜像 `sha256:9318382ce31a74323fb48a279be4bb83712826c5ed4e3f1cc104c7df32381173`；新镜像只复制固定源码，不安装或下载依赖。
- 操作 ID：`release-9d1b04f-20261006`。
- 本地私有恢复资料：`runtime/release-9d1b04f-20261006/`（不提交）。
- 服务器操作根：`/vol2/1000/10.Develop/obsidian-sync/operations/release-9d1b04f-20261006/`。
- 运维脚本：[准备器](../../scripts/ops_release_20261006.py)、[离线样本/批次执行器](../../scripts/ops_text_repair_20261006.py)。它们不是新的应用版本；应用仍固定为上述 SHA。

## 已确认状态

启动前生产五容器健康/运行；应用为 `67c6985r2`。原始快照 524 个文件、1,756,869,960 bytes；Vault 1,855 个文件、144,007,152 bytes；磁盘空闲约 716 GB。以上是文件盘点，不等于可修复文档数。

准备器已通过 SSH 启动为独立 session：首次 PID `267341`，随后新 SSH 连接核对 PPID=1、session=267341，证明原连接退出后仍执行。PID 仅为历史证据，恢复时须重新检查身份，不能照旧 PID 停进程。当前阶段由服务器状态文件决定；本记录不声称生产切换已完成。

备份与隔离恢复已完成；首次 BuildKit 将裸 sha256 ID 误认为仓库名，构建停止且未切换生产。运维脚本改为先把准确镜像 ID 绑定到本地标签，再用关闭网络的本地 legacy builder，从已有恢复点续建成功；变更记录为服务器 `build-adjustment.json`，不改变应用源码。

新镜像 `obsidian-sync:9d1b04f` 已构建，ID 为 `sha256:e964c9b8fd16a8fafc1f4f12d6f2c4f740041c8bf2ea1608d59d45baa0b5110b`。独立样本容器 ID `fa2ac867feede8d9e65c10b9843a22bacd9c9b568823803812c3d0de9e4db777`，再次建立 SSH 连接确认容器 Up、状态进入全库盘点。运行 recipe 为 `37fae92f154e57678aa4fda605fc3874ea339fd39860baf564c2198e807202f4`。**此时可关闭本地 Codex；服务器样本任务会自行继续至验收检查点。生产切换与正式历史修复尚未执行。**

## 独立服务器任务做什么

1. 验证本地上传包及脚本 hash。
2. 使用 SQLite backup API 对现网 catalog/knowledge 建立一致备份并 integrity_check；复制 Vault、原文快照、私有配置和旧 compose，生成逐文件 hash。此为在线预演备份，正式切换前另做冻结备份。
3. 从备份恢复隔离数据库/Vault，原文快照只读挂载；保持模型与远程 OCR 关闭。
4. 从现用镜像构建固定代码新镜像，禁用构建网络。
5. 启动 Docker 独立样本任务 `obsidian-sync-sample-9d1b04f-20261006`，网络禁用、CPU 1.5、内存 2 GiB、本地 OCR 每文档上限 200 页。生产数据库/Vault 不挂载到样本任务。
6. 全库质量盘点，冻结候选与真实分层样本；逐项验证快照 SHA/长度、源版本、recipe，执行原生提取与必要页 OCR，记录页级正文证据、耗时、损伤变化。
7. 每份结果写私有 `sample-item-NNNN.json`，阶段写 `sample-status.json`；隔离索引/阅读发布完成后检查全部原有 block 文本 hash 未改动。
8. **样本结束停在 `awaiting_independent_sample_review`，不自动把机器 ready 当成真实验收，不自行切换生产。** 异常停在 `stopped_for_review` 并保留数据/日志。

服务器进程和 Docker 容器不依赖 Windows/Codex 存活。退出后它们继续自己的有限任务；Codex 后续推理、独立验收及切换操作不会因退出而自动继续。用户返回同一会话后，直接读取以上状态再续做；无需重新描述背景。

## 恢复入口与后续执行顺序

首先只读读取 operation 中 `host-status.json`、`sample-status.json`、`release.json`、`launch.json` 及 Docker inspect 的 State。不要打印私有配置、环境变量或 API token。

- `backup`/`build`：核对准备器真实进程和 `prepare.log`/`build.log`，不可重启整套准备器覆盖备份。
- `isolated_sample_running`：以 Docker 容器状态及 `sample-status.json` 为准。主准备进程已退出是预期行为。
- `awaiting_independent_sample_review`：读取逐份证据，按 [docs/36](../36-validated-release-and-text-repair.md) 对照真实原文问题页、财务数字/单位、尾页；补隔离 API/升级及 worker 三连跑验证。缺项明确报告。
- `stopped_for_review`：先看具体错误，保留所有结果。单份 batch ID 和 jobs 是持久状态，续跑必须使用原冻结成员/recipe；禁止新清单覆盖冻结文件。脚本不是可不加判断反复运行的入口。

预演通过后，核对精确写者，冻结旧 worker（和升级期间 API 写者），记录新的数据库一致性备份和人工区 hash，再切换 library/knowledge-api/worker 等明确服务。保持 Syncthing 身份/目录/端口，保留旧镜像/compose。正式正文修复使用已冻结候选、单份持久任务、最多每 20 份发布一次；后台常规 worker 不得同时竞争这条队列。较差新稿不替换良好旧稿；异常停止批次并保存检查点。

正式切换/批次完成后再填写实际镜像 ID、冻结备份、索引与 Windows 同步、旧证据、人工区 hash、增量链、真实质量汇总及回退步骤。当前这些不能由启动准备任务代替。

七天观察、真实 LLM B4 质量、投资应用接入另行跟进；本次没有模型调用。旧乱码文件保留，正确阅读入口的切换与文件归档是两件独立事项。
