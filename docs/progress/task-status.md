# 任务台账

> **2026-10-06终轮验收通过：最终源码9d1b04f（含Codex补齐缺页/质量及claim资料范围）。29探针通过，431回归通过/2跳过，干净源码15项通过。S1–S4/F1–F3开发续验结束，不再下发SF返工，F4仍后置。** [最终报告](SF-ACCEPTANCE-20261006.md)、[发布与正文修复计划](../36-validated-release-and-text-repair.md)。本次未部署、未真实模型调用、未历史重处理/归档；生产仍67c6985r2。发布、真实样本/批次及模型范围/预算须分别授权。下方为历史记录。

> **2026-10-06 第五批（最新）：SF01–SF06 完成并推送（[开发报告](SF-DEV-20261006.md)，commit db61484）。** 五份验收探针全绿（SF 6/6、TQMA 7/7、MA 3/3、AC1 7/7、原 6/6），全回归 426 OK。F4 按任务书后置。生产清单/样本/批次/归档与部署全部等待各自授权；零生产变更。

> **2026-10-06独立续验0f9cb27：原23探针通过、420回归通过/2跳过，干净源码F1/S4另4项通过。S4/F1代码交付通过；S1/S2/S3/F3原任务组合条件未闭环，按原docs/34补齐SF01–SF06，不扩展范围，F4仍后置。** [续验报告](S1234-ACCEPTANCE-20261006.md)、[原任务书](../34-tqma-followup-taskbook.md)、[续验提示词](../35-tqma-followup-prompt.md)。未部署；现网67c6985r2、旧服务仍停止。生产与数据批次授权边界不变。下方为历史记录。

> **2026-10-06 第四批（最新）：S1–S4 与 F1–F3 完成并推送（[开发报告](S1234-DEV-20261006.md)，commit 25a89d6）。** 四份验收探针全绿（TQMA 7/7、MA 3/3、AC1 7/7、原 6/6），全回归 420 OK。F4（C1 展示小修）按任务书后置。生产清单/样本/批次/归档与部署全部等待各自授权；零生产变更。

> **2026-10-06 最新独立验收：fbc24bd的原16反例通过，410回归通过/2跳过。新增边界归并S1模型范围、S2有效入口与引用、S3冻结批次、S4真正只读四组，按功能限制启用；不重做已通过修复/迁移，不停现网。** [验收报告](TQMA-REVIEW-20261006.md)、[集中任务书](../34-tqma-followup-taskbook.md)、[下一位agent提示词](../35-tqma-followup-prompt.md)。样本工具未入Git等列fix清单；本次无生产变更/真实模型调用/历史重处理。生产仍67c6985r2；任何发布均须先Codex验收再获用户对具体commit/范围授权。下方开发声明为历史记录。

> **2026-10-06 第三批（最新）：TQ0–TQ4 与 MA01–MA03+C主题 完成并推送（[开发报告](TQMA-DEV-20261006.md)，commit db7b967）。** MA 探针 3/3、AC1 7/7、原 6/6 全绿；410 回归 OK。正文质量工具（清单/有界重提取/治理 dry-run）就绪待授权运行；B/C 启用门禁（全局证据编号/结果修订发布/单次上限+allowlist/主题接线）离线闭环，B4 真实质量待授权。**零生产变更，未部署。**

> **2026-10-06用户追加：正文质量TQ0–TQ4并入现有开发批次并前置于LLM。** [详细任务](../33-text-quality-repair-taskbook.md)、[统一任务](../31-maintenance-and-model-activation.md)、[更新后提示词](../32-model-activation-prompt.md)。只读核对发现当前523项提取中458项为旧stdlib-pdf；需全库质量清单、原生重提取优先、必要页OCR，不强制全库OCR。旧副本只做治理dry-run；生产重处理/归档/部署须另获具体授权。此前链接可打开的验收不代表正文内容正确，历史质量尚未修复。


> **2026-10-06 AC1续验最新结论：50cf6c1模型关闭维护范围限定通过。** [报告](AC1-FOLLOWUP-20261006.md)：原探针6/6、AC1探针7/7、全回归382通过/2跳过；旧库升级阻断解除，可进入维护发布准备，仍须用户授权。B/C启用前集中修MA01–MA03，不阻挡维护范围、不重做迁移。见[双轨任务书](../31-maintenance-and-model-activation.md)与[提示词](../32-model-activation-prompt.md)。未部署、未调用真实模型。下方历史声明不代表最新状态。


