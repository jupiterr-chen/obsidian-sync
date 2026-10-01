# Obsidian Research Knowledge Service

用于研报、财报和个人研究资料的长期知识服务。Obsidian 是研究工作台，服务端保留原文、正文、证据、版本和检索索引；研发及资金管理应用通过接口读取证据。

当前交付：**P0 设计基线、主仓库整合任务书与工程契约**。没有启动生产服务、执行全文回填、调用模型或修改现有 Vault。目录及接口表示目标结构，未实现项见交付计划。

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

- `src/research_kb/`：目标模块边界；当前仅职责说明。
- `contracts/`：版本化数据契约与合成示例。
- `config/`：无凭据配置样例。
- `tests/`：验收数据及未来自动化测试位置说明。
- `deploy/`：目标部署与运行手册。
- `docs/adr/`：架构决策记录。

原文、全文、数据库、模型产物、日志、凭据及个人笔记均不提交 Git。现有 ResearchVault、ResearchTools 保留在工程外部。后续先做离线样本，再做影子索引，最后上线查询接口。

[P0实际验证报告](docs/10-p0-validation.md)

## 下一位agent从这里开始

用户决定以本仓库为唯一主工程，复制纳入已有research-kb第一层实现，保留源目录。代码尚未导入；先执行M0，不重复建设第一层。

- [主仓库整合任务书](docs/11-integration-taskbook.md)
- [长任务执行指导书](docs/12-agent-execution-guide.md)
- [验证与复核规则](docs/13-validation-and-review-rules.md)
- [可复制的agent提示词](docs/14-agent-prompts.md)
- [最新架构决定](docs/adr/0002-consolidate-main-repository.md)

11-14与ADR0002覆盖早期独立仓库假设，任务书不代表实现已完成。
