# A–E 独立验收：部分可用，整体未完成

时间：2026-10-05 09:19 CST生产检查。被评源码：`c537b2ad8bf7277bb16c485bf54d8fc576eaf335`。依据：[目标交付链](../25-target-workflow-delivery.md)、[F0任务](../26-bugfix-first-taskbook.md)、[提交者报告](ABCDE-DELIVERY-20261005.md)。本轮仅本地测试、生产只读核对与文档提交，没有部署、重启、停机、回填或模型调用。

## 结论及影响

**不接受“A–E全部完成”或“B/C只差打开模型开关”。接受现有正文阅读可继续使用；不要求重做迁移或停止阅读服务。** 后续按能力验收，不能因总结或投资接口的问题阻断正文阅读。

|范围|独立核验结论|尚缺的交付|
|---|---|---|
|F0|既有回归通过；成功请求漏计反例已有修复|预算重试出现保守重复计数，见Q05，不是超额外发|
|A正文阅读|worker正常；服务器与Windows目录hash相同；523条正文链接0断链；4个当前版本无正文|真实“新增一份资料→来源索引→worker→Windows”尚未独立实测；批量发布有Q04；失败保留上一版入口等仍需专项验证|
|B单篇分析|只有任务登记，生产228条blocked|执行器、授权配置接线、失败恢复、完整任务身份、分析发布未接通；不能只切模型配置|
|C公司/主题总结|有版本表与阻塞占位记录|没有生成/发布消费闭环；新文档到实体的映射缺失；同一proposal重复入队，见Q03|
|D投资接入|API/参考客户端存在|as_of失效（Q01）；真实目标应用、版本背景保存/重放未验收|
|E运维|worker心跳/状态工具可用|周期一致性备份、恢复抽检、告警及7天观察缺少本轮可验收证据；不能以ops-status命令替代|

B/C模型未授权、真实应用未接入、7天未完成是报告已披露的边界，不把这些记录本身当新增缺陷。真正的问题是将未接通的实现称为“管线就绪”，会使下一位执行者误以为授权启用即可达成目标。

## 可复现问题

### Q01 / P1：历史投资背景查询没有时间过滤

位置：`app/knowledge/background.py:22–103`。`as_of/as_of_mode`仅写入返回字段；SQL仍固定选择`is_current=1`与最新提取，claims取当前revision。返回说明却写着已按截止时间过滤。

独立反例：文档2026-10-04首次接入，查询2000-01-01，system/public两模式均返回1条来源，预期0。影响历史研究、回测及决策依据，会掺入未来资料；普通正文阅读不受影响。接口也未完整保存generation及逐来源version_id，现有digest只能证明包内容，不能证明时间正确。

处理：在投资/历史查询启用前修复。可先明确拒绝尚不支持的历史模式，不能返回貌似正确的历史包。无需因此停掉library/同步/阅读。

### Q02 / P1（功能交付缺口）：B/C没有可启用的自动分析闭环

位置：`analysis_tasks.py:28,66–99`、`worker.py:182–206`、`summaries.py:58–64,125–157`。登记硬编码`disabled/no-provider`和`blocked`，worker没有从该表领取任务并调用分析/发布的消费者；总结消费者始终写空内容、空证据数组、blocked，并把事件consumed。`entity_for_source()`恒返回None；worker只从已有claim的open proposal推company总结，不能覆盖首次加入公司报告/主题。

附两个离线反例：同一来源版本的旧提取ready、最新提取review，仍登记旧提取1条；同一提取将prompt从pv1换成pv2，登记0条，因为NOT EXISTS没有纳入完整身份。当前不会造成付费，接通执行器前必须明确使用哪一提取、哪一模型/提示词/模板。

处理：将B/C状态改为“部分实现”，在离线fake provider下把worker→分析→证据校验→生成笔记→实体总结跑通；真实模型质量仍单独待授权验收。不要求先做embedding或整库分析。

### Q03 / P2，随C补全：同一更新每周期追加空总结版本

位置：`worker.py:190–205`、`summaries.py:67–85,125–157`。每轮重读所有open proposal；outbox没有事件唯一约束，同一proposal每30分钟再次插入并消费。反例同一proposal三次，产生3条blocked revision；预期同一更新只有一个逻辑任务。开启未来消费者后还可能重复生成/付费。