> **2026-10-06 第二批（最新）：R1–R5 限范围开发完成并推送（[开发报告](R12345-DEV-20261006.md)，commit 8cca7de）。** AC1 新探针 7/7 全绿、原探针 6/6 保持、全回归 382 OK；零生产变更。待 Codex AC1 续验 + 用户发布授权。

> **2026-10-06 AC1独立验收：原Q01–Q05六反例通过；整批发布暂不通过。** [报告](AC1-REVIEW-20261006.md)：基线d58119e，366项回归（364通过、2跳过）；现网仍67c6985r2。旧库升级、B→C有效证据、长文覆盖尚有核心缺口，发布/恢复及D当前选版为同批小修。见[续验任务书](../29-ac1-followup-taskbook.md)、[提示词](../30-ac1-followup-prompt.md)。不重做迁移、不停阅读；仍须Codex验收通过及用户明确授权具体发布。下方为历史记录，不代表最新验收状态。


> **2026-10-05 第二批（最新）：N1–N5 限范围开发完成并推送（[开发报告](N12345-DEV-20261005.md)，commit 9fbf1ab）。** 验收探针 6/6 全绿、全回归 364 OK、零生产变更/零模型调用；B/C 为 fake-provider 离线闭环（真实质量待授权），D 时间语义已实现（真实应用未接入），N5 修复已备未部署。**当前停在"待 Codex AC1 独立验收 + 用户发布授权"，未自行上线。**

> **2026-10-05 最新独立验收：部分可用，整体未完成。** [验收报告](ABCDE-ACCEPTANCE-20261005.md)：336项回归（334通过、2 skipped）；正文worker运行，服务器/Windows 523链接0断链；B/C缺执行与发布闭环，D历史背景as_of未生效。Q01–Q05按功能修复，不重做迁移/不停阅读。见[任务书](../27-abcde-acceptance-taskbook.md)和[提示词](../28-abcde-next-agent-prompt.md)。后续必须先接收Codex独立验收任务并验收通过，再取得用户明确生产部署授权；开发/self-test/push不授权部署。

以下为历史过程与提交者声明；与最新独立验收冲突时，以最新验收为准。

> **提交者历史声明（2026-10-05，已由上方独立验收修正）：A–E 交付链已上线**（[交付报告](ABCDE-DELIVERY-20261005.md)）。A 全链路生产运行（增量 worker/有界修复/自动阅读发布/状态页，缺正文 15→4）；B/C 管线就绪、模型保持关闭（228 任务 blocked）；D API+参考客户端就绪、待目标应用接入；E ops 工具运行中。B/C 启用需用户授权；7 天观察自 2026-10-05 起累计。

> **最新目标交付链：** [docs/25](../25-target-workflow-delivery.md)：A自动解析与阅读 → B单篇LLM分析 → C知识总结 → D投资框架接入，E稳态运维并行。当前只完成迁移与已有正文一次性阅读导出，A/B端到端尚未上线。修复按能力启用节点纳入，不重做迁移。

> **基础迁移已完成（2026-10-04）：** 旧三容器停止，新四容器运行；数据、恢复、原文、旧证据、增量三连跑和Windows同步已验证。见[迁移报告](MIGRATION-20261004.md)。第一层小时同步正常；知识自动worker/远程模型/自动候选暂未启用，fix清单后置。不要重做迁移。

> **最新独立复核及用户取舍（2026-10-04，7ded572）：基础迁移优先。** 310 tests OK/2 skip；V01–V04保留为fix清单，关闭/暂缓相应增强功能。迁移独立核验数据、恢复、同步与回滚后可推进，不等待全部增强修复或人工质量标注。见[报告](FIFTH-REVIEW-20261004.md)、[任务书](../23-fifth-review-taskbook.md)、[交接提示词](../24-fifth-review-prompt.md)。旧栈在本次检查时仍运行；以下较早结论为历史记录。

