# 下一位开发agent提示词

请在 `D:\2.Develop\8.Obsidian\obsidian-sync` 接续开发。先读AGENTS.md、docs/progress/ABCDE-ACCEPTANCE-20261005.md、docs/27-abcde-acceptance-taskbook.md、docs/25-target-workflow-delivery.md，以最新独立验收为准，不沿用“A–E全部完成/B/C只差模型开关”的结论。

本任务仅授权实现、隔离测试、文档、commit和向唯一远端git@github.com:jupiterr-chen/obsidian-sync.git正常push。**严禁自行部署生产。开发完成后提交固定commit和证据，等待Codex下发独立验收任务并验收通过，再取得用户对该次生产发布的明确授权，才可以部署。** 旧research-kb迁移授权已完成，不适用于此任务；自测通过、收到开发任务、Git push都不是部署授权。禁止以“部署验证/线上补丁”为由改生产镜像、配置、数据库、worker调度或服务状态。

先按N1/N2/N4修核心正确性与预算重试，再补齐单篇分析和公司/主题总结的真实消费者、证据验证、持久结果、自动发布；N3包含事件去重，N5分批发布断链做小修。不要重做迁移或整包重构，普通阅读保持可用。先运行scripts/review-abcde-20261005.py复现6个失败条件，再实现对应回归；不能删断言、跳测试或把NOT_RUN改PASS。

生产远程模型继续关闭，不新增付费调用/资料外发，不全库重提取或分析。用离线fake provider完成worker→分析→Obsidian→相关实体总结的三连跑、重启、幂等及人工区保护测试；mock只证明编排，不冒充真实研究质量。生产检查只读，测试必须使用隔离数据；不使用OpenCode、不输出凭据、不递归删除/移动、不改变权限、不清理旧目录和历史证据。

每个可验收小批提交并维护HANDOFF/任务台账；完成后提交开发报告和AC1验收材料，列明实际commit、验证命令/结果、真实模型/新增研报同步/目标应用/7天观察的未尽项。不得将N1–N5之外的待授权事项变成无止境返工；能独立完成的工作持续推进，最后停在“待Codex独立验收”，不要自行上线。
