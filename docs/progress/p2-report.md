# P2 验收报告：正文、OCR 路由与证据定位

日期：2026-10-01。执行：main-agent（self-reviewed）。完成度：**源码实现 + 离线（合成）验证**；真实语料质量门禁与生产 NOT_RUN/BLOCKED。

## 交付内容（ADR0004）

### 提取器注册表与四种格式（`app/knowledge/extract.py`，纯标准库）

- **TXT**：空行分段；locator `{kind:text, start_char, end_char}`（对规范化文本的字符偏移）。
- **HTML**（`html.parser` DOM 树）：script/style/noscript/template 剔除；heading/paragraph/table/caption 块；`dom_path`（`html[1]>body[1]>table[1]` 形式）；表格投影=表头联接到每行（可搜索文本，非计算数据源）；块级 start/end_char。
- **PDF**（zlib+re 内容流解析）：页对象→/Contents 引用→流解压（含 FlateDecode）→文本显示算子（Tj/TJ/'/"，字面串转义+八进制、十六进制串）→按页段落块 `{kind:pdf, page:N}`；**CID/高位字节探测→`cid_font_unsupported` 置 review，绝不猜测解码**。
- **图片**：OCR 引擎可插拔（`register_ocr_engine`）；无引擎时 `needs_ocr_engine` + review，不产假文本；有引擎时带 confidence，<0.8 标 `low_ocr_confidence`。

### 质量与 OCR 路由（`quality.py`）

阈值版本化（QUALITY_CONFIG v1）：no_text→failed；too_short/replacement_chars/control_characters/repetitive_lines/mostly_sparse_pages→review。按页路由（A08 前置）：no_text_layer/very_sparse_text/replacement_chars→OCR 候选并计入 stats。

### 不可变提取产物与证据块

- `extraction_id = sha256(source, doc_id, version_id, snapshot_sha256, parser_id, parser_version, config_digest)`；extractions/blocks 表；重复执行 no-op；不同解析器/配置产生新行，旧行不删（A03 证据绑定）。
- `to_evidence_block` 出库组装，严格对齐 `contracts/evidence-block.schema.json` v1；`schema.py` 内置无依赖校验器（正/反例测试，契约示例通过）。
- 任务链：snapshot 成功→注册 extract 任务；`python -m knowledge run-extracts`。

### 数值与表格基线（`tables.py`）

保守规范化：括号负数、千分位（含空格/欧式 1.234,56）、百分号、货币符、Unicode 减号；分组不合法/歧义小数逗号/非纯数字→显式 issues + value=None，**不猜**。TableBlock 保留原始单元格与表头行结构。A09 真实财务门禁仍 BLOCKED（需标注样本）。

### measure.py 升级（P1-04 工具就绪）

测量改走提取注册表：PDF 有文字层即测 chars/tokens/页数（标注 parser 与 extract 状态），否则带原因进未提取名单。

## 验收场景对照

| 场景 | 结果 |
|---|---|
| A06 正文可用性（每源 ready/review/failed） | PASS（合成）：状态机+issues 全覆盖；真实盲测 BLOCKED（需真实样本） |
| A07 证据定位 | PASS（合成）：块→证据块 schema 校验 0 错误；pdf page/html dom_path+char span/text span 定位正确；旧引用稳定性由不可变 extraction_id 保证 |
| A08 OCR 路由 | PASS（合成）：稀疏/零文本/替换符页→OCR 候选；真实 OCR 质量统计 BLOCKED（无本地引擎，未装重依赖） |
| A09 财务表格 | PASS（合成，规范化单测）；真实 ≥100 数值门禁 BLOCKED |
| A02/A03 回归 | PASS：提取链三跑计数稳定；新增版本→新提取行；快照/提取身份均不可变 |

## 测试

`PYTHONPATH=app python -m unittest discover -s app/tests` → **153 OK (1 skipped)** = 113 第一层 + 21 P1 + 19 P2。第一层与 P1 代码零回归改动（仅 jobs.py 扩展新方法）。

## 已知限制与升级路径

1. 标准 PDF 解析器覆盖：无对象流压缩（ObjStm）的文件；真实语料中现代 PDF 大多使用 ObjStm → 这类文件在 P1 的 measure 中标 `object-streams-unsupported`，在 P2 extract 中无页对象则 failed/no_page_objects（诚实失败）。**升级路径：选定 PyMuPDF/pdfplumber 后注册同接口提取器，extraction_id 自动区分版本**（ADR0004 已定义），无需改存储/任务。
2. 中文字体（CID）PDF：标记 review 而非解码——真实中文研报的文字层提取依赖升级解析器或 OCR，属预期 BLOCKED 而非缺陷。
3. HTML 基线解析不处理 XBRL 事实（doc/03 的独立事实适配器在 P3/P4 数据接入时另行设计）。
4. 表格仅投影+单元格结构；合并单元格、多级表头、期间/币种绑定在真实样本进入后迭代。
