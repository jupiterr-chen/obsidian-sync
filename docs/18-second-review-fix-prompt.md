# 第二轮修复提示词

复制以下整段给执行 agent：

```text
继续修复 D:\2.Develop\8.Obsidian\obsidian-sync，唯一正常推送远端 git@github.com:jupiterr-chen/obsidian-sync.git。不使用 OpenCode。持续执行到可独立完成的修复、测试、提交和交接全部完成，不要只给计划或逐阶段询问继续。

先读 AGENTS.md、docs/progress/RE-REVIEW-20261003.md、docs/17-second-review-taskbook.md、docs/progress/re-review-evidence-20261003.json 和 re-review-probe-20261003.py。评审代码基线 4949dcd；先检查最新 HEAD 和工作树，不撤销他人改动。旧 R01–R15 全 fixed/RF7 闭环声明已被第二轮复核否决，当前 NEEDS_CHANGES。

按 SR0–SR6 完成 S01–S10：预算和影响 outbox 原子事务；人工成果追加不覆盖；版本级公开时间与历史查询语义；快照返回字节校验；OCR 置信度与图片零重复处理；元数据变化下游标一致性；独立语义召回/缓存隔离；library 启动命令、构建失败传播、切换路径。先用确定性并发/中断/文件替换反例做 RED，再修复 GREEN，不以 happy-path 回归或 YAML 解析代替边界/启动验收。

可以修改主工程、补测试、安装必要项目开发依赖、创建完整小提交并正常 push。不得操作生产服务、停止现有 OCR、切换旧栈、改真实 Vault、外发资料或发起付费模型调用；真实 embedding 保持关闭。只用本地合成资料和 mock。不要重新迁移 M0，不改旧工程或源归档，不 force push，不递归清理/移动，不改权限。需要真实环境的验证集中标 NOT_RUN，继续完成其他独立任务。

未知历史时间不得伪造；历史证据不可原位改写；数据库非破坏迁移。不能通过降低门槛、仅修改测试、删除需求或补一份 ADR 关闭反例。提供不了原需求时明确能力差距。

每阶段保存 docs/progress/second-remediation-log.md、task-status 和 HANDOFF，列实际 RED/GREEN 命令、结果、提交 SHA 与缺项。持续简短反馈，20–30 分钟落盘恢复点。最后做独立复验，汇报 S01–S10 状态、全回归、真实 NOT_RUN/BLOCKED 与是否仍有 P1；未经授权不部署。现在检查基线并开始 SR0，不要复述计划。
```
