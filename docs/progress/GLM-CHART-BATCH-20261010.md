# GLM 图表批处理执行记录（2026-10-10）

## 当前状态

北京时间 14:03：B1/B2 工具完成，Luna 离线 5 项测试由 Codex 复跑通过；Codex 另 6 项独立反例通过，准备固定源码并运行只读冻结和真实试点。尚未启动本批真实 GLM 请求。用户已确认本方案，明确 GLM 额度充足；任务边界见 [任务书](../43-glm-chart-batch-taskbook.md) 和 AGENTS.md 首部。

服务器已建立独立 operation：`/vol2/1000/10.Develop/obsidian-sync/operations/glm-chart-batch-20261010/`。目前只有 `preparation.json` 与 `audit-input.json`，前者保存授权范围、输入 hash、固定模型/接口和阶段；后者复制已完成的只读盘点。没有改生产数据库、Vault、配置或常驻服务。

## 输入与执行边界

- 盘点时刻 2026-10-10 13:14，862 候选块、159 文档版本。209 原生、457 OCR、196 unknown；unknown 中有 1 个图片。候选不等于错误。
- 先核对当前有效 extraction、已有投影 head、原文和快照 hash，再冻结输入；变化项单独列原因，不偷偷替换或静默消失。
- 试点 30 项，三种来源各 10 项，尽量分散文档并纳入图片。两轮独立观察，仅返回区域类别/bbox/疑点。模型共识仍是 proposal。
- 固定既有 GLM-5.3-Flash 与 `https://open.bigmodel.cn/api/anthropic/v1/messages`，4 路并发。已只读证实现有配置的 model/endpoint 匹配且 api_key 存在，没有输出或复制凭据。
- 新工具使用已部署镜像的依赖，候选源码单独只读挂载；生产 state/snapshots 只读，无 Vault 写入。不得启动新常驻 worker 或重启旧 OCR。
- 已 dispatch 无结果的请求进入未知队列，不自动重复发送；只有验收通过后继续相同冻结范围。

## 验收与未完成

Luna 负责新的 `chart_batch.py`、独立 CLI 和 fake transport 测试。Codex 负责独立反例、固定源码、30 页真实结果和原图复核。独立 6 项已验证：旧正文 hash、过期版本、已有 head 拦截；调用前外发门禁；完整 run 的只读连接与重启缓存；并发重复页仅发一次物理请求。源码审查还核对固定 endpoint/model、禁代理和重定向、两轮输入独立、JSON 坐标校验、无 activate/生产写入。当前尚无本批真实分类质量结论，不以离线通过替代视觉验收。

后续仍需原生字符精确映射、OCR 区域定位例外处理、确认投影、按批索引/发布与 Windows 验证。既有小批的 8 页/26 图像已上线，不代表 862 候选全部治理完成；真实表格和正文必须保留。保护 docs/37 用户修改和所有源证据。
