# M0 整合验收报告

日期：2026-10-01。执行：main-agent（单一 agent，本报告 self-reviewed，复核项见下）。

## 结论

**M0 通过（源码实现 + 离线验证两级完成度；不涉及生产部署）**。源工程 research-kb 的公开可发布内容已按 allowlist 复制进主仓库，第一层回归测试在主仓库全部通过，与源基线逐文件哈希核验一致。未启动任何生产服务，未改动源工程、ResearchVault、ResearchTools。

## 执行前状态保护（V0）

| 项 | 执行前状态 | 执行后状态 |
|---|---|---|
| 源工程 research-kb | main 分支 HEAD `5442e397b3b1276af6ae18403bf2e51103ad6249`，52 跟踪文件，工作树干净 | 未改动（复制只读；执行后复检干净） |
| 主工程 obsidian-sync | main 分支 HEAD `7cf9578`，工作树干净 | 本报告所述 M0 变更 |
| ResearchVault / ResearchTools | 工程外部 | 未触碰 |

## 复制范围（V1）

- 复制方式：`git archive HEAD <allowlist>` + `git show HEAD:<file>`，仅使用 Git 跟踪内容，天然排除未跟踪私有文件。未复制 `.git`、未使用递归移动/删除。
- 导入 49 个公开跟踪文件：`app/`（32 个 Python：library 21 + tests 11）、`scripts/` 公开 6 件、`config/` 公开样例 3 件、`Dockerfile`、`docker-compose.yml`、README 与 5 个公开 docs → `docs/legacy/`。
- 合并 3 个根配置：`.gitignore`（人工合并，见下）、`.dockerignore`（适配主仓库目录，增加 runtime/src/contracts/tests/deploy 排除）、`.gitattributes`（原样采纳 `* text=auto` + eol=lf 规则）。
- **有意不合并**：源 `.gitignore` 中忽略 `AGENTS.md` 的规则（主仓库跟踪自己的 AGENTS.md）；源 AGENTS.md 内容（旧任务约束，按 ADR0002 不继承）。
- 排除类别 7 项（源 opencode.json、.env、config/config.json、未跟踪私有 docs/REVIEW/ACCEPTANCE/RUNBOOK/ENVIRONMENT/ISSUES/TASKBOOK/OPENCODE/DEPLOYMENT_MANIFEST/source-readmes、未跟踪私有 scripts、运行目录 catalog/state/backups/vault/tools/__pycache__），完整清单见 `m0-import-manifest.json`。

## 哈希核验（M0 退出标准）

对全部 49 个复制文件逐一计算源 blob sha256 与目标文件 sha256：

- **40 个字节级一致**（含 `app/` 全部 32 个 Python 文件、Dockerfile、docker-compose.yml、config.example.json、5 个公开脚本）。
- 3 个仅行尾差异（`.env.example`、`stignore`、`install-windows.ps1`）：源 blob 历史上以 CRLF 提交；在主仓库 `.gitattributes` 规则下规范化为 LF。已验证除 `\r\n`→`\n` 外内容完全一致。属必要适配，已在 manifest 逐条标注。
- 6 个文档适配（README + 5 docs → `docs/legacy/`）：仅增加来源说明头与修正文档内相对链接（`docs/X.md` → `./X.md`、根 README 引用），其余内容与源一致（manifest 中记录双哈希）。

## 回归测试（V2）

命令（原生 PowerShell，按任务书）：

```powershell
$env:PYTHONPATH="app"; python -m unittest discover -s app/tests
```

| 位置 | 结果 |
|---|---|
| 源工程（复制前基线） | Ran 113 tests — OK (skipped=1) |
| 主工程（复制后） | Ran 113 tests — OK (skipped=1) |

测试保持原样，未删改、未弱化断言。hash 文件服务、HEAD/Range/ETag、目录幂等、小时调度、变更账本、状态脱敏、人工区保护语义随 113 项测试整体通过。

## 其他检查

- 文档链接：仓库内全部 markdown 相对链接与反引号本地路径巡检通过（见提交前检查输出）；旧文档加历史说明，声明仅描述第一阶段。
- JSON/schema：`contracts/`、`config/config.example.json`、`config/settings.example.json`、导入 manifest 全部解析有效。
- 隐私：对拟提交内容扫描凭据/私网地址/真实主机名——仅存在测试用假密钥字样（用于脱敏测试断言）与 127.0.0.1 回环引用；无私网 IP（192.168.x 出现于源未跟踪文件，未导入）、无真实 API key。
- 无新增运行时依赖：app/library 仅用 Python 标准库；未安装任何包。
- 未触发生产启动/重启/调度；未向旧远端推送；无 force 操作。

## 遗留与说明

- 源目录退役清理：按任务书保留，由用户日后另行决定。
- `docs/GIT_DELIVERY.md`（legacy）中"42 文件"等描述为第一阶段历史，实际以本报告 52 跟踪文件审核为准。
- 复核状态：self-reviewed（单一 agent）。建议后续任一阶段由独立复核方抽查 manifest 与 staged diff。

## 验收对照（M0 退出标准逐条）

| 标准 | 结果 |
|---|---|
| 来源 manifest、可发布范围、排除类别、路径冲突记录 | PASS（m0-import-manifest.json；无路径冲突，主仓库原无 app/scripts/Dockerfile） |
| 源工程全套测试在目标工程通过（PowerShell + PYTHONPATH=app + unittest discover） | PASS（113 OK, 1 skipped，两侧一致） |
| 导入后 app 代码与源基线 hash 一致，无意外运行数据/新依赖 | PASS（32/32 一致；适配仅 3 个非代码文件行尾 + 6 个文档头） |
| 源工作树、Vault、ResearchTools 原状态；无生产启动 | PASS |
| 文档链接、JSON/schema、staged diff 检查；旧文档历史定位说明 | PASS |
| M0 验收报告与复核，提交主仓库，仅正常推送 | PASS（本报告；推送 obsidian-sync.git） |