> **最新独立复核：第四轮（2026-10-03，cd3bb5d）NEEDS_CHANGES。** 301 tests OK/2 skip，但U01–U05未闭环，见[结果](FOURTH-REVIEW-20261003.md)、[任务书](../21-cutover-blockers-taskbook.md)、[提示词](../22-cutover-blockers-prompt.md)。用户条件式迁移/停机授权已获得；本次因缺陷和G2证据不足未停旧栈。GLM修改已结束，影子提取仍运行。以下完成声明为历史记录。

> **最新独立复核：第三轮（2026-10-03，源码 cb254df）NEEDS_CHANGES。** 287 tests OK / 2 skipped；T01–T07 共4 P1、3 P2待修复。先读[第三轮报告](THIRD-REVIEW-20261003.md)、[下一步任务书](../19-release-readiness-taskbook.md)与[提示词](../20-release-readiness-prompt.md)。先过G1再做小批影子验收，暂不启动全量重提取或生产切换。以下完成声明为历史记录，以最新独立验收为准。

> **最新独立复核：2026-10-03，基线 4949dcd，NEEDS_CHANGES。** 268 回归 OK（2 skipped），新增反例确认 S01–S10 尚待处理（6 P1 / 4 P2）。此前 R01–R15 全 fixed/RF7 闭环是提交者历史声明，未获本轮独立验收。先读[第二轮报告](RE-REVIEW-20261003.md)、[SR 任务书](../17-second-review-taskbook.md)及[执行提示词](../18-second-review-fix-prompt.md)。真实 NOT_RUN/BLOCKED 不变；本次未操作生产。以下历史记录保留。

字段：任务ID | 状态（todo/in_progress/blocked/accepted）| 负责人 | 依赖 | 变更commit | 验收报告 | 阻塞条件 | 下一动作。
完成度口径：源码实现 / 离线验证 / 全量数据验收 / 生产部署 四类分开记录。

