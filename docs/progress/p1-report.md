# P1 验收报告：数据基础与样本测量

日期：2026-10-01。执行：main-agent（self-reviewed）。完成度：**源码实现 + 离线验证**；真实数据验收与生产部署 NOT_RUN/BLOCKED（见下）。

## 交付内容

### P1-01 接口探测（PASS，离线代码审计）

报告 `docs/progress/p1-01-interface-audit.md`：第一层身份/版本/变更账本/API/原文验证语义全部核实；知识层接入面（只读 catalog、resolve_version_path、FileLock、hash_file_stable）确定；`Catalog` 类不得用于打开生产库（会执行 DDL）的约束已记录并落实（知识层用 `mode=ro` 连接，测试覆盖写拒绝）。

### P1-02 知识层存储与幂等（PASS，合成数据）

ADR0003 + `app/knowledge/`（标准库实现，零新依赖）：

- `store.py`：独立 `knowledge.sqlite3`；kb_documents/kb_versions 幂等镜像（身份列不可变）；jobs 表以 `(source, doc_id, version_id, stage, config_digest)` UNIQUE 强制幂等；租约/attempts/状态机。
- `snapshot.py`：内容寻址不可变快照——同一文件描述符上哈希+流式复制、临时文件复验、原子 rename；同哈希跨来源去重共享；绑定前对已存在 blob 做完整哈希校验（测试暴露仅查大小的漏洞后加固）；绝不覆盖/删除既有 blob；快照身份重写直接拒绝。
- `sync.py`：全量版本对账幂等 upsert；仅 ready 版本注册快照任务；conflict/missing 如实镜像不入队。
- `jobs.py`：快照任务执行器，租约过期自动恢复；身份冲突永久失败不无限重试；跨进程 FileLock。
- CLI：`python -m knowledge sync|run-snapshots|status|sample|measure`。

### P1-03 样本契约（PASS 合成 / 真实 BLOCKED）

`sampling.py`：按 (source, format, language) 分层比例抽样，每层保底 1 席；确定性（seed）；manifest schema `researchkb.sample-manifest/1`，每样本固定 (source, doc_id, version_id, sha256, stratum, split)。默认 30 份 = 20 调优 + 10 盲测。
**BLOCKED**：真实 30 份分层样本与人工标注（A04）需真实源访问，未获得；合成运行仅验证契约与确定性。

### P1-04 测量工具（PASS 合成 / 真实 BLOCKED）

`measure.py`：从不可变快照测量 txt/html 正文（字符数、文本哈希、编码）、PDF 页数（无压缩对象流可测；压缩流诚实返回 None+原因）；token 计数可插拔，默认启发式计数器**显式标记 approximate**（CJK≈1字/token、拉丁≈4字符/token），报告字段强制携带 method/tokenizer/note；`register_token_counter` 供真实 tokenizer 接入；未提取名单（unextracted）逐条给出原因。
**BLOCKED**：真实页数/正文/精确 token（A05）需真实源 + 选定 tokenizer，均未具备；当前一切 token 数字只是数量级参考，不用于预算结论。

## 验收场景对照

| 场景 | 结果 |
|---|---|
| A02 幂等（同输入连跑3次无重复） | PASS（合成）：sync×3 计数稳定、jobs 无新增；快照二轮 0 处理、blob 数不变 |
| A03 版本与恢复 | PASS（合成）：新增版本→新行+新快照，旧快照字节不变可读；上游覆盖→conflict 镜像+不入队+旧快照保留；同长度篡改→hash fail-closed 永久失败；租约过期→自动恢复重跑成功 |
| A01 来源清单 | BLOCKED（无服务器/源访问） |
| A04 真实样本标注 | BLOCKED（同上）；工具与契约就绪 |
| A05 真实 token 测量 | BLOCKED（无源、无 tokenizer）；近似计数已显式标注 |

## 测试与验证

- 全量：`PYTHONPATH=app python -m unittest discover -s app/tests` → **134 tests OK (1 skipped)** = 113 第一层回归（未改动）+ 21 知识层新测试。
- 知识层对第一层零代码改动（只读消费）；`git diff` 复核无 library 文件变更。
- 快照验证链测试化：fd 稳定性、大小/哈希双校验、复验、原子性、去重、损坏检测、身份重写拒绝。
- CLI 冒烟（sync/run-snapshots/status）在测试中端到端跑通。

## 已知限制

1. `test_knowledge_measure` 依赖 fixtures 全 PDF 语料，img OCR/PDF 正文提取留待 P2（状态字段如实标注 not_extracted）。
2. 抽样按 language 取自 catalog documents.language，来源未标语言的归 unknown 层。
3. 快照存储成本 ≈ 源库体积（~1.76GB），服务器部署前需磁盘评估（ADR0003 已记）。
4. 真实 A01-A05 全部待源访问后执行，届时命令：`knowledge sync` → `run-snapshots` → `sample --total 30` → 人工标注 → `measure --manifest ...`（换真实 tokenizer counter）。
