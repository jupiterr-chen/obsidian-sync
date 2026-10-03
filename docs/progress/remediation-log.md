# 评审修复执行日志（RF0-RF7）

基线：评审 `534014a` + 评审文档提交 `a393a7f`。执行起点工作树干净，222 tests OK (2 skipped)——与评审报告一致。
命令（PowerShell）：`$env:PYTHONPATH="app"; python -m unittest discover -s app/tests`

## RF0 基线（2026-10-03）

- Git：HEAD `a393a7f`，clean；主远端 obsidian-sync.git。
- 回归基线：222 OK / 2 skipped。
- 修复回归载体：`app/tests/test_review_regressions.py` + `test_review_rf2..rf6.py`（逐 RF 先 RED 后 GREEN）。

## RED/GREEN 记录（修复提交均含逐项细节）

| RF | 问题 | RED（修复前复现） | GREEN（修复后） | 提交 |
|---|---|---|---|---|
| RF1 | R01 预算失效/vision 无账本 | 限额10已用9仍调用至72；vision usage 丢弃；顶层 budget 加载为 None | 统一 BudgetLedger（预留/结算/未知计费）；vision 页级门禁+入账；顶层配置生效 | 4b90a75 |
| RF1 | R03 vision 主路由无 provider | JobRunner.ocr_engine 不传 providers → chat_provider None | 角色化装配（vision 不冒充 chat）；主路由+fallback 均绑定 | 4b90a75 |
| RF2 | R04 损坏快照仍被提取发布 | 同大小/异大小损坏均成功产出伪 sha 证据 | 消费前哈希+大小校验；corrupted 标记；link 原子落位；重访校验 | 310cad4 |
| RF2 | R02 OCR 配置不进身份 | off 与 local+DPI300 digest 相同；重复任务重复付费 | 有效配置摘要（引擎/DPI/阈值/模型名/依赖版本）；预检跳过零成本重跑 | 310cad4 |
| RF2 | R05 页序/漏页 | Kids=[9,3] 时 page1=SECOND；稀疏文档 ready | pypdfium2 生产引擎+页树顺序；Kids 树回退；缺内容页降级；chars_per_page 全填充 | 310cad4 |
| RF2 | R06 HTML 重复段落定位 | 两段相同文字 locator 均 [0,23] | 解析期规范化流+精确 span；stats 暴露 normalized_chars | 310cad4 |
| RF3 | R08 历史版本混入/as_of 语义 | 2月 system 查询返回 10 月 v2；available=false 仍命中；无公开日期伪造 | ADR0007 当前版选版；版本级 first_observed（旧库 unknown）；public 需真实日期依据；available 过滤 | 1686d7d |
| RF3 | R07 中断索引发布空代 | 崩溃残留 building 重跑直接激活，active blocks=0 | verified-only 激活门禁；崩溃残留删除重建；失败保留旧 active | 1686d7d |
| RF4 | R09 混合绕过筛选 | symbols=NO_SUCH 返回 6 块 | 允许集合先行（含 as_of 版本级）；零命中零嵌入；向量形状校验 | 93e8298 |
| RF4 | R11 固定版本 URL 404 | documents/.../versions/v 全部 404 | 路由长度修正；版本详情挂 snapshot_url；/snapshots 字节服务（读时再校验+ETag+CSP）；全 URL HTTP 回访 | 93e8298 |
| RF4 | R12 分页提前结束 | 6 条 limit2 第二页仅 1 且无 cursor；limit100 无下页 | 窗口取全 offset+limit+1；确定性排序（分教+block_id）；游标绑 mode；400/409/422 分明 | 93e8298 |
| RF5 | R10 同秒候选覆盖 | 同秒候选互覆；人工候选被覆盖 | 独占创建+随机身份候选（追加式）；主文件替换前重读哈希；manifest 文件锁；写根白名单 | 29590dd |
| RF5 | R15 影响任务漏掉 | max(synced_at)+LIMIT25 静态缺陷 | 持久 impact_outbox（同步同批入队）；分批消费至清空；崩溃后补处理；幂等去重 | 29590dd |
| RF6 | R13 编排不可解析 | 两 YAML 解析错误；Dockerfile 缺依赖；CUTOVER 占位路径 | healthcheck 模块化；requirements 锁定+模型预热镜像；真实路径+写者冻结+回滚保护切换后写入；服务器 docker compose config + 镜像内 PDF/OCR 冒烟通过 | 36c84b5..6ffb0d6 |
| RF6 | R14 恢复缺快照仍成功 | 无 blob 时 ok=true exit0 | 默认用备份自带 blobs；缺引用即失败；--database-only 显式部分恢复 | 36c84b5 |

## 最终回归

`Ran 268 tests in ~65s — OK (skipped=2)`（基线 222 → 268，+46 修复回归；2 skip 为依赖装没装的分支跳过，非本轮引入）。

## 遗留（真实环境依赖，保持 NOT_RUN/BLOCKED）

- A06-A22 真实门禁（标注样本/50 查询基准/7 天窗口/真实 RTO）。
- 服务器 v3 回填仍在后台跑（未停）；修复代码已在仓库，回填完成后重启 worker 即按新逻辑（R02 身份、R04 校验、R07 索引恢复）。
- 生产切换需用户明确确认（CUTOVER.md 可执行）。
