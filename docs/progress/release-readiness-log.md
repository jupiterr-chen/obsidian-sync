# 发布前修复与影子验收日志（T01-T07 / G1 / G2）

基线：第三轮评审 `4036a2b`（评审源码基线 `cb254df`，NEEDS_CHANGES，7 组问题 4P1/3P2）。
回归命令（PowerShell）：`$env:PYTHONPATH="app"; python -m unittest discover -s app/tests`

## N0 基线（2026-10-03）

- Git：HEAD `4036a2b`，clean；评审证据 `third-review-evidence-20261003.json` + 探针 `third-review-probe-20261003.py`。
- 回归基线：287 OK / 2 skipped（与评审一致）。
- T01-T07 断言式回归载体：`app/tests/test_third_review.py`（含旧 schema fixture 构建：用 git 基线 `0a473d9` 的 SCHEMA 建带数据旧库，验证升级而非新库冒烟）。

## RED/GREEN 记录

| 任务 | RED（基线复现） | GREEN | 提交 |
|---|---|---|---|
| T01-T07 | 见下 | 见下 | 见下 |

（逐项随修复填充。）
