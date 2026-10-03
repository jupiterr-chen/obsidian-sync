# 第二轮修复执行日志（S01-S10）

基线：二轮评审 `4949dcd` + 评审材料 `0a473d9`（NEEDS_CHANGES，反例见 `re-review-evidence-20261003.json` / 探针 `re-review-probe-20261003.py`）。执行起点工作树干净，268 tests OK (2 skipped)。
回归命令（PowerShell）：`$env:PYTHONPATH="app"; python -m unittest discover -s app/tests`

## SR0 基线（2026-10-03）

- Git：HEAD `0a473d9`，clean；远端 obsidian-sync.git 正常推送。
- S01-S10 断言式回归载体：`app/tests/test_second_review.py`（+ `budget_under_test.py` 双独立连接驱动真实跨连接事务竞争）+ `test_second_review_s09.py`（部署）。先 RED：基线上 11 个 S 断言失败；S08/S10 初版断言过弱，经探针复核强化为评审原始反例（4 块翻页撤回、纯语义零词法命中）后才计入 RED。

## RED/GREEN 记录（S01-S10 全部 GREEN）

| 任务 | 原 R | RED（基线复现） | GREEN（修复机制） | 提交 |
|---|---|---|---|---|
| S01 | R01 | 双连接并发 cap10 各预留 6 → 两者都过、总预留 12；cap1 页连续接受 3 页；settle 中断后额度复活（探针三例全复现） | reserve 检查+插入并入单条 BEGIN IMMEDIATE；totals 计入未决预留与 vision-page（unknown 也计页）；settle=状态翻转+usage 同事务，usage_events.reservation_id UNIQUE 保证幂等重放；缺 usage 按预留估计入账（成功调用永不计 0）；settle_crash 崩溃钩子验证预留不消失 | `01c02d7` |
| S07 | R15 | upsert 提交后 enqueue 前中断 → 重跑 new_versions=0 且 pending=0，任务永久丢失 | enqueue 移入 upsert_versions 同一事务（_enqueue_impact_conn）；中断则整体回滚，重试原子重做两件事；期间发现并修复一次循环体误折叠（S07 测试自身拦截） | `01c02d7` |
| S04 | R04/R11 | 校验后重开路径读取 → 改写后返回新字节配旧 ETag | snapshot_bytes 哈希**将要返回的同一份字节**，并发改写重读最多 3 次，仍不一致 409+corrupted；ETag 永不描述别的字节 | `a7640fd` |
| S05 | R05 | conf=0.1、阈值 0.6、文字够长 → 文档与块都 ready | 逐页置信度/状态进 stats（page_confidences/page_ocr_status）；低于阈值、空 OCR、回退失败、预算拒绝页的块质量=review 并拉低文档状态；其他页文字量不构成证据 | `a7640fd` |
| S06 | R02 | 图片预查身份用 stdlib-image，实存 stdlib-image+engine → 命中检查在 OCR 之后，同图重跑 OCR×2 | extractor_info('img') 带实际引擎名（runner 传入将用的引擎）；预查在 OCR 前命中，零重复付费处理 | `a7640fd` |
| S02 | R10 | 最后哈希检查后、replace 前写入人工文本 → 返回 written，人工内容丢失（探针复现） | 主名只**一次独占创建**；此后任何导出（即使文件仍匹配我们的哈希）都是唯一命名追加候选——不存在可竞争的「读哈希再替换」序列；人工编辑按构造不可丢 | `a7640fd` |
| S03 | R08 | 报告期 6/30、发布 8/20，7/1 public 查询命中（未来信息泄漏） | 版本级 public_available_at+public_time_basis（published_at>filing_date>unknown；report_date 永不算公开证据）；文档预过滤+逐候选检查+允许集合 SQL 三处一致 enforcement；依据后补时回填、未知保持未知 | `a7640fd` |
| S08 | R12 | 翻页间撤回文档 A → 第二页空且 next=null，B 被跳过 | 游标绑定元数据纪元（available/symbol/doc_type/日期摘要）；元数据修订即 409 cursor_expired，撤权实时生效 | `a7640fd` |
| S10 | R09 | 弱词法命中 K 返回、强语义零词法 S 遗漏；缓存仅按 model 无 provider/维度隔离 | 向量腿独立从完整允许集合召回再 RRF 融合（S 必进候选）；缓存键=(model, dims, block)，同名模型不同维度互不复用 | `a7640fd` |
| S09 | R13 | library 继承镜像 CMD=knowledge worker；`|| true` 吞构建失败；CUTOVER 相对路径错目录、writeback 用宿主路径 | library 显式 `python -m library serve` 命令；RUN 行去掉 `|| true`（依赖/预热失败构建失败）；CUTOVER 每步显式 cd + 容器视角路径（/vault、/state/snapshots） | `e369d32` |

## SR5 隔离启动验收（S09，服务器 /tmp 独立目录，未动生产）

1. 镜像构建：`docker build -f Dockerfile.knowledge` 成功（预热失败会失败——RUN 已无 `|| true`）。
2. library 容器（显式 serve 命令）：`/healthz` 返回 ok，100 文档/85 可用/90 版本（真实只读 reports 归档）。
3. knowledge API 容器：`/api/kb/v1/health` → `{"status": "ok"}`。
4. worker 一次性闭环（同镜像，独立 state）：sync 90 版本 → 86 快照任务注册 → 86 快照落盘 → 索引发布 generation `gen-32aa9eda…`。
5. 冒烟目录（容器 root 写入）经一次性容器清理，生产容器列表未变（research-kb-library/status-collector/syncthing 原样运行）。

## SR6 最终回归

`Ran 287 tests in 66.0s — OK (skipped=2)`（二轮基线 268 → 287，+19：16 个 S 回归 + 3 个 S09 部署回归；2 skip 为依赖分支跳过，非本轮引入）。

三个第一代测试按修正后的语义更新（均带原因注释）：R08 public 基准、index_api public 过滤、RF5 writeback「机器可再覆盖主文件」断言（该行为正是 S02 废除的）。

## 真实缺项（保持 NOT_RUN/BLOCKED，不因修复关闭）

- A06-A22 真实门禁（盲测样本/50 查询基准/7 天窗口/真实 RTO/真实 provider 质量）。
- 生产切换（CUTOVER 演练需用户明确授权；本轮仅隔离目录验证）。
- 服务器 v3 OCR 回填产物为修复前身份；采用本轮修复逻辑需第四轮重提取（十几小时级，待授权）。
