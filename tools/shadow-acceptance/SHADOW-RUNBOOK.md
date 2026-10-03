# 影子验收运行手册（N5；G1 已通过后执行）

范围：30 份分层样本（20 调优 / 10 盲测），**只读源 + 隔离 state**，不触碰生产库、真实 Vault、不发起任何付费调用（本地 OCR 可用；vision 回退按配置，默认关）。

## 0) 前置检查

```sh
# 服务器上（示例路径；shadow 目录独立于 state/）
SHADOW=/vol2/1000/10.Develop/obsidian-sync/shadow
CFG=/vol2/1000/10.Develop/obsidian-sync/config-knowledge.json
```

## 1) 选样（固定身份；不接触正文）

```sh
cd /vol2/1000/10.Develop/obsidian-sync/repo
PYTHONPATH=app python tools/shadow-acceptance/shadow_sample.py \
  --config $CFG --out-dir $SHADOW
# 产出: shadow-manifest.json + annotations/（标注模板 30 份）+ ANNOTATIONS.md
```

## 2) Dry-run（先看计划再动手）

```sh
PYTHONPATH=app python tools/shadow-acceptance/shadow_run.py \
  --config $CFG --manifest $SHADOW/shadow-manifest.json \
  --state-dir $SHADOW/state --dry-run
```

## 3) 隔离处理（本地 OCR；如配置了 vision 回退则按其预算）

```sh
PYTHONPATH=app python tools/shadow-acceptance/shadow_run.py \
  --config $CFG --manifest $SHADOW/shadow-manifest.json \
  --state-dir $SHADOW/state
# 幂等：连跑三次后对账（A02）——计数应完全一致
```

## 4) 对账报告（A01/A14 证据）

```sh
PYTHONPATH=app python tools/shadow-acceptance/shadow_reconcile.py \
  --manifest $SHADOW/shadow-manifest.json --state-dir $SHADOW/state
```

## 5) 人工标注（A04/A06/A08/A09 的金标准）

- 按 `ANNOTATIONS.md` 清单逐份填写 `annotations/*.md`。
- 盲测 10 份在任何调优决定之前不得回看系统输出（标注页与系统输出分开保存）。
- 标注不足时：报告如实写 NOT_RUN，不得用 LLM 替代。

## 6) Token/成本测量（A05）

```sh
PYTHONPATH=app python -m knowledge measure \
  --config $CFG --manifest $SHADOW/shadow-manifest.json \
  --out $SHADOW/measurement.json
# 启发式计数仅数量级；接入真实 tokenizer 后重跑覆盖
```

## 红线

- shadow/state 与生产 state 完全隔离；任何失败直接删除重跑（仅 shadow 目录）。
- 不把 shadow 产物写回生产或 Vault。
- 结果只进入 `docs/progress/` 的聚合报告；正文/样本内容不进 Git。
