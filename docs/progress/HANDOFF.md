# 会话检查点 / HANDOFF

## 2026-10-18 12:20：昨天23份Discord资料已发布并同步

本批23项（22 PDF+1 PNG）全部提取ready、23正文发布/入口链接、384块有效检索通过。Windows23正文+23卡片+3阅读状态文件共49/49 bytes/SHA一致；真实API逐篇证据和关键词检索通过。PNG源文件/hash未改，只修125650→184504字节元数据，两个准确失败job恢复后done/attempts=2。22 PDF原提取保留，没有全量OCR或模型调用。

慢索引原因：全库约730万词项物化、第二份参数列表、无序B-tree写入、2MiB缓存以及worker1GiB内存/1GiB交换约束。新worker排序/迭代写入，写入缓存128MiB，内存4GiB/总5GiB；新generation `gen-eb50c9ebf47dc1a5907047d6`于12:11:04构建、12:18:04激活，整轮12:18:22成功idle。应用API/library仍6679872；仅worker使用`obsidian-sync:discord-index-20261018-dcc61fc8`，其他三服务身份与镜像未改。

恢复：服务器`operations/discord-delivery-repair-20261018/{worker-rollout.json,image-ready.json,delivery-verified.json,worker-resources.override.json}`；完整记录[Discord交付修复](DISCORD-DELIVERY-REPAIR-20261018.md)。数据已通过，不重跑rollout/PNG修复；supervise_delivery旧等待器已superseded，finish_batch.py未执行。新worker按原1800秒间隔继续增量处理，已暂停的Codex定时器未恢复。Obsidian真实UI渲染未验，不将文件同步冒充UI验收。此事不替代仍未完结的图表余量任务。

## 2026-10-12 15:50之后：职责已切为只读验收与每小时跟踪

用户最新要求其他agent只做数据、进度和服务验收，不能变更生产。入口[docs/45只读任务书](../45-readonly-acceptance-and-hourly-watch.md)、[docs/46可复制提示词](../46-readonly-acceptance-agent-prompt.md)。现有每小时heartbeat改为只读；下方15:31等历史“继续启动/发布”的指令不得再由监控agent执行。异常中断验收并只读排查、报警和留问题，不停止生产或自动修复。

15:50现场读数仍为检查点40/862交付、822未完成，前批published；library/API/Syncthing健康，worker运行，restart_count全0。下一合并数据任务未启动，118项仍是待验材料。只读监控不承担启动余量，必须真实报告WAITING_REVIEW/等待执行者。Windows107/107证据时间15:29，UI未验。后续记录仅本机runtime/readonly-acceptance-watch及READONLY-ACCEPTANCE-LOG，不写服务器或覆盖旧operation状态，不自动git提交。保护docs37。

## 2026-10-12 15:31：29页发布闭环，合并发布工具已安装

`chart-governance-remaining-20261012/release-native-01` 已完成：sequence/pinned监督器均published，生产checker通过；API实际29 raw、29 projected、98 assets、29 PDF通过，原文/人工区/历史保护通过。准确apply容器退出0；library/API健康、worker运行、原Syncthing健康。Windows在15:29核对107个发布文件，107/107存在且bytes/SHA一致，真实Obsidian UI搜索仍未实测。冻结范围已交付累计40/862，剩822；全head48含范围外旧8。不要重跑本批apply/隔离/索引。

用户本轮授权提前本地修改，当前批完成后部署接续。Luna限定实现、Codex独立验收的合并发布工具源码 **08fc6fe8abf0bad1733a294b96223c7378f3e919** 已推送，并于15:30安装到服务器 `operations/chart-merged-release-tools-20261012/08fc6fe/`。安装记录 `installation-result.json`：两个CLI通过、前批真正完成/服务恢复/准确apply退出0及pinned chain导入通过；没有重启常驻服务或启动新数据发布。应用仍6679872。

新工具：`ops_chart_release_bundle.py` SHA `8ee2622c1ba216656af33947eb3e3e0245af5e9b21f052c9764d85723a964275`；`ops_chart_release_sequence.py` SHA `a1e3bb0413f41ab8fe162e6b83a63365e195725c480aedc4555f7d0831dbce82`。14项单测13通过/1Windows symlink能力跳过；真实checker两包合并只一次build_generation、原文/人工区/幂等/回退通过；真实pinned chain仅fake进程I/O的接续集成也通过，一次隔离+一次监督器、重复拒绝。私有探针/安装证据在本地 `runtime/chart-merged-release-20261012/`。

**下一步实际工作仍为118项审查包的集中视觉/精确映射验收，不是等待当前29页。** 四包仍在 `followup-reviews/next-review-01..04/review/index.json`，没有验收的不能输入合并器。将通过的子包原始manifest/assets及hash绑定审批合并进全新operation，一个合并批次一次隔离索引、一次生产索引；不要继续按每30页独立发布。新sequence要求bundle是新operation直接子目录，沿用 `prepare-native-01/isolated-prepare-result.json` 布局和旧固定checker；前批填上述release-native-01，准备真实合并隔离副本后先plan再execute。完整门禁/参数见docs/44。原19页OCR partial缓存复用、695未精确定位余量继续，未确认正文/表格保留。普通每1小时简报，阶段完成主动接续，不因小批结束暂停。保护docs37。

> 2026-10-12 15:09：用户同意将常规汇报改为每1小时，现有heartbeat已更新；服务器发布/接续继续运行。阶段完成或实质异常主动处理，不等待用户重新下发。当前29/98批次按同批隔离索引实测约14.4分钟作短期预估，最终以正式发布/API/Windows证据为准；全库日期尚无可靠上界。

## 2026-10-12 15:05：29页隔离通过，正式生产索引构建中

`operations/chart-governance-remaining-20261012` 的隔离容器已退出0，真实结果29 manifests/98 assets、两次幂等、回退和既有Vault保留通过。sequence已自动接生产，14:59 `release-native-01/supervisor-status.json=frozen_backup_ready` 后正式checker启动；此状态不代表尚未应用。

生产容器以 `release-native-01/apply-launch.json` 为准，当前ID `edde357887f340d58ee4eba1f5ca4a003a7d36d9bb852fddec824cd4026be99d`。15:05实查最新stage=activation_progress/activated29，生产只读SQL确认本批29个head已存在，全部head48（旧8+冻结范围40）。正式索引构建有活动：CPU约81%、1.91GiB、累计写IO65.4GB。Library/API/worker已按发布流程停止，Syncthing健康；不要因服务exited/旧health unhealthy就擅自重启抢写。接续器待正式索引/正文检查后恢复服务并验证API。

当前冻结范围已应用40/862，但只有先前11项完成发布与Windows验收；新增29尚未确认发布/同步，不把head存在当交付完成。读 `progress-latest.json` 得最近聚合快照（时间以文件为准），并读正式checker/result/server-verification；完成后按既定流程验Windows并继续118审查包和其他余量。无新增模型/OCR调用，不重启任何旧任务，不重复apply。

## 2026-10-12 14:26：新29页/98图已进入服务器隔离验收与自动发布接续

**14:32追加恢复点：** 下一批118项审查材料已在服务器实际生成完毕，`followup-reviews/result.json` 为118/118、例外0，四包30/30/30/28；容器身份读 `followup-reviews-launch.json`，不可重跑。工具 `prepare_followup_reviews.py` SHA `a89449f4bb100126c321e31c3cade91fa1f15937e0e822e5153d0e792ec50681`，3个边界测试通过；仅复用缓存坐标/原分类并核对来源、重新渲染原图，没有新增模型或OCR调用。`followup-reviews/next-review-01..04/review/index.json` 是下一次集中边界验收入口；`ocr-position-index.json` 已绑定19页原图hash与976位置/3026行统计。118项仍是proposal，不是已治理；当前29页隔离checker仍运行，生产完成数仍11，勿在等待索引时重启任务。

当前operation仍为 `operations/chart-governance-remaining-20261012`。已实际查看下一批30页原图并划定100个图表面板，保护正文/真实表格；严格原文字符映射通过29页/98图，序号1因图题映射覆盖不足暂留原文，不能算已治理。私有边界 `reviewed-boxes-v2.json`、产物 `native-batch-01/`，发布输入冻结在 `release-native-01/{manifests,assets}`，不复用或重跑旧11页。

38,736,158,720字节一致性隔离备份及2,454文件Vault复制通过；29/98清单/资产hash与视觉批准全部一致。服务器脱离SSH接续器已启动，先读 `sequence-launch.json`、`sequence-current.json`；14:26 stage=isolated_started。准确容器 `obsidian-sync-chart-rem-isolated-01-20261012`，ID `6d662feb3e861514f06d03356e489d249d235869311946ecee52738853569588`，网络none，生产snapshots只读，隔离state/Vault可写。实际stage `activation_progress`，CPU约101%、内存1.85GiB，有IO活动。隔离检查点在 `isolated-native-01/operation/`；不要重新启动准备器、checker或整条链。

