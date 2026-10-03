#!/usr/bin/env python3
"""Shadow-acceptance sample selection (N5): stratified, read-only, seeded.

Selects a 30-document layered sample (20 tune / 10 blind) from a knowledge
store built from the READ-ONLY catalog, without touching production state.
Output: a sample manifest + an annotation template (all private material
stays outside git; this tool only writes to --out-dir).

Usage (server, isolated dir):
  PYTHONPATH=app python tools/shadow-acceptance/shadow_sample.py \
      --config /vol2/1000/10.Develop/obsidian-sync/config-knowledge.json \
      --out-dir /vol2/1000/10.Develop/obsidian-sync/shadow \
      [--total 30] [--tune 20] [--blind 10] [--seed 20261003]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "app"))

from knowledge.config import KnowledgeConfig  # noqa: E402
from knowledge.sampling import select_sample  # noqa: E402
from knowledge.store import KnowledgeStore  # noqa: E402

ANNOTATION_TEMPLATE = """# 标注模板（A04/A06/A08/A09）- doc: {doc_id}

## 分层信息
- stratum: {stratum} | split: {split} | source: {source} | version: {version_id}

## A06 正文可用性（人工目检）
- [ ] 段落覆盖估计（占全部可见段落）: ____%
- [ ] 阅读顺序正确（多栏/表格先后）: 是 / 否
- [ ] 明显乱码/遗漏页（列出页码）: ____
- quality(系统): {system_status} — 与人工判断一致? 是/否

## A08 OCR 页（仅扫描件）
- 需 OCR 页数(系统): {ocr_pages} | 系统 OCR 状态: {ocr_status}
- [ ] OCR 页文字可用: 是/部分/否
- 严重乱码页: ____ | 完全遗漏页: ____

## A09 财务数值（每行一个，至少覆盖关键数值）
| 原文数值 | 页/位置 | 单位 | 期间 | 币种 | 系统提取值 | 正确? |
|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |

## A07 证据引用（选取 ≥3 处）
| 原文句 | 系统块 page/dom | 定位正确? |
|---|---|---|
|  |  |  |

## 备注
"""


def main() -> int:
    parser = argparse.ArgumentParser(prog="shadow_sample")
    parser.add_argument("--config", required=True,
                        help="knowledge config (read-only catalog source)")
    parser.add_argument("--out-dir", required=True,
                        help="ISOLATED output dir (never the production state)")
    parser.add_argument("--total", type=int, default=30)
    parser.add_argument("--tune", type=int, default=20)
    parser.add_argument("--blind", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261003)
    args = parser.parse_args()

    config = KnowledgeConfig.load(args.config).resolve(
        os.path.dirname(os.path.abspath(args.config)))
    # read-only consumer view of the first-layer catalog
    from knowledge.sync import open_catalog_readonly

    conn = open_catalog_readonly(config.catalog_db)
    try:
        rows = conn.execute(
            "SELECT d.source, d.doc_id, d.title, d.language, v.version_id,"
            " v.media_type, v.ext, v.bytes"
            " FROM documents d JOIN versions v"
            " ON v.source = d.source AND v.doc_id = d.doc_id"
            " WHERE d.available = 1 AND v.is_current = 1"
            " ORDER BY d.source, d.doc_id").fetchall()
    finally:
        conn.close()
    if not rows:
        print(json.dumps({"ok": False, "error": "catalog empty/unreachable"}))
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    # phase a: catalog-only sample plan (identities fixed before any
    # processing, so the sample cannot be biased by extraction results)
    catalog_db = os.path.join(args.out_dir, "sample-plan.sqlite3")
    plan_store = KnowledgeStore(catalog_db)
    try:
        plan_store.upsert_documents([dict(r) for r in rows], "2026-10-03")
        plan = select_sample(plan_store, total=args.total, tune=args.tune,
                             blind=args.blind, seed=args.seed).to_manifest()
    finally:
        plan_store.close()

    manifest_path = os.path.join(args.out_dir, "shadow-manifest.json")
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    annotations_dir = os.path.join(args.out_dir, "annotations")
    os.makedirs(annotations_dir, exist_ok=True)
    index_lines = ["# 影子标注清单", ""]
    for sample in plan["samples"]:
        safe = "%s_%s" % (sample["source"], sample["doc_id"])
        path = os.path.join(annotations_dir, safe + ".md")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(ANNOTATION_TEMPLATE.format(
                doc_id=sample["doc_id"], stratum=sample["stratum"],
                split=sample["split"], source=sample["source"],
                version_id=sample["version_id"], system_status="NOT_PROCESSED",
                ocr_pages="NOT_PROCESSED", ocr_status="NOT_PROCESSED"))
        index_lines.append("- [%s/%s (%s)](annotations/%s.md)"
                           % (sample["source"], sample["doc_id"],
                              sample["split"], safe + ".md"))
    with open(os.path.join(args.out_dir, "ANNOTATIONS.md"), "w",
              encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(index_lines) + "\n")

    print(json.dumps({
        "ok": True, "manifest": manifest_path,
        "total": plan["actual"]["total"],
        "tune": plan["actual"]["tune"], "blind": plan["actual"]["blind"],
        "strata": plan["coverage"], "warnings": plan["warnings"],
        "note": "sample identities fixed from the read-only catalog; no"
                " production state touched",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
