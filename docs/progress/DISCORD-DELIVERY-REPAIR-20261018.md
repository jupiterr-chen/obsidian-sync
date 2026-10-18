# Discord新增资料交付修复 — 2026-10-18

用户本轮明确要求排查慢索引、修复PNG，并确保昨天新增资料解析正文发布及同步。这是本次限定修复和生产worker替换的授权；取代旧只读监督职责对本次操作的限制。未恢复定时监控，不使用OpenCode或其他执行agent，不调用真实业务模型。

## 范围和初始事实

按北京时间2026-10-17的上游first_seen_at冻结23项：22 PDF、1 PNG。23张卡片已同步Windows，23份原文HEAD通过；22 PDF已有ready提取，共383页、16页本地OCR，但本批在active索引中0块、服务器正文0份。

PNG doc_id为`1559852470337806398_0`，源文件184504字节，索引和持久版本记录误写125650字节，实际SHA与声明SHA一致；snapshot因SourceConflict失败，extract因missing snapshot失败。

私有检查证据：`runtime/readonly-acceptance-watch/discord-20261018/`。生产恢复与变更日志：服务器`operations/discord-delivery-repair-20261018/`。

## 已定位原因

1. 正文发布在worker的`build_generation`之后。索引未完成，已完成的提取没有进入发布outbox，用户只能看到资料卡片。
2. 当前索引一次物化全库词项，原`write_postings`又建立一份带generation_id的大列表。现有active约108227块、7274643条postings，不能按新增23份的大小估算其开销。
3. worker内存1GiB、交换上限1GiB都接近用满；实测进程约1GiB RSS和1GiB swap，cgroup memory.max命中约91.8万次。宿主机还有约9GiB可用，瓶颈包含容器限制。
4. 原写入按文档顺序随机更新以generation/term/block为键的B-tree，SQLite连接默认约2MiB缓存；实际读写放大到数百GB。扩内存只能缓解换页，不能改变原进程正在执行的写入顺序。
5. 旧I/O错误日志来自10月13日，累计restart_count=14不能作为这批新故障的精确时间线；未据此声称本轮磁盘满或OOM。检查时磁盘约344GB可用。

## 限定修复

- 先在线把准确worker实例调至4GiB内存/总内存加交换5GiB，保留进程验证；确认旧无序写入仍缓慢后，准备并验收worker镜像更新。
- `KnowledgeStore.write_postings`使用稳定排序按B-tree键写入；用生成器传参，取消第二份大posting元组列表；仅本次连接的写入阶段临时用128MiB缓存，成功或异常都恢复原值。选择策略、分词、原文、投影、验证和索引原子激活规则不变。
- 4项内存数据库回归覆盖：多语言无序输入/统计及输入不变、重复键最后值语义、失败时两表回滚及缓存恢复、空generation。生产候选镜像同样4项通过，无生产挂载或网络。
- PNG源文件及其SHA完全保留；备份上游索引和catalog，精确修正一个file_size及该版本catalog字节元数据。确认该PNG尚无snapshot/extraction后，再在共享写锁下修正knowledge版本字节数并重新排队两个准确失败job。保留原错误记录和变更前行，恢复尝试不清零历史attempts。
- worker使用同一6679872基础镜像，仅替换store.py及其回归测试，4GiB限制通过独立compose覆盖持久化。仅替换knowledge-worker，Library/API/Syncthing保持准确身份和镜像；旧有效索引在新generation完整验证后才切换。
- 原等待监督器已明确被本次优化worker替代；不能重启它或重复执行finish_batch脚本。正常worker负责同一轮PNG恢复、索引与正文发布。

## 恢复入口与验收

先读服务器`worker-rollout.json`，不要重复执行rollout。镜像信息`image-ready.json`；精确数据范围`target-versions.json`；PNG修改前后记录和catalog备份均在同一operation。旧有效索引身份见`active-index-before-worker-replacement.json`，回退应保护后续新写入，不能用旧DB覆盖现库。

必须验证23份提取、两个PNG job完成、383个PDF原块加PNG块进入active、23个正文及阅读入口生成、原文/资产API可达、Windows按服务器最新文件bytes/SHA匹配；另核服务身份/健康和新worker完成一轮。不能以API ready或旧last_ok代替本批数据验证。

## 最终验收（北京时间2026-10-18 12:20）

**本批23/23资料解析、检索、正文发布与Windows文件同步通过。**

| 检查 | 实际结果 |
| --- | --- |
| 来源与版本 | 23项源文件SHA及大小均与修正后的索引一致，23个原文HEAD返回200；原来22份PDF的提取身份全部保留 |
| 解析 | 23项提取ready；PNG snapshot/extract两个job均done，attempts=2，使用本地rapidocr-ppocr；没有新增业务模型请求 |
| 索引 | 384/384块进入新active generation `gen-eb50c9ebf47dc1a5907047d6` |
| 索引时间 | 新generation创建12:11:04、激活12:18:04，用时7分钟；旧无序写入构建约94分钟仍未完成后中断，不能声称旧构建最终用时 |
| 正文与入口 | 23/23正文生成、23/23发布outbox consumed，全部由开始阅读.md链接到准确提取文件 |
| 真实API | 23篇证据正文与DB一致；23篇各用关键词验证命中对应文档/提取；首轮22篇命中，另1篇换用稀有词后命中，首轮结果及补验均保留，不把单次前100排名当漏收 |
| Windows | 23篇正文+23张卡片+3个阅读入口/状态文件，共49/49 bytes/SHA一致，missing/mismatch均0 |
| 服务 | 新worker整轮成功、idle，最后完成12:18:22，重启计数0、无OOM；Library/API/Syncthing准确ID和镜像均保持、健康正常 |
| 回归 | 本地4项与禁网候选镜像4项均通过；两份compose YAML解析/worker内存配置检查通过 |

独立核验文件：本地`runtime/readonly-acceptance-watch/discord-20261018/delivery-verified.json`；同名元数据已留在服务器operation。其他原始证据包括final-server-verification.json、final-windows-verification.json、final-source-and-files.json及keyword-probe-followup.json。未实测Obsidian UI渲染；文件可读性及内容hash已经实际核对。

生产worker：`c2e86fa2ba196b346c28fbac1ba60146af2b2ecf3eb5b9aa7189fc257d87eed3`；镜像`obsidian-sync:discord-index-20261018-dcc61fc8`（ID `sha256:b5fc6d3c483f261511f7f5d280f2c2bb544048ac28315a1f66228a4fa15f229b`）。实际compose由旧基线加operation中的`worker-resources.override.json`组成；后续发布须保留本次代码与4GiB/总5GiB资源配置，仓库两份compose默认值已更新并允许显式环境覆盖。

本次操作不构成全库图表治理结案，也没有恢复已暂停的Codex定时器。原等待监督器为superseded，旧finish_batch.py未执行，禁止重启。

## 后续改进（不扩大本轮）

全量物化和全量重建仍会随库增长增加成本；真正的分批构建/增量索引及正文发布与检索解耦另列后续任务，不以此延后本批交付。不清理历史索引/备份或递归删除任何目录来换取进度。