链条会在隔离应用/幂等两次/原文保留/回退通过、worker空闲后，调用 `supervise_reviewed_batch.py` 复用固定6679872数据发布门禁：准确写者冻结、一致性备份、一次应用、索引/正文发布、API验证、恢复服务。新适配器仅为准确library容器的PDF HEAD增加60秒有界只读就绪重验。线上应用/模型开关不变。本轮尚未新增生产发布；全冻结范围完成数仍11/862，851待治理，其中29在发布验收管线。不要把隔离激活计入线上head。

固定helper：构建器 `6664fd51…`；checker `ceeedb25acdb356055f18ab9b06233664c76a5e7af6bb9adafbd53afed2513a4`；接续器v2 `9210cc0b750846e55bbc215195e3c92f88df4c9232e5d7db076288cba1a8013d`；适配器 `f6f6dc3a68697557a17d619356313bc76109ffef33fa4388490071a7c3c7a04d`。旧监督器真实路径 `operations/chart-native-release-20261012/supervise_native_release.py`，SHA `6e699e44…`；worker状态 `state/knowledge-worker.json`。构建/适配/续接定向测试4+4+5通过，并实查当前29/98准备门禁通过。`continue_native_batch01.py` 是未通过审查的旧草稿，禁止执行；只用已启动v2。

19页定向位置OCR已退出0，全部partial：3,026行OCR中976个精确映射片段；127低置信/空行、1,901非唯一或不匹配。不能当全页完成，不能重复OCR；后续复用图像/位置作针对性边界验收。156精确原生位置中，排除本次30后仍有118个双轮含图建议可形成下批审查包，另5无图建议、3轮异常待处置，不直接confirmed。

完成本批服务器发布后，核对 `release-native-01/server-verification.json` 与实际服务，再下载仅元数据按published_files逐项验Windows；UI搜索仍待实测。此小批完成后继续剩余候选，定时跟进保持ACTIVE，不暂停为全库结项。保护docs37与原始证据；无新增模型调用。

## 2026-10-12 13:56：余量处理已实跑，19页坐标补取运行中

服务器operation `operations/chart-governance-remaining-20261012`。851余量处理器已退出0，逐项结果覆盖冻结862：11已发布跳过、156精确原生坐标、695未获得完整精确位置；来源检查没有新增变动错误。下一批30页原图/双轮框/来源hash在 `coordinates/review/index.json`，仅审查材料，未获生产激活验收。分类模型结果全部复用，没有新增外发。

19页非native坐标预检v3已19/19通过。准确运行容器 `obsidian-sync-chart-rem-ocr-positions-20261012`，ID `9ed915898a245e7fd49b1abe56c685135a0b4d291f3382df8e05dc3d65f051ac`，身份以 `ocr-position-launch.json` 为准，输出 `ocr-positions/status.json`、`items/`、`pages/`、`result.json`。禁网，state/classification/previous/source只读，operation可写，单进程；直接保留RapidOCR框及置信度，仅唯一精确文字位置/完整匹配形成proposal位置，不屏蔽任何生产文字。缺失/低置信/重复/不匹配保持partial/unknown。首次旧预检因每页重复全库effective计算而被准确停止并保留superseded记录；v3仅对当前文档求同一effective逻辑。不得重启旧预检或重复已完成页OCR。

prepare_remaining.py固定SHA `d179ecf6766f28036909754c6ccc0d24c87aba22fb862bf6ef90bd4027b58e49`，5项限定测试及真机全量运行通过。recover_ocr_positions_v3.py以launch SHA为准，6个独立位置反例通过（原始offset空白、重复行、低置信、重叠、真实四点bbox形状、源hash变化零OCR），真实DB预检通过。运行产物仅在私有runtime/server operation，不入Git。生产服务不动；这156/19都是余量治理中间成果，不得计为新增发布。

下一步：检查19页坐标结果与例外；从30页审查材料集中核对图表边界/正文表格保护，再准备下一批准确manifest并按既有隔离/发布链继续。不能停在“任务未运行”的循环汇报，也不能把自动位置提取当视觉确认。定时跟进应关注此余量operation并在阶段完成后衔接下一步，已完成11页release只作为基线。

## 2026-10-12 13:47：全库余量接续准备中

用户指出11页收尾后没有接续全库任务。已对冻结862与当前production heads做只读交集：本范围已发布11，剩余851=198native+457OCR+196unknown；全库head19中的旧8不在本范围。851按原双轮分类互斥分区：610图几何一致建议、184双轮无图建议、19图几何分歧、38含轮次异常；这些均不自动等于确认/错误。分类层已覆盖862，治理发布层尚未完成。

新服务器operation `operations/chart-governance-remaining-20261012` 的 `scope.json` 已保存冻结hash、851准确ID和11排除ID；此时 `status=preparing_coordinate_runner`，还未声称服务器新处理器运行。Luna限定实现私有prepare_remaining.py（所有851的原生坐标恢复、来源校验、至多30页下一批审查图）及recover_ocr_positions.py（原B3计划中19个非native页的必要坐标补取）。只读state/snapshots，禁网，不改DB/Vault/常驻应用，不重新分类/重发成功请求。父agent须先验收实际形状fake和固定依赖，再启动准确容器并追加真实launch/进度。原B3 plan是 `chart-resolution-20261011/refine-run/plan.json`；不可错用旧audit/review-plan.json（非native数量不同）。现有LocalRapidOcr丢弃坐标，仅保存合并正文/置信度，没有发现可复用OCR框缓存。

不再次把11页发布完成当全部任务完成；下一步必须产生余量处理实际运行记录，而不是只更新监控。保护docs37，备份/原文/人工区域保留。

## 2026-10-12 13:38：11页生产发布与Windows同步已完成

本批新增11页（10份正文文件）/41图已经发布，live heads=19（含旧8页）。生产checker退出0并passed；13:37只读续验通过 raw 11/11、projected 11/11、assets 41/41、PDF HEAD 11/11。Windows 55/55文件存在、字节数与SHA256全部一致（10正文、41图片、4索引/状态/元数据）。入口Windows `ResearchVault/解析正文/开始阅读.md`。文件核验不等于真实Obsidian UI搜索验收，UI仍未实测。剩余862候选范围未全部治理，不声称7天观察完成。

09:07原监督器在library重启后立即发起PDF HEAD时ConnectionRefused，随后恢复服务但未继续验收；原生产写入与发布已经通过。13:34确认原文HEAD已200，13:37复用固定监督器的verify_api及服务身份检查，仅执行读取，未重跑apply/索引、未重启服务、未调用模型。原失败stage/traceback保留。补验绑定冻结Vault hashes及备份字节，确认原有非生成文件未变、API/library/worker/Syncthing身份与镜像未变；当前监督器状态已记录published。

恢复入口仍为服务器 `operations/chart-native-release-20261012/`：`server-verification.json`、`completion-verification-result.json`、`data-release-production-result.json`、`frozen-backup/manifest.json`。本地 `runtime/chart-native-release-20261012/server-verification.json`、`windows-verification.json`。不得重新部署本批或用旧DB覆盖；备份保留，回退须按本批准确manifest/head做CAS。下批仍需准确边界/字符映射；模型一致不能自动屏蔽正文/表格。自动反馈遵从用户最新每30分钟要求；可恢复异常先处理，不无声停机。保护docs37。

> **2026-10-12 08:48当前：已经真实应用生产11页，live heads=19（原8+新11），正在构建正式索引。** 新operation仍`chart-native-release-20261012`；冻结一致性备份已通过，frozen-backup/manifest存在，apply已启动，stage activated=11，独立生产SQLite核验19heads。library/API/worker在切换流程中，Syncthing保持运行；正文/41图发布、服务恢复和接口验证由同一监督器接续。不得重复启动或因supervisor仍显示frozen_backup_ready误判未应用（它在等待checker完成）。下一次先读apply-launch、生产stage、data-release-production-result和server-verification；生产成功后下载元数据核对Windows新正文/41图/索引hash，实际UI另验。剩余候选未完成，不恢复heartbeat，不覆盖旧DB或改docs37。详情见[执行记录](GLM-CHART-BATCH-20261010.md)首节。

> **2026-10-12 08:43 当前：已开始正式生产冻结/备份/发布流程，尚未确认应用完成。** v2隔离昨日23:19退出0，11页41图及幂等/回退全部通过，原11页真实postings诊断也全部相符；不重跑内容验收。此前监督器因state挂载范围判断和library未纳入而在停服前退出；限定修正、4反例及08:43真实服务器预检通过。新operation `chart-native-release-20261012`，supervisor SHA `6e699e44…`、checker仍`ceeedb25…`；08:43:20独立启动，08:43:47library已停、worker停机中，Syncthing/collector不动。恢复读取新op的supervisor-status、stopped记录、frozen-backup/manifest、apply-launch、data-release-production-result、server-verification；不能把复制的v2验收证据当新隔离运行。不重复启动，不覆盖DB；发布后还需Windows文件/实际UI验收。详情见[执行记录](GLM-CHART-BATCH-20261010.md)首节。heartbeat保持暂停，保护docs37。

