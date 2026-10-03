# 发布前修复与影子验收日志（T01-T07 / G1 / G2）

基线：第三轮评审 `4036a2b`（评审源码基线 `cb254df`，NEEDS_CHANGES，7 组问题 4P1/3P2）。
回归命令（PowerShell）：`$env:PYTHONPATH="app"; python -m unittest discover -s app/tests`

## N0 基线（2026-10-03）

- Git：HEAD `4036a2b`，clean；评审证据 `third-review-evidence-20261003.json` + 探针 `third-review-probe-20261003.py`。
- 回归基线：287 OK / 2 skipped（与评审一致）。
- T01-T07 断言式回归载体：`app/tests/test_third_review.py`（含旧 schema fixture 构建：用 git 基线 `0a473d9` 的 SCHEMA 建带数据旧库，验证升级而非新库冒烟）。

## RED/GREEN 记录

| 任务 | RED（基线复现） | GREEN | 提交 |
|---|---|---|---|
| T01 旧库升级 | 旧 schema（0a473d9 fixture）打开即报 no such column | 依赖列的索引移出 SCHEMA 到 POST_MIGRATION_INDEXES（列存在后才建）；版本化迁移（user_version=2）；带数据旧库升级+重开+半迁移容忍全部通过 | c99f159 |
| T02 预算状态机 | 结算中断额度复活；unknown 重放双记账；付费坏向量 release；HTTP 重试逃逸门禁 | fail_unknown 状态+usage 同事务（reservation_id UNIQUE 幂等）；坏 shape settle 真实用量不 release；attempt_ledger 门禁每次物理尝试（含重试）；counts_request 贯穿预留/usage/汇总 | c99f159/4109655 |
| T03 版本公开时间 | v2 继承 v1 的公开日期（1月→8月版本 7月查询命中） | 绑定用 STORED first_observed_at（新行用 upsert 的 synced_at 参数兜底）；早于首观察的文档日期对版本=unknown | c99f159/4109655 |
| T04 元数据纪元 | 同长度 symbol 修改 epoch 不变（只哈希长度和） | epoch 改为全部过滤相关字段值的规范化哈希（available/symbol/doc_type/日期/版本公开时间） | c99f159 |
| T05 漏页+recipe | 空 OCR 页+回退失败仍 ready；质量逻辑变化 digest 不变 | 空 OCR/回退失败页状态化（needs_ocr_unmet/ocr_empty_after_fallback/ocr_fallback_failed）并降级文档；EXTRACT_CONFIG v5 + QUALITY_CONFIG 深拷贝进 digest | c99f159 |
| T06 召回/缓存 | 前 200 截断（第 205 强语义目标永不召回）；同名同维度跨 provider 复用缓存 | 向量腿嵌入/打分完整允许集合（embed_top 只限融合 top-k）；缓存键=embedding_cache_key(provider+model+dims+host) | c99f159 |
| T07 幂等候选 | 同一 v2 三次导出=3 份重复文件 | 候选带确定性身份（name+content hash）进 manifest；重复投递返回既有文件（unchanged） | c99f159 |

（逐项随修复填充。）

## N4 G1 复验（2026-10-03）：**G1 通过**

- 逐字重跑评审探针 `third-review-probe-20261003.py`：**14/14 场景全部呈现修复后行为**（旧库打开、并发预留恰一个、页上限 1 拒 2、结算中断不复活、重放单次记账、付费坏向量不释放、重试尝试==记账、公开修订 unknown+0 命中、纪元翻转+409、混合 PDF review、recipe digest 变化、跨 provider 重嵌入、第 205 位召回、重复导出单份）。
- 全量回归：**301 tests OK (2 skipped)**（287 基线 + 12 T 回归 + S09 部署 + rf6 修正）。
- 旧库升级 fixture（git 基线 0a473d9 SCHEMA + 数据）在 T01 回归中持续验证。

## N5 影子验收（进行中，2026-10-03）

- 工具链（tools/shadow-acceptance/，已入 Git）：采样（30 份分层=20/10，身份从只读 catalog 固定）→ dry-run → 隔离执行（独立 state，任务剪枝到样本集）→ 对账报告；标注模板 30 份已生成在服务器 shadow/annotations/。
- **已在服务器启动隔离小批**：独立 knowledge DB + 快照根（shadow/state，与生产完全隔离）；快照阶段 61 done 0 failed；提取阶段进行中（OCR 密集文档约 27s/页，预计 1-2 小时完成）。进度查看：`ssh chen@192.168.1.150 'python3 -c "...jobs GROUP BY status..."'`（见 SHADOW-RUNBOOK）。
- 完成后按 RUNBOOK 执行：对账（A01/A14）→ 连跑两次验证幂等（A02）→ 人工标注（A04/A06/A08/A09 金标准，盲测集隔离）→ measure（A05）。**人工标注未完成前相关验收保持 NOT_RUN。**

## N6 全量 dry-run（只读，已完成）

在服务器以只读连接对生产知识库执行 `full_wave_dryrun.py`：
- ready 版本 524（discord 438 + reports 86）；快照全部就绪（0 需补）。
- **新 recipe（v5，含 T05 页级质量门禁）下需重提取 524 份**：预估 14,751 页、OCR 候选 2,792 页。
- 不可变性：既有 1,123 提取 / 213,829 块全部保留，新 recipe 产生全新身份行。
- 恢复：任务幂等（stage+config 唯一），中断即续。

## G2 状态：**未达成**（等影子人工标注 + 真实门禁）；全量/生产操作待授权。
