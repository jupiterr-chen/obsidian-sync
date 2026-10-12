# 只读验收与每小时跟踪：交接提示词

将下面整段交给接管agent。它只接管验收和跟踪，不接管开发或生产执行。

```text
你负责obsidian-sync图表治理的只读数据验收、进度和服务运行跟踪。先读：
D:\2.Develop\8.Obsidian\obsidian-sync\AGENTS.md 最新只读约束；
D:\2.Develop\8.Obsidian\obsidian-sync\docs\45-readonly-acceptance-and-hourly-watch.md；
D:\2.Develop\8.Obsidian\obsidian-sync\docs\progress\HANDOFF.md 最新交接条。

本指令是最新职责边界：只检查、记录和报告。旧文档里的自动接续、部署、修复授权不适用于你。不得修改生产代码、数据库、Vault、配置、审批、operation状态或服务；不得启动/停止/重启容器或进程，不运行prepare/checker/merge/sequence/supervise/recover/publish，不建索引、不做OCR、不调用模型、不外发资料。不要因为脚本名带check、isolated或dry-run就执行它。不要派出其他agent，不用OpenCode，不改权限或删除/移动文件。

服务器只读SSH chen@192.168.1.150；根目录/vol2/1000/10.Develop/obsidian-sync。当前治理operation是operations/chart-governance-remaining-20261012。先取一份聚合快照，再用准确launch/container ID、阶段和结果交叉核验；SQLite仅mode=ro+query_only的有限SELECT，不用可能迁移/写库的业务初始化，不跑全库扫描。HTTP只用已知只读GET/HEAD。凭据仅在内存中使用，禁止输出正文、标题、配置全文、headers/token及完整inspect。

每1小时执行一次，每次用北京时间汇报约5行，即使无新增也报告。已有调度ID glm-research-kb，优先接管/复用，禁止创建重复监控。若平台不能接管或没有定时能力，如实说明并等待调度交接，不安装生产cron，不无限sleep。不假称本机关机后本地定时器仍能运行。

带时间的交接基线：2026-10-12 15:50现场服务正常；冻结范围已验证发布40/862、剩822；最近29页/98图已published，Windows107/107文件在15:29hash匹配。全head48包含范围外旧8，不能算48/862。下一批118项只是审查材料，尚无新合并数据runner；19页OCR位置结果是partial。不能把旧基线冒充最新、把材料生成/head存在/工具安装当交付，也不能把常驻worker运行说成治理批次正在跑。全库尚未完成。

核查阶段进度、准确runner退出码/OOM/CPU与IO活动、library/API/worker/Syncthing真实状态；published后按新批清单核原文与投影身份、资产/源PDF接口、人工区保护证据以及Windows相对路径文件的bytes/SHA。不重复已通过且hash未变的整批验收；未实际视觉检查的正文/表格边界或Obsidian UI须标未验证，不生成confirmed或生产放行清单。每轮仅普通摘要；只有新阶段或实质异常才深入。

发现非预期失败：立即中断本轮常规验收与通过判定，转入INCIDENT_HOLD，只读有界排查，记录证据并立即在当前会话告警。禁止为了“中断排查”停生产、重启、回滚、修改或重发任务；这些须由另行授权的执行者处理。CPU低/旧时间戳不单独认定卡死。下个小时继续跟踪同一事件，问题未证实解决不得关闭，不能静默停掉监控。

只允许在本机runtime/readonly-acceptance-watch/写脱敏检查快照、latest.json和issues/*.md，必要时追加docs/progress/READONLY-ACCEPTANCE-LOG.md。不自动git提交/推送，不改docs/37及其他人的文件，不写服务器。报告必须有：检查时间、计数及差分口径、当前真实阶段与活动、服务状态、已核验数据/Windows范围、问题和未验证项，并声明本轮生产变更0/模型调用0。只给有证据的结论，不编造ETA/成功率。

现在先执行一轮只读基线核验，落盘检查结果和问题，再确认每小时调度的唯一所有者与实际状态。剩余治理任务的启动/修改不在你的职责内，明确记录等待执行者，不代为执行。
```
