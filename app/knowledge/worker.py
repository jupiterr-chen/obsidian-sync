"""Knowledge worker: periodic sync/snapshot/extract/index cycle (P6-01).

Mirrors the first-layer scheduler pattern (persisted honest state with a
heartbeat so monitoring can detect a dead worker) and shares the knowledge
file lock so a scheduled cycle never races a manual command.
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from library.config import Config
from library.locking import FileLock

from .config import KnowledgeConfig
from .extract import STAGE_EXTRACT
from .indexing import build_generation
from .jobs import JobRunner
from .memory import impact_analysis
from .snapshot import SnapshotStore
from .store import KnowledgeStore, utc_now
from .sync import SyncService

HEARTBEAT_SECONDS = 15


def consume_impact_outbox(kb, limit: int = 25) -> int:
    """R15: drain the durable impact outbox in batches.

    Each pending (source, doc_id, version_id) becomes review proposals for
    claims citing the document; the row is consumed only after the
    (idempotent) analysis ran. Crash at any point leaves unconsumed rows
    for the next cycle - nothing is inferred from sync timestamps.
    """
    from .memory import impact_analysis as _impact

    created = 0
    while True:
        batch = kb.pending_impacts(limit=limit)
        if not batch:
            return created
        for row in batch:
            impact = _impact(kb, row["source"], row["doc_id"],
                             row["version_id"])
            created += len(impact["new_proposals"])
            kb.mark_impact_consumed(row["id"])


def _extraction_for(kb, row) -> Optional[str]:
    extraction = kb.latest_extraction(row["source"], row["doc_id"],
                                      row["version_id"])
    return extraction["extraction_id"] if extraction else None


def worker_state_path(knowledge_db: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(knowledge_db)) or ".",
                        "knowledge-worker.json")


def write_state(path: str, state: Dict[str, Any]) -> None:
    state = dict(state)
    state["updated_at"] = utc_now()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def read_state(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def resolve_analysis_runtime(config: KnowledgeConfig, kb=None):
    """R3: assemble the B/C provider runtime from CONFIG with an
    explicit OFF switch - the standard service entry (CLI worker /
    KnowledgeWorker), not just a Python seam.

    Returns (chat, ledger, settings). (None, None, settings) unless
    extra.analysis.enabled is true AND a chat provider resolves AND it
    is either the offline scripted provider (no network I/O - the
    verification path) or a real provider with egress_allowed=true.
    Default (no analysis key in config): DISABLED - production stays
    off until explicitly configured."""
    settings = dict((config.extra or {}).get("analysis") or {})
    if not settings.get("enabled", False):
        return None, None, settings
    # MA03: the SERVICE path always carries a scope - unconfigured
    # means an EMPTY scope (registers nothing), never an implicit wave
    settings["scope"] = settings.get("scope") or {}
    from .providers import OpenAICompatibleVision, load_providers

    chat = (load_providers(config.extra or {}) or {}).get("chat")
    if isinstance(chat, OpenAICompatibleVision):
        chat = None  # R03: a vision model never impersonates chat
    offline_script = bool(getattr(chat, "is_offline_script", False))
    if chat is None or not (offline_script
                            or getattr(chat, "egress_allowed", False)):
        return None, None, settings
    ledger = None
    if kb is not None:
        from .budget import BudgetLedger, load_budget

        ledger = BudgetLedger(kb, load_budget(config.extra or {}))
    return chat, ledger, settings


def run_cycle(config: KnowledgeConfig, library_config: Config,
              max_impact_versions: int = 25, chat=None, ledger=None,
              analysis_prompt_version: str = "pv1",
              analysis_limit: int = 5,
              analysis_scope="__unset__") -> Dict[str, Any]:
    """One full knowledge cycle. Idempotent; safe to run back-to-back.

    chat/ledger are the B/C provider seam: production passes None (tasks
    register blocked, summaries defer); offline tests and authorized
    setups inject a provider to run analysis and summarization for real.
    No provider bytes leave without both a caller-provided provider and
    its own egress/budget gates."""
    kb = KnowledgeStore(config.knowledge_db)
    lock = FileLock(os.path.join(os.path.dirname(config.knowledge_db) or ".",
                                 "knowledge.lock"))
    cycle: Dict[str, Any] = {"started_at": utc_now(), "ok": True}
    try:
        if not lock.acquire(blocking=False):
            return {"ok": False, "skipped": True,
                    "reason": "another knowledge command holds the lock"}
        try:
            # the worker owns extraction: ensure the extract stage is
            # registered even if the config only lists snapshot
            import copy as _copy

            worker_config = _copy.deepcopy(config)
            stages = list(worker_config.register_stages or ("snapshot",))
            if STAGE_EXTRACT not in stages:
                stages.append(STAGE_EXTRACT)
            worker_config.register_stages = tuple(stages)
            runner = JobRunner(kb, worker_config, library_config)
            sync = SyncService(kb, config)
            cycle["sync"] = sync.run()
            cycle["snapshots"] = runner.run_snapshot_jobs()

            # A2: bounded repair lane runs BEFORE extraction so its
            # re-registrations process in the same cycle
            from .repair import register_repair_jobs
            cycle["repair"] = register_repair_jobs(
                kb, runner.extract_digest, max_items=10)

            cycle["extracts"] = runner.run_extract_jobs()
            # TQ3: extractions recorded THIS cycle (new documents AND
            # explicit reprocess batches) feed their entities' summary
            # events - keyed per extraction so the same re-extraction
            # queues exactly once and C never stays stuck on the
            # pre-repair material after a batch lands
            from .summaries import entities_for_document, \
                enqueue_summary_update, remember_document_entities

            extraction_events = 0
            topic_rules = ((config.extra or {}).get("summarization")
                           or {}).get("topics")
            with kb._lock:
                fresh = kb._conn.execute(
                    "SELECT source, doc_id, version_id, extraction_id"
                    " FROM extractions WHERE created_at >= ?",
                    (cycle["started_at"],)).fetchall()
            for row in fresh:
                entities = entities_for_document(
                    kb, row["source"], row["doc_id"],
                    topic_rules=topic_rules)
                remember_document_entities(kb, row["source"],
                                           row["doc_id"], entities)
                for entity in entities:
                    if enqueue_summary_update(
                            kb, entity["entity_type"], entity["entity_id"],
                            "extraction_updated",
                            {"source": row["source"], "doc_id": row["doc_id"],
                             "version_id": row["version_id"],
                             "extraction_id": row["extraction_id"]},
                            event_key="extraction:%s"
                                      % row["extraction_id"]):
                        extraction_events += 1
            cycle["entity_extraction_events"] = extraction_events
            from .content import scan_new_blocks
            chart_settings = (config.extra or {}).get("chart_governance") or {}
            # The deployed config owns this switch, including disabling it.
            with kb._tx() as conn:
                conn.execute("INSERT INTO content_settings VALUES('hold_candidates',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ('true' if chart_settings.get('enabled') and chart_settings.get('hold_candidates') else 'false',))
            if chart_settings.get("enabled"):
                cycle["chart_review"] = scan_new_blocks(kb, chart_settings.get("scan_limit", 500))
            cycle["index"] = build_generation(kb)

            # A3: extraction commits become durable pending publishes; the
            # reading consumer renders notes + index after the (possibly
            # new) generation is live. Vault dir may be absent on hosts
            # that only run extraction - publishing is then skipped and
            # the outbox stays pending (consumed by the node that owns
            # the vault).
            vault_dir = (config.extra or {}).get("vault_dir")
            if vault_dir and os.path.isdir(vault_dir):
                from .reading import ReadingPublisher

                publisher = ReadingPublisher(
                    kb, vault_dir,
                    (config.extra or {}).get(
                        "public_base_url", "http://192.168.1.150:8765"))
                # Reconcile, do not window: every current version whose
                # LATEST extraction has no outbox row yet is (re)enqueued.
                # Identity includes the extraction, so a re-OCR (new
                # extraction, same version) republishes and the index
                # switches - and work that finished while the worker was
                # down (crash between extraction and publish) is picked
                # up instead of aging out of a started_at window. The
                # unique index makes re-enqueues no-ops.
                with kb._lock:
                    due = kb._conn.execute(
                        "SELECT DISTINCT j.source, j.doc_id, j.version_id"
                        " FROM jobs j"
                        " JOIN kb_versions v ON v.source=j.source"
                        " AND v.doc_id=j.doc_id AND v.version_id=j.version_id"
                        " AND v.is_current=1"
                        " WHERE j.stage='extract' AND j.status='done'"
                        " AND EXISTS (SELECT 1 FROM extractions e"
                        " WHERE e.source=j.source AND e.doc_id=j.doc_id"
                        " AND e.version_id=j.version_id AND e.rowid ="
                        " (SELECT MAX(e2.rowid) FROM extractions e2"
                        "  WHERE e2.source=e.source AND e2.doc_id=e.doc_id"
                        "  AND e2.version_id=e.version_id)"
                        " AND NOT EXISTS (SELECT 1 FROM publish_outbox p"
                        " WHERE p.source=e.source AND p.doc_id=e.doc_id"
                        " AND p.version_id=e.version_id"
                        " AND p.extraction_id=e.extraction_id))"
                    ).fetchall()
                enqueued = 0
                for row in due:
                    extraction_id = _extraction_for(kb, row)
                    if extraction_id and publisher.enqueue(
                            row["source"], row["doc_id"], row["version_id"],
                            extraction_id):
                        enqueued += 1
                cycle["reading"] = publisher.consume()
                cycle["reading"]["enqueued"] = enqueued
            else:
                cycle["reading"] = {"skipped": True,
                                    "reason": "vault_dir not configured"}

            # A20 hooks (R15): durable outbox drives impact analysis -
            # paged until empty, no time-stamp heuristics, crash-safe.
            # N3: each NEW version also maps to its entities (symbol ->
            # company) BEFORE consumption, so the FIRST document of a
            # company queues a summary event - not only claims that
            # already have review proposals.
            from .summaries import (entities_for_document,
                                    enqueue_summary_update,
                                    remember_document_entities)
            topic_rules = ((config.extra or {}).get("summarization")
                           or {}).get("topics")
            doc_events = 0
            for row in kb.pending_impacts(limit=max_impact_versions * 4):
                entities = entities_for_document(
                    kb, row["source"], row["doc_id"],
                    topic_rules=topic_rules)
                # C-topic: the doc->entity mapping is PERSISTED at event
                # time so topic evidence queries do not depend on config
                # being re-derivable later
                remember_document_entities(kb, row["source"],
                                           row["doc_id"], entities)
                for entity in entities:
                    if enqueue_summary_update(
                            kb, entity["entity_type"], entity["entity_id"],
                            "document_added",
                            {"source": row["source"], "doc_id": row["doc_id"],
                             "version_id": row["version_id"]},
                            event_key="doc:%s:%s:%s" % (
                                row["source"], row["doc_id"],
                                row["version_id"])):
                        doc_events += 1
            proposals = consume_impact_outbox(kb,
                                              limit=max_impact_versions)
            cycle["impact_proposals"] = proposals
            cycle["entity_doc_events"] = doc_events

            # N2: analysis tasks under the configured identity; with a
            # chat provider (tests/authorized setups) the executor runs,
            # otherwise tasks stay blocked(model_disabled) exactly as
            # before - enabling is an explicit step, never implicit
            from .analysis_tasks import (PLANNED_MODEL_IDENTITY,
                                         execute_analysis_tasks,
                                         register_ready_analysis_tasks,
                                         task_counts)
            if chat is not None:
                model_identity = "%s/%s" % (
                    getattr(chat, "name", "chat"),
                    getattr(chat, "model", "unknown"))
                # MA03: the SERVICE path always passes a scope; an
                # unconfigured/empty scope registers NOTHING (never an
                # implicit corpus wave toward a new model)
                analysis_settings = ((config.extra or {})
                                     .get("analysis") or {})
                scope = analysis_settings.get("scope")
                if analysis_scope != "__unset__":
                    # explicit parameter (service entry) wins - the
                    # resolver already defaulted an unconfigured scope
                    # to {} = register nothing (MA03)
                    scope = analysis_scope
                cycle["analysis_tasks"] = register_ready_analysis_tasks(
                    kb, prompt_version=analysis_prompt_version,
                    model_identity=model_identity,
                    model_name=getattr(chat, "model", None),
                    blocked_reason=None,
                    scope=scope)
                cycle["analysis_executed"] = execute_analysis_tasks(
                    kb, chat, ledger=ledger,
                    prompt_version=analysis_prompt_version,
                    limit=analysis_limit,
                    max_attempts=int(analysis_settings.get(
                        "max_attempts", 3)),
                    # S1: the claim obeys the ACTIVE identity and scope -
                    # old queues from other providers/prompts and
                    # out-of-sample documents never execute here
                    model_identity=model_identity,
                    scope=scope)
            else:
                cycle["analysis_tasks"] = register_ready_analysis_tasks(kb)
                cycle["analysis_executed"] = {"skipped": True,
                                              "reason": "model_disabled"}
            cycle["analysis_task_counts"] = task_counts(kb)

            # N3: publish finished analyses when the worker owns a vault
            vault_dir = (config.extra or {}).get("vault_dir")
            if vault_dir and os.path.isdir(vault_dir):
                from .analysis_publish import AnalysisPublisher

                analysis_publisher = AnalysisPublisher(
                    kb, vault_dir,
                    (config.extra or {}).get(
                        "public_base_url", "http://192.168.1.150:8765"))
                cycle["analysis_published"] = analysis_publisher.consume()
            else:
                cycle["analysis_published"] = {
                    "skipped": True, "reason": "vault_dir not configured"}

            # C: entities whose evidence changed (open review proposals)
            # queue a summary revision; each event keys on its proposal so
            # revisiting a proposal across cycles queues exactly once
            from .summaries import (consume_updates,
                                    enqueue_blocked_entity_refreshes,
                                    enqueue_summary_update,
                                    publish_pending_summaries)
            proposal_events = 0
            for proposal in kb.list_review_proposals(status="open"):
                detail = proposal.get("detail") or {}
                with kb._lock:
                    claim = kb._conn.execute(
                        "SELECT subject FROM claims WHERE claim_id=?",
                        (proposal["claim_id"],)).fetchone()
                subject = claim["subject"] if claim else None
                if subject:
                    if enqueue_summary_update(
                            kb, "company", subject, "evidence_changed",
                            {"proposal_id": proposal["proposal_id"],
                             "source": detail.get("source"),
                             "doc_id": detail.get("doc_id")},
                            event_key="proposal:%s" %
                            proposal["proposal_id"]):
                        proposal_events += 1
            cycle["entity_proposal_events"] = proposal_events
            # a provider enables deferred (blocked) generations to run
            if chat is not None:
                cycle["summary_refreshes"] = enqueue_blocked_entity_refreshes(
                    kb)
            # S1: with a provider active, C generates ONLY for the
            # authorized entities. The allowed set comes from the
            # summarization scope when configured; otherwise it derives
            # from the deployment's own authorization boundary - the
            # analysis scope symbols plus the configured topic rules -
            # and NEVER from "no scope found" (empty = nothing sends)
            allowed_entities = None
            allowed_documents = None
            if chat is not None:
                summarization = (config.extra or {}).get(
                    "summarization") or {}
                c_scope = summarization.get("scope")
                if c_scope is None:
                    effective_scope = analysis_settings.get("scope")
                    if analysis_scope != "__unset__":
                        effective_scope = analysis_scope
                    allowed = set()
                    for symbol in ((effective_scope or {})
                                   .get("symbols") or []):
                        allowed.add(("company",
                                     (symbol or "").strip().upper()))
                    for rule in (summarization.get("topics") or []):
                        topic_id = str((rule or {}).get("id") or "").strip()
                        if topic_id:
                            allowed.add(("topic", topic_id))
                    allowed_entities = allowed
                    doc_scope = effective_scope
                else:
                    allowed_entities = {
                        ("company", (s or "").strip().upper())
                        for s in (c_scope.get("symbols") or [])} | {
                        ("topic", (t or "").strip())
                        for t in (c_scope.get("topics") or [])}
                    doc_scope = c_scope
                # S1/SF01: the authorized DOCUMENT set comes from the
                # declared scope only (symbols + doc_ids) - topic
                # classification adds ENTITIES to summarize, never
                # documents to send
                if doc_scope is not None:
                    scope_symbols = {(s or "").strip().upper()
                                     for s in (doc_scope.get("symbols")
                                               or [])}
                    scope_docs = {(d or "").strip()
                                  for d in (doc_scope.get("doc_ids")
                                            or [])}
                    allowed_documents = set()
                    if scope_symbols or scope_docs:
                        with kb._lock:
                            rows = kb._conn.execute(
                                "SELECT source, doc_id, UPPER(symbol) sym"
                                " FROM kb_documents").fetchall()
                        for row in rows:
                            if ((scope_symbols and row["sym"] in
                                 scope_symbols)
                                    or (scope_docs and row["doc_id"] in
                                        scope_docs)):
                                allowed_documents.add(
                                    (row["source"], row["doc_id"]))
            cycle["summaries"] = consume_updates(kb, chat=chat,
                                                 ledger=ledger,
                                                 allowed_entities=
                                                 allowed_entities,
                                                 allowed_documents=
                                                 allowed_documents)
            if vault_dir and os.path.isdir(vault_dir):
                cycle["summary_published"] = publish_pending_summaries(
                    kb, vault_dir,
                    (config.extra or {}).get(
                        "public_base_url", "http://192.168.1.150:8765"))
            else:
                cycle["summary_published"] = {
                    "skipped": True, "reason": "vault_dir not configured"}
            cycle["counts"] = kb.counts()
            generation = kb.active_generation()
            cycle["generation_id"] = generation["generation_id"] if generation else None
            cycle["ok"] = bool(cycle["sync"].get("ok")) and \
                bool(cycle["snapshots"].get("ok")) and \
                bool(cycle["extracts"].get("ok")) and bool(cycle["index"].get("ok"))
        finally:
            lock.release()
    except Exception as exc:
        cycle["ok"] = False
        cycle["error"] = "%s: %s" % (type(exc).__name__, exc)
        cycle["traceback"] = traceback.format_exc()[-2000:]
    finally:
        cycle["finished_at"] = utc_now()
        kb.close()
    return cycle


class KnowledgeWorker:
    """In-process hourly cycle with persisted heartbeat state.

    R3: chat/ledger/analysis settings come from the CONFIG through
    resolve_analysis_runtime (explicit off switch) when not injected -
    the standard service entry, not just a test seam."""

    def __init__(self, config: KnowledgeConfig, library_config: Config,
                 interval_seconds: int = 3600,
                 chat=None, ledger=None, analysis_settings=None):
        self.config = config
        self.library_config = library_config
        self.interval = max(60, int(interval_seconds))
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self._started_at = utc_now()
        self._runtime_kb = None  # keeps the ledger's store alive
        if chat is None and analysis_settings is None:
            kb = KnowledgeStore(config.knowledge_db)
            try:
                chat, ledger, analysis_settings = \
                    resolve_analysis_runtime(config, kb=kb)
            except Exception:
                kb.close()
                raise
            if chat is not None:
                self._runtime_kb = kb  # ledger binds this connection
            else:
                kb.close()
        self.chat = chat
        self.ledger = ledger
        self.analysis_settings = analysis_settings or {}

    def _state_path(self) -> str:
        return worker_state_path(self.config.knowledge_db)

    def _write(self, **updates: Any) -> None:
        state = read_state(self._state_path()) or {
            "kind": "knowledge-worker",
            "interval_seconds": self.interval,
            "started_at": self._started_at,
        }
        state.update(updates)
        try:
            write_state(self._state_path(), state)
        except OSError:
            pass

    def _heartbeat(self) -> None:
        while not self.stop_event.wait(HEARTBEAT_SECONDS):
            self._write()

    def _loop(self) -> None:
        self._write(state="idle")
        settings = self.analysis_settings or {}
        while not self.stop_event.is_set():
            attempt_started = utc_now()
            self._write(state="running", attempt_started_at=attempt_started)
            try:
                cycle = run_cycle(
                    self.config, self.library_config,
                    chat=self.chat,
                    ledger=self.ledger,
                    analysis_prompt_version=str(
                        settings.get("prompt_version", "pv1")),
                    analysis_limit=int(settings.get(
                        "max_tasks_per_cycle", 5)),
                    analysis_scope=settings.get("scope"))
                self._write(state="idle", last_ok=bool(cycle.get("ok")),
                            last_error=cycle.get("error"),
                            last_cycle=cycle,
                            last_finished_at=cycle.get("finished_at"))
            except Exception as exc:  # never kill the worker thread
                self._write(state="idle", last_ok=False,
                            last_error="%s: %s" % (type(exc).__name__, exc))
            moment = datetime.now(timezone.utc)
            next_at = (moment + timedelta(seconds=self.interval)).replace(
                microsecond=0).isoformat().replace("+00:00", "Z")
            self._write(next_check_at=next_at)
            self.stop_event.wait(self.interval)

    def start(self) -> None:
        self.thread = threading.Thread(target=self._loop,
                                       name="knowledge-worker", daemon=True)
        self.thread.start()
        self.heartbeat_thread = threading.Thread(
            target=self._heartbeat, name="knowledge-heartbeat", daemon=True)
        self.heartbeat_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self._write(state="stopped", next_check_at=None)
        if self._runtime_kb is not None:
            self._runtime_kb.close()
            self._runtime_kb = None


def worker_is_stale(path: str, max_age_seconds: int = 120) -> Optional[bool]:
    """True/False freshness, None when no state file exists yet."""
    state = read_state(path)
    if not state:
        return None
    updated = state.get("updated_at")
    if not updated:
        return None
    try:
        moment = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        return None
    age = (datetime.now(timezone.utc) - moment).total_seconds()
    return age > max_age_seconds
