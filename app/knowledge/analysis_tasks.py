"""Single-document analysis pipeline (B2/B3).

N2 (Q02) closes the loop that previously ended at registration:

- registration targets the LATEST extraction of each current version
  (never an older ready extraction hiding under a newer review one) and
  uses the FULL identity (source, doc, version, extraction, model,
  prompt, template) for duplicate detection, so a prompt change
  registers a new task while an identical identity never re-registers;
- a lease-based executor claims pending tasks, analyses the document's
  OWN blocks (not a corpus search) through the budgeted
  execute_analysis_run (citation verification included), persists the
  run, and enqueues a durable publish event;
- crash recovery returns expired leases to pending; retryable failures
  re-queue, non-retryable ones fail honestly; budget exhaustion leaves
  the task pending for the next cycle (never a paid call past the cap);
- with no provider authorized, tasks stay ``blocked(model_disabled)``
  exactly as before - enabling is a separate, explicit step.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from .store import KnowledgeStore, utc_now

ANALYSIS_TEMPLATE_VERSION = "single-doc-v1"
STATUS_PENDING = "pending"
STATUS_BLOCKED = "blocked"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
# R3: sections were analysed but budget stopped coverage or the final
# synthesis - an honest partial with recorded coverage, resumable
STATUS_PARTIAL = "partial"

# model/prompt identity used BEFORE any provider exists; changing the
# planned model bumps the identity so re-analysis is explicit
PLANNED_MODEL_IDENTITY = "disabled/no-provider"

SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    extraction_id TEXT NOT NULL,
    model_identity TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    template_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    blocked_reason TEXT,
    result_note TEXT,
    run_id TEXT,
    model_name TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_until TEXT,
    error TEXT,
    coverage_json TEXT,
    publish_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE (source, doc_id, version_id, extraction_id, model_identity,
            prompt_version, template_version)
);
CREATE TABLE IF NOT EXISTS analysis_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    consumed_at TEXT
);
"""

_EXTRA_COLUMNS = (("model_name", "TEXT"),
                  ("attempts", "INTEGER NOT NULL DEFAULT 0"),
                  ("lease_until", "TEXT"),
                  ("error", "TEXT"),
                  ("coverage_json", "TEXT"),
                  ("publish_path", "TEXT"))


def ensure_schema(kb: KnowledgeStore) -> None:
    with kb._tx() as conn:
        conn.executescript(SCHEMA)
        # stores created by the first A-E delivery lack the executor
        # columns; add them idempotently (existing rows: attempts=0)
        for column, decl in _EXTRA_COLUMNS:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(analysis_tasks)").fetchall()]
            if column not in cols:
                conn.execute("ALTER TABLE analysis_tasks ADD COLUMN %s %s"
                             % (column, decl))


def task_key(source: str, doc_id: str, version_id: str, extraction_id: str,
             model_identity: str, prompt_version: str, template: str) -> str:
    identity = "\x00".join((source, doc_id, version_id, extraction_id,
                            model_identity, prompt_version, template))
    return "anl-" + hashlib.sha256(identity.encode()).hexdigest()[:32]


def register_ready_analysis_tasks(
        kb: KnowledgeStore, prompt_version: str = "pv1",
        model_identity: str = PLANNED_MODEL_IDENTITY,
        model_name: Optional[str] = None,
        blocked_reason: Optional[str] = "model_disabled") -> Dict[str, int]:
    """Register analysis tasks for the LATEST extraction of CURRENT
    versions when that latest extraction is READY (review/failed on the
    latest row excludes the document - B4; an older ready extraction
    must never be analysed as if it were current). Duplicate detection
    uses the FULL identity, so a new prompt/model/template registers a
    new task while an existing identity never re-registers."""
    ensure_schema(kb)
    registered = 0
    with kb._tx() as conn:
        rows = conn.execute(
            "SELECT v.source, v.doc_id, v.version_id, e.extraction_id,"
            " e.status FROM kb_versions v JOIN extractions e"
            " ON e.rowid = (SELECT MAX(e2.rowid) FROM extractions e2"
            "  WHERE e2.source=v.source AND e2.doc_id=v.doc_id"
            "  AND e2.version_id=v.version_id)"
            " WHERE v.is_current=1 AND e.status='ready'"
            " AND NOT EXISTS (SELECT 1 FROM analysis_tasks t"
            "  WHERE t.source=v.source AND t.doc_id=v.doc_id"
            "  AND t.version_id=v.version_id AND t.extraction_id=e.extraction_id"
            "  AND t.model_identity=? AND t.prompt_version=?"
            "  AND t.template_version=?)",
            (model_identity, prompt_version, ANALYSIS_TEMPLATE_VERSION)
        ).fetchall()
        now = utc_now()
        status = STATUS_BLOCKED if blocked_reason else STATUS_PENDING
        for row in rows:
            key = task_key(row["source"], row["doc_id"], row["version_id"],
                           row["extraction_id"], model_identity,
                           prompt_version, ANALYSIS_TEMPLATE_VERSION)
            conn.execute(
                "INSERT INTO analysis_tasks (task_key, source, doc_id,"
                " version_id, extraction_id, model_identity, prompt_version,"
                " template_version, status, blocked_reason, model_name,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(task_key) DO NOTHING",
                (key, row["source"], row["doc_id"], row["version_id"],
                 row["extraction_id"], model_identity, prompt_version,
                 ANALYSIS_TEMPLATE_VERSION, status, blocked_reason,
                 model_name, now, now))
            registered += 1
    return {"registered": registered}