> **2026-10-11 22:59 当前：v2隔离复验和自动发布接续已运行，生产尚未切换。** 首轮17:46因私有checker给keep片段插空格分词的误报失败，隔离回退成功、未冻结生产，四服务正常。原文offset字符保留门禁修正在新v2 helper内完成，独立6项回归通过，仍严格校验全Counter/真实缺字，原清单/41图/应用不变。新operation `chart-native-release-20261011-v2`：prepare退出0；22:58:53新隔离容器启动，22:59实查running且监督器身份匹配，自动验收→备份→数据发布→接口验证已接续。读取continuation-result/isolated-launch/data-release-isolated-result/supervisor-status及后续生产结果，不重跑旧operation或启动器。checker SHA `ceeedb25…`，supervisor仍`da1970e8…`；首轮失败证据保留。详情见[执行记录](GLM-CHART-BATCH-20261010.md)首节；生产完成后仍须Windows同步与UI验收，全库治理未完成。heartbeat保持暂停，保护docs37。

> **2026-10-11 17:40 当前：11页/41图的隔离验收及自动发布接续已在服务器独立运行。** operation `chart-native-release-20261011`；隔离容器 `0b3d5f8b…` 已应用11页、正在构建索引，生产仍原8页。监督器已脱离SSH，launch/process/started落盘且实际进程身份匹配，SHA `da1970e8…`；固定checker `0de4fda1…`、现网6679872镜像。真实隔离检索/发布/幂等/回退通过且worker空闲后，自动冻结准确写者→一致性备份→本批数据投影/索引/发布→恢复同一API/worker→接口/原文/图像/人工区验证。无需用户再触发，不恢复heartbeat。恢复先读supervisor-launch/started/status、data-release-isolated-result、apply-launch、data-release-production-result、server-verification（按阶段存在），禁止重复启动。生产完成后还须Windows正文/41图/索引hash核对及实际UI验收；剩余19个OCR/unknown复核页未映射，862全库未治理完。完整SHA、备份与失败边界见[执行记录](GLM-CHART-BATCH-20261010.md)首节；保护docs37。

> **2026-10-11 B3-3 当前：11 native 页 / 41 图已真实视觉核验并精确映射，隔离备份准备已完成。** 新服务器 operation `chart-native-release-20261011`；prepare 容器 67106561…退出0，36,486,787,072字节 SQLite 一致性副本、Vault/清单/资产复制验证通过。恢复读 prepare-launch/isolated-prepare-result/input-hashes 和之后 data-release-*-result/supervisor-status（若有），不重复初始化。下一步隔离应用/发布/幂等/回退，通过后仅数据投影小批切换；生产仍6679872/原8页，本批尚未激活。私有视觉/映射证据在 chart-resolution-20261011/native-manifests-v1 与 native-visual-acceptance.json；11页41图实际查看，19个OCR/unknown复核页尚未精确映射。无新增模型调用，不恢复heartbeat，保护docs37。

> **2026-10-11 17:01 当前：B3-2已在12:06完成，结构核验通过。** 30项60请求=59valid/1truncated，零HTTP/unknown/熔断，容器e890a5b4…退出0。原21分歧中18项新双轮图表一致、2仍分歧、1截断；全30项为27一致/2分歧/1截断，另1图/表冲突可重叠。真实视觉边界、精确字符映射与生产发布尚未完成，不能将模型一致直接confirmed。恢复入口 `chart-resolution-20261011/refine-run/proposals.json`、`refine-structural-acceptance.json` 及[执行记录](GLM-CHART-BATCH-20261010.md)首节；不重跑已结束模型任务，heartbeat保持暂停。

> **2026-10-11 11:42 当前后台任务：B3-2边界复核已启动。** `operations/chart-resolution-20261011/refine-run/`，容器e890a5b4…，计划c9f1ce9f…，helper1e98a369…；30项=21图表差异（含3图/表冲突）+9对照，native11/OCR14/来源unknown5，旧请求unknown全部排除，最多60调用/3并发；11:43:31实查3 dispatch/0返回、无熔断，真实请求已发出。固定121ff6c源、生产只读、新purpose/cache，proposal-only不激活。先看launch/started/cache/proposals/circuit与容器，不重复execute。B3-1审计已完成；下一步仅在本批完成或实质异常时集中验收，不重复全量分类、不重启OCR、不恢复半小时Codex唤醒。详见[执行记录](GLM-CHART-BATCH-20261010.md)首节。下面为历史检查点。

> **2026-10-11 当前：B3-1禁网只读审计已通过，B3-2小批工具准备中。** 审计工具121ff6c；server operation `chart-resolution-20261011/output/audit/`，容器203f8164…退出0。862全current，159快照核验，209native页全文精确对应；619图表几何一致/184双轮无chart/21图表分歧/38异常。原720分歧仅21涉及chart，另3图/表冲突可重叠。准备最多30页新目的GLM边界复核，不重跑B2/不发送unknown/不激活生产。详见[执行记录](GLM-CHART-BATCH-20261010.md)首节；只读复核产物，勿重跑旧分类或审计容器。定时heartbeat仍暂停。

> **2026-10-11 10:49 已收尾：862/862 分类结束。** 最后7批在03:13完成；独立核对10份接受报告与冻结清单，全覆盖无重漏、全部proposal-only。824项双轮结构有效、38项异常；104项双轮一致、720项分类/框选不一致，不能据此直接激活。生产服务健康，B3精确映射/裁图/发布未执行。当前入口 `remaining/continuation-v3-http/sequence-result.json`、`complete.json` 和[执行记录](GLM-CHART-BATCH-20261010.md)首节。旧分类任务已结束，勿重跑；Codex heartbeat保持暂停。以下为历史状态。

> **2026-10-10 20:50 新续跑入口：continuation-v3-http。** 第 2 批 100 项/200 请求完成（96 双 valid，1 HTTP500/1 schema/2 truncated），旧 v3 在 19:04 因 HTTP500 门禁停止。累计处理230/862，剩余632。限定操作层 HTTP 留档规则验收及服务器真实预检通过；20:50:40 新监督器已脱离SSH启动，20:51:41已实查batch-003容器32b6dc87…运行，3workers/只读生产挂载正确，dispatch0（预检渲染）。新目录 `operations/glm-chart-batch-20261010/remaining/continuation-v3-http/`，计划 `39a3ba54…`，仅原003–009批、3并发、旧请求不重发、生产只读/proposal-only。先读新 sequence/launch/cache/complete/stopped，勿重启旧v3。详见[执行记录](GLM-CHART-BATCH-20261010.md)首节；定时 Codex 唤醒仍暂停，B3未开始。以下均为历史检查点。

> **18:02:01 已实查 v3 第 2 批启动：** `sequence-status=batch_running/batch-002`，容器 `glm-chart-v3-002-20261010` / `3b0621cd…`，3 workers，policy marker 存在，生产只读挂载正确；dispatch/返回仍 0（预检渲染阶段）。监督器活跃。下一次进度只读 `remaining/continuation-v3/sequence-status.json`、当前批 cache 与 result，勿启动新开发或重复全量验收。

> **2026-10-10 当前恢复入口已切至 v3。** 17:51 查明旧 49 已全发，但普通超时使旧后续队列停止；原 200 请求已零调用合并为 100 项/90 双 valid。Luna 操作层普通超时留档适配经 Codex 集中验收，剩余 8 批 732 项已提交服务器独立启动。新目录 `operations/glm-chart-batch-20261010/remaining/continuation-v3/`；只读 supervisor-launch/sequence-status/各批 cache/result 判断实际进度，不沿用旧 follow-on 状态或重复 execute。计划 SHA `92c888be…`，3 并发，未知不重发；普通 TimeoutError/HTTP400/schema/truncated 留异常后继续，认证/429/错模型/源变化等仍停止。工具 hash 与真实预检见[执行记录](GLM-CHART-BATCH-20261010.md)首节。生产服务/DB/Vault不改，Codex半小时唤醒保持暂停。

> **2026-10-10 17:51 最新：49 请求全部已发，但 16:44 因新一次 TimeoutError 停止；732 项未启动。** 49 记录=46 valid/1 schema/1 truncated/1 unknown；与原 151 合并恰 200 请求、100 项、90 项双 valid，旧请求一律不重发。后续监督器已 GateError 退出，不能沿用 16:32 “等待中”状态。Luna 正准备仅 operation 的 v3，使普通超时等已记录例外不再阻断无关项；仍保留 auth/429/错模型/源变化/未配对 dispatch 的停止条件。尚未完成 v3 验收/启动。见[执行记录](GLM-CHART-BATCH-20261010.md)首节；定时 Codex 唤醒仍暂停，生产健康。

> **2026-10-10 16:32 当前恢复入口：服务器续跑及后 8 批衔接均已启动。** 49 未发送请求续接实际 dispatch 23 / valid 返回 20 / 在途 3；`follow-on-supervisor-launch.json` 对应进程身份已核实，等待精确续接容器成功并完成对账后自动跑 002–009 共 732 项，3 并发。续批输出 `remaining/batch-001/continuation/follow-on/`；先读 status/result/停止记录，勿重跑 execute 或原 sequence。工具 SHA/门禁/检查点见[执行记录](GLM-CHART-BATCH-20261010.md)首节。生产服务健康，DB/Vault 只读，不 activate。半小时主模型 heartbeat 已暂停并缩短恢复提示；以后只做阶段验收，不恢复高频读取历史。用户 docs37 未动。以下为历史记录。

