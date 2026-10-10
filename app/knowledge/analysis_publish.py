"""Analysis-page publishing (B3): Obsidian pages for single-doc analyses.

Done analysis tasks flow through a durable analysis_outbox to an
AnalysisPublisher that renders one page per analysed document into the
generated ``分析报告/`` directory plus a derived index ``分析索引.md``.

Every page states the machine provenance (model identity, prompt and
template versions, generation time, run id), binds the analysed source
version and extraction, carries the model draft WITH its citation
verification outcome, and is explicitly marked 机器生成待人工复核 -
model output is never presented as a human-verified conclusion. Pages
are append-only through the shared writeback rules (a human edit forces
the candidate path); only the fully derived index refreshes in place.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from .store import KnowledgeStore, utc_now
from .writeback import register_write_root, write_candidate
from .analysis_tasks import (STATUS_BLOCKED, STATUS_DONE, STATUS_FAILED,
                             STATUS_PARTIAL, STATUS_PENDING,
                             STATUS_RUNNING)

ANALYSIS_DIR_NAME = "分析报告"
ANALYSIS_INDEX_NAME = "分析索引.md"


def analysis_page_filename(source: str, doc_id: str,
                           extraction_id: str) -> str:
    identity = "\x00".join((source, doc_id, extraction_id))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return "analysis-%s.md" % digest[:24]


def render_analysis_page(title: str, task: Dict[str, Any], run: Dict[str, Any],
                         block_count: int, original_url: str) -> str:
    """Markdown page for one finished analysis task. cited_blocks (from
    the publisher) carries the verbatim text of each valid citation so
    the page shows the ORIGINAL EVIDENCE the model cited, not just the
    citation numbers."""
    verification = run.get("verification") or {}
    citations = run.get("citations") or []
    cited_blocks = run.get("cited_blocks") or []

    def cite_label(c):
        return "[%s]" % (c["n"] if isinstance(c, dict) else c)

    lines = [
        "# 分析：%s" % title,
        "",
        "> **机器生成，待人工复核。** 模型输出不等于已验证的研究结论；"
        "引用校验通过只证明引用存在，不证明结论成立。",
        "",
        "- **状态**：%s" % ("分析完成（机器）" if task.get("status") == "done"
                            else task.get("status")),
        "- **模型身份**：%s" % task.get("model_identity"),
        "- **模型**：%s" % (task.get("model_name") or "未配置"),
        "- **提示词/模板**：%s / %s" % (task.get("prompt_version"),
                                        task.get("template_version")),
        "- **生成时间**：%s" % (run.get("finished_at")
                                or run.get("updated_at")),
        "- **分析运行**：`%s`" % task.get("run_id"),
        "- **源版本**：%s / %s / %s" % (task.get("source"),
                                         task.get("doc_id"),
                                         task.get("version_id")),
        "- **提取版本**：`%s`（%d 个正文块）" % (task.get("extraction_id"),
                                                 block_count),
        "- **[原文](%s)**" % original_url,
        "",
        "## 引用校验",
        "",
        "- 全部引用有效：%s" % ("是" if verification.get("all_valid")
                                 else "否"),
        "- 有效引用：%s" % (" ".join(cite_label(c) for c in citations)
                            or "无"),
    ]
    if verification.get("invalid"):
        lines.append("- 无效引用：%s" % ", ".join(
            cite_label(c) for c in verification["invalid"]))
    lines += [
        "",
        "## 模型草稿（原文引用为 [n]）",
        "",
        (run.get("draft") or "").rstrip(),
    ]
    if cited_blocks:
        lines += ["", "## 引用证据（原文块）", ""]
        for item in cited_blocks:
            lines.append("- %s（第 %s 页，`%s`）：%s" % (
                cite_label(item), item.get("page", "?"),
                item.get("block_id"), (item.get("text") or "").strip()))
    lines += [
        "",
        "## 边界",
        "",
        "- 本页由系统在提取完成后自动生成；人工批注请另存人工区或在候选中确认。",
        "- 与上一版分析的差异、尚缺证据等待后续版本补充；未验证数字不得进入高质量事实。",
        "",
    ]
    return "\n".join(lines)


class AnalysisPublisher:
    """Consumes the analysis outbox and maintains the analysis directory."""

    def __init__(self, kb: KnowledgeStore, vault_dir: str,
                 base_url: str = "http://192.168.1.150:8765"):
        self.kb = kb
        self.base_url = base_url.rstrip("/")
        self.output = os.path.join(vault_dir, ANALYSIS_DIR_NAME)
        os.makedirs(self.output, exist_ok=True)
        register_write_root(self.output)

    # ------------------------------------------------------------ outbox
    def pending(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.kb._lock:
            rows = self.kb._conn.execute(
                "SELECT * FROM analysis_outbox WHERE status='pending'"
                " ORDER BY id LIMIT ?", (max(1, int(limit)),)).fetchall()
        return [dict(r) for r in rows]

    def consume(self, limit: int = 200) -> Dict[str, Any]:
        """Publish finished analyses; rebuild the index after the batch."""
        published = skipped = 0
        for item in self.pending(limit):
            if self._publish_page_for(item["task_key"]):
                published += 1
            else:
                skipped += 1
            with self.kb._tx() as conn:
                conn.execute(
                    "UPDATE analysis_outbox SET status='consumed',"
                    " consumed_at=? WHERE id=?", (utc_now(), item["id"]))
        index = self.rebuild_index()
        return {"published": published, "skipped": skipped,
                "index_outcome": index, "pending_before": published + skipped}

    # ------------------------------------------------------------- pages
    def _original_url(self, source: str, doc_id: str,
                      version_id: str) -> str:
        from urllib.parse import quote

        return "%s/api/v1/files/%s/%s?version=%s" % (
            self.base_url, quote(source, safe=""), quote(doc_id, safe=""),
            quote(version_id, safe=""))

    def _publish_page_for(self, key: str) -> bool:
        with self.kb._lock:
            task = self.kb._conn.execute(
                "SELECT * FROM analysis_tasks WHERE task_key=?",
                (key,)).fetchone()
            if task is None or task["status"] not in (STATUS_DONE,
                                                      STATUS_PARTIAL):
                return False
            run = self.kb._conn.execute(
                "SELECT * FROM analysis_runs WHERE run_id=?",
                (task["run_id"],)).fetchone() if task["run_id"] else None
            doc = self.kb._conn.execute(
                "SELECT title FROM kb_documents WHERE source=? AND doc_id=?",
                (task["source"], task["doc_id"])).fetchone()
            block_count = self.kb._conn.execute(
                "SELECT COUNT(*) FROM blocks WHERE extraction_id=?",
                (task["extraction_id"],)).fetchone()[0]
        title = unquote((doc["title"] if doc else None)
                        or task["doc_id"])
        run_dict = dict(run) if run else {}
        run_dict["verification"] = _load_json(
            run_dict.get("verification_json"))
        run_dict["citations"] = _load_json(
            run_dict.get("citations_json")) or []
        # verbatim text of each valid citation: the page must show the
        # ORIGINAL EVIDENCE the model cited (B3), not just [n] markers
        cited_blocks = []
        for citation in run_dict["citations"]:
            block_id = (citation or {}).get("block_id") \
                if isinstance(citation, dict) else None
            if not block_id:
                continue
            with self.kb._lock:
                row = self.kb._conn.execute(
                    "SELECT b.text, b.locator_json FROM blocks b"
                    " WHERE b.block_id=?", (block_id,)).fetchone()
            if row:
                locator = _load_json(row["locator_json"]) or {}
                cited_blocks.append({
                    "n": citation.get("n"), "block_id": block_id,
                    "page": locator.get("page"),
                    "text": row["text"]})
        run_dict["cited_blocks"] = cited_blocks
        content = render_analysis_page(
            title, dict(task), run_dict, block_count,
            self._original_url(task["source"], task["doc_id"],
                               task["version_id"]))
        name = analysis_page_filename(task["source"], task["doc_id"],
                                      task["extraction_id"])
        outcome = write_candidate(self.output, name, content,
                                  owner="analysis-publisher")
        # R4: remember the path ACTUALLY written. When an older analysis
        # identity (e.g. pv1) already owns the main name, the shared
        # writeback rules preserve it and deliver this revision as a
        # candidate beside it - the index must link THAT file so every
        # published revision stays reachable, old and new.
        written = outcome.get("candidate_path") or outcome.get("path") \
            or os.path.join(self.output, name)
        with self.kb._tx() as conn:
            conn.execute(
                "UPDATE analysis_tasks SET publish_path=? WHERE"
                " task_key=?", (os.path.basename(written), key))
        return True

    def rebuild_index(self) -> Dict[str, Any]:
        """Regenerate 分析索引.md across ALL analysis tasks (derived page).

        N5 parity: a page is only linked when its file is on disk; tasks
        not yet published render as 待发布."""
        entries: List[str] = []
        done = pending_pages = 0
        with self.kb._lock:
            tasks = self.kb._conn.execute(
                "SELECT t.*, d.title FROM analysis_tasks t LEFT JOIN"
                " kb_documents d ON d.source=t.source AND d.doc_id=t.doc_id"
                " ORDER BY t.created_at").fetchall()
            for task in tasks:
                title = unquote((task["title"] if task else None)
                                or task["doc_id"])
                url = self._original_url(task["source"], task["doc_id"],
                                         task["version_id"])
                from .content import is_stale
                if is_stale(self.kb._conn, "analysis", task["run_id"]):
                    entries.append("- %s — 证据内容已修订，历史分析待重算；[原文](%s)" % (title, url))
                    continue
                # R4: link the path ACTUALLY published for THIS task
                # identity (prompt/model revisions of the same document
                # publish beside each other; the index reaches each one)
                published_name = task["publish_path"] if "publish_path" in \
                    task.keys() else None
                if task["status"] in (STATUS_DONE, STATUS_PARTIAL) \
                        and published_name \
                        and os.path.isfile(os.path.join(self.output,
                                                        published_name)):
                    if task["status"] == STATUS_DONE:
                        done += 1
                        entries.append("- [%s](%s) — %s（%s / %s）" % (
                            title, published_name, task["model_identity"],
                            task["prompt_version"], task["template_version"]))
                    else:
                        pending_pages += 1
                        entries.append(
                            "- [%s](%s) — 部分分析（待续，预算恢复后自动"
                            "继续）" % (title, published_name))
                elif task["status"] in (STATUS_DONE, STATUS_PARTIAL):
                    pending_pages += 1
                    entries.append("- %s — 待发布；[原文](%s)" % (title, url))
                elif task["status"] == STATUS_BLOCKED:
                    entries.append("- %s — 未分析（模型未启用）；[原文](%s)"
                                   % (title, url))
                elif task["status"] == STATUS_FAILED:
                    entries.append("- %s — 分析失败（%s）；[原文](%s)" % (
                        title, (task["error"] or "")[:60], url))
                elif task["status"] == STATUS_RUNNING:
                    entries.append("- %s — 分析中；[原文](%s)" % (title, url))
                else:
                    entries.append("- %s — 待分析；[原文](%s)" % (title, url))
        pending_note = ("；另有 %d 份待发布" % pending_pages
                        if pending_pages else "")
        lines = ["# 分析索引", "",
                 "单篇机器分析的入口；机器生成不代表人工验收。", "",
                 "**已完成 %d 份%s。**" % (done, pending_note), ""]
        lines += entries if entries else ["（暂无分析任务）"]
        lines += [""]
        outcome = write_candidate(self.output, ANALYSIS_INDEX_NAME,
                                  "\n".join(lines), owner="analysis-publisher",
                                  refreshable=True)
        return {"outcome": outcome["outcome"], "done": done,
                "pending_pages": pending_pages}


def _load_json(value: Optional[str]) -> Any:
    import json as _json

    try:
        return _json.loads(value) if value else None
    except (TypeError, ValueError):
        return None
