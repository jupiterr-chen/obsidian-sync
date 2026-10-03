# 第二轮修复任务书（S01–S10）

状态：待执行；基线 `4949dcd`；当前整体 NEEDS_CHANGES。以[第二轮独立复核](progress/RE-REVIEW-20261003.md)覆盖此前 R01–R15 “全部 fixed/RF7 闭环”声明，历史日志保留。完整证据见[JSON](progress/re-review-evidence-20261003.json)和[可重跑探针](progress/re-review-probe-20261003.py)。

## 工作范围

只在主仓库实现、测试、记录、提交及正常推送；保护现有工作树、旧 research-kb、源归档、Vault 与 ResearchTools。无须重新迁移 M0 或改造整个 library。禁止真实模型外发/计费、停旧栈、停止当前 OCR、生产切换、真实 Vault 写回、force push。递归删除/移动必须另有当前会话准确路径批准；本任务不需要这些操作。

## 任务链与交付

执行顺序：`SR0 -> SR1 -> SR2 -> SR3 -> SR4 -> SR5 -> SR6`。同一 store/schema 变更串行集成。可以独立完成的工作持续推进，真实环境缺项集中记录，不反复询问是否继续。

|任务|责任范围/问题|交付与明确验收|
|---|---|---|
|SR0 基线|Git、探针、台账|记录 HEAD/dirty、268 测试基线；将 S01–S10 转为断言式回归并先 RED；区分语义断言失败与依赖缺失。探针历史输出不修改成“成功证据”。|
|SR1 原子事务|budget/store/providers/analysis/ocr：S01；sync/store/worker/memory：S07|检查+预留同 DB 写事务；结算状态+usage 同事务，唯一 reservation 关联和幂等结算；记录页预留。两个独立连接/进程竞争 cap10 各6只能一个成功；cap1不能第二页；在每个提交边界中断，不遗失消费或重复记账。覆盖发出后超时/缺usage/格式错误/重试。版本与 outbox 原子写，迁移补漏；生产者、消费者、ack 边界中断后全部预期候选最终生成且不重复。|
|SR2 原文与提取|snapshot/kbapi：S04；extract/jobs/quality：S05、S06|返回字节与校验字节一致；返回前改写/替换/截断 blob 要么拒绝要么给正确原字节。低置信度、空 OCR、回退失败、预算拒绝逐页降级并传递到块和文档。图片同身份连续/重启重跑零额外 OCR；修改有效引擎/模型/阈值产生新身份；并发任务不能双重计费。|
|SR3 写回|writeback/config/CLI：S02|成果采用唯一追加、禁止覆盖人工可编辑路径；latest 仅机器元数据。最后检查后模拟编辑、首次创建竞态、同秒/多进程写、Syncthing 冲突均保留人工内容；历史文件不迁移、不清理。任务完成不代表获准真实 Vault 写回。|
|SR4 时间与检索|indexing/kbapi/store/analysis/contracts/ADR：S03、S08、S10|版本级 public 时间有依据，报告期末不得冒充公开时间；6/30报告8/20发布的7/1查询必须排除。区分当前内容过滤与历史全文模式，不支持的语义显式说明；覆盖v1/v2不同公开/接入时间。元数据变更后游标409或稳定一致结果，实时撤权始终生效。词法/向量独立从允许集合召回再融合；同名模型跨provider/维度缓存不复用；仅用mock验证。|
|SR5 部署|Dockerfile/compose/CUTOVER/config/deploy README：S09|library 显式启动正确 serve 命令；依赖安装/OCR预热失败使构建失败；每服务最终配置和路径可解析；容器写回用容器挂载路径。隔离目录启动并 GET library 与知识 API 健康端点、查看 worker 心跳；从任意 cwd 执行非生产切换演练。若无 Docker，记录 NOT_RUN，不能以 YAML 解析替代容器验收。|
|SR6 独立复验|测试、文档、报告|S01–S10 逐项 RED→GREEN、提交 SHA、实际命令/输出和剩余风险；全回归通过；审查所有对外返回字节/外发/写回/事务边界。同步 README、REVIEW-GUIDE、task-status、HANDOFF，保持历史报告。无未解决 P1，且真实验收满足后，才讨论生产切换。|

## 测试与恢复规则

1. 优先用 barrier、故障注入、受控 provider 和文件替换复现确定性交错，避免靠 sleep 概率测试。独立连接竞争比只测同一 Python 对象更接近 worker 运行。
2. 先让测试在当前基线因目标断言失败，再做最小修复。禁止只修测试、降低门槛、将 unknown 当 0、将低质量当 ready 或用 ADR 静默删验收需求。
3. 未知历史公开时间和接入时间保留 unknown，不倒填。数据库迁移非破坏、可恢复；已有证据身份不原位改写。
4. 每阶段落盘检查点与完整提交，20–30 分钟以上任务另存中间恢复点。单项报告包含触发条件、修复机制、回归、commit、未运行内容。持续简短反馈，不依赖用户催促。
5. 真实盲测、性能、7 天运行、生产备份恢复保留原 NOT_RUN/BLOCKED。实现修复和真实验收分别签收。

## 最终交付格式

新增 `docs/progress/second-remediation-log.md`：S 编号、原 R 编号、状态、RED 命令和失败断言、GREEN 结果、源码提交、独立复验、真实缺项。最终只汇报未解决问题、实际验证、提交和下一步；不要用“所有测试通过”推导“可以生产切换”。
