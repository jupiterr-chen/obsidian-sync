# 迁移后的下一阶段提示词

> **请先执行[docs/26中的F0提示词](26-bugfix-first-taskbook.md)。** F0完成后才使用下列A阶段提示词；不能跳过已排在首位的bug fix。

基础迁移已经完成，不需要再向其他agent下发迁移任务。本提示词留给后续“仅新增全文处理”阶段。

```text
在 D:\2.Develop\8.Obsidian\obsidian-sync 工作，先读 AGENTS.md、docs/progress/MIGRATION-20261004.md 和 docs/23-fifth-review-taskbook.md。

M1–M6基础迁移已完成：新四服务运行，旧三容器已停止，Windows同步正常。不要再次迁移、重新整合M0或启动旧栈。真实生产编排在报告指定的releases/42d0dd4/deploy/migration-compose.json，不要直接用旧默认全栈命令覆盖线上配置。

后续优先设计并实现“仅新增/真实修改内容”的知识层增量处理，保留旧提取/索引/证据，避免新recipe触发524份旧资料全量回填。当前knowledge-worker尚未启动，第一层小时同步正常。按有限样本、可中断恢复、重复三连跑、模型全部关闭的方式验收后再受控开启worker。全量旧recipe升级应另列可预算任务，不混进本阶段。

V01请求计数、V03历史public-as-of、V04候选导出作为对应功能启用前的fix，V02影子工具在再次用作发布门禁前修复；CLI snapshot_root未传入API的问题已有working_dir=/部署规避，后续补正确配置传递。不要为了这些非当前交付范围的问题重新整包返工或重做基础迁移。质量金标准仍NOT_RUN，七天观察未完成，诚实记录。

禁止OpenCode、新增付费模型/资料外发、递归删除或移动、改权限、宽泛pkill、force push、输出凭据。保留旧目录、备份、人工文件和所有历史证据。每阶段记录实际证据和恢复点，源码/脱敏文档正常提交push到唯一远端git@github.com:jupiterr-chen/obsidian-sync.git。
```
