"""Bounded repair queue for missing/low-quality extractions (A2).

Builds an explicitly bounded queue (default max 25) of current versions
whose extraction is missing or has no readable text, or whose latest
extraction failed - re-registering ONLY those for extraction. This is a
repair lane, deliberately bounded so it can never degrade into an
implicit full-corpus re-extraction; the historical wave remains a
separately authorized pass (A1 ``historical`` flag).

TQ3: an EXPLICIT reprocess batch lane for the text-quality inventory's
candidates (legacy stdlib engines, damaged pages). Items are selected
from the read-only inventory by recommended action and registered under
the CURRENT recipe - a NEW extraction identity, so historical blocks,
evidence URLs and old reading notes all stay intact. The batch is
bounded, idempotent (three runs register once) and crash-resumable
(jobs are the durable state); a worse new extraction never replaces
the reading entry (the publisher switches only on usable text). No
batch is ever derived implicitly from a recipe change alone.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .store import KnowledgeStore, utc_now

REPROCESS_SCHEMA = """
CREATE TABLE IF NOT EXISTS reprocess_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    recommended_action TEXT,
    recipe_digest TEXT,
    registered_at TEXT NOT NULL,
    UNIQUE (batch_id, source, doc_id, version_id)
);
"""


def build_repair_queue(kb: KnowledgeStore, max_items: int = 25) -> List[Dict[str, Any]]:
    """Current versions with missing/empty/failed text, newest first."""
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT v.source, v.doc_id, v.version_id, d.title,"
            " e.extraction_id, e.status AS extraction_status,"
            " (SELECT COUNT(*) FROM blocks b WHERE b.extraction_id ="
            "  e.extraction_id AND LENGTH(TRIM(b.text)) > 0) AS readable"
            " FROM kb_versions v JOIN kb_documents d"
            " ON d.source=v.source AND d.doc_id=v.doc_id"
            " LEFT JOIN extractions e ON e.extraction_id = ("
            "  SELECT e2.extraction_id FROM extractions e2"
            "  WHERE e2.source=v.source AND e2.doc_id=v.doc_id"
            "   AND e2.version_id=v.version_id ORDER BY e2.rowid DESC LIMIT 1)"
            " WHERE v.is_current=1"
            " ORDER BY v.source, v.doc_id").fetchall()
    queue = []
    for row in rows:
        item = dict(row)
        needs = (item["extraction_id"] is None
                 or item["extraction_status"] == "failed"
                 or not item["readable"])
        if needs:
            queue.append(item)
    return queue[:max_items]


def register_repair_jobs(kb: KnowledgeStore, digest: str,
                         max_items: int = 25) -> Dict[str, Any]:
    """(Re-)register extract jobs for the bounded repair queue."""
    queue = build_repair_queue(kb, max_items=max_items)
    registered = 0
    for item in queue:
        if kb.register_job(item["source"], item["doc_id"], item["version_id"],
                           "extract", digest):
            registered += 1
    return {"queue_size": len(queue), "registered": registered,
            "bounded_to": max_items}


# ------------------------------------------------------------------ TQ3
def select_reprocess_items(inventory: Dict[str, Any],
                           actions: Optional[List[str]] = None,
                           max_items: int = 20) -> List[Dict[str, Any]]:
    """Deterministic, bounded selection from a TQ0 inventory.

    Only documents whose recommended action is in `actions` (default:
    the two candidate classes) and whose source is available are
    eligible; ordering is stable (source, doc_id) so every run of the
    same inventory yields the same batch."""
    wanted = actions or ["native-reextract-candidate", "ocr-candidate"]
    items = [doc for doc in inventory["documents"]
             if doc.get("recommended_action") in wanted
             and doc.get("source_available")
             and doc.get("extraction_id")]
    items.sort(key=lambda d: (d["source"], d["doc_id"]))
    return items[:max(1, int(max_items))]


def register_reprocess_batch(kb: KnowledgeStore, digest: str,
                             items: List[Dict[str, Any]],
                             batch_id: str) -> Dict[str, Any]:
    """Register ONE explicit reprocess batch under a FROZEN recipe.

    S3/TA05: the FIRST registration freezes the member list and the
    recipe digest for that batch id. Re-running the same batch id ONLY
    ever restores the frozen members - a fresh inventory selection that
    now contains different documents (e.g. the next candidate after A
    was fixed) is refused as a divergence, never silently added; new
    members require a NEW batch id. A different recipe digest for the
    same batch id is refused outright. The per-invocation max is a
    slice, not a batch-size limit - the freeze is what bounds the
    batch. Idempotent per member; the jobs table stays the durable
    execution state; nothing is deleted or overwritten."""
    with kb._tx() as conn:
        conn.executescript(REPROCESS_SCHEMA)
        # forward-fill recipe_digest for pre-S3 rows (they froze under
        # the digest that created them; unknown rows record none)
        conn.execute(
            "UPDATE reprocess_batches SET recipe_digest=? WHERE"
            " batch_id=? AND recipe_digest IS NULL", (digest, batch_id))
        frozen = conn.execute(
            "SELECT source, doc_id, version_id FROM reprocess_batches"
            " WHERE batch_id=? ORDER BY source, doc_id",
            (batch_id,)).fetchall()
    frozen_members = [(row["source"], row["doc_id"], row["version_id"])
                      for row in frozen]
    frozen_digest_row = None
    with kb._lock:
        row = kb._conn.execute(
            "SELECT recipe_digest FROM reprocess_batches WHERE"
            " batch_id=? LIMIT 1", (batch_id,)).fetchone()
        frozen_digest_row = row["recipe_digest"] if row else None

    if frozen_members:
        if frozen_digest_row is not None and \
                frozen_digest_row != digest:
            return {"batch_id": batch_id, "refused": True,
                    "reason": "recipe_digest_mismatch",
                    "frozen_recipe": frozen_digest_row,
                    "requested_recipe": digest,
                    "note": "open a NEW batch id for a different recipe"}
        incoming = {(item["source"], item["doc_id"],
                     item["version_id"]) for item in items}
        frozen_set = set(frozen_members)
        added = sorted(incoming - frozen_set)
        missing = sorted(frozen_set - incoming)
        if added:
            return {"batch_id": batch_id, "refused": True,
                    "reason": "membership_divergence",
                    "frozen_members": len(frozen_members),
                    "attempted_new_members": [
                        {"source": s, "doc_id": d, "version_id": v}
                        for s, d, v in added],
                    "note": ("this batch id is FROZEN with its original"
                             " members; register new documents under a"
                             " NEW batch id")}
        # pure resume (or subset call): restore the frozen members only
        items = [item for item in items
                 if (item["source"], item["doc_id"],
                     item["version_id"]) in frozen_set]
        if missing:
            # the caller selected fewer than frozen (inventory
            # changed): still register the missing frozen members so a
            # resume is complete - the freeze, not the fresh selection,
            # defines the batch
            items = list(items) + [
                {"source": s, "doc_id": d, "version_id": v}
                for s, d, v in missing]

    # S3/SF06: the FREEZE is one atomic transaction covering the
    # COMPLETE member list - a crash during the later per-member job
    # registration leaves the full freeze intact, so a retry resumes
    # the original batch instead of being rejected as divergent
    registered_audit = 0
    if not frozen_members:
        now = utc_now()
        with kb._tx() as conn:
            conn.executescript(REPROCESS_SCHEMA)
            for item in items:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO reprocess_batches (batch_id,"
                    " source, doc_id, version_id, recommended_action,"
                    " recipe_digest, registered_at) VALUES"
                    " (?,?,?,?,?,?,?)",
                    (batch_id, item["source"], item["doc_id"],
                     item["version_id"], item.get("recommended_action"),
                     digest, now))
                registered_audit += cursor.rowcount
        frozen_members = [(item["source"], item["doc_id"],
                           item["version_id"]) for item in items]

    registered_jobs = 0
    for item in items:
        if kb.register_job(item["source"], item["doc_id"],
                           item["version_id"], "extract", digest):
            registered_jobs += 1
    result = {"batch_id": batch_id, "items": len(items),
              "audit_rows_added": registered_audit,
              "jobs_registered": registered_jobs}
    if frozen_members:
        result["resumed_frozen_members"] = len(frozen_members)
    return result
