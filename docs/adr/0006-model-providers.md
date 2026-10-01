# ADR 0006：模型 provider 抽象、默认关闭与用量账本

状态：已接受，2026-10-01（P4 实现）。

## 决定

1. **Provider 接口而非具体集成**：`providers.py` 定义 `EmbeddingProvider`（embed → 向量 + 用量）与 `ChatProvider`（complete → 文本 + 用量）两个协议；真实供应商适配器在用户提供供应商、凭据使用方式、外发范围与预算前**不实现、不注册**。配置里出现 provider 名但无凭据 → `ProviderNotConfigured`（运行期 422/503，不静默降级为真实调用）。
2. **默认关闭**：knowledge 配置无 `providers` 段时，hybrid 检索与分析任务保持 P3 的 422 行为。工程 agent 订阅不等于 API 账户授权（docs/13 V4）。
3. **Mock 只验协议**：`MockEmbedder`（确定性哈希向量）与 `ScriptedChat`（脚本化回复）仅供测试协议、状态机、引用验证与预算门禁；不用于宣称质量或成本（A16/A17 真实部分 BLOCKED）。
4. **用量账本**：`usage_events` 表逐调用记录 provider/model/kind、input/output token、成本口径（cost_basis 字符串：provider 计费类别）、关联 run/阶段与时间；预算门禁按账本累计值判断，超限拒绝新任务（A18）。
5. **混合召回**：关键词与向量并行召回 → RRF（k=60）融合，可选 rerank 接口留空；向量按 (model, block_id) 缓存于 `block_embeddings`，embedding 属可重算派生数据，缓存失效由 model 名变更自然实现。

## 代价

接口层间接性；真实供应商接入时需补适配器 + tokenizer 计数 + 价格表（P4-01 真实部分），存储已就绪。