|任务|状态|负责人|依赖|commit|验收报告|阻塞|下一动作|
|---|---|---|---|---|---|---|---|
|TQ0 全库质量清单|todo：只读初查完成，完整映射未做|next-agent|docs/33|—|docs/33-text-quality-repair-taskbook.md|不可用文件数冒充文档数|引擎/页/提取/文件去重清单|
|TQ1/TQ2 源头与下游质量门|todo：前置于LLM|next-agent|TQ0|—|同上|控制字符/CID路由及OCR拼接污染|隔离回归，不改生产|
|TQ3 有界版本化重处理|todo：工具先做，生产批次待授权|next-agent|TQ1/TQ2|—|同上|新recipe/新extraction/旧证据保留|原生重提取优先，必要页OCR|
|TQ4 Vault历史副本治理|todo：仅dry-run|next-agent|TQ0|—|同上|人工修改/引用/manifest/hash及精确授权|不自动清理，准备恢复映射|
|SF01 主题不扩大C资料范围（文档级过滤）|dev-done、待Codex续验|main-agent|0f9cb27|db61484|SF-DEV-20261006.md|续验+模型授权|Codex续验|
|SF02 新稿须全可用才赢得入口|dev-done、待Codex续验|main-agent|0f9cb27|db61484|同上|续验+批次授权|Codex续验|
|SF03 全Vault wikilink/片段引用保护|dev-done、待Codex续验|main-agent|0f9cb27|db61484|同上|续验+归档授权|Codex续验|
|SF04 执行层遵守冻结recipe|dev-done、待Codex续验|main-agent|0f9cb27|db61484|同上|续验+批次授权|Codex续验|
|SF06 批次原子冻结+中断恢复|dev-done、待Codex续验|main-agent|0f9cb27|db61484|同上|续验+批次授权|Codex续验|
|SF05 预算等待退还attempt|dev-done、待Codex续验|main-agent|0f9cb27|db61484|同上|续验|Codex续验|
|S1 执行范围（B领取/partial/C发送）|dev-done、待Codex续验|main-agent|fbc24bd|25a89d6|S1234-DEV-20261006.md|续验+模型授权|Codex续验|
|S2 有效提取统一+引用保护|dev-done、待Codex续验|main-agent|fbc24bd|25a89d6|同上|续验+批次授权|Codex续验|
|S3 批次冻结与恢复|dev-done、待Codex续验|main-agent|fbc24bd|25a89d6|同上|续验+批次授权|Codex续验|
|S4 真正只读预检|dev-done、待Codex续验|main-agent|fbc24bd|25a89d6|同上|续验|Codex续验|
|F1 样本工具入Git+实测|dev-done（合成PDF端到端）|main-agent|fbc24bd|25a89d6|同上|真实样本窗口授权|按TQ-SAMPLE-PLAN|
|F2 盘点补全|dev-done|main-agent|fbc24bd|25a89d6|同上|批次授权时使用|—|
|F3 重试/退避接线|dev-done（付费无人值守前）|main-agent|fbc24bd|25a89d6|同上|真实provider授权后复核|—|
|F4 C1展示小修|延期（仅展示层）|main-agent|—|—|任务书后置|依赖：展示细节，不影响防护|按需排期|
|TQ1/TQ2 损伤路由+OCR选择+下游防护|dev-done、待Codex验收|main-agent|989e28d|721dde8|TQMA-DEV-20261006.md|验收+生产样本授权|Codex验收|
|TQ0/TQ3/TQ4 清单/重提取/治理工具|dev-done（只读/dry-run/显式批）|main-agent|TQ1/2|2de919b|同上|批次授权|Codex验收|
|样本方案+隔离测量 harness|方案+工具就绪|main-agent|TQ0|2d9f703|同上|生产样本授权|按TQ-SAMPLE-PLAN执行|
|MA01–MA03+C主题 启用门禁|dev-done（离线闭环）|main-agent|R批|db7b967|同上|B4真实模型授权|Codex验收|
|R1 旧库前向升级 AC01|accepted：原反例及旧库周期通过|main-agent|d58119e|e58e91b|AC1-FOLLOWUP-20261006.md|生产发布待用户授权|维护范围可准备发布|
|R2/R2b 证据接线+落盘恢复 AC02|原反例与公司离线链路accepted|main-agent|R1|bbbe98a|同上|主题/后续变更触发待完善；真实质量待授权|docs/31轨道B|
|R3 分段覆盖+partial+服务接线 AC03|原反例accepted；真实模型启用未通过|main-agent|R2|8cca7de|同上|MA02引用/MA03单次预算及范围|模型启用前集中修|
|R4 发布身份/状态 AC04|换版/状态原反例accepted|main-agent|R3|8cca7de|同上|MA01续跑完成稿未重新发布|随模型启用批修|
|R5 无截止当前视图 AC05|accepted：原反例通过|main-agent|—|8cca7de|同上|真实投资应用未接入；发布待授权|维护范围准备|
|N1 历史背景时间过滤 Q01|原反例通过；AC05已修复|main-agent|c537b2a|c9032a7/8cca7de|AC1-FOLLOWUP-20261006.md|发布待授权；真实应用待接入|不重做|
|N2 分析任务/执行器 Q02|原反例通过；模型启用仍受MA清单限制|main-agent|N4|0ceb43d..8cca7de|同上|MA01–MA03|docs/31轨道B|
|N3 总结闭环+事件去重 Q03|升级/证据/已落盘恢复通过|main-agent|N2|9fbf1ab..8cca7de|同上|主题及后续影响事件待完善|docs/31轨道B|
|N4 预算重试计数 Q05|原反例及既有回归accepted|main-agent|—|3df6742|同上|发布待授权；新路径单次预算另见MA03|保留修复，不重做|
|N5 分批发布断链 Q04|原反例及既有回归accepted；未部署|main-agent|—|a8f4d8a|同上|维护发布待授权|可准备维护发布|
|A1 增量知识处理（worker）|部分验收：正常周期已核实|main-agent|F0|b4fcde1..5b3fb75|ABCDE-ACCEPTANCE-20261005.md|真实新增来源端到端NOT_RUN|补隔离新增/更新/重启验收|
|A2 有界修复队列|部分验收：当前缺正文4|main-agent|A1|同上|同上|真实质量与失败恢复待专项验收|有界补证据，不全库重跑|
|A3/A4 自动阅读发布+入口|当前523链接通过；Q04待修|main-agent|A1|c8b088a|同上|积压分批时短暂断链|N5小修，保持现有阅读|
|B2 单篇分析任务|部分实现；生成/发布未接通|main-agent|A|同上|同上|Q02/Q05及真实模型授权|N2/N4离线闭环后独立验收|
|C 版本化知识总结|部分实现；生成/发布未接通|main-agent|B|同上|同上|缺实体初次发现/消费者；Q03|N3与B衔接|
|D 背景包API+客户端|未通过历史语义验收|main-agent|A|b95f06d|同上|Q01；真实应用未接入|N1修复或显式拒绝历史模式|
|E 稳态运维工具|心跳核实；完整E待验收|main-agent|—|5b3fb75|同上|周期备份/恢复/告警/7天证据不足|准备隔离证据和授权后的上线计划|
|M0 源工程整合|accepted（源码+离线验证）|main-agent|P0|0f3a19f|docs/progress/m0-report.md|无|无，已完成|
|P0 设计基线|accepted|前序会话|无|a26f8f2/7cf9578|docs/10-p0-validation.md|无|无|
|P1-01 library接口核对|accepted（离线审计）|main-agent|M0|2889a12|docs/progress/p1-01-interface-audit.md|真实A01需源访问|已完成|
|P1-02 游标/版本幂等/不可变快照|accepted（源码+离线验证）|main-agent|P1-01|2889a12|docs/progress/p1-report.md|无|已完成|
|P1-03 分层30样本|accepted（工具+合成契约）/真实BLOCKED|main-agent|P1-01|2889a12|docs/progress/p1-report.md|真实源访问|源访问后执行真实抽样与标注|
|P1-04 页数/正文/tokenizer测量|accepted（工具+合成）/真实BLOCKED|main-agent|P1-03|2889a12|docs/progress/p1-report.md|真实源+tokenizer|源与tokenizer具备后真实测量|
|P2-01 PDF文字层与布局位置|accepted（源码+合成）/真实盲测BLOCKED|main-agent|P1-02|1fd8d78|docs/progress/p2-report.md|解析器选型+真实样本|注册真实解析器后实测|
|P2-02 按页质量判断与OCR路由|accepted（接口+合成路由）/真实OCR BLOCKED|main-agent|P2-01|1fd8d78|docs/progress/p2-report.md|本地OCR引擎未选型|引擎选定后注册|
|P2-03 HTML/图片/文本解析|accepted（源码+合成）|main-agent|P1-02|1fd8d78|docs/progress/p2-report.md|无|XBRL适配器P3+|
|P2-04 表格和数值口径|accepted（基线+单测）/A09真实门禁BLOCKED|main-agent|P2-01|1fd8d78|docs/progress/p2-report.md|真实标注样本|样本后迭代|
|P2-05 不可变提取产物、块与配置版本|accepted（源码+合成）|main-agent|P2-01/02/03|1fd8d78|docs/progress/p2-report.md|无|已完成|
|P3-01 中英文词法及筛选|accepted（源码+合成）/A10真实基准NOT_RUN|main-agent|P2-05|9eacef3|docs/progress/p3-report.md|真实语料|真实50查询基准待源访问|
|P3-02 HTTP服务、鉴权、分页、事件|accepted（源码+合成）|main-agent|P3-01|9eacef3|docs/progress/p3-report.md|生产部署|部署后A21性能实测|
|P3-03 影子全量回填与原子发布|accepted（工具）/生产BLOCKED|main-agent|P2/P3-01|9eacef3|docs/progress/p3-report.md|服务器+真实523基线|源访问后执行A14对账|
|P3-04 卡片证据链接集成|accepted（源码+合成，不写Vault）|main-agent|P3-02/03|9eacef3|docs/progress/p3-report.md|真实Vault写回授权|P5/P6决定写回路径|
|P4-01 embedding选型及预算|accepted（抽象+账本+mock）/真实BLOCKED|main-agent|P1-04/P3|240b4dd|docs/progress/p4-report.md|供应商与预算未定|用户给定后接入真实适配器|
|P4-02 混合召回及可选重排|accepted（RRF+缓存）/真实基准NOT_RUN|main-agent|P4-01|240b4dd|docs/progress/p4-report.md|同上|rerank真实评测后决定|
|P4-03 分析、引用验证、成本账本|accepted（源码+mock）/真实评测BLOCKED|main-agent|P4-02|240b4dd|docs/progress/p4-report.md|同上|真实化后执行A17|
|P5-01 claim/decision版本与review|accepted（源码+离线）|main-agent|P4-03|c4abc89|docs/progress/p5-report.md|无|已完成|
|P5-02 更新影响与反证候选|accepted（离线）/A20真实评测BLOCKED|main-agent|P5-01|c4abc89|docs/progress/p5-report.md|真实新旧版本语料|真实化后评测|
|P5-03 Obsidian安全成果写回|accepted（机制+离线）/真实Vault BLOCKED|main-agent|P5-01|c4abc89|docs/progress/p5-report.md|写回路径授权与目录登记|用户登记后启用|
|P6-01 生产调度、监控与资源限制|accepted（源码+离线+compose准备）/A21生产NOT_RUN|main-agent|P3|9a20156|docs/progress/p6-report.md|生产主机|部署后7天记录与性能实测|
|P6-02 备份、恢复及回滚|accepted（工具+离线演练）/A22真实演练BLOCKED|main-agent|P3|9a20156|docs/progress/p6-report.md|同上|生产后真实RPO/RTO演练|
|P6-03 研发与资金应用接入|accepted（接入上下文清单+示例）/真实客户端BLOCKED|main-agent|P3|9a20156|docs/progress/p6-report.md|客户端与生产|接入验收A13/A19|

