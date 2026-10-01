"""Stratified sample selection for quality baselines (P1-03).

Selects a reproducible, stratified sample of ready versions from the
knowledge store for measurement, tuning and blind evaluation. Emits a sample
manifest (JSON) that is the contract between sampling, measurement and
annotation: every sample row pins (source, doc_id, version_id, sha256, strata).

Real-source sampling is a separate concern: the same code runs against the
production catalog once read access exists. Synthetic runs validate the
contract offline.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .store import KnowledgeStore

DEFAULT_TOTAL = 30
DEFAULT_TUNE = 20
DEFAULT_BLIND = 10

MEDIA_FORMATS = ("pdf", "html", "img", "txt")


def format_of(media_type: Optional[str], ext: Optional[str]) -> str:
    value = (ext or media_type or "").lower()
    if "pdf" in value:
        return "pdf"
    if "html" in value or "htm" in value:
        return "html"
    if "png" in value or "jpg" in value or "jpeg" in value or "image" in value:
        return "img"
    if "text" in value or value in ("txt",):
        return "txt"
    return "other"


def language_of(value: Optional[str]) -> str:
    return (value or "unknown").lower()[:8]


@dataclass
class Stratum:
    source: str
    fmt: str
    language: str

    def key(self) -> str:
        return "%s|%s|%s" % (self.source, self.fmt, self.language)


@dataclass
class SamplePlan:
    total: int = DEFAULT_TOTAL
    tune: int = DEFAULT_TUNE
    blind: int = DEFAULT_BLIND
    seed: int = 20261001
    strata: List[Stratum] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    coverage: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_manifest(self) -> Dict[str, Any]:
        tune_rows = [r for r in self.rows if r["split"] == "tune"]
        blind_rows = [r for r in self.rows if r["split"] == "blind"]
        return {
            "schema": "researchkb.sample-manifest/1",
            "seed": self.seed,
            "requested": {"total": self.total, "tune": self.tune, "blind": self.blind},
            "actual": {"total": len(self.rows), "tune": len(tune_rows),
                       "blind": len(blind_rows)},
            "coverage": self.coverage,
            "warnings": self.warnings,
            "samples": self.rows,
        }


def _ready_rows(kb: KnowledgeStore) -> List[Dict[str, Any]]:
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT v.source, v.doc_id, v.version_id, v.sha256, v.bytes,"
            " v.media_type, v.ext, v.is_current, d.language"
            " FROM kb_versions v JOIN kb_documents d"
            " ON d.source = v.source AND d.doc_id = v.doc_id"
            " WHERE v.state = 'ready'").fetchall()
    return [dict(r) for r in rows]


def select_sample(kb: KnowledgeStore, total: int = DEFAULT_TOTAL,
                  tune: int = DEFAULT_TUNE, blind: int = DEFAULT_BLIND,
                  seed: int = 20261001) -> SamplePlan:
    """Deterministic stratified selection across (source, format, language).

    Allocation is proportional to stratum size with a minimum of one slot per
    non-empty stratum (bounded by total). Assignment to tune/blind splits is
    seeded and deterministic.
    """
    plan = SamplePlan(total=total, tune=tune, blind=blind, seed=seed)
    rows = _ready_rows(kb)
    if not rows:
        plan.warnings.append("no ready versions available")
        return plan

    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        stratum = Stratum(row["source"], format_of(row["media_type"], row["ext"]),
                          language_of(row["language"]))
        row["stratum"] = stratum.key()
        buckets.setdefault(stratum.key(), []).append(row)
    plan.coverage = {key: len(items) for key, items in sorted(buckets.items())}

    non_empty = {k: v for k, v in buckets.items() if v}
    slots = max(1, min(total, len(non_empty)))
    quota: Dict[str, int] = {}
    if len(non_empty) >= total:
        # more strata than slots: take the largest strata deterministically
        ranked = sorted(non_empty, key=lambda k: (-len(non_empty[k]), k))[:total]
        quota = {k: 1 for k in ranked}
    else:
        # proportional allocation with every stratum guaranteed one slot
        base = {k: 1 for k in non_empty}
        remaining = total - len(base)
        weights = {k: len(v) for k, v in non_empty.items()}
        weight_total = sum(weights.values())
        ordered = sorted(non_empty, key=lambda k: (-weights[k], k))
        for key in ordered:
            if remaining <= 0:
                break
            extra = min(remaining, max(0, round(weights[key] / weight_total * total) - 1))
            base[key] += extra
            remaining -= extra
        quota = base

    rng = random.Random(seed)
    picked: List[Dict[str, Any]] = []
    for key in sorted(quota):
        items = sorted(buckets[key], key=lambda r: (r["source"], r["doc_id"], r["version_id"]))
        take = min(quota[key], len(items))
        picked.extend(rng.sample(items, take))
    if len(picked) < total:
        plan.warnings.append(
            "only %d of %d requested samples available" % (len(picked), total))

    picked.sort(key=lambda r: (r["source"], r["doc_id"], r["version_id"]))
    split_target = ["tune"] * min(tune, len(picked)) + ["blind"] * max(0, len(picked) - tune)
    rng.shuffle(split_target)

    for row, split in zip(picked, split_target):
        plan.rows.append({
            "source": row["source"], "doc_id": row["doc_id"],
            "version_id": row["version_id"], "sha256": row["sha256"],
            "bytes": row["bytes"], "media_type": row["media_type"],
            "stratum": row["stratum"], "split": split,
        })
    plan.strata = [Stratum(*key.split("|")) for key in sorted(non_empty)]
    return plan


def manifest_digest(manifest: Dict[str, Any]) -> str:
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