> **2026-10-10 16:22：49 个未发送请求已在服务器续接。** 容器 `glm-chart-unissued-20261010` / `f1786fcd…`，源码工具 SHA `134df734…`，计划 SHA `a913a9ab…`，3 并发、旧 151 请求全部排除。完整 driver 离线 fake + 服务器逐对象差集验收通过。真实状态入口 `operations/glm-chart-batch-20261010/remaining/batch-001/continuation/`；16:22:49 running/尚在预检，dispatch 0。先查 started/status/results/cache，勿重跑 execute。后 8 批 732 项的服务器自动衔接尚在准备；生产只读、旧 9 异常保留、不激活投影。半小时 Codex heartbeat 保持暂停，按新分工只做阶段验收。详见[执行记录](GLM-CHART-BATCH-20261010.md)。

> **2026-10-10 16:04 核验 / 用户恢复授权：第一批因超时停止，正在准备仅未发送请求续接。** 原 batch-001 在 15:59:53 退出 0，监督器因结果门禁停止；151 dispatch 对应 142 valid、2 HTTP 400、4 格式错误、2 截断、1 unknown timeout，45 项两轮有效。49 个第二轮请求从未发送，后 8 批未启动。旧请求均保留且不重发；Luna 私有 `resume_unissued.py` 正进行运行修正和独立验收，尚未获本次上线验收。用户要求降低 Codex 消耗：服务器脚本调度/统计、GLM 批量、Luna 限定修复、主会话阶段验收。原半小时 heartbeat 保持 PAUSED；不要恢复旧高频监控，不按历史“运行中”检查点重复启动。生产/应用源码不改；新运行状态以本条之后的启动记录为准。

> **2026-10-10 15:34：第一批仍在第一轮，72 dispatch / 68返回（67valid、1 HTTP400）/4在途。** 第二轮未开始、双轮齐备0，最新返回距快照20秒，正在推进。HTTP400非认证/限流、无熔断、未重试；既有监督器会在本批结束后因该错误停止续批，届时核查实际结果和身份，勿盲目重启或改目录重发。当前不修改运行中任务，生产服务健康。详见[执行记录](GLM-CHART-BATCH-20261010.md)文末；sequence/各批launch仍是恢复入口。

> **2026-10-10 15:17：剩余832项已启动9批服务器顺序分类。** 30项真实视觉验收完成、B2仅proposal放行，B3精确映射未验收。`remaining/plan.json`按100×8+32，根已核对冻结对象原样/排除30试点/不重不漏。私有`run_remaining_batches.py` SHA736f75b8…已审查，真实runner fake产物独立5项通过；`sequence-status.json`为恢复入口，勿重跑--execute。第一批launch容器ae162b20…15:17:42启动，15:18:55实际7请求/3valid返回/4在途、双轮齐备0。每批4并发、单runner顺序接续、state/secret/source只读，生产与Vault不改。原试点/诊断不重启，未知不重发，格式/截断保留例外。半小时heartbeat已更新；详细[执行记录](GLM-CHART-BATCH-20261010.md)。

> **2026-10-10 15:04 起：原30项v2已退出0，真实视觉验收30项完成，B2限定通过。** 35新增请求全返回+25复用=59 valid/1 truncated；29项双轮有效、序号26保留截断例外。实际看到22图表页/8仅表格正文（58图表面板），存在11/20/29等框选边界风险，禁止按模型bbox激活。私有`visual-review-v2.json`给出逐项hash与判断，允许剩余832仅proposal分类；正在准备9个顺序批次、每批最多100、4物理请求并发的服务器独立监督器。旧pilot/diagnostic不重启，生产不改，B3精确映射/发布待独立验证。先读[执行记录](GLM-CHART-BATCH-20261010.md)后续launch，勿重复初始化。

> **2026-10-10 14:44：围栏兼容修复 `dd8180d` 已验收，原30项有界续跑已启动。** 9回归+Codex完整流程6项通过；禁网真实预检25回复复用（旧24+诊断1），仅35已知失败补调用。服务器新源码source-v2、新容器身份见`pilot-v2-launch.json`，结果pilot-run-v2，4并发、生产state只读。旧试点/诊断不重启，成功项无新dispatch，未知不重发。已看13/16/25/30四页均应保留表格/正文，另26项待v2真实视觉验收；832后续未开始。半小时heartbeat已更新。恢复入口见[执行记录](GLM-CHART-BATCH-20261010.md)，保护docs37与所有原始证据。

> **2026-10-10 14:34：首轮图表试点与诊断完成；正修复已证实的 JSON 围栏兼容。** 原60请求全有结果：24 valid、35格式失败、1截断，14:18退出0。额外1次诊断证实完整JSON围栏解包后8区域合法，原始回复私有保留。Luna仅改原三工具/测试文件，Codex独立验收；要求复用成功缓存和可恢复诊断，不重发未知请求、不无条件重跑60次。生产不改，832后续候选未启动；review-v1禁网渲染用于先看4个两轮有效但有分歧的页。详见[执行记录](GLM-CHART-BATCH-20261010.md)，先查现有容器/产物勿重复。

> **2026-10-10 14:07：图表试点首批回复存在格式校验失败，正在有界诊断。** 14:06 已 dispatch 15，返回 11（2 valid、9 invalid_json_or_schema），无 HTTP/熔断；原 4 路继续。服务器已排队 `supervise_diagnostic.py`，只在准确 pilot 容器退出后对 1 个同范围已知失败做诊断，原始回复仅私有保存，不超过全局 4 并发。先读 diagnostic-supervisor/diagnostic 检查点；不要重复启动或重发未知请求。真实质量未验收，剩余 832 尚未启动。详见[执行记录](GLM-CHART-BATCH-20261010.md)；现有 heartbeat 已包含本恢复分支，生产不改。

> **2026-10-10 14:03：GLM 图表 30 项真实试点已在服务器启动。** B1/B2 工具固定 `34edf46` 已推送，离线 5 项与 Codex 独立 6 项通过；禁网冻结核对 862/862 有效、跳过 0，30 试点来自 30 份文档，三来源各 10，含图片。新 operation `operations/glm-chart-batch-20261010`，先读 `pilot-launch.json`/实际容器与 `pilot-run/cache`、proposals；4 路、两轮、最多 60 请求，已 dispatch 无结果不重发。生产数据/服务不改，结果仅 proposal。现有 heartbeat 已改“GLM图表批处理与验收”继续半小时跟进，真实质量/后续批量与 B3 映射发布尚未完成。[执行记录](GLM-CHART-BATCH-20261010.md)含准确恢复路径；不得重启旧发布/OCR。下方为历史准备状态。

> **2026-10-10 13:56：用户确认现有 GLM 批量治理剩余候选，额度不作为约束；先 30 页双轮试点。** [任务书](../43-glm-chart-batch-taskbook.md)、[新执行记录](GLM-CHART-BATCH-20261010.md)。Luna 正在限定新文件中实现 B1/B2，Codex 负责独立验收及真实运行。服务器新 operation `operations/glm-chart-batch-20261010` 已建立，目前仅 preparation/audit 输入，尚无本批真实调用；生产仍 `6679872`，不重跑已完成发布或旧 OCR。862 候选冻结时须复核有效版本/hash/head，结果仅 proposal；原文/表格、docs/37 与凭据边界继续保护。下方为已完成小批及历史状态。

> **2026-10-10 13:16：图表小批已上线，服务器与 Windows 文件验收通过；只剩 Obsidian 实际 UI 验收。** 固定应用源码 `6679872`，12:46 三服务换成新镜像，worker 12:47 完成首轮。8 页/26 图像、8 raw/8 projected/8 PDF、生产三连跑、原文/账本保留、冻结备份独立 SHA 均通过；Windows 36/36 文件匹配，26 图像引用存在。已添加 53 条精确旧副本搜索排除，文件仍保留，配置备份在本地 operation runtime。全库有 862 块/159 文档版本的未确认线索；candidate hold 关闭，不把候选当已确认错误。Obsidian 未运行，CLI 无法连接，尚未实查默认搜索/图片显示，待用户打开应用并开启 CLI；跟进暂停，不重部署、不重跑 OCR。证据/备份/`recover-v2.py` 入口见[生产记录](CHART-PRODUCTION-20261010.md)。用户 docs/37 保持原 hash。下方是历史检查点。

> **2026-10-10 12:13：图表隔离验收全部通过，自动生产切换已开始，尚未确认上线。** v2 隔离容器退出 0；8 页/26 图像、三连跑、原文保留、零新增模型使用及回退通过。`supervisor-v2-status.json=cutover_running`，12:13 `cutover-status.json=freezing_knowledge_writers`；准确服务停止/冻结备份/生产应用由现有 `cutover-v2.py` 继续，不重复启动。最新阶段以服务器 operation 检查点为准。Windows 此时 Obsidian CLI 找不到运行中的应用，实际搜索验收需要应用运行并开启 CLI；不影响服务器发布。继续沿用下方 v2 清单、回退位置、授权及 docs/37 保护规则。

