# P3 验收报告：全文检索、查询 API、影子回填与证据链接

日期：2026-10-01。执行：main-agent（self-reviewed）。完成度：**源码实现 + 离线（合成）验证**；生产全量回填与真实性能 NOT_RUN/BLOCKED。

## 交付内容

### P3-01 词法索引与检索（`indexing.py`）

- 混合分词：ASCII 词（字母数字+`. _ % + -`，覆盖 `600519`/`10-Q`/`AAPL`）+ CJK 单字与二字 bigram（**两字词如「毛利」可检索**，一字词回退）。
- 倒排索引（index_postings/index_doc_terms）按 generation 不可变存储；BM25（k1/b 版本化常量）查询期打分，含块长度归一化。
- 过滤：source/symbol/doc_type/日期区间/**as_of 双模式**（system=first_seen_at、public=报告/公告日期；A11 语义）。
- 查询上限 2000 字符；词去重保序。

### P3-02 /api/kb/v1（`kbapi.py`，ADR0005）

独立端口标准库服务（`python -m knowledge serve-kb`）。实现 docs/04 全部路由：health/ready、POST search、documents、document versions、evidence（契约校验+前后文）、extraction blocks（游标分页）、changes（sequence 游标）、analysis-runs（默认 422 task_disabled）。

- 鉴权：Bearer + scope（research.read/analysis.run）；401/403/404/409/422/503 错误结构含 code/message/request_id/retryable。
- 游标绑定查询摘要+generation：跨 generation 或跨查询 → 409 cursor_expired。
- hit 结构对齐 contracts/examples/search-response.json（含 evidence_url/source_version_url/score_kind/snippet）。
- 事件：kb_events（sequence 单调、event_id 内容寻址幂等）；sync 发 document.discovered/version.registered，提取发 extraction.completed，索引发布发 index.published。

### P3-03 影子回填与原子发布（`indexing.build_generation`）

- 影子构建：posting 写入 building generation → 计数核验（blocks 与 extraction 数一致，否则失败保留旧 active）→ 单事务切换 active 指针 → 旧代 retired。
- manifest_hash 相同 → no-op；强制重建 `--force`。CLI `rebuild-index`。
- **BLOCKED（生产）**：523 基线全量对账（A14）需真实源+服务器；工具与流程就绪，未在生产执行。

### P3-04 证据链接（`cards.py`）

- `evidence_links_for_document`：按当前版本最新提取输出块级证据链接清单（block_id/locator/quality/evidence_url），CLI `evidence-links`；Markdown 片段渲染（页码/DOM 路径/质量状态）。
- **不写 Vault**：输出到 knowledge 自有目录或 API 载荷，第一层 markdown 渲染器零改动（A15 人工区保护）；真实 Vault 写回授权留待 P5/P6。

## 验收场景对照（离线/合成）

| 场景 | 结果 |
|---|---|
| A10 搜索效果 | 合成通过（相关性排序正确）；**真实 50 查询 Recall 基准 NOT_RUN**（无真实语料） |
| A11 短词与时间 | PASS（合成）：两字中文词/代码/数字/中英混排可检索；as_of 双模式过滤正确（system 早于 first_seen 不返回） |
| A12 API 与分页 | PASS（合成）：权限先行（401/403）；游标跨查询/跨 generation 409；limit/错误结构/422 符合契约 |
| A13 访问控制 | PASS（合成）：无 token 401、错 token 403、无 scope 403；日志无凭据。**跨集合/个人笔记**：当前仅 source_documents 集合，个人笔记默认关闭且未实现集合 → 403 路径已测 |
| A14 全量对账 | 工具就绪；**生产 BLOCKED**（需服务器与真实 523 基线） |
| A15 人工区 | PASS：本阶段零 Vault 写入；卡片链接为 knowledge 侧产物 |
| A02 幂等（索引） | PASS：manifest 未变重建 no-op；generation 切换原子；事件 event_id 幂等 |

## 测试

**171 OK (1 skipped)** = 113 第一层 + 21 P1 + 19 P2 + 18 P3。HTTP 层真实 socket 测试（临时端口）覆盖鉴权/搜索/错误结构/changes。

## 已知限制

1. BM25 为内存打分（数百文档规模足够）；A21 真实性能（P95/并发5）NOT_RUN，待生产部署。
2. snippet 的字符偏移在块内坐标系；跨块定位依赖 locator（页码/DOM 路径）。
3. 事件保留策略（retention）未实现自动清理（配置化保留期属 P6 运维项）；sequence 游标语义已实现。
4. 生产部署（端口暴露、TLS/反代）按 docs/04 要求另行配置，默认仅绑定回环。
