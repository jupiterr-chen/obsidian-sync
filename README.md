# Obsidian Research Knowledge Service

用于研报、财报和个人研究资料的长期知识服务。Obsidian 是研究工作台，服务端保留原文、正文、证据、版本和检索索引；研发及资金管理应用通过接口读取证据。

当前交付：设计、M0整合与P1–P6实现及真实影子处理已落地。**2026-10-04独立复核：310 tests OK/2 skip；按用户要求，基础迁移先行，增强功能缺陷后置。** 当前限制模型外发、历史public-as-of与自动候选导出；迁移需独立通过数据、恢复、同步和回滚门禁。见[第五轮报告](docs/progress/FIFTH-REVIEW-20261004.md)与[迁移任务书/fix清单](docs/23-fifth-review-taskbook.md)。

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
- `app/tests/`：全部测试（本轮运行 310 项，`PYTHONPATH=app python -m unittest discover -s app/tests`）。
- `app/knowledge/`：知识层（P1-P6）：不可变快照 store、提取/证据块、质量与 OCR 路由、词法+RRF 混合检索、`/api/kb/v1`、事件流、研究记忆（claim/decision/影响分析）、安全写回、worker 调度。CLI：`python -m knowledge sync|run-snapshots|run-extracts|rebuild-index|serve-kb|worker|sample|measure|evidence-links|status`。
- `src/research_kb/`：目标模块边界职责说明（参考，不建第二套服务）。
- `contracts/`：版本化数据契约与合成示例。
- `config/`：无凭据配置样例（library 用 `config.example.json`/`.env.example`/`stignore`，知识层用 `settings.example.json`）。
- `scripts/`：部署与校验脚本（来自第一层，公开部分）。
- `deploy/`：目标部署与运行手册。
- `docs/legacy/`：源工程 research-kb 的历史文档（仅第一阶段，不替代本仓库计划）。
- `docs/adr/`：架构决策记录。

原文、全文、数据库、模型产物、日志、凭据及个人笔记均不提交 Git。现有 ResearchVault、ResearchTools 保留在工程外部。后续先做离线样本，再做影子索引，最后上线查询接口。

[P0实际验证报告](docs/10-p0-validation.md) · [M0整合验收报告](docs/progress/m0-report.md) · [导入manifest](docs/progress/m0-import-manifest.json) · [任务台账](docs/progress/task-status.md) · [会话检查点](docs/progress/HANDOFF.md)

## 下一位agent从这里开始

先读[第四轮评审](docs/progress/FOURTH-REVIEW-20261003.md)、[迁移阻断任务书](docs/21-cutover-blockers-taskbook.md)和[执行提示词](docs/22-cutover-blockers-prompt.md)。按C0–C6修复并独立复验，通过真实迁移门禁后接续已授权的切换。无需重做M0或再次索取相同停机授权。

- [主仓库整合任务书](docs/11-integration-taskbook.md)
- [长任务执行指导书](docs/12-agent-execution-guide.md)
- [验证与复核规则](docs/13-validation-and-review-rules.md)
- [可复制的agent提示词](docs/14-agent-prompts.md)
- [最新架构决定](docs/adr/0002-consolidate-main-repository.md)

11-14与ADR0002覆盖早期独立仓库假设，任务书不代表实现已完成。

## 首轮独立评审（历史，2026-10-02）

基线534014a：222测试通过（2跳过），迁移保真基本通过；知识层整体NEEDS_CHANGES，15组修复问题，尚不满足生产切换条件。

- [评审结果与问题](docs/progress/INDEPENDENT-REVIEW-20261002.md)
- [RF0-RF7修复任务书](docs/15-review-remediation-taskbook.md)
- [直接交给agent的修复提示词](docs/16-review-fix-prompt.md)

## 第二轮独立复核（历史，2026-10-03）

[第二轮结果](docs/progress/RE-REVIEW-20261003.md) · [证据](docs/progress/re-review-evidence-20261003.json) · [修复任务书](docs/17-second-review-taskbook.md) · [可复制提示词](docs/18-second-review-fix-prompt.md)

R03/R06/R07/R14 首轮具体反例可关闭；其余按第二轮报告继续验收，RF7 未通过。迁移基线保留，本轮未操作生产或真实模型。

## 第三轮独立复核（历史，2026-10-03）

[结果与问题](docs/progress/THIRD-REVIEW-20261003.md) · [证据](docs/progress/third-review-evidence-20261003.json) · [下一步任务书](docs/19-release-readiness-taskbook.md) · [提示词](docs/20-release-readiness-prompt.md)

认可同事务预算预留/成功结算、不可覆盖主文件、同字节快照服务、图片顺序幂等、新版本outbox和部署命令修复；异常/升级/长期重复运行的剩余问题按第三轮报告验收。

## 最新独立复核：第四轮（2026-10-03）

[报告](docs/progress/FOURTH-REVIEW-20261003.md) · [证据](docs/progress/fourth-review-evidence-20261003.json) · [任务书](docs/21-cutover-blockers-taskbook.md) · [提示词](docs/22-cutover-blockers-prompt.md)