> **2026-10-10 11:20 图表治理授权发布：第二次隔离验收运行中，尚未切换生产。** 固定源码 `6679872`、8 页/26 图像、零新增模型调用。首轮因 Windows 样本导出换行改变导致 5 页清单哈希不同，已证明生产/备份/隔离原文一致，并对 8 页/41 区间按原始字节重新绑定；不改应用、不重跑 OCR。当前读 `operations/chart-release-6679872-20261010/` 内 `attempt-v2-launch.json`、`rebind-v2-result.json`、`isolated-result-v2.json`、`supervisor-v2-status.json`、`cutover-status.json`、`production-result.json`。首轮结果保留，仅为历史。续接脚本为 `check-v2.py`/`supervise-v2.py`/`cutover-v2.py`，必要回退为 `recover-v2.py` 配合 `manifests-v2/`；不要重跑启动脚本或根据旧 PID 操作。用户授权优先于下方历史“未授权”，不重复索要本次许可。[生产记录](CHART-PRODUCTION-20261010.md)有备份及证据。保护 docs/37 用户修改；旧 OCR/迁移任务不重启；实际 Obsidian 搜索仍待 CLI 开启。

> **2026-10-10 图表治理本地发布候选独立验收通过，固定源码 `6679872`。** 用户本轮授权 Luna 执行、Codex 验收。分析页按引用绑定投影，不重新导出原始图表碎片；粗粒度 claim 与旧单篇分析的候选暂缓路径补齐；索引失败有独立 `reindex` 恢复入口且回退 CAS 不放宽。Codex 独立 6/6、全回归 468（466 通过/2 跳过）、干净提交 20/20；10 页既有真实隔离产物的 30 图片/33 保留范围复核通过。[验收报告](CHART-CONTENT-ACCEPTANCE-20261010.md)、[Luna 记录](LUNA-CHART-RELEASE-20261010.md)、[操作手册](../42-chart-governance-operations.md)。本批未部署、未调用真实模型、未改真实 Vault；G4 小批上线、全候选确认及 Obsidian 旧副本搜索隔离仍待对应授权和执行。不要复用旧 OCR 授权或重启历史任务；保护 docs/37 用户修改。下方为此前状态。

> **2026-10-10 图表治理固定实现 `1c718b3`，待独立验收及本批生产授权。** 全回归 464 项（462 通过/2 跳过），Git archive 干净源码 16 反例通过。[交付记录](CHART-CONTENT-DELIVERY-20261010.md)、[运行手册](../42-chart-governance-operations.md)、[任务书](../41-chart-content-governance.md)。区域投影、统一消费门禁、历史依赖失效、原图资产/阅读版本/API 已落地；真实 8 页及追加 2 页隔离验证完成。服务器只读对账 1,791 文件，Windows 同名 hash 全部一致；3 个登记 hash 冲突、268 未知归属、8 个归档候选均未动。生产仍用原策略；全候选确认、旧副本搜索隔离和新增暂缓开关待 G4。禁止恢复历史迁移或重跑 OCR；不使用 OpenCode，不擅自部署，不覆盖 docs/37 用户修改。

> **2026-10-08 用户追加提高 GLM 并发，已从 2 路接续为 4 路。** 沿用既有 runner 的 `--workers 4`，应用/runner/recipe/页面缓存不变；原 8 份完成文档跳过，138 页已返回结果复用。新容器 ID `7be0e47d622bec65e340a70a9d690058780d638e1471a2d6cc4319831e8a51d4`，现行名称仍 `obsidian-sync-glm-ocr-20261008`；旧容器保留为 `obsidian-sync-glm-ocr-20261008-w2-retired`。读取 operation 的 `launch.json` 与 `concurrency-4/` 恢复记录，禁止重启旧写者；新 supervisor 独立运行。以下 2 路信息是首次启动历史。累计页数应汇总 item stats/页面缓存，重启后的 `status.json` 页计数只覆盖本进程。

> **2026-10-08 GLM OCR 接续已在服务器启动。** 用户明确批准指定样本测试与原 458 份清单的剩余批次外发到现有 GLM-5.3-Flash 接口。真实试验通过限定混合路由：普通页 2 路并行，密集表格/失败/截断页回落本地 OCR，模型结果保留 review。旧 OCR 准确停止，已完成 249 份不重发，剩余 209 份冻结；容器 `obsidian-sync-glm-ocr-20261008` 已启动，应用镜像仍 `9d1b04f`。恢复先查服务器 `operations/glm-ocr-20261008/{status,launch,supervisor-status}.json`，禁止重复 handoff 或盲目重启旧 OCR。15.6 GB 一致性备份完整性/SHA 已通过，服务健康；新批次与结束后恢复本地增量 worker 的 supervisor 均独立于电脑运行。详情及真实验收限制见 [GLM OCR 记录](GLM-OCR-PILOT-20261008.md)。本轮未部署下面的手动同步按钮，未改常驻模型开关；保护 docs/37 既有用户修改。

> **2026-10-07 手动同步入口已开发并本地验收，待本批生产发布授权。** 见 [docs/40](../40-manual-sync-and-cadence.md)。状态面板新增“立即同步资料”（仅第一层接入/卡片，复用 ingest 锁，重复请求合并）及本机 Syncthing `127.0.0.1:18384` 入口。资料自动检查 3600 秒、知识 worker 1800 秒；两端文件监听开启、聚合 10 秒，Syncthing 3600 秒为兜底扫描。5 项新增行为测试、438 项全套回归（2 跳过）及真实浏览器隔离点击通过。未改生产/修复/OCR/模型；发布只更新 library，须遵守用户“验收后再授权生产发布”的规则。保护工作区既有 docs/37 用户修改，不混入提交。

> **2026-10-07 知识库 API 使用说明已落地。** 见 [docs/39](../39-knowledge-api-usage.md)：Windows SSH 隧道、只读认证、腾讯关键词检索、固定证据/完整正文/快照、背景包与当前限制。服务端现网只读调用通过；8 段 PowerShell 语法检查通过，Windows 隧道端到端未实测。README 新增实际使用入口，docs/04 标清设计与实现差异。未改生产/模型/OCR任务。旧背景客户端 `published` 参数与当前 `public` 不一致，使用 docs/39 的直接 HTTP 示例；此项不另启开发返工。

> **2026-10-07 用户已授权使用现有 GLM；腾讯跨期财报单次真实分析已完成。** 复用分析执行与写回模块，隔离适配现有Anthropic接口，1次GLM-5.3-Flash调用（输入143,421 / 输出3,128 tokens），原文固定两份中报；核对稿已落本地Vault `自动研究候选/0700财报试用-20261007/腾讯00700-2026中报变化与初步分析.md`。见[真实调用记录](GLM-TENCENT-PILOT-20261007.md)。生产模型仍关闭，未修改OCR任务；不把本次指定证据的单次试用当作B/C自动流程全量验收。已有结果无需重发。下方方案中的“未调用模型”为当时状态。

> **2026-10-07 下一阶段使用方案已落地，当前仅文档规划。** 用户要求历史修复继续运行，同时准备如何消化研报并接入投资框架。见[研究使用方案](../37-research-use-and-investment-workflow.md)与[研究模板和提示词](../38-research-templates-and-prompts.md)。建议两家公司、一主题、约十二份核对资料开展 B4 试点，复用已有 B/C/D；未启用模型、未部署新代码、未更改服务器修复任务。现有公司研究/主题研究/周报/分析草稿均为人工区，自动总结应使用已登记生成区。正式试点前补齐关注对象、目标应用和 provider/资料范围/预算。本方案不重新开启已通过的开发返工，也不覆盖当前修复授权。

> **2026-10-07：已按用户明确授权修复 Obsidian 保存 EPERM。** 两端仅将 `research-vault.ignorePerms` 设为 true，本地 2,049 个 Markdown 清除 ReadOnly；全量正文 hash 与 NTFS ACL 不变，原报错文件可写，双方同步 0 错误/0 待同步。保持该配置，后续部署不要用旧配置覆盖。OCR 未中断，最新观察第 212/458 份。证据与恢复路径见[运行记录](RELEASE-REPAIR-20261006.md)。

> **最新：用户要求立即开始正式服务器重识别，新增问题另列 fix；已启动独立发布/修复监督进程。应用仍固定 `9d1b04f`，未改应用代码。** 自动冻结备份→切换 API/library→458 份正式候选重处理/分批发布→恢复增量 worker。无需再次授权或用户回来触发。恢复优先读 operation 的 `production/supervisor-status.json`、`production/repair-status.json`；下面只跑样本后等待的安排已被覆盖。详情 [运行记录](RELEASE-REPAIR-20261006.md)。

> **2026-10-06 用户已授权本次生产发布及正文修复，由 Codex 直接执行。服务器独立操作已启动；不要重新发开发任务或再次请求相同授权。** 固定应用源码 `9d1b04f`，操作 ID `release-9d1b04f-20261006`。首先读取[运行记录](RELEASE-REPAIR-20261006.md)与服务器 `operations/release-9d1b04f-20261006/{host-status,sample-status,repair-status}.json` 实际存在的文件；未完成样本验收前生产仍旧版。模型关闭、保留全部旧正文和人工内容。下方未授权状态为历史。