## 评审修复（2026-10-03，独立评审 R01-R15）

|问题|状态|修复提交|回归|
|---|---|---|---|
|R01 预算/账本|fixed|4b90a75|test_review_regressions.R01BudgetTest|
|R03 provider 装配|fixed|4b90a75|R03ProviderWiringTest|
|R04 快照消费校验|fixed|310cad4|test_review_rf2.R04|
|R02 配置身份|fixed|310cad4|test_review_rf2.R02|
|R05 PDF 页序/引擎|fixed|310cad4|test_review_rf2.R05|
|R06 HTML 偏移|fixed|310cad4|test_review_rf2.R06|
|R08 选版/as_of|fixed（ADR0007）|1686d7d|test_review_rf3.R08|
|R07 索引恢复|fixed|1686d7d|test_review_rf3.R07|
|R09 混合先过滤|fixed|93e8298|test_review_rf4.R09|
|R11 固定 URL/快照|fixed|93e8298|test_review_rf4.R11|
|R12 分页|fixed|93e8298|test_review_rf4.R12|
|R10 写回唯一性|fixed|29590dd|test_review_rf5.R10|
|R15 影响 outbox|fixed|29590dd|test_review_rf5.R15|
|R13 部署可执行|fixed（服务器 compose config + 镜像冒烟通过）|36c84b5..6ffb0d6|test_review_rf6.R13|
|R14 恢复严格化|fixed|36c84b5|test_review_rf6.R14|

