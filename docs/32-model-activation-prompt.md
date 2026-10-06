# 下一位开发agent提示词：正文质量修复与模型启用前集中完善

> 最新（2026-10-06）：本批开发已完成独立复核，原16探针通过；仅续修[docs/34四组边界](34-tqma-followup-taskbook.md)，转交使用[docs/35提示词](35-tqma-followup-prompt.md)。详见[验收报告](progress/TQMA-REVIEW-20261006.md)。保留本文设计要求，不从头重做全部TQ/MA。

请在 `D:\2.Develop\8.Obsidian\obsidian-sync` 继续。先读AGENTS.md、docs/progress/AC1-FOLLOWUP-20261006.md、docs/31-maintenance-and-model-activation.md和docs/33-text-quality-repair-taskbook.md。用户已要求把正文乱码问题合并到本批，优先执行TQ0–TQ4，再集中完成MA任务。

TQ范围：全库只读质量清单，区分文档/版本/提取/页面/文件；旧stdlib-pdf可能没有degraded标记，不可漏筛。修正CID/控制字符异常的逐页路由和质量门；坏文本层OCR成功后不能再拼回旧乱码，失败不得假ready。review污染内容不能作为B/C有效证据。提供有界原生重提取/按需OCR、新extraction、可恢复发布与历史证据保留。旧主稿/候选治理只做manifest+hash+引用核对及dry-run，不按文件名清理。不能粗暴删除¥、Ø、Ë等合法字符，也不能用删控制字符冒充恢复原文。

“全量梳理”指全库质量核对，不是强制全库OCR。先准备约12–20份分层样本的隔离验证与资源测量方案，再申请具体生产数据批次；不要把另一agent的304/321统计当准确OCR任务数。生产已有523项最新提取中458项是旧stdlib-pdf，问题清单须结合引擎/文本/原文验证去重。本任务不授权实际历史批量重提取、Vault归档/移除、生产切换或真实模型调用。

原6+7验收探针已通过，50cf6c1的“模型关闭维护范围”已获Codex限定验收。不要重做R1–R5或迁移，不因本批问题停止普通阅读。**这不授权部署；50cf6c1维护发布仍需用户明确授权，且其验收不得沿用到你新增的代码。**

默认执行docs/31轨道B，集中完成：partial→done结果修订能重新发布且B完成驱动C更新；分段引用全局唯一、合并稿再校验；每次分段/合并/总结都执行输入上限；配置资料allowlist和有界重试，避免历史全库被自动发送。主题规则如要宣称可用须从标准服务入口接到证据查询；若延期则明确禁用与未实现范围。

先复现scripts/review-model-activation-20261006.py的3个问题；保留原13探针，补标准服务入口的两篇冲突长文、跨轮预算中断/恢复、B/C页面和版本/证据/账本检查。使用离线fake/scripted provider；不真实模型调用、不外发、不购买额度、不全库回填。不要只让探针变绿而遗漏实际发布内容或最终引用。

授权仅限本地主仓库实现、隔离测试、文档、commit与唯一远端git@github.com:jupiterr-chen/obsidian-sync.git正常push。生产只读，不部署、不重启/停机、不改生产配置/库/镜像/调度。部署须先收到Codex独立验收任务、验收通过，再获用户对具体commit和范围的明确授权。开发/self-test/push/旧迁移授权都不算。

不使用OpenCode，不递归删除/移动、不改权限、不输出凭据，保留人工内容和旧证据。逐批提交证据、更新HANDOFF与状态，完成后停在待Codex验收；真实B4模型质量与维护发布分别等待对应授权，不以此为由搁置可独立完成的开发。
