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
    task_key TEXT NOT NULL,
    result_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    consumed_at TEXT,
    UNIQUE (task_key, result_hash)
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
        # MA01 forward migration: the outbox identity widens from
        # task_key to (task_key, result_hash) so a partial->done revision
        # publishes again. SQLite cannot alter a UNIQUE constraint: detect
        # the old shape, copy every row (data preserved), swap atomically
        # inside this transaction.
        info = conn.execute("PRAGMA table_info(analysis_outbox)").fetchall()
        if info and "result_hash" not in [r[1] for r in info]:
            conn.execute(
                "CREATE TABLE analysis_outbox_new (id INTEGER PRIMARY KEY"
                " AUTOINCREMENT, task_key TEXT NOT NULL, result_hash TEXT"
                " NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT"
                " 'pending', created_at TEXT NOT NULL, consumed_at TEXT,"
                " UNIQUE (task_key, result_hash))")
            conn.execute(
                "INSERT INTO analysis_outbox_new (id, task_key,"
                " result_hash, status, created_at, consumed_at)"
                " SELECT id, task_key, '', status, created_at, consumed_at"
                " FROM analysis_outbox")
            conn.execute("DROP TABLE analysis_outbox")
            conn.execute("ALTER TABLE analysis_outbox_new RENAME TO"
                         " analysis_outbox")
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


def enqueue_result_publish(kb: KnowledgeStore, key: str,
                           result_note: Optional[str]) -> bool:
    """MA01: one publish event PER RESULT REVISION.

    The event identity is (task_key, result_hash): a published partial
    followed by a done (or further partial) revision enqueues a NEW
    event, so the Obsidian page and index reach the CURRENT result
    instead of staying on the first published draft. Replays of the
    same content hash are no-ops; old pages are never overwritten."""
    ensure_schema(kb)
    digest = hashlib.sha256((result_note or "").encode(
        "utf-8")).hexdigest()
    with kb._tx() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO analysis_outbox (task_key, result_hash,"
            " status, created_at) VALUES (?,?,'pending',?)",
            (key, digest, utc_now()))
        return cursor.rowcount > 0