> **2026-10-06终轮验收通过：最终源码9d1b04f（含Codex补齐缺页/质量及claim资料范围）。29探针通过，431回归通过/2跳过，干净源码15项通过。S1–S4/F1–F3开发续验结束，不再下发SF返工，F4仍后置。** [最终报告](SF-ACCEPTANCE-20261006.md)、[发布与正文修复计划](../36-validated-release-and-text-repair.md)。本次未部署、未真实模型调用、未历史重处理/归档；生产仍67c6985r2。发布、真实样本/批次及模型范围/预算须分别授权。下方为历史记录。

> **当前状态（2026-10-06 第五批）：SF01–SF06 六条续验条件全部闭合并推送（db61484），停在"待 Codex 独立续验"**。见[开发报告](SF-DEV-20261006.md)：五份探针全绿（SF 6/6、TQMA 7/7、MA 3/3、AC1 7/7、原 6/6），全回归 426 OK；零生产变更/零模型调用。主题分类不再扩大 C 资料发送范围（文档级过滤）；新提取必须"全可用"才赢得入口（部分损坏不压完整旧稿，仅降级回退）；治理保护全 Vault wikilink/片段引用；JobRunner 拒绝冻结 recipe 不符的 job 且可恢复；批次冻结原子化（中断恢复完整批次）；预算等待退还 attempt 不耗尽故障重试。部署与数据批次均需 Codex 验收 + 用户对具体 commit/范围授权。

> **2026-10-06独立续验0f9cb27：原23探针通过、420回归通过/2跳过，干净源码F1/S4另4项通过。S4/F1代码交付通过；S1/S2/S3/F3原任务组合条件未闭环，按原docs/34补齐SF01–SF06，不扩展范围，F4仍后置。** [续验报告](S1234-ACCEPTANCE-20261006.md)、[原任务书](../34-tqma-followup-taskbook.md)、[续验提示词](../35-tqma-followup-prompt.md)。未部署；现网67c6985r2、旧服务仍停止。生产与数据批次授权边界不变。下方为历史记录。

> **当前状态（2026-10-06 第四批）：S1–S4 执行边界 + F1–F3 已完成并推送（25a89d6），停在"待 Codex 独立续验"**。见[开发报告](S1234-DEV-20261006.md)：TQMA 探针 7/7、MA 3/3、AC1 7/7、原 6/6 全绿，全回归 420 OK；零生产变更/零模型调用。执行范围覆盖 B 领取/partial/C 发送（空范围零调用）；阅读/检索/治理统一有效提取选择（坏新稿不压旧正文，被引用文件必留）；批次成员/recipe 冻结；三个预检 CLI 真正只读（外来库拒绝不初始化）；样本 harness 入 Git 并以合成含数字 PDF 实测。部署与数据批次均需 Codex 验收 + 用户对具体 commit/范围授权。

> **2026-10-06 最新独立验收：fbc24bd的原16反例通过，410回归通过/2跳过。新增边界归并S1模型范围、S2有效入口与引用、S3冻结批次、S4真正只读四组，按功能限制启用；不重做已通过修复/迁移，不停现网。** [验收报告](TQMA-REVIEW-20261006.md)、[集中任务书](../34-tqma-followup-taskbook.md)、[下一位agent提示词](../35-tqma-followup-prompt.md)。样本工具未入Git等列fix清单；本次无生产变更/真实模型调用/历史重处理。生产仍67c6985r2；任何发布均须先Codex验收再获用户对具体commit/范围授权。下方开发声明为历史记录。

> **当前状态（2026-10-06 第三批）：TQ0–TQ4 正文质量防护/工具 + MA01–MA03/C主题 已完成并推送（721dde8→db7b967），停在"待 Codex 独立验收"**。见[开发报告](TQMA-DEV-20261006.md)：三探针全绿（6/6+7/7+3/3）、全回归 410 OK、零生产变更/零模型调用/零历史批量重提取。正文防护已进代码路径（损伤路由/替换不拼接/下游证据过滤/入口状态区分），生产清单与修复批次等待授权窗口。部署（含 50cf6c1 维护版）均需 Codex 验收 + 用户对具体 commit/范围授权。

> **2026-10-06用户追加：正文质量TQ0–TQ4并入现有开发批次并前置于LLM。** [详细任务](../33-text-quality-repair-taskbook.md)、[统一任务](../31-maintenance-and-model-activation.md)、[更新后提示词](../32-model-activation-prompt.md)。只读核对发现当前523项提取中458项为旧stdlib-pdf；需全库质量清单、原生重提取优先、必要页OCR，不强制全库OCR。旧副本只做治理dry-run；生产重处理/归档/部署须另获具体授权。此前链接可打开的验收不代表正文内容正确，历史质量尚未修复。


> **2026-10-06 AC1续验最新结论：50cf6c1模型关闭维护范围限定通过。** [报告](AC1-FOLLOWUP-20261006.md)：原探针6/6、AC1探针7/7、全回归382通过/2跳过；旧库升级阻断解除，可进入维护发布准备，仍须用户授权。B/C启用前集中修MA01–MA03，不阻挡维护范围、不重做迁移。见[双轨任务书](../31-maintenance-and-model-activation.md)与[提示词](../32-model-activation-prompt.md)。未部署、未调用真实模型。下方历史声明不代表最新状态。


> **当前状态（2026-10-06 第二批）：R1–R5 已完成并推送（e58e91b→8cca7de），停在"待 Codex AC1 续验"**。见[开发报告](R12345-DEV-20261006.md)：新探针 7/7、旧探针 6/6、全回归 382 OK、零生产变更/零模型调用。关键集成：旧版库起步+两篇冲突合成报告经标准服务入口（worker --once）到 B/C 页面。部署仍需 Codex 续验通过 + 用户对具体 commit/范围的授权。

> **2026-10-06 AC1独立验收：原Q01–Q05六反例通过；整批发布暂不通过。** [报告](AC1-REVIEW-20261006.md)：基线d58119e，366项回归（364通过、2跳过）；现网仍67c6985r2。旧库升级、B→C有效证据、长文覆盖尚有核心缺口，发布/恢复及D当前选版为同批小修。见[续验任务书](../29-ac1-followup-taskbook.md)、[提示词](../30-ac1-followup-prompt.md)。不重做迁移、不停阅读；仍须Codex验收通过及用户明确授权具体发布。下方为历史记录，不代表最新验收状态。


> **当前状态（2026-10-05 第二批）：N1–N5 已开发完成并推送（c9032a7→9fbf1ab），停在"待 Codex 独立验收（AC1）"**。见[开发报告](N12345-DEV-20261005.md)：探针 6/6 全绿、全回归 364 OK、零生产变更/零模型调用。B/C 为 fake-provider 离线闭环（真实质量待授权）；D 时间语义已实（真实应用未接入）；A 的 N5 断链修复已备但未部署。**部署需：Codex 验收通过 + 用户对该次 commit/范围的明确授权。**

> **2026-10-05 最新独立验收：部分可用，整体未完成。** [验收报告](ABCDE-ACCEPTANCE-20261005.md)：336项回归（334通过、2 skipped）；正文worker运行，服务器/Windows 523链接0断链；B/C缺执行与发布闭环，D历史背景as_of未生效。Q01–Q05按功能修复，不重做迁移/不停阅读。见[任务书](../27-abcde-acceptance-taskbook.md)和[提示词](../28-abcde-next-agent-prompt.md)。后续必须先接收Codex独立验收任务并验收通过，再取得用户明确生产部署授权；开发/self-test/push不授权部署。

以下为历史过程与提交者声明；与最新独立验收冲突时，以最新验收为准。

> **提交者历史声明（2026-10-05，已由上方独立验收修正）：A–E 交付链已上线**，详见[交付报告](ABCDE-DELIVERY-20261005.md)与[readiness log](release-readiness-log.md)。五容器运行（含新 knowledge-worker，间隔 30 分钟增量周期）；缺正文 15→4；阅读入口自动发布并已同步 Windows；228 条分析任务 blocked(model_disabled)；0 新增模型调用。下一步可选：B/C 模型启用（需用户授权 provider/范围/预算）、D 目标应用接入、7 天观察累计。

> **F0 bug fix 已完成（2026-10-04，a2407d1）**，见[docs/26](../26-bugfix-first-taskbook.md)与[readiness log](release-readiness-log.md)。V01–V04 与 CLI snapshot_root 全部修复，探针 ALL-PASS。

> **目标交付链：** [docs/25](../25-target-workflow-delivery.md)：A自动解析与阅读（已上线）→ B单篇LLM分析（管线就绪、模型关闭）→ C知识总结（同）→ D投资框架接入（API+客户端就绪、待真实应用）→ E稳态运维（ops_status/心跳已上线）。

> 2026-10-04 已补 Obsidian `解析正文/开始阅读.md`：512份已有正文及15份缺正文清单，见[阅读交付](TEXT-READING-20261004.md)。本次仅导出已有数据，未启动全文增量worker。