受影响的 P1-P6 离线 accepted 状态按任务书重开为 NEEDS_CHANGES → 现 fixed，待独立复验（RF7）。真实 NOT_RUN/BLOCKED 项不变。最终回归 268 OK。

## 第二轮评审修复（2026-10-03，RE-REVIEW-20261003 S01-S10）

|问题|状态|修复提交|回归载体|
|---|---|---|---|
|S01 预算原子性|fixed|01c02d7|test_second_review.S01BudgetAtomicityTest|
|S02 写回覆盖窗口|fixed|a7640fd|S02WritebackAppendOnlyTest|
|S03 public 时间泄漏|fixed|a7640fd|S03PublicAsOfTest|
|S04 快照字节一致性|fixed|a7640fd|S04SnapshotBytesTest|
|S05 OCR 置信度门禁|fixed|a7640fd|S05OcrConfidenceGateTest|
|S06 图片重复 OCR|fixed|a7640fd|S06ImageDuplicateOcrTest|
|S07 outbox 事务间隙|fixed|01c02d7|S07OutboxAtomicTest|
|S08 游标元数据一致性|fixed|a7640fd|S08CursorMetadataTest|
|S09 部署启动/构建/路径|fixed（隔离目录实测启动）|e369d32|test_second_review_s09|
|S10 独立召回/缓存隔离|fixed|a7640fd|S10IndependentRecallTest|

