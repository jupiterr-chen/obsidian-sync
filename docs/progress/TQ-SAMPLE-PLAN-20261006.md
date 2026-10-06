# 正文质量分层样本与资源测量方案（TQ，2026-10-06）

依据[docs/33](../33-text-quality-repair-taskbook.md)"全量梳理≠强制全库OCR"。**本文件是方案；生产样本运行与历史批量重提取均未授权、未执行。**代码已就绪：`knowledge quality-inventory`（只读清单）、`knowledge reprocess --dry-run`（批次选择预演）、隔离测量 harness（`tools/text-quality/sample_measure.py`）。

## 1. 分层样本（目标 12–20 份，从 TQ0 清单确定性选取）

分层依据 = 推荐动作 × 引擎 × 问题类型 × 格式。选取规则（确定性、可复算）：每层按 `(source, doc_id)` 字典序取前 N 份，记录选取时的 inventory manifest_hash。

|层|选取条件（TQ0 字段）|份数|验证目的|
|---|---|---|---|
|L1 旧引擎+损伤|action=native-reextract 且 pages_damaged>0 且 engine=stdlib-pdf*|4|原生重提取是否消除控制字符/CID；坏文本层页是否被干净替代|
|L2 旧引擎+无损伤标记|action=native-reextract 且 pages_damaged=0|3|引擎升级收益；正常文本不得回归|
|L3 扫描/稀疏|unmet_ocr_pages>0 或 pages 里 recorded_status=needs_ocr_unmet|3|按需 OCR 页数、置信度分布|
|L4 混合|pages_damaged 与健康页并存|2|逐页路由精度（健康页不 OCR）|
|L5 正常对照|action=keep，中英/繁体/特殊字符（¥ £ Ø Ë é）|2|零误伤：不误送 OCR、不删合法字符|
|L6 已有良好 OCR|engine 含 rapidocr 且 status=ready|1|重提取不劣化既有结果|
|L7 缺/坏原文|action=missing-source|1|诚实失败路径|
|L8 长报告|pages_total 最大者|1|分段/资源上限、断点续跑|
|L9 财务表关键数字|含数字/百分比密度最高的 2 份|2|关键数字页对照（重提取前后一致）|

合计 19 份。每层宁可少不可缺；某层不足时记录"层缺失"。

## 2. 隔离测量（不触生产）

`tools/text-quality/sample_measure.py`（本轮交付）：输入 inventory JSON + 选取规则 → 对每份样本在**隔离 state**（独立 snapshot_root 副本目录）执行：原生重提取 → 逐页路由 → 必要页本地 OCR（rapidocr）→ 新旧 block 对照。输出每份：页数、OCR 候选页数、OCR 实际页数、每页 CPU 时间、峰值内存（psutil 不可用时标 unknown）、前后损伤页数、关键数字抽样 diff（正则 抓取 数字/百分比/页码并对照）、失败原因。汇总：小批（≤20）/中批（≤100）/保守（全库候选）三档外推，页数/时间未知项如实标 unknown。

## 3. 生产批次流程（待授权）

1. 用户授权后：生产 `quality-inventory` 全量清单（只读）→ 按本方案选样本 → 授权窗口内对样本实跑测量 → 人工对照问题页/对照页/尾页/财务数字。
2. 测量结论 → 分批 `reprocess --batch-id <date>-<n> --max ≤20`（每批显式、可审计、可中断续跑）→ 每批后 `quality-inventory` 复扫 + 阅读入口抽查。
3. 全部批次完成 → 全库复扫 + 样本人工对照 → 达标后才允许索引/阅读主入口整体呈现新结果（TQ3 切换保护已在每批生效）。
4. Vault 治理：`governance-plan` 逐文件计划 → 用户按精确路径授权后才执行归档/移除（归档为 Vault 外可恢复档案，保留 path/hash/extraction 映射）。

## 4. 边界（如实）

- 不把另一 agent 的 304/321 当 OCR 任务数；本方案以 TQ0 清单的实际推荐动作与页级分类为准。
- 不强制全页 OCR；原生引擎成功且文本健康的页直接保留。
- 本地 PDF 提取/本地 OCR 不消耗 LLM token；远程视觉模型不是默认 fallback，若需外发另行授权。
- 修复正文不触发历史全库 LLM 重分析（分析 allowlist 见 MA03）。