生产目前summary_outbox和summaries均为0，尚未见该问题造成线上膨胀。无需停服务；在C消费者交付时一起修，blocked事件不能丢失重试身份/证据。

### Q04 / P2，修复清单：正文分批发布时目录提前指向未写出的文件

位置：`reading.py:124–140,172–218`。consume默认只处理200条，rebuild_index却对全部当前版本生成链接，没有核对成功发布记录/文件。反例2条待发布、limit=1：目录包含第二份不存在的正文，pending=1。大批导入或恢复积压时用户可遇暂时断链。

生产本轮523链接均存在，因此不是当前空正文投诉的解释，也不是停服理由。修复应将未发布项显示为待发布；不能只把批大小调大或要求用户手工导出。

### Q05 / P2，模型启用前一起修：失败物理请求重复计入上限

位置：`budget.py:91–105,138–144,252–265`。失败http-attempt同时计入requests和dispatched_attempts，门禁又将二者相加。上限2、第一次超时、第二次本可成功的离线反例：仅发1次即报ProviderCallError，第二次未尝试。

影响可用重试额度，属于过早阻断，不是多花钱或资料外发；当前模型关闭，正文阅读无影响。已有成功计数修复保留，在同批补一个精确物理请求计数定义，覆盖成功/失败/重试/并发/重启，不另开全工程返工。

## 证据与范围

- 本地全回归：`$env:PYTHONPATH='app'; python -m unittest discover -s app/tests -v`，**Ran 336 tests in 63.613s，OK (skipped=2)**。提交者报告的“334 OK + 2 skipped”与总数336并不矛盾。私有日志：`runtime/abcde-review-tests.log`。
- 新独立反例：[review-abcde-20261005.py](../../scripts/review-abcde-20261005.py)，运行`python scripts/review-abcde-20261005.py`。6项条件全部复现不满足，返回1是验收未通过，不是脚本异常。只用合成数据和覆盖_transport的fake provider，没有真实HTTP/LLM；合成库保留在测试临时目录。
- 生产5容器运行，library/knowledge-api/syncthing健康；旧research-kb三容器仍Exited。镜像`obsidian-sync:67c6985r2`。容器内worker/background/analysis_tasks/summaries/reading/writeback/budget七文件SHA256逐一与评审工作区相同；没有声称整个镜像均完成供应链验证。
- 只读SQLite（mode=ro）：538文档；publish_outbox consumed526、pending0；analysis_tasks blocked/model_disabled228；总结/总结outbox均0；usage仍只有历史chat1次26602输入/852输出，没有新增模型用量记录。
- 09:19 CST心跳idle且fresh，最近完成周期08:52:42 CST，last_ok=true；该轮new_documents/new_versions/extract_processed均0，索引unchanged；repair队列4、注册0。不能把这次无变更轮次作为新增研报验收。
- 服务器、Windows `解析正文/开始阅读.md` SHA256均为`e2ffe973c1e907f8c0089cb7e52647c4867bf57692aa6be335c80e75199d1ba9`；均523正文链接、0缺文件，服务器530份readable文件含旧提取版本。此次只核对文件存在/同步一致，不代表正文人工质量已验收。
- 三provider enabled=false，OCR fallback=null。现有450条extract failed是累计状态，未归因为本次新增失败；不能据此推断450份当前资料坏掉。

## 发布边界与检查疏漏

本轮用户明确收紧后续权限：开发任务不授权部署。**先领取Codex独立验收任务、验收通过，再获得用户对该次固定commit/范围的明确生产部署授权。** 已同步AGENTS、CUTOVER、下一步任务书和提示词。旧迁移授权不能沿用。当前未授权变更现有生产或轮换配置。

本轮只读配置检查曾误将`api_tokens`映射键当作字段名输出，导致内部API令牌出现在本会话工具记录中；未写入仓库、报告不保存令牌值。已停止输出该映射。轮换应在用户授权的维护窗口与消费者同步更新、验证旧令牌失效；不能谎称已经轮换，也不把此检查疏漏归因于交付者。

下一步：[限范围任务书](../27-abcde-acceptance-taskbook.md)、[可直接交给开发agent的提示词](../28-abcde-next-agent-prompt.md)。