最终回归 287 OK。逐项 RED/GREEN、隔离启动验收记录见 `second-remediation-log.md`。真实 NOT_RUN/BLOCKED 项不变。

## 第三轮评审修复 + 发布准备（2026-10-03，THIRD-REVIEW S/T01-T07）

|问题|状态|修复提交|回归载体|
|---|---|---|---|
|T01 旧库升级|fixed|c99f159|test_third_review.T01（旧 schema fixture）|
|T02 预算状态机|fixed|c99f159/4109655|T02BudgetStateMachineTest|
|T03 版本公开时间|fixed|c99f159/4109655|T03VersionPublicTimeTest|
|T04 元数据纪元|fixed|c99f159|T04MetadataEpochTest|
|T05 漏页/recipe|fixed|c99f159|T05MixedPdfAndRecipeTest|
|T06 召回/缓存|fixed|c99f159|T06FullRecallAndCacheTest|
|T07 幂等候选|fixed|c99f159|T07IdempotentCandidatesTest|

**G1 通过**：探针 14/14 + 301 tests。N5 影子小批进行中（服务器隔离目录）；N6 全量 dry-run 完成（524 重提取/14,751 页/OCR 2,792 页；旧产物全保留）。详见 `release-readiness-log.md`。

## 第四轮评审修复（2026-10-04，U01-U05 全 fixed）

|问题|状态|提交|证据|
|---|---|---|---|
|U01 旧库迁移|fixed|6a2e57d|生产库副本升级+实际运行业务（26,612 token/3 req，旧行零丢失）|
|U02 三入口门禁|fixed|6a2e57d|chat/vision/embedding cap1 均 1 次 transport；无孤儿 reserved|
|U03 legacy 时间|fixed|6a2e57d|NULL=unknown 不绑定；探针 0 命中|
|U04 claim 导出|fixed|6a2e57d|同 claim 三导出恰 1 候选|
|U05 影子链|fixed|6a2e57d|manifest hash+sha256；生产路径拒绝；强制禁外发（usage=0 实证）；标注不覆盖|

310 tests OK；shadow2 独立 run 30/30 全成+幂等；G2 待人工标注。

## F0 迁移后 Bug Fix（2026-04-04 基础迁移后，V01-V04+CLI）

|问题|状态|提交|证据|
|---|---|---|---|
|V01 成功请求预算|fixed|a2407d1|探针 8/8 + test_f0_fixes（三入口/重启/重试/旧库）|
|V02 影子校验|fixed|a2407d1|manifest sha+recipe 锁定；reconcile 只读严格（缺数据 NOT_RUN/问题 FAIL）|
|V03 历史时间|fixed（生产无需修）|a2407d1|sync 自愈+审计工具；生产审计 0 误填行（528 全 null）|
|V04 写回幂等|fixed|a2407d1|同 revision 单产物；中断收养；人工编辑保留|
|CLI snapshot_root|fixed|a2407d1|serve-kb 传配置路径，任意 cwd 快照哈希核验|

324 tests OK；探针 ALL-PASS；生产零改动（修复随下次发布上线）。F0 完成→接 docs/25 A 阶段。

## 记录

