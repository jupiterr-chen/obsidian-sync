# ADR 0002：以obsidian-sync统一主工程

状态：用户决定，2026-10-01；导入实现待M0验收。

决定：主remote为obsidian-sync.git，research-kb公开源码通过复制导入并保留源目录；根保留统一设计，历史文档放docs/legacy。复用app/library与第一层能力，新功能放app/knowledge，不实现重复接入系统。现有HTTP标准库实现先保留，FastAPI仅作为后续评估项。

本ADR覆盖0001及01/07中早期独立新工程的部署/代码归属假设，不改变证据版本、人工区保护及分阶段验收目标。Compose统一部署，但OCR/LLM独立worker。

代价：需要M0复制manifest、规则合并和完整回归。原repo不删除、不改remote；真正退役与清理由用户另行授权。当前提交为任务起点，不代表已复制或部署。