def register_ready_analysis_tasks(
        kb: KnowledgeStore, prompt_version: str = "pv1",
        model_identity: str = PLANNED_MODEL_IDENTITY,
        model_name: Optional[str] = None,
        blocked_reason: Optional[str] = "model_disabled",
        scope: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """Register analysis tasks for the LATEST extraction of CURRENT
    versions when that latest extraction is READY (review/failed on the
    latest row excludes the document - B4; an older ready extraction
    must never be analysed as if it were current). Duplicate detection
    uses the FULL identity, so a new prompt/model/template registers a
    new task while an existing identity never re-registers.

    MA03 allowlist: the SERVICE entry (worker/CLI via
    resolve_analysis_runtime) always passes a scope -
    {"symbols": [...], "doc_ids": [...]} - and an EMPTY scope registers
    NOTHING (reported as scope_required): the authorized-sample rule is
    enforced on the config path, never left to per-cycle limits, and
    the corpus is never implicitly queued for a new model. scope=None
    keeps the direct programmatic API (tests, probes, explicit batch
    tooling) - the caller then owns the sample choice; the worker never
    uses that mode. blocked registrations (no provider) are inert and
    need no scope."""
    ensure_schema(kb)
    if blocked_reason is None and scope is not None:
        symbols = {(s or "").strip().upper()
                   for s in (scope.get("symbols") or [])}
        doc_ids = {(d or "").strip()
                   for d in (scope.get("doc_ids") or [])}
        if not symbols and not doc_ids:
            return {"registered": 0, "scope_required": True,
                    "note": "analysis.scope (symbols/doc_ids) must list"
                            " the authorized sample; nothing registered"}
    else:
        symbols = doc_ids = None
    registered = 0
    with kb._tx() as conn:
        rows = conn.execute(
            "SELECT v.source, v.doc_id, v.version_id, e.extraction_id,"
            " e.status, d.symbol FROM kb_versions v JOIN extractions e"
            " ON e.rowid = (SELECT MAX(e2.rowid) FROM extractions e2"
            "  WHERE e2.source=v.source AND e2.doc_id=v.doc_id"
            "  AND e2.version_id=v.version_id)"
            " JOIN kb_documents d ON d.source=v.source AND d.doc_id=v.doc_id"
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
            if symbols is not None:
                symbol = (row["symbol"] or "").strip().upper()
                if symbol not in symbols and row["doc_id"] not in doc_ids:
                    continue  # outside the authorized sample
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
                                 lease_seconds: int = 900,
                                 max_attempts: int = 3,
                                 model_identity: Optional[str] = None,
                                 prompt_version: Optional[str] = None,
                                 scope: Optional[Dict[str, Any]] = None
                                 ) -> List[Dict[str, Any]]:
    """Atomically claim up to `limit` pending tasks under a lease.

    R3: PARTIAL tasks are claimable too - resuming continues from the
    last completed section without re-paying earlier ones.

    MA03: retries are BOUNDED - a pending task at/over max_attempts is
    terminally failed here (attempts, lease and error state preserved),
    and the lease grows linearly with attempts so retries back off
    across cycles instead of hammering a failing provider.

    S1: the claim obeys the ACTIVE execution context. With a
    model_identity/prompt_version filter, only tasks registered under
    THAT identity are claimable - an old queue from a previous
    provider/prompt never executes under a new configuration. With a
    scope ({"symbols", "doc_ids"}), only in-scope documents are
    claimable; an EMPTY scope claims nothing. scope=None keeps the
    direct programmatic API (tests/explicit batch tooling own their
    sample); the worker never uses that mode."""
    ensure_schema(kb)
    from datetime import datetime, timedelta, timezone

    with kb._tx() as conn:
        conn.execute(
            "UPDATE analysis_tasks SET status=?, error=?, lease_until=NULL,"
            " finished_at=?, updated_at=? WHERE status=? AND attempts >= ?",
            (STATUS_FAILED, "max_attempts_exceeded", utc_now(), utc_now(),
             STATUS_PENDING, max(1, int(max_attempts))))
    symbols = doc_ids = None
    if scope is not None:
        symbols = {(s or "").strip().upper()
                   for s in (scope.get("symbols") or [])}
        doc_ids = {(d or "").strip()
                   for d in (scope.get("doc_ids") or [])}
        if not symbols and not doc_ids:
            return []  # empty scope: nothing is authorized to execute
    now = datetime.now(timezone.utc)
    claimed: List[Dict[str, Any]] = []
    with kb._tx() as conn:
        sql = ("SELECT t.* FROM analysis_tasks t"
               " JOIN kb_documents d ON d.source=t.source"
               " AND d.doc_id=t.doc_id"
               " WHERE t.status IN (?,?)"
               " AND (t.lease_until IS NULL OR t.lease_until < ?)")
        params: List[Any] = [STATUS_PENDING, STATUS_PARTIAL, utc_now()]
        if model_identity is not None:
            sql += " AND t.model_identity=?"
            params.append(model_identity)
        if prompt_version is not None:
            sql += " AND t.prompt_version=?"
            params.append(prompt_version)
        if symbols is not None:
            sql += (" AND (UPPER(d.symbol) IN (%s) OR t.doc_id IN (%s))"
                    % (",".join("?" for _ in symbols) or "''",
                       ",".join("?" for _ in doc_ids) or "''"))
            params.extend(sorted(symbols))
            params.extend(sorted(doc_ids))
        sql += " ORDER BY t.created_at LIMIT ?"
        params.append(max(1, int(limit)))
        rows = conn.execute(sql, params).fetchall()
        for row in rows:
            # linear backoff: attempt n waits n * base seconds
            lease_until = (now + timedelta(
                seconds=lease_seconds * max(1, (row["attempts"] or 0) + 1)
            )).strftime("%Y-%m-%dT%H:%M:%SZ")
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
    TQ2: binary-polluted blocks never enter a prompt - they stay in the
    vault for diagnosis and TQ3 reprocessing. Blocks are enriched with
    source/doc_id (build_analysis_prompt's provenance line needs them)
    and returned keyword-search-shaped so execute_analysis_run's hit
    unwrapping works unchanged."""
    from .quality import block_evidence_usable

    def retriever(query, top_k):
        limit = min(max_blocks, int(top_k) if top_k else max_blocks)
        hits = []
        for block in kb.get_blocks(extraction_id):
            usable, _why = block_evidence_usable(block.get("text", ""))
            if not usable:
                continue
            if len(hits) >= limit:
                break
            block = dict(block)
            block.setdefault("source", source)
            block.setdefault("doc_id", doc_id)
            hits.append({"block": block, "score": 1.0})
        return hits
    return retriever


class _PerRunCapExceeded(Exception):
    """MA03: one call's input exceeds the per-run token cap. Raised
    BEFORE any reservation or provider bytes leave."""


def _budgeted_complete(kb, chat, ledger, prompt, run_id=None,
                       budget=None):
    """One budgeted chat call. Returns (draft, usage); raises
    BudgetExceeded when the cap refuses the call BEFORE any bytes leave
    and ProviderCallError-family exceptions on transport failure.

    MA03: the SINGLE-CALL input cap (max_input_tokens_per_run) is
    enforced here too - the old execute_analysis_run checked it, the
    sectioned path must not bypass it. _PerRunCapExceeded signals the
    caller to split the section or record a partial/blocked result
    without sending."""
    from .budget import BudgetExceeded, estimate_tokens

    est = estimate_tokens(prompt) + 8
    per_run = getattr(budget, "max_input_tokens_per_run", None) \
        if budget is not None else None
    if per_run and est > per_run:
        raise _PerRunCapExceeded(
            "per-run input cap: %d > %d tokens" % (est, per_run))
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


def _split_section(section: List[Dict[str, Any]]
                   ) -> List[List[Dict[str, Any]]]:
    """Halve a section (MA03: token-capped sections split instead of
    being skipped); a single oversized block is returned whole for the
    caller to fail honestly."""
    if len(section) <= 1:
        return [section]
    middle = len(section) // 2
    return [section[:middle], section[middle:]]


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
                           section_blocks: int = 8,
                           model_identity: Optional[str] = None,
                           scope: Optional[Dict[str, Any]] = None
                           ) -> Dict[str, Any]:
    """Claim and run pending analysis tasks.

    R3: long documents are analysed SECTION BY SECTION (consecutive
    block chunks, every block covered), each section a budgeted call.
    Completed sections persist to the task after every call, so a crash
    resumes without re-paying them. Budget exhaustion mid-document
    records an honest PARTIAL (coverage in analysis_runs.verification
    and the task row) that stays claimable for continuation; only full
    coverage (plus the synthesis over sections when there is more than
    one) marks the task done. Provider/budget refusals never send past
    the cap; non-retryable failures fail honestly.

    S1: with model_identity/scope supplied, ONLY tasks of that identity
    and that authorized sample are claimed (including PARTIAL resumes)
    - an old queue from a previous provider/prompt never executes under
    a new configuration, and an empty scope executes nothing."""
    from .analysis import build_analysis_prompt, verify_citations
    from .budget import Budget, BudgetLedger, BudgetExceeded

    ensure_schema(kb)
    release_expired_analysis_tasks(kb)
    ledger = ledger or BudgetLedger(kb, Budget())
    done = partial = failed = retried = 0
    errors: List[Dict[str, Any]] = []
    for task in claim_pending_analysis_tasks(
            kb, limit=limit, max_attempts=max_attempts,
            model_identity=model_identity,
            prompt_version=prompt_version, scope=scope):
        query = _document_query(kb, task["source"], task["doc_id"])
        all_blocks = kb.get_blocks(task["extraction_id"])
        # TQ2: binary-polluted blocks (byte-decoded glyph indexes) are
        # not valid analysis evidence - excluded from the prompt. They
        # remain visible in the vault for diagnosis and TQ3 reprocessing
        from .quality import block_evidence_usable

        blocks, excluded = [], 0
        for block in all_blocks:
            usable, _why = block_evidence_usable(block.get("text", ""))
            if usable:
                blocks.append(block)
            else:
                excluded += 1
        if not blocks:
            # every block is polluted: nothing analysable - honest
            # failure, never an empty "done" analysis
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status=?, error=?,"
                    " lease_until=NULL, updated_at=? WHERE task_key=?",
                    (STATUS_FAILED, "no_usable_evidence_all_blocks_damaged",
                     utc_now(), task["task_key"]))
            failed += 1
            errors.append({"task_key": task["task_key"],
                           "error": "no_usable_evidence", "status":
                           STATUS_FAILED})
            continue
        sections = _sections(blocks, section_blocks)
        # MA02: evidence numbers are GLOBAL across the document - block n
        # keeps [n] in every section prompt, in the synthesis and in the
        # final verification map, so [3] always means the same block
        global_numbers = {block["block_id"]: index + 1
                          for index, block in enumerate(blocks)}
        # MA03: pre-split any section whose prompt exceeds the per-run
        # input cap (stable section order -> stable resume progress)
        per_run_cap = getattr(ledger.budget,
                              "max_input_tokens_per_run", None)
        if per_run_cap:
            from .budget import estimate_tokens

            def section_over_cap(section):
                probe = _numbered_prompt(query, [
                    (block, global_numbers[block["block_id"]])
                    for block in section])
                return estimate_tokens(probe) + 8 > per_run_cap

            oversized_single = False
            for index in range(len(sections)):
                while section_over_cap(sections[index]):
                    if len(sections[index]) <= 1:
                        oversized_single = True
                        break
                    halves = _split_section(sections[index])
                    sections[index:index + 1] = halves
            if oversized_single:
                with kb._tx() as conn:
                    conn.execute(
                        "UPDATE analysis_tasks SET status=?, error=?,"
                        " lease_until=NULL, finished_at=?, updated_at=?"
                        " WHERE task_key=?",
                        (STATUS_FAILED,
                         "block_exceeds_per_run_cap:%d" % per_run_cap,
                         utc_now(), utc_now(), task["task_key"]))
                failed += 1
                errors.append({"task_key": task["task_key"],
                               "error": "block exceeds per-run cap",
                               "status": STATUS_FAILED})
                continue
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
                prompt = _numbered_prompt(query, [
                    (block, global_numbers[block["block_id"]])
                    for block in section])
                try:
                    draft, _usage = _budgeted_complete(
                        kb, chat, ledger, prompt, run_id=run_id,
                        budget=ledger.budget)
                except BudgetExceeded as exc:
                    budget_stop = True
                    errors.append({"task_key": task["task_key"],
                                   "error": str(exc)[:300],
                                   "status": "partial"})
                    break
                # section-level verification against the GLOBAL numbers
                cited = sorted({int(m) for m in __import__("re").findall(
                    r"\[(\d+)\]", draft)})
                section_ns = {global_numbers[b["block_id"]]
                              for b in section}
                valid_ns = [n for n in cited if n in section_ns]
                invalid_ns = [n for n in cited if n not in section_ns]
                citations = [{
                    "n": n,
                    "block_id": blocks[n - 1]["block_id"],
                    "source": task["source"],
                    "doc_id": task["doc_id"],
                    "evidence_url": "/api/kb/v1/evidence/%s"
                                    % blocks[n - 1]["block_id"],
                } for n in valid_ns]
                section_outputs.append({
                    "index": index,
                    "block_ids": [b["block_id"] for b in section],
                    "draft": draft,
                    "valid_citations": citations,
                    "invalid_citations": invalid_ns,
                    "all_valid": not invalid_ns,
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
                    "document into its single-document analysis. The",
                    "evidence markers [n] are GLOBAL document block",
                    "numbers - keep them exactly; report the report's",
                    "core views, checkable facts, assumptions, catalysts,",
                    "risks and counter-evidence, missing evidence. Do",
                    "not invent facts beyond the sections.",
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
                        run_id=run_id, budget=ledger.budget)
                except _PerRunCapExceeded:
                    # synthesis input over the cap: keep the verified
                    # sections as an honest partial, never send oversized
                    budget_stop = True
                    synthesis_pending = True
                    errors.append({"task_key": task["task_key"],
                                   "error": "synthesis over per-run cap",
                                   "status": "partial"})
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
            # F3: a provider FAILURE backs off for real - the task
            # cannot be re-claimed until its attempt-scaled
            # next-attempt time passes (lease_until), distinguishing it
            # from budget waits which retry on the next cycle
            lease_value = "NULL"
            if new_status == STATUS_PENDING:
                from datetime import datetime, timedelta, timezone

                backoff = timedelta(
                    seconds=900 * max(1, task.get("attempts") or 1))
                lease_value = (datetime.now(timezone.utc)
                               + backoff).strftime("%Y-%m-%dT%H:%M:%SZ")
            with kb._tx() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status=?, error=?,"
                    " run_id=?, coverage_json=?, updated_at=?,"
                    " lease_until=? WHERE task_key=?",
                    (new_status,
                     ("retry_backoff: %s" % str(exc)[:480])
                     if new_status == STATUS_PENDING
                     else str(exc)[:500],
                     run_id,
                     json.dumps({"sections": section_outputs},
                                ensure_ascii=False),
                     utc_now(), lease_value, task["task_key"]))
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
        # MA03: budget stopped before ANY section ran - stay queued, an
        # empty partial has nothing to resume from
        if budget_stop and not section_outputs and not complete_now:
            with kb._tx() as conn:
                # F3/SF05: waiting for budget is NOT a provider failure -
                # refund the claim's attempt so budget waits can never
                # exhaust the failure-retry allowance
                conn.execute(
                    "UPDATE analysis_tasks SET status=?, error=?,"
                    " run_id=?, updated_at=?, lease_until=NULL,"
                    " attempts=MAX(0, attempts-1) WHERE task_key=?",
                    (STATUS_PENDING, "budget_exhausted_before_first_section",
                     run_id, utc_now(), task["task_key"]))
            retried += 1
            errors.append({"task_key": task["task_key"],
                           "error": "budget exhausted (queued)",
                           "status": "pending"})
            continue
        coverage = {
            "total_blocks": len(all_blocks),
            "excluded_damaged_blocks": excluded,
            "covered_blocks": covered,
            "sections_total": len(sections),
            "sections_done": len(section_outputs),
            "partial": not complete_now,
            "synthesis_pending": synthesis_pending,
        }
        if complete_now:
            draft_final = synthesis if len(section_outputs) > 1 \
                else section_outputs[0]["draft"]
            # MA02: the FINAL text is re-verified against the GLOBAL
            # number map - [999] is invalid no matter how valid every
            # section was; citations resolve to real block ids
            cited_final = sorted({int(m) for m in __import__(
                "re").findall(r"\[(\d+)\]", draft_final)})
            valid_final = [n for n in cited_final
                           if 1 <= n <= len(blocks)]
            invalid_final = [n for n in cited_final
                             if not (1 <= n <= len(blocks))]
            citations = [{
                "n": n,
                "block_id": blocks[n - 1]["block_id"],
                "source": task["source"],
                "doc_id": task["doc_id"],
                "evidence_url": "/api/kb/v1/evidence/%s"
                                % blocks[n - 1]["block_id"],
            } for n in valid_final]
            sections_all_valid = all(o.get("all_valid", True)
                                     for o in section_outputs)
            verification = {
                "all_valid": (not invalid_final) and sections_all_valid,
                "valid": citations,
                "invalid": invalid_final,
                "section_invalid": [n for o in section_outputs
                                    for n in o.get("invalid_citations",
                                                   [])],
                "coverage": coverage,
                "verified_against": "global block numbering v1",
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
            done += 1
            # MA01: a NEW result revision publishes again, and the
            # entity's summary updates from the fresh analysis evidence
            enqueue_result_publish(kb, task["task_key"], note)
            _notify_entities_of_result(kb, task, note)
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
            partial += 1
            # MA01: partials publish too (marked 待续); a later revision
            # (further sections or done) publishes again by result hash
            enqueue_result_publish(kb, task["task_key"], note)
    return {"done": done, "partial": partial, "failed": failed,
            "retried": retried, "errors": errors}


def _numbered_prompt(query: str, numbered_blocks) -> str:
    """Section prompt with GLOBAL block numbers (MA02): block 17 is [17]
    in its section, in the synthesis and in the final verification."""
    lines = [
        "You are a research assistant. Answer strictly using the numbered",
        "evidence blocks below. Cite every factual statement as [n] - n is",
        "the DOCUMENT-WIDE block number shown on each block. If the",
        "evidence does not support a number, say unknown instead of",
        "guessing.",
        "",
        "Question: %s" % query,
        "",
    ]
    for block, number in numbered_blocks:
        lines.append("[%d] (%s/%s page %s) %s" % (
            number, block.get("source", ""), block.get("doc_id", ""),
            (block.get("locator") or {}).get("page", "?"),
            block.get("text", "")))
    return "\n".join(lines)


def _notify_entities_of_result(kb, task, note: str) -> int:
    """MA01: B's completed revision feeds the entity summaries - a
    second analysis round can never leave a company summary stuck on
    round-one material. Event key includes the result hash, so each
    revision queues exactly once."""
    import hashlib as _hashlib

    from .summaries import entities_for_document, enqueue_summary_update

    result_hash = _hashlib.sha256(
        (note or "").encode("utf-8")).hexdigest()
    queued = 0
    for entity in entities_for_document(kb, task["source"],
                                        task["doc_id"]):
        if enqueue_summary_update(
                kb, entity["entity_type"], entity["entity_id"],
                "analysis_completed",
                {"source": task["source"], "doc_id": task["doc_id"],
                 "version_id": task["version_id"],
                 "task_key": task["task_key"]},
                event_key="analysis:%s:%s" % (task["task_key"],
                                              result_hash)):
            queued += 1
    return queued


def task_counts(kb: KnowledgeStore) -> Dict[str, int]:
    ensure_schema(kb)
    with kb._lock:
        rows = kb._conn.execute(
            "SELECT status, COUNT(*) c FROM analysis_tasks"
            " GROUP BY status").fetchall()
    return {r["status"]: r["c"] for r in rows}
