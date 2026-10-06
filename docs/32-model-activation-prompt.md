# 下一位开发agent提示词：模型启用前集中完善

请在 `D:\2.Develop\8.Obsidian\obsidian-sync` 继续。先读AGENTS.md、docs/progress/AC1-FOLLOWUP-20261006.md、docs/31-maintenance-and-model-activation.md。

原6+7验收探针已通过，50cf6c1的“模型关闭维护范围”已获Codex限定验收。不要重做R1–R5或迁移，不因本批问题停止普通阅读。**这不授权部署；50cf6c1维护发布仍需用户明确授权，且其验收不得沿用到你新增的代码。**

默认执行docs/31轨道B，集中完成：partial→done结果修订能重新发布且B完成驱动C更新；分段引用全局唯一、合并稿再校验；每次分段/合并/总结都执行输入上限；配置资料allowlist和有界重试，避免历史全库被自动发送。主题规则如要宣称可用须从标准服务入口接到证据查询；若延期则明确禁用与未实现范围。

先复现scripts/review-model-activation-20261006.py的3个问题；保留原13探针，补标准服务入口的两篇冲突长文、跨轮预算中断/恢复、B/C页面和版本/证据/账本检查。使用离线fake/scripted provider；不真实模型调用、不外发、不购买额度、不全库回填。不要只让探针变绿而遗漏实际发布内容或最终引用。

授权仅限本地主仓库实现、隔离测试、文档、commit与唯一远端git@github.com:jupiterr-chen/obsidian-sync.git正常push。生产只读，不部署、不重启/停机、不改生产配置/库/镜像/调度。部署须先收到Codex独立验收任务、验收通过，再获用户对具体commit和范围的明确授权。开发/self-test/push/旧迁移授权都不算。

不使用OpenCode，不递归删除/移动、不改权限、不输出凭据，保留人工内容和旧证据。逐批提交证据、更新HANDOFF与状态，完成后停在待Codex验收；真实B4模型质量与维护发布分别等待对应授权，不以此为由搁置可独立完成的开发。