> **基础迁移已完成（2026-10-04）：** 旧三容器停止，新四容器运行；数据、恢复、原文、旧证据、增量三连跑和Windows同步已验证。见[迁移报告](MIGRATION-20261004.md)。第一层小时同步正常；知识自动worker/远程模型/自动候选暂未启用，fix清单后置。不要重做迁移。

> **最新独立复核及用户取舍（2026-10-04，7ded572）：基础迁移优先。** 310 tests OK/2 skip；V01–V04保留为fix清单，关闭/暂缓相应增强功能。迁移独立核验数据、恢复、同步与回滚后可推进，不等待全部增强修复或人工质量标注。见[报告](FIFTH-REVIEW-20261004.md)、[任务书](../23-fifth-review-taskbook.md)、[交接提示词](../24-fifth-review-prompt.md)。旧栈在本次检查时仍运行；以下较早结论为历史记录。

> **最新独立复核：第四轮（2026-10-03，cd3bb5d）NEEDS_CHANGES。** 301 tests OK/2 skip，但U01–U05未闭环，见[结果](FOURTH-REVIEW-20261003.md)、[任务书](../21-cutover-blockers-taskbook.md)、[提示词](../22-cutover-blockers-prompt.md)。用户条件式迁移/停机授权已获得；本次因缺陷和G2证据不足未停旧栈。GLM修改已结束，影子提取仍运行。以下完成声明为历史记录。

> **最新独立复核：第三轮（2026-10-03，源码 cb254df）NEEDS_CHANGES。** 287 tests OK / 2 skipped；T01–T07 共4 P1、3 P2待修复。先读[第三轮报告](THIRD-REVIEW-20261003.md)、[下一步任务书](../19-release-readiness-taskbook.md)与[提示词](../20-release-readiness-prompt.md)。先过G1再做小批影子验收，暂不启动全量重提取或生产切换。以下完成声明为历史记录，以最新独立验收为准。

> **最新独立复核：2026-10-03，基线 4949dcd，NEEDS_CHANGES。** 268 回归 OK（2 skipped），新增反例确认 S01–S10 尚待处理（6 P1 / 4 P2）。此前 R01–R15 全 fixed/RF7 闭环是提交者历史声明，未获本轮独立验收。先读[第二轮报告](RE-REVIEW-20261003.md)、[SR 任务书](../17-second-review-taskbook.md)及[执行提示词](../18-second-review-fix-prompt.md)。真实 NOT_RUN/BLOCKED 不变；本次未操作生产。以下历史记录保留。

更新：2026-10-01（P6 离线部分完成后，本会话收尾）。

## 当前状态

- **M0、P1-P6 离线部分全部完成并验收**，提交已推送 obsidian-sync.git：
  `0f3a19f`(M0) → `2889a12`(P1) → `1fd8d78`(P2) → `9eacef3`(P3) → `240b4dd`(P4) → `c4abc89`(P5) → P6 提交见 git log。
- 测试基线：**202 OK (1 skipped)**（113 第一层回归 + 89 知识层）。
  命令（原生 PowerShell）：`$env:PYTHONPATH="app"; python -m unittest discover -s app/tests`
- 源工程 research-kb 未改动（基线 5442e397）；ResearchVault/ResearchTools 未触碰；无生产服务启动/重启；无真实模型调用；工作树干净。

## 已完成任务（摘要，详见各报告）

| 阶段 | 交付 | 报告 |
|---|---|---|
| M0 | 49 文件复制整合+manifest+根配置合并 | m0-report.md |
| P1 | 知识库存储/不可变快照/幂等同步/抽样与测量工具（ADR0003） | p1-report.md, p1-01-interface-audit.md |
| P2 | 提取器注册表（txt/html/pdf/img）+证据块+质量路由+OCR接口+数值规范化（ADR0004） | p2-report.md |
| P3 | 混合分词 BM25 索引+generation 原子发布+/api/kb/v1+事件流+证据链接（ADR0005） | p3-report.md |
| P4 | provider 抽象（默认关闭）+RRF 混合召回+引用验证分析+用量账本+预算门禁（ADR0006） | p4-report.md |
| P5 | claim/decision 追加式历史+决策冻结+影响分析 proposal+安全写回 | p5-report.md |
| P6 | worker 周期闭环+心跳监控+在线备份/恢复演练+compose 准备+接入示例 | p6-report.md |

## 失败测试 / 已知问题

- 无失败测试。各阶段已知限制见对应报告（标准库 PDF 解析器覆盖、事件保留期未配、rerank 未实现、unsupported_numeric_claims 占位等）。

## 2026-10-04（晚）F0 迁移后 Bug Fix 完成（V01-V04+CLI，探针 ALL-PASS）

- 第五轮 V01-V04 + CLI snapshot_root 全部修复（`a2407d1`，324 tests，探针 8/8）。**生产零改动**：只读审计确认 V03 误填从未发生（生产 528 版本 basis 全 null）、V01 无孤儿预留；新四容器 healthy、旧栈停止。修复代码未部署（随下次发布上线；knowledge-api 的 working_dir 规避继续有效）。
- 下一步：docs/25 的 A 阶段（自动解析/阅读）。F0/一次性导出≠自动解析上线。

## 2026-10-04 第四轮修复完成（U01-U05，探针+服务器实测）

- 第四轮复核 → 全部修复（`6a2e57d`）：旧库迁移在**生产库副本**上实际运行业务通过；三 provider 入口统一 attempt 门禁；legacy NULL 不绑定；claim 导出幂等；影子链封闭（manifest hash/生产路径拒绝/强制禁外发——shadow2 全程 usage_events=0）。
- 310 tests OK；shadow2（seed 20261004）30/30 处理+三连跑幂等+对账 ready 28/review 2/failed 0；shadow1 保留。
- 待人工：shadow2/annotations 30 份金标准（A04/A06/A08/A09）→ NOT_RUN。全量/停机条件见 release-readiness-log。

## 2026-10-03（深夜）第三轮修复 + G1 通过 + 影子验收进行中

- 第三轮复核（T01-T07）→ 全部修复（提交 c99f159 → 552a67b）；**G1 通过**：探针 14/14、301 tests。
- N5 影子小批**已在服务器隔离目录运行**（shadow/state，独立库+快照；快照 61 done 0 failed；提取进行中，OCR 密集约 27s/页）。完成后按 tools/shadow-acceptance/SHADOW-RUNBOOK.md：对账→幂等重跑→人工标注→measure。
- N6 全量 dry-run（只读）完成：新 recipe 需重提取 524 份（14,751 页 / OCR 2,792 页），旧产物全保留；**未启动全量**（待授权）。
- 全量/生产切换前置：影子人工标注（A04/A06/A08/A09 金标准）+ 用户明确授权。

## 2026-10-03（晚）第二轮评审修复完成（S01-S10 全部 fixed，待复验）

- 二轮复核（RE-REVIEW-20261003，基线 4949dcd，NEEDS_CHANGES，S01-S10）→ 全部修复。RED/GREEN 矩阵与隔离启动验收见 `second-remediation-log.md`；提交 01c02d7 → a7640fd → e369d32。
- 最终回归：**287 tests OK (2 skipped)**（二轮基线 268 + 19）。
- 隔离启动验收（S09）：服务器 /tmp 独立目录中 library 显式 serve（/healthz ok，100 文档）、knowledge API（/api/kb/v1/health ok）、worker 一次性闭环（90 版本→86 快照→索引发布）全部实测；生产栈与回填未动。
- 复验入口：以 ≥ e369d32 重跑 re-review-probe-20261003.py + test_second_review*。
- 待用户决定：第四轮全量重提取（采用修复后身份逻辑）；生产切换（CUTOVER）。

## 2026-10-03 独立评审修复完成（R01-R15 全部 fixed，待复验）

- 独立评审（基线 534014a，NEEDS_CHANGES，15 组问题）见 `INDEPENDENT-REVIEW-20261002.md`；修复任务书 `docs/15`。
- RF0-RF6 完成：预算账本/角色装配/快照校验/配置身份/PDF 页序引擎/HTML 偏移/选版 as_of/索引恢复/混合先过滤/固定 URL 快照服务/分页/写回唯一性/影响 outbox/部署可执行/恢复严格化。逐项 RED/GREEN 证据在 `remediation-log.md`，提交 4b90a75 → 6ffb0d6。
- 最终回归：**268 tests OK (2 skipped)**（基线 222 + 46 修复回归）。
- 服务器：两份 compose `docker compose config` 通过；knowledge 镜像 build + 容器内 pypdfium2/RapidOCR/模块冒烟通过；OCR v3 回填未停仍在跑（旧代码进程，完成后重启 worker 采用新逻辑）。
- 真实切换前置：评审方复验 R01-R15 + OCR 回填完成 + 用户明确确认旧栈下线（CUTOVER.md 已可执行）。

## 2026-10-02 真实数据阶段开启（用户已授权）