# ------------------------------------------------------------- executor
def release_expired_analysis_tasks(kb: KnowledgeStore) -> int:
    """Crash recovery: a 'running' task whose lease expired returns to
    pending so the next cycle re-claims it (attempts keep counting)."""
    ensure_schema(kb)
    with kb._tx() as conn:
        cursor = conn.execute(
            "UPDATE analysis_tasks SET status=?, lease_until=NULL,"
            " updated_at=? WHERE status=? AND lease_until IS NOT NULL"
            " AND lease_until < ?",
            (STATUS_PENDING, utc_now(), STATUS_RUNNING, utc_now()))
        return cursor.rowcount


def claim_pending_analysis_tasks(kb: KnowledgeStore, limit: int = 5,
                                 lease_seconds: int = 900
                                 ) -> List[Dict[str, Any]]:
    """Atomically claim up to `limit` pending tasks under a lease.

    R3: PARTIAL tasks are claimable too - resuming continues from the
    last completed section without re-paying earlier ones."""
    ensure_schema(kb)
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    lease_until = (now + timedelta(seconds=lease_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    claimed: List[Dict[str, Any]] = []
    with kb._tx() as conn:
        rows = conn.execute(
            "SELECT * FROM analysis_tasks WHERE status IN (?,?)"
            " AND (lease_until IS NULL OR lease_until < ?)"
            " ORDER BY created_at LIMIT ?",
            (STATUS_PENDING, STATUS_PARTIAL, utc_now(),
             max(1, int(limit)))).fetchall()
        for row in rows:
            cursor = conn.execute(
                "UPDATE analysis_tasks SET status=?, lease_until=?,"
                " attempts=attempts+1, updated_at=? WHERE task_key=?"
                " AND status=?",
                (STATUS_RUNNING, lease_until, utc_now(), row["task_key"],
                 row["status"]))
            if cursor.rowcount:
                task = dict(row)
                task["status"] = STATUS_RUNNING
                task["attempts"] = (task.get("attempts") or 0) + 1
                claimed.append(task)
    return claimed


def _document_query(kb: KnowledgeStore, source: str, doc_id: str) -> str:
    with kb._lock:
        row = kb._conn.execute(
            "SELECT title, display_title FROM kb_documents"
            " WHERE source=? AND doc_id=?", (source, doc_id)).fetchone()
    from urllib.parse import unquote

    if row and (row["title"] or row["display_title"]):
        return unquote(row["title"] or row["display_title"])
    return doc_id


def _own_blocks_retriever(kb: KnowledgeStore, source: str, doc_id: str,
                          extraction_id: str, max_blocks: int = 40):
    """Single-document analysis reads the document's OWN extracted blocks
    (B2), not a corpus search; long documents are bounded by blocks.
    Blocks are enriched with source/doc_id (build_analysis_prompt's
    provenance line needs them) and returned keyword-search-shaped so
    execute_analysis_run's hit unwrapping works unchanged."""
    def retriever(query, top_k):
        limit = min(max_blocks, int(top_k) if top_k else max_blocks)
        hits = []
        for block in kb.get_blocks(extraction_id)[:limit]:
            block = dict(block)
            block.setdefault("source", source)
            block.setdefault("doc_id", doc_id)
            hits.append({"block": block, "score": 1.0})
        return hits
    return retriever


def _budgeted_complete(kb, chat, ledger, prompt, run_id=None):
    """One budgeted chat call. Returns (draft, usage); raises
    BudgetExceeded when the cap refuses the call BEFORE any bytes leave
    and ProviderCallError-family exceptions on transport failure."""
    from .budget import BudgetExceeded, estimate_tokens

    est = estimate_tokens(prompt) + 8
    gated = hasattr(chat, "attempt_ledger")
    reservation = ledger.reserve("chat", est, run_id=run_id,
                                 count_request=not gated)
    if gated:
        chat.attempt_ledger = ledger
    try:
        draft, usage = chat.complete(prompt)
    except Exception:
        ledger.fail_unknown(reservation, run_id=run_id)
        raise
    ledger.settle(reservation, usage, run_id=run_id)
    return draft, usage


def _sections(blocks: List[Dict[str, Any]], section_blocks: int
              ) -> List[List[Dict[str, Any]]]:
    """Consecutive section chunks covering EVERY block (R3/AC03: the
    tail risk section must reach the model, never a silent truncate)."""
    size = max(1, int(section_blocks))
    return [blocks[i:i + size] for i in range(0, len(blocks), size)]


def execute_analysis_tasks(kb: KnowledgeStore, chat,
                           ledger=None, prompt_version: str = "pv1",
                           limit: int = 5,
                           max_attempts: int = 3,
                           section_blocks: int = 8) -> Dict[str, Any]:
    """Claim and run pending analysis tasks.

    R3: long documents are analysed SECTION BY SECTION (consecutive
    block chunks, every block covered), each section a budgeted call.
    Completed sections persist to the task after every call, so a crash
    resumes without re-paying them. Budget exhaustion mid-document
    records an honest PARTIAL (coverage in analysis_runs.verification
    and the task row) that stays claimable for continuation; only full
    coverage (plus the synthesis over sections when there is more than
    one) marks the task done. Provider/budget refusals never send past
    the cap; non-retryable failures fail honestly."""
    from .analysis import build_analysis_prompt, verify_citations
    from .budget import Budget, BudgetLedger, BudgetExceeded

    ensure_schema(kb)
    release_expired_analysis_tasks(kb)
    ledger = ledger or BudgetLedger(kb, Budget())
    done = partial = failed = retried = 0
    errors: List[Dict[str, Any]] = []
    for task in claim_pending_analysis_tasks(kb, limit=limit):
        query = _document_query(kb, task["source"], task["doc_id"])
        blocks = kb.get_blocks(task["extraction_id"])
        sections = _sections(blocks, section_blocks)
        try:
            progress = json.loads(task["coverage_json"] or "{}") \
                if task.get("coverage_json") else {}
        except ValueError:
            progress = {}
        section_outputs = progress.get("sections") or []

        run_id = task.get("run_id")
        if not run_id:
            run = kb.create_analysis_run(
                query, mode="single-doc", prompt_version=prompt_version)
            run_id = run["run_id"]
        else:
            kb.update_analysis_run(run_id, status="running", error=None)

        budget_stop = False
        try:
            for index in range(len(sections)):
                if index < len(section_outputs):
                    continue  # already paid and durably recorded
                section = sections[index]
                section = [dict(b, source=task["source"],
                                doc_id=task["doc_id"]) for b in section]
                prompt = build_analysis_prompt(query, section)
                try:
                    draft, _usage = _budgeted_complete(
                        kb, chat, ledger, prompt, run_id=run_id)
                except BudgetExceeded as exc:
                    budget_stop = True
                    errors.append({"task_key": task["task_key"],
                                   "error": str(exc)[:300],
                                   "status": "partial"})
                    break
                verified = verify_citations(
                    draft, sorted({int(m) for m in
                                   __import__("re").findall(
                                       r"\[(\d+)\]", draft)}),
                    section)
                section_outputs.append({
                    "index": index,
                    "block_ids": [b["block_id"] for b in section],
                    "draft": draft,
                    "valid_citations": verified["valid"],
                    "all_valid": verified["all_valid"],
                })
                # durable per-section progress: a crash here resumes
                # from this section without re-paying earlier ones
                with kb._tx() as conn:
                    conn.execute(
                        "UPDATE analysis_tasks SET coverage_json=?,"
                        " run_id=?, updated_at=? WHERE task_key=?",
                        (json.dumps({"sections": section_outputs},
                                    ensure_ascii=False),
                         run_id, utc_now(), task["task_key"]))

            covered = sum(len(s["block_ids"]) for s in section_outputs)
            all_covered = len(section_outputs) == len(sections)
            synthesis = None
            synthesis_pending = False
            if all_covered and len(section_outputs) > 1:
                synth_prompt = [
                    "You are combining section analyses of ONE research",
                    "document into its single-document analysis. Keep the",
                    "cited evidence markers [n] from the sections; report",
                    "the report's core views, checkable facts, assumptions,",
                    "catalysts, risks and counter-evidence, missing",
                    "evidence. Do not invent facts beyond the sections.",
                    "",
                    "Document: %s" % query, ""]
                for output in section_outputs:
                    synth_prompt.append(
                        "== section %d (blocks %s) ==" % (
                            output["index"] + 1,
                            ",".join(output["block_ids"][:3]) + ("..." if
                             len(output["block_ids"]) > 3 else "")))
                    synth_prompt.append(output["draft"])
                    synth_prompt.append("")
                try:
                    synthesis, _usage = _budgeted_complete(
                        kb, chat, ledger, "\n".join(synth_prompt),
                        run_id=run_id)
                except BudgetExceeded as exc:
                    budget_stop = True
                    synthesis_pending = True
                    errors.append({"task_key": task["task_key"],
                                   "error": "synthesis deferred: %s"
                                   % str(exc)[:200],
                                   "status": "partial"})
        except __import__("knowledge.providers", fromlist=[
                "ProviderCallError"]).ProviderCallError as exc:
            new_status = STATUS_PENDING if exc.retryable else STATUS_FAILED
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status=?, error=?,"
                    " run_id=?, coverage_json=?, updated_at=?,"
                    " lease_until=NULL WHERE task_key=?",
                    (new_status, str(exc)[:500], run_id,
                     json.dumps({"sections": section_outputs},
                                ensure_ascii=False),
                     utc_now(), task["task_key"]))
            if new_status == STATUS_PENDING:
                retried += 1
            else:
                failed += 1
            errors.append({"task_key": task["task_key"],
                           "error": str(exc)[:300],
                           "status": new_status})
            continue
        except Exception as exc:  # transport/ledger edge cases
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status=?, error=?,"
                    " run_id=?, coverage_json=?, updated_at=?,"
                    " lease_until=NULL WHERE task_key=?",
                    (STATUS_PENDING, "%s: %s" % (type(exc).__name__,
                                                 exc)[:500],
                     run_id,
                     json.dumps({"sections": section_outputs},
                                ensure_ascii=False),
                     utc_now(), task["task_key"]))
            retried += 1
            errors.append({"task_key": task["task_key"],
                           "error": str(exc)[:300],
                           "status": "pending"})
            continue

        # single-section documents need no synthesis pass; multi-section
        # documents complete only when the synthesis also ran
        complete_now = all_covered and (len(section_outputs) <= 1
                                        or synthesis is not None)
        coverage = {
            "total_blocks": len(blocks),
            "covered_blocks": covered,
            "sections_total": len(sections),
            "sections_done": len(section_outputs),
            "partial": not complete_now,
            "synthesis_pending": synthesis_pending,
        }
        if complete_now:
            draft_final = synthesis if len(section_outputs) > 1 \
                else section_outputs[0]["draft"]
            citations = [c for output in section_outputs
                         for c in output["valid_citations"]]
            verification = {
                "all_valid": all(o["all_valid"] for o in section_outputs),
                "valid": citations,
                "invalid": [],
                "coverage": coverage,
            }
            note = "**覆盖：全部 %d 块（%d 段，完整分析）**\n\n%s" % (
                len(blocks), len(sections), draft_final)
            kb.update_analysis_run(
                run_id, status="done", draft=note,
                citations=[c for c in citations],
                verification=verification, finished_at=None, error=None)
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status=?, run_id=?,"
                    " result_note=?, finished_at=?, updated_at=?,"
                    " lease_until=NULL, coverage_json=? WHERE task_key=?",
                    (STATUS_DONE, run_id, note, utc_now(), utc_now(),
                     json.dumps({"sections": section_outputs,
                                 "coverage": coverage},
                                ensure_ascii=False), task["task_key"]))
                conn.execute(
                    "INSERT OR IGNORE INTO analysis_outbox (task_key,"
                    " status, created_at) VALUES (?, 'pending', ?)",
                    (task["task_key"], utc_now()))
            done += 1
        else:
            # honest partial: what exists is published as 待续 with its
            # coverage; the task stays claimable for continuation
            drafts = [o["draft"] for o in section_outputs]
            note = ("**部分覆盖：已分析 %d/%d 块（%d/%d 段），待续；"
                    "预算恢复后自动继续**\n\n%s" % (
                        covered, len(blocks), len(section_outputs),
                        len(sections),
                        "\n\n---\n\n".join(drafts) if drafts
                        else "（尚无已分析段落）"))
            kb.update_analysis_run(
                run_id, status="done", draft=note, citations=[],
                verification={"all_valid": None, "valid": [],
                              "invalid": [], "coverage": coverage},
                finished_at=None, error=None)
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status=?, run_id=?,"
                    " result_note=?, updated_at=?, lease_until=NULL,"
                    " coverage_json=?, error=NULL WHERE task_key=?",
                    (STATUS_PARTIAL, run_id, note, utc_now(),
                     json.dumps({"sections": section_outputs,
                                 "coverage": coverage},
                                ensure_ascii=False), task["task_key"]))
                conn.execute(
                    "INSERT OR IGNORE INTO analysis_outbox (task_key,"
                    " status, created_at) VALUES (?, 'pending', ?)",
                    (task["task_key"], utc_now()))
            partial += 1
    return {"done": done, "partial": partial, "failed": failed,
            "retried": retried, "errors": errors}


def task_counts(kb: KnowledgeStore) -> Dict[str, int]:
    ensure_schema(kb)
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT status, COUNT(*) c FROM analysis_tasks"
            " GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}
