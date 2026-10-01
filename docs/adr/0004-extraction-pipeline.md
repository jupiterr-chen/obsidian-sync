# ADR 0004：提取层架构与解析器策略

状态：已接受，2026-10-01（P2 实现）。

## 背景

P2 需要可定位正文、HTML 解析、按页质量判断与 OCR 路由、证据块与不可变提取产物（docs/02/03）。docs/03 列出 PyMuPDF/pdfplumber/Docling/PaddleOCR/Tesseract 为候选，但当前环境未选定、未安装，且授权边界允许安装必要开发依赖但要求离线可测。

## 决定

1. **可插拔解析器注册表**：`extract.py` 按 format 注册提取器（`register_extractor`）；每个提取器自报 `parser_id` 与 `parser_version`，进入 extraction_id。默认实现全部纯标准库（zlib+re 解 PDF 流、html.parser 解 HTML）；PyMuPDF 等真实解析器作为后续替换项注册，不改存储与任务结构。
2. **extraction_id 幂等**：`sha256(source, doc_id, version_id, snapshot_sha256, parser_id, parser_version, config_digest)`。同一提取配置重复执行为 no-op（A02）；配置/解析器变化产生新 extraction 行，旧块不删除（证据绑定旧提取版本）。
3. **存储**：knowledge 库新增 `extractions`（含 status/quality/stats）与 `blocks`（对齐 contracts/evidence-block.schema.json v1：block_id、block_type、text、locator JSON、quality）。证据块出库时按 schema 组装；测试内置最小 schema 校验器（不引入 jsonschema 依赖）。
4. **质量与 OCR 路由**：`quality.py` 按字符密度、替换符比例、重复行、控制字符给出 ready/review/failed 与 issues；OCR 引擎接口 `OcrEngine` 可插拔，无引擎时如实标 `needs_ocr`/`not_extracted`，不伪造文本。OCR 独立 worker 的执行边界在 P3/P4 落地，本阶段仅接口与路由判定。
5. **诚实的能力边界**：标准库 PDF 解析器处理未压缩/zlib 压缩内容流的单字节字体文本与页映射；CID/CJK 字体无 ToUnicode 时标记 `cid_font_unsupported`（quality=review）而非猜测字节。中文 PDF 真实质量门禁（A06/A07 真实部分）依赖解析器升级与真实样本，BLOCKED 状态如实记录。
6. **任务链**：snapshot 任务成功后注册 `extract` 任务（stage 依赖顺序内聚于 runner）；sync 不直接注册 extract。
7. **measure.py 升级**：测量工具直接消费注册表提取器，PDF 不再一律 not_extracted——能提取就测，不能就带原因进未提取名单。

## 收益与代价

收益：零新增依赖下打通 提取→质量→块→证据契约 全链路；真实解析器/OCR 引擎接入点明确；旧提取永不覆盖，引用稳定。

代价：标准库 PDF 解析器覆盖率有限（预期真实语料相当部分落入 review/needs_ocr），真实质量达标必须等解析器选型与实测；HTML 表格投影仅保结构不保口径（A09 真实门禁后置）。
