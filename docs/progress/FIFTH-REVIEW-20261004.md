# 第五轮独立复核：分离基础迁移与增强功能修复

日期：2026-10-04。源码基线：`7ded572c91ed6e72b82a3a41696f3a7cf9d47a52`，开始时工作树干净。范围：第四轮 U01–U05 修复及 shadow2 真实证据。本轮未修改业务实现、未调用真实模型、未改生产配置、未停止服务。

**修订结论：4 项缺陷保留，但不再将其全部作为基础迁移阻断。** 用户于本轮明确要求按主体功能影响控制返工，优先交付。用户已有条件式迁移与旧栈停机授权，不需要重复询问相同授权。P1/P2 表示相关功能启用时的修复优先级，不等于基础迁移必须等待。

基础交付范围：保留资料接入、同步、原文、已有数据和普通检索；远程模型请求保持关闭，public-as-of 历史检索暂不对外启用，新增自动研究候选导出暂缓。V01/V03/V04 进入 fix 清单，在对应功能启用前修复。V02 的自动验收工具修复可以后置，但**迁移的实际数据核验不能省略**，当前执行者通过独立全量哈希/数据库对账及恢复验证补足，不依赖该脚本 exit0。30 样本人工质量金标准是分析/OCR质量宣称的门禁，不阻塞保留现有能力的基础迁移。

## 已确认通过与证据边界

- 独立全回归：`PYTHONPATH=app python -m unittest discover -s app/tests`，310 tests / OK / 2 skipped，退出 0。
- 重跑第四轮探针：旧 schema 升级后 reserve 成功；chat/vision 超时重试 cap1 均仅一次 transport；旧行 NULL 且尚未误填 public 时间时，不再绑定文档日期，历史查询无命中。
- 服务器只读检查：shadow2 确有 30 snapshots / 30 extractions，ready 28 / review 2，usage_events=0。独立按 snapshot_root 解析相对路径并逐个计算实际文件 SHA256/bytes，30/30 与数据库一致。因此**没有证据说明当前这 30 个文件实际损坏**；问题在于 manifest 未锁定输入以及对账工具不能发现损坏。
- 服务器三个相关脚本/模块的 SHA256 与本地一致。旧 `research-kb-library`、`research-kb-status-collector`、`research-kb-syncthing` 仍运行，library/syncthing healthy。
- 提交者记录的生产副本升级演练、三连跑为既有证据；本轮未重新执行它们。人工金标准 A04/A06/A08/A09 仍 NOT_RUN，不当作代码缺陷，也不当作已通过。

## V01 / P1：成功请求完全不计请求预算（U02 未闭环）

位置：`app/knowledge/providers.py:_post/_close_attempt`，及 analysis/OCR/embedding 的业务 reservation。

成功的物理请求走 `release(attempt_rid)`；上层业务预留同时为 `count_request=False`。于是成功调用既不留下 request usage，也不保留占用。三个真实业务入口分别设置 `max_requests_total=1`，mock 成功 transport 后连续调用两次，均成功两次，而 `_totals()['requests']==0`。这会绕过每日/累计请求数量限制；失败重试已修复不代表成功分支正确。

验收要求：每次已发送请求持久计数恰一次，成功、失败与响应解析异常都不能变成未发送 release；token 只结算一次。三个入口各覆盖连续成功、跨重启、重试与并发，不以只测失败替代成功测试。

## V02 / P1：真实 manifest 哈希仍为空，对账可误报通过（U05 未闭环）

位置：`tools/shadow-acceptance/shadow_sample.py:81`、`shadow_run.py`、`shadow_reconcile.py:36–82`。

SELECT 仍只有 `v.media_type, v.ext, v.bytes`，没有 `v.sha256`。服务器 shadow2 manifest 文件哈希为 `d25c541a2f144c54d9f5322060006c519c82da6a084ae70d0fecf5dde1af71d4`，**30/30 samples 的 sha256 为空，30/30 未指定期望 recipe**。文件自哈希不能替代每份来源内容哈希，与 C6“SELECT 含 sha256、影子链闭合”的声明不符。

对账仍以可写 `KnowledgeStore` 打开数据库，并只信 snapshots.state 与任意 latest_extraction。独立反例：

1. 空 state、manifest 有一份文档：工具创建了数据库，输出 snapshot=0/extraction=0，退出仍为 0。
2. 只有 verified 元数据、文件不存在、manifest SHA 与 snapshot SHA 不同、提取 recipe 不同：仍报 with_snapshot=1/ready=1，退出 0。

验收要求：manifest 强制非空内容哈希与期望提取身份；runner 校验锁定输入；reconcile 严格只读，核验实际 blob、大小、来源版本及指定 recipe。缺失/不匹配/损坏返回失败，数据不足明确 NOT_RUN，禁止把 exit0 当作真实门禁。

## V03 / P1：此前误填的公开时间未修复，历史查询仍泄漏修订（U03 部分修复）

位置：`app/knowledge/store.py:493–497`。

NULL 行今后不再误绑定已修复。但先前代码留下的错误值被 `COALESCE(excluded.public_available_at, public_available_at)` 保留。本轮按先前错误状态造库：v2 的 first_observed_at=NULL，public_available_at 被误填 1 月文档日期；升级后重复 sync 仍为 1 月，7 月 public-as-of 查询仍命中该修订。未发现 C3 要求的误填识别/审计修复工具。

此为升级路径反例，**不声称生产库已存在这些误填行**。应先只读审计实际影响，再按可证明的来源规则修正；无法确认的公开时间隔离为 unknown。保留真实显式版本证据，不得一刀切清空所有历史时间。

## V04 / P2：导出幂等仍有首次重复与中断窗口（U04 部分修复）

位置：`app/knowledge/writeback.py:_unique_candidate/write_candidate/export_claim_candidates`。

稳定业务身份只登记到 candidates，第一次主文件未登记；同 claim/revision 跨秒导出三次产生主文件+候选两份。随后对 revision2 在创建候选后、保存 manifest 前模拟中断，重试会创建第二份 revision2 文件。现有测试将“主文件+候选”视为成功，也未覆盖 C4 要求的中断窗口。

验收要求：业务身份覆盖首次和后续产物，文件与登记之间中断可恢复；同版本只发布一次，版本变化只新增一次。人工主文件与人工候选均原样保留，不以覆盖或删除去重。

## 复现与交付

- [第五轮探针](fifth-review-probe-20261004.py)：仓库根运行 `python docs/progress/fifth-review-probe-20261004.py`。使用 mock 网络、合成数据库，保留唯一 runtime 目录，不清理数据。
- [机器可读证据](fifth-review-evidence-20261004.json)：本轮完整结果，未包含原文、凭据或来源标题。
- 本地原始回归日志：`runtime/review-fifth-20261004/full-tests.log`（忽略，不入 Git）。
- [下一步任务书](../23-fifth-review-taskbook.md)、[执行提示词](../24-fifth-review-prompt.md)。

本次检查时旧服务保持运行。后续先完成基础迁移专属门禁：备份与隔离恢复、全量数据和 Syncthing 对账、新服务可用、人工区保护与可回滚，再切换；增强能力修复及金标准并行后置。不得以 fix 清单代替真实迁移核验，也不得以增强能力未完阻止基础交付。不声称已完成迁移或七天观察。
