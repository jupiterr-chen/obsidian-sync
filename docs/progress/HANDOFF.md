# 会话检查点 / HANDOFF

更新：2026-10-01（P6 离线部分完成后，本会话收尾）。

## 当前状态

- **M0、P1-P6 离线部分全部完成并验收**，提交已推送 obsidian-sync.git：
  `0f3a19f`(M0) → `2889a12`(P1) → `1fd8d78`(P2) → `9eacef3`(P3) → `240b4dd`(P4) → `c4abc89`(P5) → P6 提交见 git log。
- 测试基线：**202 OK (1 skipped)**（113 第一层回归 + 89 知识层）。
  命令（原生 PowerShell）：`$env:PYTHONPATH="app"; python -m unittest discover -s app/tests`
- 源工程 research-kb 未改动（基线 5442e397）；ResearchVault/ResearchTools 未触碰；无生产服务启动/重启；无真实模型调用；工作树干净。

## 已完成任务（摘要，详见各报告）

| 阶段 | 交付 | 报告 |
|---|---|---|
| M0 | 49 文件复制整合+manifest+根配置合并 | m0-report.md |
| P1 | 知识库存储/不可变快照/幂等同步/抽样与测量工具（ADR0003） | p1-report.md, p1-01-interface-audit.md |
| P2 | 提取器注册表（txt/html/pdf/img）+证据块+质量路由+OCR接口+数值规范化（ADR0004） | p2-report.md |
| P3 | 混合分词 BM25 索引+generation 原子发布+/api/kb/v1+事件流+证据链接（ADR0005） | p3-report.md |
| P4 | provider 抽象（默认关闭）+RRF 混合召回+引用验证分析+用量账本+预算门禁（ADR0006） | p4-report.md |
| P5 | claim/decision 追加式历史+决策冻结+影响分析 proposal+安全写回 | p5-report.md |
| P6 | worker 周期闭环+心跳监控+在线备份/恢复演练+compose 准备+接入示例 | p6-report.md |

## 失败测试 / 已知问题

- 无失败测试。各阶段已知限制见对应报告（标准库 PDF 解析器覆盖、事件保留期未配、rerank 未实现、unsupported_numeric_claims 占位等）。

## 剩余工作 = 外部条件依赖（合并缺项清单）

1. **真实源访问**（服务器只读路径或本地挂载）：A01 清单对账、A04 真实 30 样本、A05 真实 token 测量、A10 真实检索基准、A14 全量影子回填（523 基线）。具备后执行：`python -m knowledge sync → run-snapshots → run-extracts → rebuild-index`，再 `sample/measure`（接真实 tokenizer counter）。
2. **生产主机与部署授权**（主机、目录、运行用户、回滚）：compose 已备（deploy/docker-compose.knowledge.yml）；A21 性能与 7 天记录、A22 真实恢复演练、P6 全部生产门禁。
3. **模型供应商+凭据方式+外发范围+预算**：P4 真实适配器（providers.py 预留）、A16 成本、A17 分析评测、真实 tokenizer。
4. **OCR 引擎选型**（本地、离线、许可）：P2 真实 OCR 质量门禁（A08 真实部分）。
5. **真实 Vault 写回授权**（登记 `自动研究候选/` 等生成目录）：P5-03 生产启用。

## 准确续跑起点

- 读本文件 → docs/progress/task-status.md（状态表）→ 对应阶段报告的「BLOCKED/已知限制」节。
- 任何新会话先跑全量测试确认基线，再从上述缺项中已具备的条件切入；无需重做 M0-P6 离线部分。
- 约束提醒：不修改源工程/原始归档；不 force-push；不猜凭据；OCR/LLM 独立 worker；`/api/v1` 行为保持；人工笔记零覆盖。

## 会话执行说明

本会话为普通交互会话，无自动唤醒能力：会话结束后不会后台继续。所有已声明完成的工作均已在本会话内执行、测试并推送；未执行事项均如实标注 NOT_RUN/BLOCKED，无虚构。
