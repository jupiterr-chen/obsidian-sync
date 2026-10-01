# 主仓库整合任务书（项目起点）

## 用户决定与当前状态

唯一后续主仓库为 `git@github.com:jupiterr-chen/obsidian-sync.git`，本地工程 `D:\2.Develop\8.Obsidian\obsidian-sync`。现有 `D:\2.Develop\7.zcode\discord-export\research-kb` 的可发布实现纳入主仓库，作为已完成第一层的代码基础。原库 `research-kb.git` 不再承载本任务新增开发。

当前交付只有整合计划、任务链、提示词和验收规则；**旧代码尚未复制到主仓库，生产部署未改变**。下一执行agent从M0开始，不能把现有设计骨架当成服务实现。

源工程检查基线：2026-10-01，HEAD `5442e397b3b1276af6ae18403bf2e51103ad6249`，52个Git跟踪文件，检查时工作树干净。执行时重新获取实际状态及HEAD，保留所有后续用户修改。

## “移动过来”的实施方式

采用复制、验证、切换后续开发归属。保留源目录及原仓库，不删除、不递归移动、不改权限、不改源工程remote。用户当前指示没有列出用于递归移动批准的准确路径和操作，所以不视为满足机器安全规则的递归移动许可。复制可在明确范围内自动完成，原目录退役清理由用户以后单独决定。

## M0 导入范围

以源工程 `git ls-files` 为候选，不直接复制整个目录。允许 app/、公开scripts/、公开config样例、Dockerfile、docker-compose.yml、.dockerignore、.gitattributes及公开docs。不得导入.git、.env、实际config、凭据、运行数据、Vault、opencode权限配置、私有部署证据、缓存或安装包。

源README转为 `docs/legacy/README.md`；源公开docs转为 `docs/legacy/`，保留相对结构并修正指向脚本/config的链接。根README维护当前项目导航，不被旧README覆盖。源.gitignore/.dockerignore/.gitattributes审阅后合并其规则；根AGENTS保留当前授权，不复制源“禁止commit/push”或指定OpenCode的旧任务约束。记录被排除的文件类别，不输出凭据内容。

目标代码采用 `app/library/` 作为现有服务位置、`app/tests/`保留回归测试。新功能原则上放 `app/knowledge/`，共享接口只能通过明确适配层。`src/research_kb/`当前仅职责说明目录，保留并标明参考；不建立第二套同功能服务，不靠空stub宣称功能完成。

同名文件不得盲覆盖：先比较hash，内容一致可跳过；冲突由执行agent读公开内容后合并，无法判断才报告具体冲突。导入后为每个公开源文件保存来源commit、源/目标路径和sha256的manifest，manifest不得含机器凭据或运行源数据。

## M0退出标准

- 来源manifest、可发布范围、排除类别和路径冲突全部记录。
- 源工程全套测试在目标工程通过，测试命令使用原生PowerShell设置PYTHONPATH=app，再运行python unittest discover。
- 导入后的app代码与源基线hash一致（明确必要适配另列），没有意外运行数据或新依赖。
- 源工程工作树、现有Vault和ResearchTools保持原状态；未触发生产启动/重启/调度。
- 所有文档链接、JSON/schema和staged diff检查通过；说明旧文档仅描述第一阶段历史，不替代新总体计划。
- 完成M0验收报告与独立复核，提交到主仓库。推送仅限该仓库，禁止force-push。

## 复用边界与已知差异

现有library使用标准库HTTP/Python与SQLite，已有Catalog、Ingestor、Scheduler、FileLock和changes。新功能不以替换FastAPI或数据库为第一任务；先保留行为，再确定新增API如何托管。技术变动必须ADR说明收益与回归成本。

现有changes包括 imported、metadata_updated、new_version、current_changed、became_unavailable、recovered、content_conflict、ledger_baseline。可作为增量任务发现依据，但不能假定现有账本已经具备完整外部消费接口/无限事件保留；每日版本对账作为补偿。

现有原文版本在上游字节被覆盖后会失败关闭。第二阶段应增加经过同文件描述符hash验证的不可变快照，不能将上游可能变化的路径当永久证据存储。现有可用版本先复制并核验；已丢失历史只能标记，不伪造恢复。

新正文任务以(source,doc_id,version_id,stage,config_digest)幂等。新正文状态和索引独立存储，避免未经审核的大型迁移损伤现有catalog。接口保留/api/v1行为，新增/api/kb/v1；是否同HTTP进程由P3 ADR决定。OCR/LLM放独立worker，避免阻塞原文访问和小时调度。

## 整体执行顺序

M0整合 -> P1版本/样本/测量 -> P2正文/OCR -> P3全文/API/全量 -> P4语义/分析 -> P5记忆 -> P6生产稳态。

详细阶段任务沿用07文档；12文档给出具体启动、完成和转阶段规则。遇到无法获取服务器、模型账户或价格时，继续离线实现、合成测试和部署准备，生产相关项保持BLOCKED/NOT_RUN，不虚构已完成。
