# 会话检查点 / HANDOFF

更新：2026-10-01（M0 完成后，P1 开始前）。

## 当前状态

- M0 已完成并验收（`docs/progress/m0-report.md`），已提交 `0f3a19f` 并推送 obsidian-sync.git。
- 主分支 main，远端唯一 `git@github.com:jupiterr-chen/obsidian-sync.git`。
- 源工程 `D:\2.Develop\7.zcode\discord-export\research-kb` 未改动、保留；基线 commit `5442e397`。
- 无启动中的进程/服务/后台任务；无未完成测试（两侧 113 OK, 1 skipped）。

## 已完成任务

- M0 全部（复制 49 文件 + 3 根配置合并 + manifest + 报告 + 台账），详见 task-status.md 与 m0-report.md。

## 失败测试 / 已知问题

- 无。唯一跳过的测试为源工程原有 skip（非本次引入）。

## 下一步（P1 起点）

1. P1-01：读 `app/library/`（catalog.py、adapters/、changes.py、ingest.py、runtime.py），产出接口探测报告与来源权限清单。
2. P1-02：设计 `app/knowledge/`（游标、版本任务幂等键 `(source,doc_id,version_id,stage,config_digest)`、不可变快照），先 ADR 再实现。
3. P1-03/04：合成样本契约 + 测量工具先行；真实 30 份样本与 token 实测在获得真实源访问前记 BLOCKED（不阻塞其他任务）。

## 阻塞 / 缺项（合并清单）

- 真实源资料访问方式（本地只读路径或服务器）未提供 → P1 真实样本测量、A01/A04/A05 真实部分 BLOCKED。
- LLM/embedding 供应商、凭据、预算未定 → P4 真实调用 BLOCKED（默认关闭，不影响 P1-P3 离线开发）。
- 生产服务器访问未授权 → P3 全量影子回填生产部分、P6 全部 BLOCKED（部署配置可离线准备）。

## 约束提醒

不修改源工程与两份原始归档；不 force-push；不猜凭据；OCR/LLM 走独立 worker；`/api/v1` 行为保持，新接口 `/api/kb/v1`；人工笔记不自动覆盖。
