"""Reading-note rendering and durable publish pipeline (A3).

Renders extraction blocks into the human-readable ``-readable.md`` note
format (the same bytes as the one-time exporter, so reruns stay no-ops)
and maintains a durable ``publish_outbox``: an extraction commit enqueues a
pending publish; the consumer renders the note (stable identity =
source/doc/version/extraction), writes it through the writeback rules
(human edits preserved) and regenerates the ``开始阅读.md`` index, then
consumes the event. Idempotent and crash-safe.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote

from .store import KnowledgeStore, utc_now
from .writeback import register_write_root, write_candidate

READING_DIR_NAME = "解析正文"
INDEX_NAME = "开始阅读.md"

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def literal(text: str) -> str:
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    text = _CTRL_RE.sub("", text)
    return re.sub(r"([\\`*_{}\[\]()<>#!|$~])", r"\\\1", text)


def reading_filename(source: str, doc_id: str, extraction_id: str) -> str:
    identity = hashlib.sha256(
        ("%s\0%s\0%s" % (source, doc_id, extraction_id)).encode()).hexdigest()
    return "text-%s-readable.md" % identity


def render_reading_note(title: str, source: str, doc_id: str,
                        version_id: str, extraction: Dict[str, Any],
                        blocks: List[Dict[str, Any]], original_url: str) -> str:
    """Render the exact reading-note format shared with the exporter."""
    lines = ["---",
             "generated: true",
             "source: %s" % json.dumps(source, ensure_ascii=False),
             "doc_id: %s" % json.dumps(doc_id, ensure_ascii=False),
             "source_version: %s" % json.dumps(version_id, ensure_ascii=False),
             "extraction_id: %s" % json.dumps(extraction["extraction_id"],
                                               ensure_ascii=False),
             "extraction_status: %s" % json.dumps(extraction["status"],
                                                   ensure_ascii=False),
             "extracted_at: %s" % json.dumps(extraction["created_at"],
                                              ensure_ascii=False),
             "---", "", "# " + literal(title), "",
             "> 已有提取结果的阅读副本，不是新生成的研究结论。OCR 可能有错字、漏字；数字和表格请对照原文。",
             "",
             "- 解析状态：`%s`（ready 仅为机器状态，不代表人工验收）" % extraction["status"],
             "- [打开这一版本原文](%s)" % original_url,
             "- 提取版本：`%s`" % extraction["extraction_id"], ""]
    hidden = sum(len(_CTRL_RE.findall(block["text"])) for block in blocks)
    if hidden:
        lines += ["> 此阅读副本省略了 %d 个不可显示的控制字符；数据库原文未改动。这不是 OCR 修复，请对照 PDF 复核。" % hidden, ""]
    page = None
    for block in blocks:
        locator = block.get("locator") or json.loads(block.get("locator_json") or "{}")
        current_page = locator.get("page")
        if current_page is not None and current_page != page:
            lines += ["## 第 %s 页" % current_page,
                      "[对照 PDF 本页](%s#page=%s)" % (original_url, current_page), ""]
            page = current_page
        lines += [literal(block["text"]), "", "^" + block["block_id"], ""]
    return "\n".join(lines)


def render_index(entries: List[str], absent: List[str],
                 published: int, without_text: int,
                 pending_publish: int = 0) -> str:
    pending_note = ("；另有 %d 份正文待发布（下一轮自动完成）" % pending_publish
                    if pending_publish else "")
    lines = ["# 解析正文目录", "",
             "这里显示服务器已经保存的最新提取正文；新增研报处理完成后自动更新。",
             "原来的“资料目录”卡片仍负责元数据和原文访问。人工研究请写在原人工区，不要直接改本生成区。", "",
             "**正文 %d 份%s；当前版本缺少正文 %d 份。**" % (
                 published, pending_note, without_text), "",
             "ready：机器检查通过；review：需要复核；failed：提取失败或不完整。它们都不等于人工确认正确。", "",
             "## 已有正文", ""]
    lines += entries
    lines += ["", "## 当前没有正文", ""]
    lines += absent
    lines += [""]
    return "\n".join(lines)


class ReadingPublisher:
    """Consumes the publish outbox and maintains the reading directory."""

    def __init__(self, kb: KnowledgeStore, vault_dir: str,
                 base_url: str = "http://192.168.1.150:8765"):
        self.kb = kb
        self.base_url = base_url.rstrip("/")
        self.output = os.path.join(vault_dir, READING_DIR_NAME)
        os.makedirs(self.output, exist_ok=True)
        register_write_root(self.output)

    # ------------------------------------------------------------ outbox
    def enqueue(self, source: str, doc_id: str, version_id: str,
                extraction_id: str) -> bool:
        """Idempotent: the unique identity index collapses re-enqueues
        (crash healing, worker restarts) into one pending row."""
        with self.kb._tx() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO publish_outbox (source, doc_id,"
                " version_id, extraction_id, status, created_at)"
                " VALUES (?,?,?,?, 'pending', ?)",
                (source, doc_id, version_id, extraction_id, utc_now()))
            return cursor.rowcount > 0

    def pending(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self.kb._lock:
            rows = self.kb._conn.execute(
                "SELECT * FROM publish_outbox WHERE status='pending'"
                " ORDER BY id LIMIT ?", (max(1, int(limit)),)).fetchall()
        return [dict(r) for r in rows]

    def consume(self, limit: int = 200, rebuild_index_every: int = 50) -> Dict[str, Any]:
        """Publish pending notes; rebuild the index after the batch."""
        published = skipped = 0
        batch = self.pending(limit)
        for item in batch:
            note = self._publish_note_for(item)
            if note:
                published += 1
            else:
                skipped += 1
            with self.kb._tx() as conn:
                conn.execute(
                    "UPDATE publish_outbox SET status='consumed',"
                    " consumed_at=? WHERE id=?", (utc_now(), item["id"]))
        index = self.rebuild_index()
        return {"published": published, "skipped": skipped,
                "index_outcome": index, "pending_before": len(batch)}

    # ------------------------------------------------------------ notes
    def _original_url(self, source: str, doc_id: str, version_id: str) -> str:
        return "%s/api/v1/files/%s/%s?version=%s" % (
            self.base_url, quote(source, safe=""), quote(doc_id, safe=""),
            quote(version_id, safe=""))

    def _publish_note_for(self, item: Dict[str, Any]) -> bool:
        extraction = self.kb.get_extraction(item["extraction_id"])
        if extraction is None:
            return False
        blocks = [b for b in self.kb.get_blocks(item["extraction_id"])
                  if b["text"].strip()]
        if not blocks:
            return False  # no readable text; the index lists it as absent
        with self.kb._lock:
            doc = self.kb._conn.execute(
                "SELECT title FROM kb_documents WHERE source=? AND doc_id=?",
                (item["source"], item["doc_id"])).fetchone()
        title = unquote((doc["title"] if doc else None) or item["doc_id"])
        content = render_reading_note(
            title, item["source"], item["doc_id"], item["version_id"],
            extraction, blocks, self._original_url(
                item["source"], item["doc_id"], item["version_id"]))
        name = reading_filename(item["source"], item["doc_id"],
                                item["extraction_id"])
        write_candidate(self.output, name, content, owner="reading-publisher")
        return True

    def rebuild_index(self) -> Dict[str, Any]:
        """Regenerate 开始阅读.md from current versions (read-only scan).

        N5/Q04: a note is only LINKED when its file is on disk. Batches
        are bounded (consume(limit)), so notes still queued for publish
        render as 待发布 with the original-document link instead of a
        dangling markdown link; the next consume completes them.
        """
        entries: List[str] = []
        absent: List[str] = []
        published = pending_publish = without = 0
        with self.kb._lock:
            versions = self.kb._conn.execute(
                "SELECT v.source, v.doc_id, v.version_id, d.title"
                " FROM kb_versions v JOIN kb_documents d"
                " ON d.source=v.source AND d.doc_id=v.doc_id"
                " WHERE v.is_current=1 ORDER BY v.source, v.doc_id").fetchall()
            for version in versions:
                extraction = self.kb._conn.execute(
                    "SELECT extraction_id, status FROM extractions"
                    " WHERE source=? AND doc_id=? AND version_id=?"
                    " ORDER BY rowid DESC LIMIT 1",
                    (version["source"], version["doc_id"],
                     version["version_id"])).fetchone()
                title = unquote(version["title"] or version["doc_id"])
                url = self._original_url(version["source"], version["doc_id"],
                                         version["version_id"])
                if extraction is None:
                    without += 1
                    absent.append("- %s — 未提取；[原文](%s)" % (literal(title), url))
                    continue
                block_count = self.kb._conn.execute(
                    "SELECT COUNT(*) FROM blocks WHERE extraction_id=?"
                    " AND LENGTH(TRIM(text)) > 0",
                    (extraction["extraction_id"],)).fetchone()[0]
                if not block_count:
                    without += 1
                    absent.append("- %s — %s；[原文](%s)" % (
                        literal(title), extraction["status"], url))
                    continue
                name = reading_filename(version["source"], version["doc_id"],
                                        extraction["extraction_id"])
                if not os.path.isfile(os.path.join(self.output, name)):
                    # text exists but this batch has not published the
                    # note yet: visible as pending, never a dead link
                    pending_publish += 1
                    entries.append(
                        "- %s — 待发布（下一轮自动发布）；[原文](%s)" % (
                            literal(title), url))
                    continue
                published += 1
                entries.append("- [%s](%s) — %s" % (
                    literal(title), name, extraction["status"]))
        content = render_index(entries, absent, published, without,
                               pending_publish)
        # index/status pages are fully derived: refreshable lets the entry
        # switch as content changes, guarded by the manifest hash proof
        # (any human edit forces the candidate path instead)
        outcome = write_candidate(self.output, INDEX_NAME, content,
                                  owner="reading-publisher", refreshable=True)
        # A4: processing-status page - every current version with its
        # stage (未发现/未提取/无正文/ready/review/failed) so users never
        # need hash filenames to know where a report is stuck
        status_lines = ["# 处理状态", "",
                        "每个当前版本的处理阶段；机器状态不代表人工验收。", ""]
        for entry in entries + absent:
            status_lines.append(entry)
        status_outcome = write_candidate(self.output, "处理状态.md",
                                         "\n".join(status_lines) + "\n",
                                         owner="reading-publisher",
                                         refreshable=True)
        return {"outcome": outcome["outcome"], "published": published,
                "without_text": without, "pending_publish": pending_publish,
                "status_outcome": status_outcome["outcome"]}
