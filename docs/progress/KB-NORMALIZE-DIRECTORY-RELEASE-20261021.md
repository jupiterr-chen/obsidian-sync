# 发布记录：KB-NORMALIZE-DIRECTORY-20261021

```text
发布 ID / 北京时间：kb-normalize-20261021（终版 04f4e7a）/ 2026-10-21 21:20–22:05
固定 commit / 实际 image ID / 变更服务：
  终版 commit 04f4e7a（含中间版 f697f30），main 分支，已推送 GitHub
  终版镜像 obsidian-sync:kb-normalize-20261021-04f4e7a = sha256:a91fbe6010b51733eeaa2c06d94158e3e8f99a481f31743aa2921f23d98399a8
  中间镜像 kb-normalize-20261021-f697f30 = sha256:ba3dff3dd2e2a4227e0905a52b5af6cec4eb4019140a99fe17d743b905edbe8b（已被终版取代）
  变更服务：knowledge-api、knowledge-worker（两次替换；Library/Syncthing/状态采集器未动）
独立验收证据 / 用户授权范围：
  用户在本会话明确指令「开始部署和验收」，范围=本批 obsidian-sync KB 变更（归一化/目录 API/元数据 flags/表格结构化）
  本地 pytest 全量：f697f30=519 passed / 3 skipped；04f4e7a=522 passed / 3 skipped
  容器内离线门（unittest discover --network none）：失败集与现役生产镜像完全一致（42 项存量环境失败：镜像不打包 app/ 外的 Dockerfile/scripts/contracts 等文件所致），无本批新增失败；仅 test_chart_release_bundle 为老镜像构建后新增的同类环境项（读 /scripts/… 不存在）。此门命令相对测试演进已失真，建议后续换 pytest 变体
Compose 文件组合 / 配置挂载 / 资源和调度：
  终版 releases/kb-normalize-20261021-04f4e7a/deploy/production-compose.json（复刻 6679872 版全部服务定义，仅换 api/worker 镜像）
  worker 资源内联 4 GiB 内存 / 5 GiB 总量（原 10-18 override 折叠进 base），--interval 1800 保留，挂载全部保留（/app-config 仍挂 releases/6679872/deploy/config 私有配置）
  docker compose -p obsidian-sync -f <终版 compose> up -d --no-deps --no-build --pull never knowledge-api knowledge-worker（两次，第二次为终版）
本批来源、版本、提取和数量（私有清单位置）：
  数据无变更：catalog 未动、无新增提取配方重跑（EXTRACT_CONFIG v2 仅影响新任务）、发布 613 文档 / 595 快照 / 233,637 块
备份 / 恢复演练 / 冻结恢复点 / 兼容回退入口：
  备份 backups/kb-normalize-20261021-f697f30/（SQLite backup API，49G + 595 blobs 1.9G，102s）
  恢复演练 operations/kb-normalize-20261021-f697f30/acceptance.py + drill（ok=true，595/595 blob 哈希验证，integrity_check ok，RTO 3662s；drill 目录已清理回收 49G）
  回退：docker compose -p obsidian-sync -f releases/6679872/deploy/production-compose.json -f operations/discord-delivery-repair-20261018/worker-resources.override.json up -d --no-deps --no-build <service>（schema 纯增量，旧镜像兼容新库；索引 v4 generation 对旧镜像查询侧简繁不命中，可接受或触发重建回 v3 不必要——保留 v4 即可，旧 API 仍能服务繁体原文检索以外的功能）
当前阶段 / 准确任务身份 / 下一只读检查点：
  已上线并验收完成；worker 终版镜像整轮 cycle ok=true（2026-10-21T14:01:01Z，extracts 0 failed / snapshots 595 done）
  下一检查点：worker 下轮 cycle（约 +30 分钟）last_ok 保持 true；4 项存量缺快照 repair 任务（reports/0c2d7fb2、233f143b、af174666、dce67a52）预计继续按轮重试失败，属 10-04 起既有状态，非本批引入
服务器验收 / Windows 文件验收 / UI 实测范围与时间：
  服务器 8/8 PASS（2026-10-21 22:00 前后）：简体「资产负债」×symbols=01810 命中且与繁体同结果集；全角ＡＳＭＬ命中；目录 GET /documents?symbol=01810 total=17；全量分页 613/613；metadata_flags 12 文档（period_missing×9、period_title_mismatch×3——含 09988「2023財政年度中期報告」存 2021-12-31、「2023財務年度報告」存 2022-09-30（用户调研报告确认的原始案例）、「2025財務年度中期報告」存 2023-09-30）；evidence 回归通过；active generation gen-b777d7f4c63c4ff2d9279c85（v4 归一化索引，13:51 由 worker 原子重建激活，旧 gen-31ef206b 退役）
  Windows 文件验收 / Obsidian UI：本批不产生 Vault 内容变更（无重提取 pass），不适用
失败、未验项及负责人：
  表格结构化证据（evidence table 节）在生产行为未验证——历史语料需显式授权的重提取 pass（配方 evidence-block-v2）后才会有带 table 的块；本地/镜像内 8 个测试已验证全链路。NOT_VERIFIED（生产），负责人：用户决定是否排期重提取
  unittest discover 离线门失真（见上），负责人：后续 agent 换 pytest 门
禁止重放的 apply、历史修复和监督器：
  本发布两次容器替换不得重放；10-18 discord 修复不重跑；旧等待监督器不恢复；不自动开启 embedding/hybrid（配置属部署决策，未获授权不动）
```

## 变更内容（用户视角）

1. 检索简繁/全半角归一化（NFKC+繁→简，索引与查询同侧；TOKENIZER_VERSION 入 generation manifest，SELECTION_POLICY v3→v4 强制整代重建）
2. 新端点 GET /api/kb/v1/documents 目录列表（symbol/doc_type/source/日期/available + 游标绑定过滤集与元数据 epoch）
3. documents 响应 metadata_flags：period_invalid / period_suspect / period_missing / symbol_missing / period_title_mismatch（财年标题-期间一致性）
4. HTML 表格结构化证据：block_tables 附加表 + /evidence 兄弟级 table 节（读时数字解释）；提取配方 evidence-block-v2
5. 文档：docs/04-api-contract.md 增补；docs/50-position-manage-integration-prompt.md（研究端对接提示词）