- 2026-10-01：M0 完成。源基线 commit 5442e397（52 跟踪文件，工作树干净），复制 49 个公开文件（40 字节一致 / 3 行尾规范化 / 6 文档加来源头），合并 3 个根配置，排除 7 类私有内容。源工程与目标工程测试同为 113 OK（1 skipped）。源目录、Vault、ResearchTools 未改动。
- 2026-10-01：P1 完成（离线）。app/knowledge（store/snapshot/sync/jobs/sampling/measure + CLI），ADR0003；134 测试全过（113 回归不变+21 新增）。A01/A04/A05 真实部分 BLOCKED：真实源访问、真实 tokenizer 未具备。
- 2026-10-01：P2 完成（离线）。ADR0004 + extract/quality/tables/schema 模块；提取器注册表（txt/html/pdf/img 标准库实现）；不可变 extractions/blocks 对齐 evidence-block 契约；153 测试全过。真实 A06-A09 盲测/OCR/财务门禁 BLOCKED（解析器选型、OCR 引擎、真实样本未具备）。
- 2026-10-01：P3 完成（离线）。indexing/kbapi/cards + 事件流；/api/kb/v1 全路由与鉴权（ADR0005，独立端口）；影子索引原子发布；171 测试全过。A10 真实基准/A14 生产对账/A21 性能 BLOCKED（真实语料与服务器未具备）。
- 2026-10-01：P4 完成（离线）。ADR0006 + providers/analysis；RRF 混合召回、引用验证、usage_events 账本、预算门禁；185 测试全过。真实 provider/质量/成本 BLOCKED（供应商、凭据、预算未定）。
- 2026-10-01：P5 完成（离线）。memory/writeback：追加式 claim 历史、决策冻结、影响分析 proposal（不自动覆盖）、哈希门禁写回；196 测试全过。真实 Vault 写回与 A20 真实评测 BLOCKED。
- 2026-10-01：P6 离线部分完成。worker（sync→快照→提取→索引→影响分析闭环+心跳）、在线备份/独立目录恢复演练、compose 准备、接入示例；202 测试全过。生产部署/A21/A22 BLOCKED。至此 M0+P1-P6 离线可完成部分全部完成；剩余工作均依赖外部条件（源访问/服务器/模型供应商/写回授权），见 HANDOFF。

## 独立复核追加（2026-10-02，基线534014a）

当前总体NEEDS_CHANGES。M0保真基本通过，222回归OK/2skip；R01-R15重新打开受影响的P1-P6源码验收，原accepted为历史self-review记录，不是独立验收结论。已明确的真实NOT_RUN/BLOCKED仍保留。修复入口为[RF任务书](../15-review-remediation-taskbook.md)，修复任务RF0-RF7当前均todo。

## 第二轮修复台账（独立复核，2026-10-03）

|任务|问题|状态|退出依据|
|---|---|---|---|
|SR0|基线与失败回归|todo（独立探针已提供）|转换为断言式 RED 回归|
|SR1|S01/S07|todo|预算与 outbox 原子性、中断恢复|
|SR2|S04/S05/S06|todo|返回字节、OCR质量、图片幂等|
|SR3|S02|todo|人工内容不覆盖|
|SR4|S03/S08/S10|todo|时间语义、游标、独立召回|
|SR5|S09|todo|服务正确启动、隔离切换演练|
|SR6|全部|todo|独立复验及真实缺项清单|

详见 docs/17；本表覆盖此前 RF7 闭环判断，不改写历史修复提交。

## 发布前与影子验收（第三轮独立复核，2026-10-03）

|任务|范围|状态|进入/退出条件|
|---|---|---|---|
|N0|基线与断言式反例|todo，独立探针已提供|T01–T07目标断言RED|
|N1|旧库升级与异常账本|todo|有数据升级、逐请求成本与故障恢复|
|N2|版本时间、逐页质量、recipe升级|todo|未知不伪造，漏页不ready，新旧产物独立|
|N3|游标、语义召回、缓存、候选幂等|todo|同长度变化、205块、同维provider、三连跑|
|N4/G1|独立复验|未通过|T01–T07及全回归GREEN，契约无虚假声明|
|N5|小批影子验收|待G1；脚本模板可先准备|docs/08真实证据，未运行保留NOT_RUN|
|N6/G2|全量/切换变更包|待影子结果|范围/预算/恢复明确，实际变更单独授权|

## 第四轮独立验收（2026-10-03）

|条目|状态|接续|
|---|---|---|
|U01 旧库账本迁移|OPEN/P1|C1|
|U02 三类provider请求门禁和attempt终态|OPEN/P1|C2|
|U03 旧版本unknown时间|OPEN/P1|C3|
|U04 真实claim导出幂等|OPEN/P2|C4|
|U05 影子身份/外发/范围/标注/对账|OPEN/P1|C5|
|G1/G2|未独立通过|C6及真实验收|
|条件式迁移/停旧栈授权|已获得|条件通过后执行；本轮未停服|
