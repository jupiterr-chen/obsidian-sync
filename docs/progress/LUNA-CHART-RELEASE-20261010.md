# Luna 图表发布边界核查（2026-10-10）

基于固定实现 `1c718b35209f379bf155cd2e89f34828c9b50ea1`，本轮只对有界发布反例做修复；未部署、未改生产服务、未调用模型、未移动或删除文件，未提交代码。保留同时存在的用户修改。

## 修复

- `app/knowledge/analysis_publish.py`：分析页引用按 citation 绑定的 `projection_id` 读取历史投影正文并生成带版本参数的知识库证据路径。该路径显示为需经已认证客户端访问的代码引用，不拼接 library 服务地址；原始 PDF 链接仍可点击。缺失/错配投影直接失败，不能静默回落原始 block；未带投影 id 的历史 raw 引用仍展示原文。
- `app/knowledge/content.py`：claim 证据绑定到有图表投影的 extraction 时，粗粒度引用无法证明具体安全范围，拒绝进入当前消费；`hold_candidates` 开启时同步拒绝指向未投影候选页的 block 引用及粗粒度 extraction 引用。正常未投影文档及关闭暂缓后的证据仍可用。
- `app/knowledge/summaries.py`：单篇分析进入总结前核对其引用，并检查整个 extraction 是否含有未投影的暂缓候选；即使 run 只引用干净 block，也不会带入同一 extraction 的旧分析。run 及其原始引用仍留存审计。
- `app/knowledge/content.py`：回退的 compare-and-swap 保持严格，避免把另一次激活误认成已完成回退。若回退指针已提交但索引构建失败，`app/knowledge/chart_governance.py` 的 `reindex` 子命令可幂等恢复派生索引。

## 验证

新增隔离测试 `app/tests/test_chart_release_edges.py`：分析页投影和证据路径、投影后粗粒度 claim、候选页 claim 暂缓、单篇分析暂缓（模型只引用干净 block 仍被 extraction 暂缓）、回退 CLI 提交后索引构建异常及独立 reindex 恢复。四项全部通过，未调用模型。

可重复命令（仓库根目录，使用本机 Anaconda Python）：

```powershell
$env:PYTHONPATH='app;app/tests'
$env:TEMP='D:\2.Develop\8.Obsidian\obsidian-sync\runtime\chart-tests'
$env:TMP=$env:TEMP
& 'D:\2.Develop\Anaconda\python.exe' -m unittest test_chart_release_edges -v
```

结果：`Ran 4 tests ... OK`。单独运行时没有加载既有图表测试文件，避免触发其本机 HTTP socket 测试。

若 `rollback --apply` 已提交指针、随后索引构建失败，不要重放原 CAS 回退命令；执行 `python -m knowledge.chart_governance reindex --db <same-isolated-db>`，该命令可重复运行。

本轮未重跑 464 项总回归、固定提交干净副本或 10 页真实隔离样本；这三项留给根 agent 独立验收。合成反例不能代表真实全库验证。无其他已确认发布阻断留在本轮边界内。
