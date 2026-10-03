# 迁移阻断修复提示词

```text
继续 D:\2.Develop\8.Obsidian\obsidian-sync，不使用 OpenCode。先读 AGENTS.md、docs/progress/FOURTH-REVIEW-20261003.md、docs/21-cutover-blockers-taskbook.md及fourth-review证据/探针。评审基线cd3bb5d，先检查实际HEAD/dirty，保护他人改动。

完成C0–C6/U01–U05，先RED再GREEN：补齐旧库usage_events.counts_request迁移并实际运行业务；chat/vision/embedding全部入口逐次请求门禁与attempt闭合；旧版本unknown日期不得继承文档日期；真实claim导出跨秒幂等；影子manifest hash、禁外发、路径/任务隔离、标注不覆盖和真实只读严格对账。

不能只修底层合成字符串或新空库测试。必须从升级旧库、真实CLI/API入口、恢复/重试/重复运行验证。保持当前shadow产物和人工标注，使用新独立run目录做新验证，不清理、不覆盖。新真实模型调用/资料外发仍禁止。

用户已授权review无问题后的整体迁移、旧栈停机和验证，不要反复询问相同授权。但U问题和真实G2门禁尚未通过，不能现在停旧栈。先修复、独立复验并准备备份/恢复/精确切换步骤，满足条件后才能接续实施。递归删除/移动、改权限、宽泛pkill、force push、覆盖人工内容均不允许；迁移用复制/备份，保留旧目录。

持续推进可独立完成工作，更新docs/progress/release-readiness-log.md、task-status、HANDOFF和评审入口，保存实际RED/GREEN、提交SHA、真实缺项。完整小提交并正常push唯一远端git@github.com:jupiterr-chen/obsidian-sync.git。不要只给计划，不逐阶段询问继续。最终说明U01–U05状态与迁移条件，不把测试数或提交者自评当独立验收。
```
