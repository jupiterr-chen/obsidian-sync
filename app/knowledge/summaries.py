"""Company/topic knowledge summaries with versioned history (C).

N3 (Q03) closes the loop and fixes event duplication:

- every update event carries a UNIQUE event_key: the same logical event
  (same proposal, same ingested version, same refresh) enqueues exactly
  one outbox row no matter how many cycles revisit it - the review
  counter-example (one open proposal, three cycles, three empty
  revisions) now yields ONE;
- with no provider, an event is consumed into ONE blocked revision that
  PRESERVES its evidence identity (reason, detail, claim revisions) so
  generation can recover when a provider is authorized - never an empty
  "result" revision, and never silently dropped;
- with a provider, the consumer assembles the entity's evidence context
  (accepted/challenged claims with counter-evidence and source refs)
  through the budget ledger, and records a real versioned revision;
  unrelated entities are never touched (no corpus-wide sends);
- entity mapping covers FIRST documents: a document's symbol maps to
  its company entity at ingest time, not only claims that already have
  review proposals;
- every finished or blocked revision is publishable to the generated
  总结/ directory (one immutable page per revision + a derived index),
  append-only so human edits always win.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from .store import KnowledgeStore, utc_now
from .writeback import register_write_root, write_candidate

SUMMARY_TEMPLATE_VERSION = "entity-summary-v1"
STATUS_PENDING = "pending"
STATUS_BLOCKED = "blocked"
STATUS_DONE = "done"

SCHEMA = """
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,          -- company | topic
    entity_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    content TEXT,
    evidence_claim_revisions_json TEXT,
    event_key TEXT,
    blocked_reason TEXT,
    model_identity TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (entity_type, entity_id, revision)
);
CREATE TABLE IF NOT EXISTS summary_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    detail_json TEXT,
    event_key TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    consumed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_summary_outbox_event
    ON summary_outbox(event_key) WHERE event_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS summary_publish_log (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    published_at TEXT NOT NULL,
    UNIQUE (entity_type, entity_id, revision)
);
"""

SUMMARY_DIR_NAME = "总结"
SUMMARY_INDEX_NAME = "总结索引.md"


def ensure_schema(kb: KnowledgeStore) -> None:
    """Idempotent forward migration (R1/AC01).

    Stores created by the previous release lack event_key on
    summary_outbox/summaries while SCHEMA creates a UNIQUE INDEX over
    that column - running the script first crashed the upgrade (and the
    worker's second half even with models off). Columns are detected and
    patched BEFORE any index is created; interrupted migrations retry
    cleanly because each ALTER only runs when its column is missing.
    Existing queued events and revision history are never rebuilt."""
    with kb._tx() as conn:
        for table, columns in (
                ("summary_outbox", (("event_key", "TEXT"),)),
                ("summaries", (("event_key", "TEXT"),)),
        ):
            existing = [r[1] for r in conn.execute(
                "PRAGMA table_info(%s)" % table).fetchall()]
            if not existing:
                continue  # fresh store: SCHEMA below creates it in full
            for column, decl in columns:
                if column not in existing:
                    conn.execute("ALTER TABLE %s ADD COLUMN %s %s"
                                 % (table, column, decl))
        conn.executescript(SCHEMA)


def entities_for_document(kb: KnowledgeStore, source: str, doc_id: str,
                          topic_rules: Optional[List[Dict[str, Any]]] = None
                          ) -> List[Dict[str, str]]:
    """Map a source document to the entities it feeds (N3: first-doc
    coverage). Company entities come from the document's symbol; the
    doc-level metadata is already mirrored in kb_documents.

    Topic mapping (R2) is MINIMAL and CONFIGURABLE only: rules are
    [{"id": "流动性", "keywords": ["流动性", "liquidity"]}] supplied by
    the deployment config (extra.summarization.topics); a document whose
    title matches a keyword feeds that topic entity. Without configured
    rules no topic entities are produced - no automatic topic discovery
    is claimed."""
    with kb._lock:
        row = kb._conn.execute(
            "SELECT symbol, title, display_title FROM kb_documents"
            " WHERE source=? AND doc_id=?",
            (source, doc_id)).fetchone()
    entities: List[Dict[str, str]] = []
    title = ((row["title"] or row["display_title"] or "") if row else "")
    if row and (row["symbol"] or "").strip():
        entities.append({"entity_type": "company",
                         "entity_id": row["symbol"].strip().upper()})
    for rule in (topic_rules or []):
        topic_id = str((rule or {}).get("id") or "").strip()
        keywords = [str(k) for k in (rule or {}).get("keywords") or [] if k]
        if topic_id and keywords and any(
                keyword in title for keyword in keywords):
            entities.append({"entity_type": "topic", "entity_id": topic_id})
    # dedupe (a doc may match several keywords of one topic)
    unique = {(e["entity_type"], e["entity_id"]): e for e in entities}
    return list(unique.values())


def _default_event_key(entity_type: str, entity_id: str, reason: str,
                       detail: Optional[Dict[str, Any]]) -> str:
    identity = "\x00".join((entity_type, entity_id, reason,
                            json.dumps(detail or {}, ensure_ascii=False,
                                       sort_keys=True)))
    return "sum-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def enqueue_summary_update(kb: KnowledgeStore, entity_type: str,
                           entity_id: str, reason: str,
                           detail: Optional[Dict[str, Any]] = None,
                           event_key: Optional[str] = None) -> bool:
    """Queue one summary update event. Idempotent per event_key: the
    same logical event never queues twice (Q03)."""
    if entity_type not in ("company", "topic") or not entity_id:
        return False
    ensure_schema(kb)
    key = event_key or _default_event_key(entity_type, entity_id, reason,
                                          detail)
    with kb._tx() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO summary_outbox (entity_type, entity_id,"
            " reason, detail_json, event_key, status, created_at)"
            " VALUES (?,?,?,?,?, 'pending', ?)",
            (entity_type, entity_id, reason,
             json.dumps(detail or {}, ensure_ascii=False), key, utc_now()))
        return cursor.rowcount > 0


def pending_updates(kb: KnowledgeStore, limit: int = 100) -> List[Dict[str, Any]]:
    ensure_schema(kb)
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT * FROM summary_outbox WHERE status='pending'"
            " ORDER BY id LIMIT ?", (max(1, int(limit)),)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["detail"] = json.loads(item.pop("detail_json") or "{}")
        result.append(item)
    return result


def _entity_claim_evidence(kb: KnowledgeStore, entity_type: str,
                           entity_id: str) -> List[Dict[str, Any]]:
    """Deterministic evidence assembly for one entity: claims whose
    subject matches, latest revision each, with counter-evidence - the
    model context is assembled by retrieval, the whole DB is never
    sent."""
    if entity_type != "company":
        return []
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT claim_id, current_revision, statement, status,"
            " evidence_json, counterevidence_json, updated_at FROM claims"
            " WHERE subject=? ORDER BY updated_at DESC LIMIT 50",
            (entity_id,)).fetchall()
    evidence = []
    for row in rows:
        evidence.append({
            "claim_id": row["claim_id"],
            "revision": row["current_revision"],
            "statement": row["statement"],
            "status": row["status"],
            "evidence": json.loads(row["evidence_json"] or "[]"),
            "counterevidence": json.loads(
                row["counterevidence_json"] or "[]"),
        })
    return evidence


def _entity_document_evidence(kb: KnowledgeStore, entity_type: str,
                              entity_id: str,
                              max_docs: int = 10,
                              max_blocks_per_doc: int = 6,
                              max_analyses: int = 10
                              ) -> List[Dict[str, Any]]:
    """R2: the entity's evidence includes the documents' OWN extracted
    text and finished single-doc analyses - a company's first report
    carries real content even with zero human claims. Every item binds
    source/version/extraction/block (or the analysis run identity)."""
    from urllib.parse import unquote as _unquote

    with kb._lock:
        if entity_type == "company":
            docs = kb._conn.execute(
                "SELECT d.source AS source, d.doc_id AS doc_id,"
                " v.version_id AS version_id, d.title AS title FROM"
                " kb_documents d JOIN kb_versions v"
                " ON v.source=d.source AND v.doc_id=d.doc_id"
                " AND v.is_current=1 WHERE UPPER(d.symbol)=UPPER(?)"
                " ORDER BY v.synced_at DESC LIMIT ?",
                (entity_id, max_docs)).fetchall()
        else:
            # topics are mapped at event time from configured keyword
            # rules; there is no re-derivable topic->document join here
            docs = []
        evidence: List[Dict[str, Any]] = []
        for doc in docs:
            title = _unquote(doc["title"] or doc["doc_id"])
            extraction = kb._conn.execute(
                "SELECT extraction_id FROM extractions WHERE source=? AND"
                " doc_id=? AND version_id=? ORDER BY rowid DESC LIMIT 1",
                (doc["source"], doc["doc_id"], doc["version_id"])).fetchone()
            blocks = kb._conn.execute(
                "SELECT block_id, text, locator_json FROM blocks"
                " WHERE extraction_id=? AND LENGTH(TRIM(text))>0"
                " ORDER BY ordinal LIMIT ?",
                ((extraction["extraction_id"] if extraction else ""),
                 max_blocks_per_doc)).fetchall()
            for block in blocks:
                locator = json.loads(block["locator_json"] or "{}")
                evidence.append({
                    "kind": "document_block", "title": title,
                    "source": doc["source"], "doc_id": doc["doc_id"],
                    "version_id": doc["version_id"],
                    "extraction_id": (extraction["extraction_id"]
                                      if extraction else None),
                    "block_id": block["block_id"],
                    "page": locator.get("page"),
                    "text": block["text"],
                })
        # finished single-doc analyses for the same documents: the B
        # results join C's evidence with their run identity (stores that
        # predate the B pipeline simply have no such table yet)
        has_tasks = kb._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND"
            " name='analysis_tasks'").fetchone()
        if entity_type == "company" and has_tasks:
            analyses = kb._conn.execute(
                "SELECT t.source, t.doc_id, t.version_id,"
                " t.extraction_id, t.task_key, t.run_id,"
                " t.model_identity, t.result_note FROM analysis_tasks t"
                " JOIN kb_documents d ON d.source=t.source"
                " AND d.doc_id=t.doc_id"
                " WHERE t.status IN ('done','partial')"
                " AND UPPER(d.symbol)=UPPER(?)"
                " ORDER BY t.finished_at DESC LIMIT ?",
                (entity_id, max_analyses)).fetchall()
        else:
            analyses = []
        for row in analyses:
            evidence.append({
                "kind": "analysis", "source": row["source"],
                "doc_id": row["doc_id"], "version_id": row["version_id"],
                "extraction_id": row["extraction_id"],
                "task_key": row["task_key"], "run_id": row["run_id"],
                "model_identity": row["model_identity"],
                "text": (row["result_note"] or "")[:2000],
            })
    return evidence


def _summary_evidence(kb: KnowledgeStore, entity_type: str,
                      entity_id: str) -> List[Dict[str, Any]]:
    """Combined evidence for one entity: human-reviewed claims PLUS the
    documents' own text blocks PLUS finished analyses (R2). Claim items
    keep their historical keys (claim_id/revision/statement/...)."""
    claims = _entity_claim_evidence(kb, entity_type, entity_id)
    for claim in claims:
        claim.setdefault("kind", "claim")
    return claims + _entity_document_evidence(kb, entity_type, entity_id)


def _evidence_has_content(evidence: List[Dict[str, Any]]) -> bool:
    """Real input material only: document text, an analysis draft, or a
    claim statement. Identity-only rows (bare event records) do NOT
    count - no evidence means the summary is blocked, never an empty
    paid generation (R2)."""
    for item in evidence:
        text = (item.get("text") or item.get("statement") or "").strip()
        if text:
            return True
    return False


def build_summary_prompt(entity_type: str, entity_id: str,
                         evidence: List[Dict[str, Any]],
                         detail: Optional[Dict[str, Any]]) -> str:
    lines = [
        "You are a research assistant maintaining a company/topic memo.",
        "Summarize ONLY from the evidence below - report text, single-doc",
        "analyses and reviewed claims. Distinguish the original reports'",
        "views from system aggregation. Where evidence conflicts, present",
        "both sides with their sources; do not resolve the conflict by",
        "guessing.",
        "",
        "Entity: %s %s" % (entity_type, entity_id),
        "Update reason: %s" % json.dumps(detail or {}, ensure_ascii=False),
        "",
    ]
    for i, item in enumerate(evidence, start=1):
        kind = item.get("kind", "claim")
        if kind == "claim":
            lines.append("[%d] (claim %s rev%s, %s) %s" % (
                i, item["claim_id"], item["revision"], item["status"],
                item["statement"]))
            for ref in item["evidence"][:3]:
                lines.append("    evidence: %s/%s/%s" % (
                    ref.get("source"), ref.get("doc_id"),
                    ref.get("version_id")))
            for counter in item["counterevidence"][:2]:
                lines.append("    counter: %s" % json.dumps(
                    counter, ensure_ascii=False))
        elif kind == "document_block":
            lines.append(
                "[%d] (report %s/%s/%s extraction %s block %s page %s) %s"
                % (i, item["source"], item["doc_id"], item["version_id"],
                   item["extraction_id"], item["block_id"],
                   item.get("page", "?"), item["text"]))
        elif kind == "analysis":
            lines.append(
                "[%d] (analysis %s/%s/%s run %s model %s) %s" % (
                    i, item["source"], item["doc_id"], item["version_id"],
                    item["run_id"], item["model_identity"], item["text"]))
    return "\n".join(lines)


def record_summary(kb: KnowledgeStore, entity_type: str, entity_id: str,
                   content: str, claim_revisions: List[Dict[str, Any]],
                   model_identity: str = "disabled/no-provider",
                   blocked_reason: Optional[str] = None,
                   event_key: Optional[str] = None) -> Dict[str, Any]:
    """Append a new summary revision (history preserved)."""
    ensure_schema(kb)
    with kb._tx() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(revision),0) r FROM summaries"
            " WHERE entity_type=? AND entity_id=?",
            (entity_type, entity_id)).fetchone()
        revision = row["r"] + 1
        conn.execute(
            "INSERT INTO summaries (entity_type, entity_id, revision,"
            " status, content, evidence_claim_revisions_json, event_key,"
            " blocked_reason, model_identity, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (entity_type, entity_id, revision,
             STATUS_BLOCKED if blocked_reason else STATUS_DONE,
             content,
             json.dumps(claim_revisions, ensure_ascii=False), event_key,
             blocked_reason, model_identity, utc_now()))
    return {"entity_type": entity_type, "entity_id": entity_id,
            "revision": revision}


def enqueue_blocked_entity_refreshes(kb: KnowledgeStore) -> int:
    """Recovery path: when a provider becomes available, re-queue the
    entities whose LATEST revision is blocked so the deferred generation
    actually happens (new event_key per blocked revision - idempotent)."""
    ensure_schema(kb)
    queued = 0
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT entity_type, entity_id, MAX(revision) rev FROM"
            " summaries WHERE status='" + STATUS_BLOCKED + "'"
            " GROUP BY entity_type, entity_id").fetchall()
    for row in rows:
        with kb._lock:
            latest = kb._conn.execute(
                "SELECT status FROM summaries WHERE entity_type=? AND"
                " entity_id=? AND revision=?",
                (row["entity_type"], row["entity_id"],
                 row["rev"])).fetchone()
        if latest and latest["status"] == STATUS_BLOCKED:
            if enqueue_summary_update(
                    kb, row["entity_type"], row["entity_id"],
                    "provider_enabled_refresh",
                    {"previous_revision": row["rev"]},
                    event_key="refresh:%s:%s:%s" % (
                        row["entity_type"], row["entity_id"], row["rev"])):
                queued += 1
    return queued


def _generated_for_event(kb: KnowledgeStore, event_key: Optional[str]
                         ) -> Optional[Dict[str, Any]]:
    """R2b: find a DONE revision already persisted for this event.

    record_summary commits before the outbox row is consumed; a crash
    between the two leaves the event pending with its result durably on
    disk. Retrying must reuse that result - never re-call the provider,
    never append a second revision. (A network answer that never reached
    the disk has no such guarantee: those events stay pending and cost
    one retry - documented, not hidden.)"""
    if not event_key:
        return None
    ensure_schema(kb)
    with kb._lock:
        row = kb._conn.execute(
            "SELECT * FROM summaries WHERE event_key=? AND status=?"
            " ORDER BY revision DESC LIMIT 1",
            (event_key, STATUS_DONE)).fetchone()
    return dict(row) if row else None


def consume_updates(kb: KnowledgeStore, chat=None, ledger=None,
                    prompt_version: str = "pv1",
                    limit: int = 100) -> Dict[str, Any]:
    """Drain the summary outbox.

    - no real evidence (no document text, no analysis, no claim) -> the
      event is consumed into ONE blocked(insufficient_evidence)
      revision recording the event identity - never a paid generation
      of an empty summary (R2);
    - no provider -> blocked(model_disabled) preserving the assembled
      evidence for recovery;
    - a DONE revision already exists for the event key -> consume only
      (R2b durable-result resume: no second call, no second revision);
    - otherwise generate through the budget ledger and record a real
      revision. Provider/budget refusals leave the event pending."""
    from .budget import Budget, BudgetLedger, BudgetExceeded

    ensure_schema(kb)
    ledger = ledger or BudgetLedger(kb, Budget())
    blocked = done = reused = 0
    errors: List[Dict[str, Any]] = []
    for item in pending_updates(kb, limit):
        event_key = item.get("event_key")
        already = _generated_for_event(kb, event_key)
        if already is not None:
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE summary_outbox SET status='consumed',"
                    " consumed_at=? WHERE id=?", (utc_now(), item["id"]))
            reused += 1
            continue
        evidence = _summary_evidence(
            kb, item["entity_type"], item["entity_id"])
        if not _evidence_has_content(evidence):
            record_summary(
                kb, item["entity_type"], item["entity_id"],
                content=None,
                claim_revisions=[{"kind": "event", "event": item["reason"],
                                  "detail": item["detail"],
                                  "event_key": event_key}],
                model_identity="disabled/no-provider",
                blocked_reason="insufficient_evidence",
                event_key=event_key)
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE summary_outbox SET status='consumed',"
                    " consumed_at=? WHERE id=?", (utc_now(), item["id"]))
            blocked += 1
            continue
        if chat is None:
            record_summary(
                kb, item["entity_type"], item["entity_id"],
                content=None,
                claim_revisions=evidence,
                model_identity="disabled/no-provider",
                blocked_reason="model_disabled",
                event_key=event_key)
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE summary_outbox SET status='consumed',"
                    " consumed_at=? WHERE id=?", (utc_now(), item["id"]))
            blocked += 1
            continue
        identity = "%s/%s" % (getattr(chat, "name", "chat"),
                              getattr(chat, "model", "unknown"))
        prompt = build_summary_prompt(
            item["entity_type"], item["entity_id"], evidence,
            item["detail"])
        from .budget import estimate_tokens

        est = estimate_tokens(prompt) + 8
        gated = hasattr(chat, "attempt_ledger")
        try:
            reservation = ledger.reserve(
                "chat", est, count_request=not gated)
        except BudgetExceeded as exc:
            errors.append({"entity_id": item["entity_id"],
                           "error": str(exc)[:200]})
            continue  # stays pending; queued, not paid
        if gated:
            chat.attempt_ledger = ledger
        try:
            draft, usage = chat.complete(prompt)
        except Exception as exc:
            ledger.fail_unknown(reservation)
            errors.append({"entity_id": item["entity_id"],
                           "error": "%s: %s" % (type(exc).__name__,
                                                exc)[:200]})
            continue  # stays pending for the next cycle
        ledger.settle(reservation, usage)
        record_summary(
            kb, item["entity_type"], item["entity_id"], content=draft,
            claim_revisions=evidence, model_identity=identity,
            event_key=event_key)
        done += 1
        with kb._tx() as conn:
            conn.execute(
                "UPDATE summary_outbox SET status='consumed', consumed_at=?"
                " WHERE id=?", (utc_now(), item["id"]))
    return {"consumed": blocked + done + reused, "generated": done,
            "blocked": blocked, "reused_durable": reused,
            "remaining": len(pending_updates(kb)), "errors": errors}


def summary_history(kb: KnowledgeStore, entity_type: str,
                    entity_id: str) -> List[Dict[str, Any]]:
    ensure_schema(kb)
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT revision, status, blocked_reason, created_at,"
            " content, event_key FROM summaries WHERE entity_type=? AND"
            " entity_id=? ORDER BY revision",
            (entity_type, entity_id)).fetchall()
    return [dict(r) for r in rows]


def latest_summary(kb: KnowledgeStore, entity_type: str,
                   entity_id: str) -> Optional[Dict[str, Any]]:
    history = summary_history(kb, entity_type, entity_id)
    return history[-1] if history else None


# ------------------------------------------------------------- publish
def summary_page_filename(entity_type: str, entity_id: str,
                          revision: int) -> str:
    digest = hashlib.sha256(
        ("%s\x00%s" % (entity_type, entity_id)).encode("utf-8")
    ).hexdigest()
    return "summary-%s-r%d.md" % (digest[:20], revision)


def publish_pending_summaries(kb: KnowledgeStore, vault_dir: str,
                              base_url: str = "http://192.168.1.150:8765",
                              limit: int = 200) -> Dict[str, Any]:
    """Render one immutable page per unpublished revision into the
    generated 总结/ directory and refresh the derived index. Pages are
    append-only (human edits win); each revision gets its own file so
    history is preserved and never overwritten."""
    ensure_schema(kb)
    output = os.path.join(vault_dir, SUMMARY_DIR_NAME)
    os.makedirs(output, exist_ok=True)
    register_write_root(output)

    published = 0
    with kb._lock:
        todo = kb._conn.execute(
            "SELECT s.* FROM summaries s WHERE NOT EXISTS ("
            " SELECT 1 FROM summary_publish_log l WHERE"
            " l.entity_type=s.entity_type AND l.entity_id=s.entity_id"
            " AND l.revision=s.revision) ORDER BY s.id LIMIT ?",
            (max(1, int(limit)),)).fetchall()
    for row in todo:
        name = summary_page_filename(row["entity_type"], row["entity_id"],
                                     row["revision"])
        evidence = json.loads(row["evidence_claim_revisions_json"] or "[]")
        title = "%s %s" % ("公司" if row["entity_type"] == "company"
                           else "主题", unquote(row["entity_id"]))
        lines = [
            "# 总结：%s" % title,
            "",
            "> **机器生成，待人工审核。** 自动总结不覆盖人工确认的判断；"
            "人工确认请在人工区进行。",
            "",
            "- **状态**：%s" % ("待生成（模型未启用）"
                                if row["status"] == STATUS_BLOCKED
                                else "机器生成（待人工审核）"),
            "- **版本**：rev %d（历史版本全部保留）" % row["revision"],
            "- **模型身份**：%s" % row["model_identity"],
            "- **生成时间**：%s" % row["created_at"],
            "",
            "## 总结内容",
            "",
            (row["content"] or "（模型未启用，本版本为可恢复的阻塞记录；"
             "证据身份已保存，启用后自动重新生成。）").rstrip(),
            "",
            "## 证据（claim 修订）",
            "",
        ]
        for item in evidence[:50]:
            if "claim_id" in item:
                lines.append("- `%s` rev%s（%s）：%s" % (
                    item.get("claim_id"), item.get("revision"),
                    item.get("status"), item.get("statement", "")))
            else:
                lines.append("- 事件：%s" % json.dumps(
                    item, ensure_ascii=False))
        lines.append("")
        write_candidate(output, name, "\n".join(lines),
                        owner="summary-publisher")
        with kb._tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO summary_publish_log (entity_type,"
                " entity_id, revision, published_at) VALUES (?,?,?,?)",
                (row["entity_type"], row["entity_id"], row["revision"],
                 utc_now()))
        published += 1

    # derived index: latest revision per entity, links only files on disk
    entries: List[str] = []
    done_entities = 0
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT entity_type, entity_id, MAX(revision) rev FROM"
            " summaries GROUP BY entity_type, entity_id"
            " ORDER BY entity_type, entity_id").fetchall()
    for row in rows:
        latest = latest_summary(kb, row["entity_type"], row["entity_id"])
        name = summary_page_filename(row["entity_type"], row["entity_id"],
                                     row["rev"])
        label = "%s %s" % ("公司" if row["entity_type"] == "company"
                           else "主题", unquote(row["entity_id"]))
        if os.path.isfile(os.path.join(output, name)):
            done_entities += 1
            state = "机器生成" if latest["status"] == STATUS_DONE \
                else "待生成（模型未启用）"
            entries.append("- [%s](%s) — rev %d，%s" % (
                label, name, row["rev"], state))
        else:
            entries.append("- %s — 待发布" % label)
    lines = ["# 总结索引", "",
             "公司/主题知识总结入口；机器状态不代表人工验收。", "",
             "**实体 %d 个。**" % done_entities, ""]
    lines += entries if entries else ["（暂无总结）"]
    lines.append("")
    outcome = write_candidate(output, SUMMARY_INDEX_NAME,
                              "\n".join(lines), owner="summary-publisher",
                              refreshable=True)
    return {"published": published,
            "index_outcome": outcome["outcome"],
            "entities": done_entities}
