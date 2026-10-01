# 会话检查点 / HANDOFF

更新：2026-10-01（P1 完成后，P2 开始前）。

## 当前状态

- M0 已完成（`0f3a19f`）；P1 已完成（`2889a12`，离线实现+验证），均已推送 obsidian-sync.git。
- 主分支 main，远端唯一 `git@github.com:jupiterr-chen/obsidian-sync.git`。
- 测试基线：**134 OK (1 skipped)** = 113 第一层回归 + 21 知识层。命令：PowerShell `$env:PYTHONPATH="app"; python -m unittest discover -s app/tests`。
- 源工程 research-kb 未改动（基线 5442e397）；无运行中进程；工作树干净。

## 已完成任务

- M0：整合（49 文件、manifest、报告）。
- P1：接口审计报告、ADR0003、app/knowledge（store/snapshot/sync/jobs/sampling/measure + CLI `python -m knowledge ...`）。真实 A01/A04/A05 BLOCKED 已记录。

## 失败测试 / 已知问题

- 无失败。skip 1 项为源工程原有。已知限制见 p1-report.md（快照存储≈源库体积、PDF正文/OCR留P2、language=unknown层）。

## 下一步（P2 起点）

1. P2 ADR：解析器选型（纯标准库文本/PDF文字层/HTML DOM 的离线实现边界；OCR 本地引擎与外部依赖的引入策略——默认不装重依赖，先标准库+可插拔接口）。
2. `app/knowledge/extract.py`：extraction_id（源版本+解析器+配置摘要）、extract stage 任务、正文/块/locator 存储表、证据块 schema 对齐 contracts/evidence-block.schema.json。
3. 按页质量判断与 OCR 路由接口（本地引擎可插拔；无引擎时诚实标 not_extracted）。
4. HTML DOM 解析（标准库 HTMLParser）+ 固定快照证据视图准备。
5. 更新 measure.py 挂接真实提取器，使 P1-04 工具在 P2 后可测 PDF 页数/正文。

## 阻塞 / 缺项（合并清单）

- 真实源资料访问（本地只读路径或服务器）→ A01/A04/A05 真实部分、全量对账 BLOCKED。
- LLM/embedding 供应商、凭据、预算 → P4 真实调用 BLOCKED（默认关闭）。
- 生产服务器访问 → P3 影子回填生产部分、P6 BLOCKED（配置可离线准备）。
- OCR 本地引擎选型（PaddleOCR/Tesseract）许可与离线能力 → P2 真实 OCR 质量门禁 BLOCKED；接口与合成路由测试先行。

## 阻塞 / 缺项（合并清单）

- 真实源资料访问方式（本地只读路径或服务器）未提供 → P1 真实样本测量、A01/A04/A05 真实部分 BLOCKED。
- LLM/embedding 供应商、凭据、预算未定 → P4 真实调用 BLOCKED（默认关闭，不影响 P1-P3 离线开发）。
- 生产服务器访问未授权 → P3 全量影子回填生产部分、P6 全部 BLOCKED（部署配置可离线准备）。

## 约束提醒

不修改源工程与两份原始归档；不 force-push；不猜凭据；OCR/LLM 走独立 worker；`/api/v1` 行为保持，新接口 `/api/kb/v1`；人工笔记不自动覆盖。
