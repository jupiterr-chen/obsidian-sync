# Obsidian Research Knowledge Service

**使用入口（2026-10-07）：[知识库 API 使用说明](docs/39-knowledge-api-usage.md)**。包含 Windows 连接、认证、全文检索、证据/正文和公司背景包示例，已只读核对现网。应用 `9d1b04f` 已发布，服务器历史正文修复按[运行记录](docs/progress/RELEASE-REPAIR-20261006.md)续行；[GLM 单次分析试用](docs/progress/GLM-TENCENT-PILOT-20261007.md)已完成，生产常驻模型服务尚未启用。下方“未部署”等均为历史阶段记录，不代表当前状态。

**最新：代码续验通过。固定源码9d1b04f，29探针与431回归通过（2跳过）。** [最终验收](docs/progress/SF-ACCEPTANCE-20261006.md)、[下一步发布与正文修复](docs/36-validated-release-and-text-repair.md)。未部署；真实样本、历史数据修复及模型质量按各自阶段授权验收。以下旧验收信息为历史记录。

最新续验：0f9cb27的23探针与420回归通过（2跳过）；S4/F1通过，S1/S2/S3/F3仍须补齐原任务组合条件。见[续验报告](docs/progress/S1234-ACCEPTANCE-20261006.md)、[原任务书](docs/34-tqma-followup-taskbook.md)、[提示词](docs/35-tqma-followup-prompt.md)。未部署，不扩展范围，F4仍后置。

最新验收（2026-10-06）：fbc24bd原16反例通过，410回归通过/2跳过；四组执行边界按功能续修，见[报告](docs/progress/TQMA-REVIEW-20261006.md)、[任务书](docs/34-tqma-followup-taskbook.md)、[提示词](docs/35-tqma-followup-prompt.md)。现网未变，未授权启用模型或历史重处理；不重做已通过修复。

用于研报、财报和个人研究资料的长期知识服务。Obsidian 是研究工作台，服务端保留原文、正文、证据、版本和检索索引；研发及资金管理应用通过接口读取证据。

最新优先事项：已将PDF正文乱码问题并入[统一任务书](docs/31-maintenance-and-model-activation.md)，先做[正文质量TQ0–TQ4](docs/33-text-quality-repair-taskbook.md)，再启用LLM。全库质量扫描、原生文字重提取优先、仅必要页OCR；现有链接可打开不代表历史正文质量已通过。生产重处理和旧副本治理仍需具体授权。

当前交付：基础迁移已完成，现网仍67c6985r2，正文阅读运行。**AC1续验：50cf6c1的模型关闭维护范围限定通过**，原6+7探针全绿，382回归通过/2跳过。可以准备维护发布，仍需用户明确授权；B/C启用前的结果发布、合并引用和单次预算问题集中后续处理，不阻挡维护范围。见[最新报告](docs/progress/AC1-FOLLOWUP-20261006.md)。

下一步：[维护发布与模型启用任务](docs/31-maintenance-and-model-activation.md)、[开发agent提示词](docs/32-model-activation-prompt.md)。不重做迁移，不停现有阅读；验收通过不等于部署授权，更不等于真实模型外发授权。

## 阅读顺序

1. [总体设计](docs/01-architecture.md)
2. [数据与版本设计](docs/02-data-and-provenance.md)
3. [接入、解析与检索](docs/03-processing-and-search.md)
4. [API 实际使用说明](docs/39-knowledge-api-usage.md) · [接口契约](docs/04-api-contract.md)
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
