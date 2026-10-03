# Obsidian Research Knowledge Service

用于研报、财报和个人研究资料的长期知识服务。Obsidian 是研究工作台，服务端保留原文、正文、证据、版本和检索索引；研发及资金管理应用通过接口读取证据。

当前交付：设计、M0 整合和 P1–P6 源码已落地，并在真实语料上做过部分处理。**最新独立复核（2026-10-03，基线 4949dcd）：NEEDS_CHANGES，6 个 P1、4 个 P2 待修复。** 本地 268 项回归通过（2 skipped），新增边界反例未通过；不能据此切换生产。旧栈和既有回填状态见 HANDOFF，真实质量/性能/持续运行验收仍保留 NOT_RUN/BLOCKED。

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
- `app/tests/`：全部测试（本轮运行 268 项，`PYTHONPATH=app python -m unittest discover -s app/tests`）。
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

先读[第二轮评审](docs/progress/RE-REVIEW-20261003.md)、[SR0–SR6 任务书](docs/17-second-review-taskbook.md)和[执行提示词](docs/18-second-review-fix-prompt.md)。当前先完成 S01–S10 源码修复与复验，再继续真实数据验收。无需重做 M0；旧历史 accepted/fixed 声明以最新独立复核为准。

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

## 最新独立复核（2026-10-03）

[第二轮结果](docs/progress/RE-REVIEW-20261003.md) · [证据](docs/progress/re-review-evidence-20261003.json) · [修复任务书](docs/17-second-review-taskbook.md) · [可复制提示词](docs/18-second-review-fix-prompt.md)

R03/R06/R07/R14 首轮具体反例可关闭；其余按第二轮报告继续验收，RF7 未通过。迁移基线保留，本轮未操作生产或真实模型。
