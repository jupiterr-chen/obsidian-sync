# Obsidian Research Knowledge Service

用于研报、财报和个人研究资料的长期知识服务。Obsidian 是研究工作台，服务端保留原文、正文、证据、版本和检索索引；研发及资金管理应用通过接口读取证据。

当前交付：**P0 设计基线 + M0 源工程整合**。已通过复制纳入原 research-kb 第一层实现（`app/library/`：目录、入库、小时调度、原文版本服务、变更账本、状态面板与 113 项回归测试，全部在主仓库通过）。尚未启动生产服务、执行全文回填、调用模型或修改现有 Vault。P1-P6 未实施，见交付计划。

## 阅读顺序

1. [总体设计](docs/01-architecture.md)
2. [数据与版本设计](docs/02-data-and-provenance.md)
3. [接入、解析与检索](docs/03-processing-and-search.md)
4. [接口契约](docs/04-api-contract.md)
5. [长期记忆与应用集成](docs/05-memory-and-analysis.md)
6. [部署与运维](docs/06-operations.md)
7. [分阶段任务](docs/07-delivery-plan.md)
8. [验收方案](docs/08-acceptance.md)
9. [LLM 与 Token 预算](docs/09-llm-and-token-budget.md)
10. [现状与待确认事项](docs/00-baseline.md)

## 工程结构

- `app/library/`：**已运行的第一层服务**（标准库实现）：统一目录、适配接入、Markdown 卡片、版本化原文服务、小时调度、文件锁、变更账本与状态面板。
- `app/tests/`：第一层回归测试（113 项，`PYTHONPATH=app python -m unittest discover -s app/tests`）。
- `app/knowledge/`：P1 起新增知识功能的目标位置（尚未创建）。
- `src/research_kb/`：目标模块边界职责说明（参考，不建第二套服务）。
- `contracts/`：版本化数据契约与合成示例。
- `config/`：无凭据配置样例（library 用 `config.example.json`/`.env.example`/`stignore`，知识层用 `settings.example.json`）。
- `scripts/`：部署与校验脚本（来自第一层，公开部分）。
- `deploy/`：目标部署与运行手册。
- `docs/legacy/`：源工程 research-kb 的历史文档（仅第一阶段，不替代本仓库计划）。
- `docs/adr/`：架构决策记录。

原文、全文、数据库、模型产物、日志、凭据及个人笔记均不提交 Git。现有 ResearchVault、ResearchTools 保留在工程外部。后续先做离线样本，再做影子索引，最后上线查询接口。

[P0实际验证报告](docs/10-p0-validation.md) · [M0整合验收报告](docs/progress/m0-report.md) · [导入manifest](docs/progress/m0-import-manifest.json)

## 下一位agent从这里开始

M0 整合已完成并验收（见进度台账）。下一步从 P1 开始：接入游标、版本表幂等、不可变快照与 30 份样本测量。

- [主仓库整合任务书](docs/11-integration-taskbook.md)
- [长任务执行指导书](docs/12-agent-execution-guide.md)
- [验证与复核规则](docs/13-validation-and-review-rules.md)
- [可复制的agent提示词](docs/14-agent-prompts.md)
- [最新架构决定](docs/adr/0002-consolidate-main-repository.md)

11-14与ADR0002覆盖早期独立仓库假设，任务书不代表实现已完成。
