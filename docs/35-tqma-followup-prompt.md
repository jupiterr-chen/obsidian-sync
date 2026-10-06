# 下一位开发agent提示词

**最新续验入口（保持原任务范围）**：从0f9cb27519d3cae1b513538667f1eb2d091964bf继续，先读docs/progress/S1234-ACCEPTANCE-20261006.md。原23探针与420回归通过（2跳过），S4/F1通过，不重做。只补齐原S1/S2/S3/F3未闭环条件：主题规则不能扩大C资料发送范围；部分污染/缺页新稿不能压掉完整健康旧稿；人工目录wikilink及片段引用须保护；批次完整清单原子冻结、首次登记中断可恢复、JobRunner执行时校验冻结recipe；多次预算等待不得耗尽故障重试。先复现scripts/review-s1234-followup-20261006.py的6项，再与原23探针、针对性集成及全回归统一交付。F4仍后置，不启用后来撤回的任务扩展。以下原任务与授权边界继续适用。

请在`D:\2.Develop\8.Obsidian\obsidian-sync`继续，先读AGENTS.md、docs/progress/TQMA-REVIEW-20261006.md、docs/34-tqma-followup-taskbook.md。验收基线fbc24bd64102f57fded3b7875e3ce9b94ede51a6。410回归通过/2跳过、原6+AC1 7+MA3探针已由Codex复跑通过，不要重做这些修复或迁移。

集中完成S1–S4：模型scope必须覆盖B旧队列/partial执行及C真实证据发送，空范围零调用且模型/prompt身份一致；污染非空新提取不得压掉旧好阅读/检索入口，治理要保护真实被引用文件；同batch id冻结成员/recipe，完成A后重跑不能自动加入B；quality-inventory/governance-plan/reprocess --dry-run必须真正只读，不初始化或迁移源库。先运行scripts/review-tqma-20261006.py复现七条RED（归并四组），修复为GREEN，保留原16探针并跑有意义的CLI/worker集成与全回归。不要放宽断言或仅修改计数。

同批按任务书处理F1样本harness未入Git、F2批次所需盘点信息；F3重试设置/退避在付费无人值守前落实，F4 C1展示可以后置。将可延期项写清依赖功能，不扩大成全项目返工。样本工具必须在fresh checkout用合成含数字PDF实际运行，不能把忽略文件或--help成功当交付。全库梳理是质量核对，原生重提取优先，仅必要页OCR；不强制全页OCR，不自动触发全库LLM分析。

授权仅限本地实现、隔离测试、文档、commit及唯一远端git@github.com:jupiterr-chen/obsidian-sync.git正常push。不用OpenCode，不真实模型调用/付费/资料外发，不历史批量重提取/OCR，不操作生产库/配置/镜像/调度/服务，不归档或删除Vault文件，不改权限、不跨shell破坏操作。生产只读，检查不得调用有初始化副作用的KnowledgeStore。任何递归删除/移动须另列准确绝对路径并获明确确认，本任务无需这些操作。

完成后交付固定完整源码SHA、各任务RED/GREEN证据、通过/跳过计数、未尽事项并停在待Codex独立续验。**必须先收到Codex验收任务并验收通过，再获用户对该commit/范围的明确授权，才能部署生产；开发任务、自测全绿、push、旧迁移授权都不算发布授权。**模型provider/资料范围/预算、生产数据批次、文件归档也分别需要授权。此前50cf6c1维护限定验收不沿用到新代码。
