# AC1续验开发提示词

在 `D:\2.Develop\8.Obsidian\obsidian-sync` 接续。先读AGENTS.md、docs/progress/AC1-REVIEW-20261006.md、docs/29-ac1-followup-taskbook.md。基线d58119e；Q01–Q05原六反例已独立通过，不重做迁移或已通过修复。

本轮只补R1–R4，并合并R5的D接口小修：旧版summary表无损幂等升级；B分析/原文真正进入C的版本化证据输入，没证据不空生成；总结结果落盘后中断不能再调用/追加；长文按章节覆盖并准确记录partial/续跑；服务配置到B/C执行器的默认关闭接线；pending/failed索引及模型/提示词换版发布地址；无截止时间的背景包遵循is_current。先复现scripts/review-ac1-20261006.py，保留原探针6/6，再逐项提交回归与集成证明。集成测试从旧SCHEMA和新增合成报告起步，不直接填claims/结果来伪造内容链路。

授权仅限本地主仓库实现、隔离测试、文档、正常commit/push到git@github.com:jupiterr-chen/obsidian-sync.git。**禁止自行部署生产。交付固定commit和证据后，等待Codex独立验收任务并验收通过，再取得用户对该次具体commit/范围的明确部署授权，才允许发布。** 开发、自测、push、历史迁移授权都不替代这两个条件。

生产只读；不改生产库/配置/镜像/调度，不重启/停机，不全库回填，不真实模型调用/资料外发，不输出凭据。用离线fake provider验证标准服务入口，保持默认关闭。不使用OpenCode，不递归删除/移动或改权限，保留人工内容、旧目录、证据和历史版本。

R1独立提交，R2/R3/R4同一轮闭环；不要扩大到embedding或新投资应用，不因P2要求阅读停服或整包返工。持续完成不依赖用户的修复，最后给出实际SHA、测试证据、内容/证据覆盖范围、未完成项，停在“待Codex AC1续验”。真实模型质量和生产新增研报窗口等如实保留待授权。
