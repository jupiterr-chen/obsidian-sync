# GLM 完成后的第四轮独立复核

**结论：NEEDS_CHANGES；G1 仍有实现缺口，G2 未达成，不执行旧服务停机或生产迁移。**

源码基线 `cd3bb5d3fd560ca7876d945d7547494beae47347`。2026-10-03 23:29（上海时间）检测到 GLM 会话结束（finishReason=stop、无待发模型工具调用），Git 工作树干净；其服务器影子提取进程继续运行。本轮独立执行 **301 tests，OK，2 skipped，63.782s，退出码 0**，重跑第三轮探针并新增端到端反例。

用户已授权“复核无问题后整体迁移、停旧栈并验证”，该授权有效，无需再次索取相同确认。本次没有执行切换，因为下列问题使条件尚未成立；不是授权缺失。旧目录和服务保留。本轮只写评审文档/合成探针，服务器操作全部只读，没有模型调用、停进程、改库或改权限。

## 已认可的修复

T01 原索引先于加列的错误已消除；T02 unknown 事务及重复结算、坏向量释放的原反例已修复；T04 同长度元数据变更现使游标失效；T05 空 OCR 混合页降级与 recipe 升级已修复；T06 205块召回和跨 provider 缓存的原反例已修复；T07 完全相同文本重复投递已去重。遗留问题主要位于旧数据、其他 provider 入口及真实渲染/影子流程。

## U01 [P1] 旧库升级漏加 usage_events.counts_request（T01）

位置：`app/knowledge/store.py:341-350`；`app/knowledge/budget.py:82-94`。

新 SCHEMA 给 usage_events 和 budget_reservations 都加了 counts_request，但迁移列表只覆盖后者。用 `0a473d9` schema 建库再升级：KnowledgeStore 打开成功，第一次 `BudgetLedger.reserve()` 就报 **no such column: counts_request**。旧库测试仅验证打开/旧行保留，没有执行升级后的账本业务。

服务器现用知识库的 usage_events 仍只有旧列（只读 PRAGMA 已确认），因此真实迁移会命中此缺陷。必须补齐迁移，并用有数据旧库实际执行 reserve/settle/unknown、API和worker路径；重复升级不得破坏旧账目。

## U02 [P1] 逐次 HTTP 门禁仅接在 embedding；请求记录不闭合（T02）

位置：`app/knowledge/analysis.py:52-55,270-284`；`app/knowledge/ocr.py:149-157`；`app/knowledge/providers.py:135-145`。

attempt_ledger 只在 budgeted_embed 内赋值。execute_analysis_run 和 VisionApiOcr 未装配此门禁，合成请求上限=1、第一次超时、允许内部重试时：**chat 和 vision 均发生2次 transport调用，账本各只计1次**。所有 transport 已 mock，没有真实请求。

embedding 成功路径另有未决记录：一次实测用量5 token后，http-attempt reservation 永久停留 reserved，汇总变为6 token。调用没有保存 attempt reservation id、没有结算/未知状态，也不能把尝试关联到 run。修复应统一 chat/vision/embedding 的物理请求状态机，分开请求数、token估算与真实usage；成功、超时、门禁拒绝都进入可解释终态。不能以只覆盖embedding的测试代表三个入口全部通过。

## U03 [P1] 迁移旧版本的 unknown 首次观察时间仍被当作允许填日期（T03）

位置：`app/knowledge/store.py:449-484`。

新记录v2的反例已修复，但旧数据 first_observed_at=NULL 时，`not row_first` 分支仍允许把文档旧发布日期填给版本。合成迁移旧v2：首次观察未知，重新同步后 public_available_at 被填成1月1日，7月查询返回v2内容（命中1）。服务器现用库早于这些字段，旧记录正是需要覆盖的主要场景。

unknown 应表示证据缺失，不是允许绑定；公开时间必须有针对该版本的来源依据。也要核对上轮误填时间的非破坏性纠正策略，COALESCE保留历史错误值不能作为验收通过。禁止以“入库晚于发布日期”直接判断所有原始版本不可信，应由来源身份/版本证据区分首版与修订版。

## U04 [P2] 真实 claim 导出仍因当前时间每次产生新候选（T07）

位置：`app/knowledge/writeback.py:91-114,193,222-238`。

当前去重键是渲染文本hash，render_claim_candidate 又插入每次运行的 utc_now。通过真实 export_claim_candidates 入口对同一个 accepted claim、同一 revision 连续模拟3个不同秒：**生成3个Markdown文件**。底层 write_candidate 相同字符串测试不覆盖实际定时导出。

幂等键应使用 claim_id/revision/模板版本等稳定业务身份，生成时间来自固定版本元数据。三次导出、重启、并发、创建文件后写manifest前中断均不能重复发布；人工修改继续保留。

## U05 [P1] 影子验收未形成可用于迁移的封闭证据（N5）

位置：`tools/shadow-acceptance/shadow_sample.py` 的 catalog SELECT/标注输出；`shadow_run.py` 的 shadow_config.extra/队列范围；`shadow_reconcile.py`。

2026-10-03 23:34只读检查实测：

|项目|结果|
|---|---|
|manifest样本数|30|
|样本缺sha256|30/30（catalog SELECT没有取v.sha256）|
|影子快照|61，其中31不在manifest|
|影子提取|31份产物不在manifest；总任务48 done / 12 pending / 1 running|
|影子usage_events|0行；本次观察没有已记账模型调用|
|继承的provider配置|chat/vision允许外发，embedding关闭；OCR fallback=vision-api|
|旧栈|library、status-collector、syncthing仍运行；library/syncthing healthy|

影子runner直接复用生产config.extra，没有将“本地OCR/禁止新增外发”变成有效约束；现有开启的vision fallback会在触发条件满足时调用模型。这里确认的是可触发路径，不把空账本说成已经发生外发。

61份状态可能包含此前工具修复前运行遗留，不能将全部 done 汇总当成30份样本的证据。必须按不可变run manifest界定版本/hash/recipe，核对实际读取字节、样本内任务和样本外遗留；重启不得重新拾取非样本任务。新运行必须使用独立目录，拒绝指向生产state；保留现有运行和证据，不清理重建冒充修复。

标注脚本还会以w模式重写已有 annotations/*.md，重跑选样能覆盖人工金标准；应只首次创建或另建样本版本。reconcile目前仅检查数据库记录，无blob复验、期望recipe或遗漏/失败退出门禁，且用KnowledgeStore会运行迁移，不能宣称只读验收。补齐这些链路再签署G2。

## 迁移条件和交付

- 用户条件式停机授权已获得，记录到任务书；不得把“需要用户再授权”当作本轮阻塞原因。
- 当前阻塞是 U01–U05 和未完成的真实影子标注/证据门禁；旧服务未停，生产数据未迁移。
- 人工金标准、真实引用巡检、恢复演练、对账与切换回滚准备仍按 docs/08、docs/19 执行；不以合成301测试推导已满足。
- [合成探针](fourth-review-probe-20261003.py)、[本地与服务器聚合证据](fourth-review-evidence-20261003.json)、[后续任务书](../21-cutover-blockers-taskbook.md)、[提示词](../22-cutover-blockers-prompt.md)。
- 本轮报告提交后暂停 `glm-research-kb` 自动跟进，避免在缺陷已确认时自动停服。修复并请求继续复核后，可沿用既有条件式授权。
