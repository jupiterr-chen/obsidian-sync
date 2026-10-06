# AC1续验：模型关闭的维护范围通过，B/C启用仍有前置修复

> 同日用户新增正文乱码问题，见[docs/33](../33-text-quality-repair-taskbook.md)。本报告保留原代码范围验收，不构成历史正文质量已验收或新TQ代码已获发布许可。整改已前置到LLM启用之前，旧数据未在本次任务中重处理。

日期：2026-10-06（Asia/Shanghai）。源码基线：`50cf6c1247e8bd48f246f075323a7e2bd33739ac`。依据[R1–R5开发报告](R12345-DEV-20261006.md)、[上一轮验收](AC1-REVIEW-20261006.md)、[任务书](../29-ac1-followup-taskbook.md)。开始时工作树干净。本轮无生产写入、部署、重启、真实模型调用或资料外发。

## 验收结论与发布范围

**原六反例6/6及AC1七反例7/7全部独立通过。旧库升级发布阻断已解除。** 旧库补列/索引幂等、公司总结接到正文和分析内容、已落盘总结结果恢复、分段覆盖/数据库partial续跑、服务配置入口默认关闭、prompt换版入口及当前版本选择的具体修复得到确认。

**AC1限定通过：50cf6c1可作为“模型关闭的维护版本”进入发布准备/授权申请。** 范围为旧库升级、已有正文自动处理/阅读发布、N1/R5背景包选版修复及关闭状态下的任务登记；不会因剩余B/C问题要求重做迁移或停止阅读。D目标应用集成、历史研究质量不在此验收范围内。

此结论不是生产部署授权，也不是镜像上线验收。发布前必须固定上述源码SHA，完成镜像隔离启动、备份/恢复与回退准备，明确配置差异，再由用户授权该次发布。`analysis.enabled=false`，chat/embedding/vision_ocr关闭，OCR远程fallback关闭；不全库回填或付费补分析。实际镜像若加入未验收代码，不适用本结论。

**B/C生产启用尚未通过。** 剩余MA01–MA03集中在模型启用前处理；目前全处于关闭路径之外，不阻挡上述维护范围。不能把这些代码问题写成“只差真实模型质量B4”，也不能据本报告开启模型。

## 独立证据

- `python scripts/review-abcde-20261005.py`：6/6 PASS。
- `python scripts/review-ac1-20261006.py`：7/7 PASS。与39521d4比较，两份探针均未修改。
- `$env:PYTHONPATH='app'; python -m unittest discover -s app/tests -v`：**Ran 384 tests in 72.228s，OK (skipped=2)**，即382通过、2跳过。日志`runtime/ac1-followup-20261006-tests.log`（忽略目录）。
- 既有测试的调整经核对：pending允许显式partial、混合证据中筛选claim、恢复前补有正文的样本，均与新语义对应，没有删除原探针断言。
- AC1旧库真实SCHEMA升级回归、模型关闭完整worker周期、标准CLI的合成两报告链路均随全回归执行。它们是隔离证据，不冒充生产新增资料到Windows或真实模型质量。
- 生产只读核对：worker/API/library仍为`obsidian-sync:67c6985r2`且启动时间仍在2026-10-04；旧research-kb三容器exited；10:41:59 CST心跳idle、last_ok=true。analysis开关缺省false，三provider enabled=false；账本仍仅历史chat1次26602输入/852输出。未输出令牌或配置全文。

## 模型启用前的集中修复清单

复现脚本：[review-model-activation-20261006.py](../../scripts/review-model-activation-20261006.py)，独立合成库与fake provider，直接运行exit 1。三项均复现。它是B/C启用门禁，不是模型关闭维护版本的阻断清单。

### MA01 / P2：partial发布后续跑完成，Obsidian仍停在旧稿

`analysis_tasks.py`的partial与done分支都向同一task_key的analysis_outbox做INSERT OR IGNORE；partial已发布后该行是consumed，后续done不会产生新的待发布事件。`AnalysisPublisher`因此不重写/新增新版，索引却依据数据库done显示完成。

反例：16块文档、请求上限1先产生partial并发布，恢复预算后任务done；再次consume发布数0，链接文件仍写“部分覆盖”。应按结果修订/hash生成可恢复发布事件，保存各版路径；partial→partial→done与同版重放均需验证。人工稿和旧版照常保留。

### MA02 / P1（限带证据的LLM结果启用）：合并稿没有重新校验引用，段内编号互相冲突

`analysis_tasks.py`分段分别从[1]编号，合并时要求保留[n]；最终citations仅平铺各段valid_citations，verification.all_valid仅对各段做all()，没有核对最终synthesis。两个段的[1]分别代表两个不同block，最终编号不唯一。

反例：两段各输出有效[1]，合并fake回复含不存在的[999]；最终草稿保留[999]，verification.all_valid却true，证据编号为[1,1]。这是确定性的引用映射缺陷，不需要付费模型才能修。应使用文档全局唯一证据ID，合并后再解析/校验实际输出；无效引用降级/复核，不能标全部有效或作为已核实事实。

### MA03 / P1（限真实模型启用）：新分段路径漏掉单次输入上限

`analysis_tasks._budgeted_complete`仅调用BudgetLedger.reserve；该方法只管累计输入/请求/页数，不检查max_input_tokens_per_run。旧execute_analysis_run的单次检查被新路径绕开。总结路径同样需纳入统一检查。

反例max_input_tokens_per_run=1，仍调用fake provider一次。应在每个分段/合并/总结发送前按同一预算定义校验，超限继续拆分或明确partial/blocked，不能发出；累计预算和物理请求上限的既有正确行为保持。此反例未证明累计预算失效，报告不混淆两者。

## 同阶段已知缺口（不扩成维护发布阻断）

- 主题规则只有函数级映射：worker没有传summarization.topics；C的topic正文查询仍返回空。报告中“最小可配置主题总结”尚未从服务入口实现。作为C主题子任务排期，暂不宣称可用。
- 资料范围配置尚未进入分析任务筛选；换实际模型后会为所有当前ready提取登记新模型任务。小批真实验收前必须有可执行allowlist/批次范围，不能只靠max_tasks_per_cycle限制每轮数量，也不能默认历史全库补分析。
- 已done的公司总结不会因B稍后完成而自动触发新事件；要把分析结果修订接入C影响事件，避免批量任务分多轮完成后总结停在较早材料。与MA01的结果变更事件同批考虑。
- 重试次数参数max_attempts在新执行分支未落实；开启付费前补有界重试/退避，并保留失败状态与成本，不盲目周期重试。

上述属于模型启用阶段的同批完善；不要求重新做R1/N1/N4/N5。真实B4质量、生产新增研报到Windows、D目标应用、7天观察、备份调度/恢复抽检/告警、令牌轮换继续按实际授权分别处理，不伪装已完成。

下一步：[维护发布边界及模型启用任务](../31-maintenance-and-model-activation.md)、[下一位agent提示词](../32-model-activation-prompt.md)。