- **SSH 授权**：`chen@192.168.1.150`（密钥认证可用）；新工程目录 `/vol2/1000/10.Develop/obsidian-sync/`（与 research-kb 同级）已建立：`repo/`（代码，git archive 上传）、`config-knowledge.json`/`config-library.json`（主机路径版）、`state/`（2.2G）。
- **真实源路径**（来自旧工程 RUNBOOK）：reports `/vol2/1000/10.Develop/reports-fetcher/reports`；discord `/vol2/1000/10.Develop/discord_export`；现网 catalog 只读消费。
- **已执行（写入仅限新目录，未触碰任何现有容器/数据）**：
  1. 首次真实 sync：538 文档/528 版本镜像，524 快照任务（4 非 ready 如实跳过）——与旧工程验收记录一致（A01 对账通过）。
  2. 代表性样本 30 份全通过 → 影子全量回填：524/524 快照（18.5s）、提取（97s）、索引 104,723 块/140 万词项/14.3M 字符。
  3. 真实检索验证：两字中文词、英文、代码均可检索。
  4. **真实质量基线**：discord ready 1/review 315/failed 122；reports ready 32/review 43/failed 11；122 份纯扫描件（23%）、19% 页面需 OCR（2792/14751）、220 份 CID 字体（标准库解析器不支持，待 PyMuPDF 级解析器）、343 份 control_characters 标记。
  5. 分层 30 样本测量：23 份测得正文（启发式约 48.3 万 token，全库外推约 8.4M，仅数量级参考），7 份待 OCR。
- **待用户决定/授权**：① 模型配置填写（完整模板 `config/knowledge.example.json`，服务器实际配置只改 FILL-ME 项：base_url/api_key/model，egress_allowed 默认 false）；② OCR 路线已实现开关（`ocr.engine`: local/vision-api/off，默认 local=RapidOCR/PP-OCR）；③ **research-kb 旧容器编排下线需用户明确确认**（已记录为待确认事项，本工程完成全部验收前不动）；④ Vault 写回已授权（待登记生成目录后启用）。
- **2026-10-02 OCR 路线落地（本地引擎默认）**：`ocr.engine` 开关（local/vision-api/off）实现并测试（211 测试 OK）；服务器 venv 装入 rapidocr-onnxruntime + pypdfium2（清华镜像，PEP668 系统禁用 --user 后改 venv）。
- **真实 OCR 冒烟（纯扫描件 discord/1527272124073382069_0，6 页）**：3 页 / 80.5s（约 27s/页），置信度 0.96-0.98，中英混排质量好，质量检查 ready。全量估算：2792 页 ≈ 21 小时 CPU。
- **后台 OCR 回填已启动**（nohup，只写新目录，任务粒度可中断续跑）：日志 `/vol2/1000/10.Develop/obsidian-sync/state/ocr-backfill.log`，查看 `ssh chen@192.168.1.150 'pgrep -f run-extracts'`，停止 `pkill -f "knowledge run-extracts"`。EXTRACT_CONFIG 升 v2 → 全部 524 份产生新提取行（旧行保留，历史证据不变）。
- 完整配置模板：`config/knowledge.example.json`（全部默认值已填，仅 base_url/api_key/model 为 FILL-ME）；服务器实际配置已重写为同样形式。FILL-ME 未填时该 provider 自动视为关闭，不报错。
- **2026-10-02 真实 provider 接入与首次真实分析**：OpenAI 兼容适配器（chat/embedding/vision，urllib）+ 协议测试（218 OK）。
  - chat=GLM-5.3 打通：精确用量可得（含 reasoning_tokens 细分，印证 docs/09 推理计费提醒；小 max_tokens 会被 reasoning 耗尽导致空正文）。
  - embedding 报 429 丙码113 余额不足：coding 套餐端点无 embedding 资源包→ 混合检索保持 keyword 模式（422 按设计），需用户充值/换资源后开启。
  - vision_ocr 已配置 GLM-5.3-Flash 但 egress_allowed=false → 按门禁拒绝测试；待用户翻开开关后验证其图片输入支持。
  - **首次真实分析（A17 首个真实数据点）**：查询毛利率观点，6 个真实证据块→ GLM-5.3 引用全部有效；证据仅为笔记标题清单时模型诚实回答 unknown 拒绝编造（docs/05 要求的行为）；真实用量：输入 26,602 + 输出 852 tokens，已入 usage_events 账本。
- 后台 OCR 回填进度：extract v2 任务 done 568 / pending 479（总 1048，含旧一代），零失败；v2 提取行 44（OCR 慢速段）。
- **2026-10-02 晚：三模型实测与 Vault 写回打通**：
  - vision（GLM-5.3-Flash，egress 已开）：**确认支持图片输入**。真实扫描页对比：flash 21.4s/页、拼写与空格明显更好（本地 "Commodies/Sel-ff" 类错误），成本约 7.5K tokens/页；本地 RapidOCR 56.4s（同时背负 OCR 回填 CPU 竞争，中文两者相当）。结论：批量走本地，疑难页/图表用 flash 复核仍是合理路线（fallback 混合路由待实现）。
  - embedding（opencode.ai zen + deepseek/deepseek-v4.1-flash）：`/embeddings` 返回 **HTTP 403 error 1010**（网关拒绝该端点/模型不可 embedding）—— 需用户确认网关支持的 embedding 模型名或换回智谱 embedding-3；混合检索继续 keyword 模式（按设计 422）。
  - **分析产物 Vault 写回已打通**（零 Syncthing 配置变更）：`export-analysis` CLI → 服务器 `research-kb/vault/自动研究候选/`（新增生成子区，旧渲染器不碰）→ 现有 Syncthing 文件夹对 → Windows `ResearchVault/自动研究候选/` （实测 30 秒内到达，含引用验证与证据链接）。写回带哈希门禁：人工编辑后不被覆盖。注：文件以只读属性同步，标注请复制或改属性，哈希门禁保护两者。
- **2026-10-02 深夜：fallback OCR + 全栈编排 + embedding 关闭**：
  - `ocr.fallback=vision-api` 实现并上线（EXTRACT_CONFIG v3）：本地页置信度 < fallback_min_confidence(0.6) 或空文本时才升级问 flash（每页记录双置信度）；回退失败不伤主流程。后台 v3 全量回填已重启（446 个被取代的 v2 pending 任务已标记 superseded）；至今 fallback 触发 0 次（本地置信度普遍 0.96+）。
  - embedding egress 已改 false（用户决定后续再开）；chat/vision 不变。
  - **`deploy/docker-compose.full.yml`：全栈切换目标编排**（library+syncthing+status-collector+knowledge-worker+knowledge-api，容器名 obsidian-sync-*，资源限制+健康检查，catalog 只读挂载）；**`deploy/CUTOVER.md`：切换手册**——回答“为何现在还写旧目录”（旧栈仍在服役，过渡期搭便车）；切换时迁移 Syncthing 设备身份+文件夹 ID → **Windows 端零改动**；回滚=启动旧栈；旧目录清理是另一次单独授权。旧栈下线仍需用户明确确认 + 真实验收完成。
  - 测试基线 **222 OK**（+3 fallback 路由/门禁）。
- 修复：CLI rebuild-index 分发 bug（真机首跑发现，已修+回归测试，203 测试 OK，提交 f7f0e45）。

## 剩余工作 = 外部条件依赖（合并缺项清单）

1. ~~真实源访问~~ 已解决（2026-10-02）；后续：真实 tokenizer 接入（A05 精确计数）、A10 真实 50 查询基准、A04 人工标注。
2. **生产部署**（compose 已备 `deploy/docker-compose.knowledge.yml`）：A21 性能与 7 天记录、A22 真实恢复演练；旧 research-kb 容器下线待明确确认。
3. **模型供应商+凭据方式+外发范围+预算**：P4 真实适配器（providers.py 预留 + providers.example.json 模板）、A16 成本、A17 分析评测、真实 tokenizer。
4. **OCR 引擎选型**：真实需求数据已测得（122 全扫描件/19% 页面）；本地引擎 vs 多模态 LLM 待用户定。
5. **真实 Vault 写回**：已授权；待在 ResearchVault 登记 `自动研究候选/` 等生成目录后启用（P5-03）。

## 准确续跑起点

- 读本文件 → docs/progress/task-status.md（状态表）→ 对应阶段报告的「BLOCKED/已知限制」节。
- 任何新会话先跑全量测试确认基线，再从上述缺项中已具备的条件切入；无需重做 M0-P6 离线部分。
- 约束提醒：不修改源工程/原始归档；不 force-push；不猜凭据；OCR/LLM 独立 worker；`/api/v1` 行为保持；人工笔记零覆盖。

## 会话执行说明

本会话为普通交互会话，无自动唤醒能力：会话结束后不会后台继续。所有已声明完成的工作均已在本会话内执行、测试并推送；未执行事项均如实标注 NOT_RUN/BLOCKED，无虚构。

## 独立评审接续（2026-10-02）

基线534014a已复核：整体NEEDS_CHANGES。未改业务代码或生产服务；下一执行从docs/15-review-remediation-taskbook.md的RF0开始，提示词在docs/16-review-fix-prompt.md。15组问题及合成证据见INDEPENDENT-REVIEW-20261002.md/review-evidence.json。当前不应执行CUTOVER；源迁移无需重做。原真实验收缺项继续保留，源码修复有独立可执行任务。
