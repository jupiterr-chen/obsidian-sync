"""Evidence links for Obsidian cards (P3-04).

Generates evidence-link manifests and Markdown fragments for documents that
have extractions. Output goes to knowledge-owned locations or API payloads -
this module never writes into the synchronized Vault; the first-layer
markdown renderer stays untouched (human-area protection, A15).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .store import KnowledgeStore

MAX_LINKS_PER_DOC = 50
PREFERRED_TYPES = ("heading", "paragraph", "table")


def evidence_links_for_document(kb: KnowledgeStore, source: str, doc_id: str,
                                version_id: Optional[str] = None) -> Dict[str, Any]:
    """Evidence URLs for a document's latest extraction blocks."""
    if version_id is None:
        with kb._lock:
            row = kb._conn.execute(
                "SELECT version_id FROM kb_versions WHERE source=? AND doc_id=?"
                " AND is_current=1", (source, doc_id)).fetchone()
        if row is None:
            return {"source": source, "doc_id": doc_id, "links": [],
                    "reason": "no_current_version"}
        version_id = row["version_id"]
    extraction = kb.latest_extraction(source, doc_id, version_id)
    if extraction is None:
        return {"source": source, "doc_id": doc_id, "version_id": version_id,
                "links": [], "reason": "no_extraction"}
    blocks = kb.get_blocks(extraction["extraction_id"])
    ordered = sorted(
        blocks,
        key=lambda b: (PREFERRED_TYPES.index(b["block_type"])
                       if b["block_type"] in PREFERRED_TYPES else len(PREFERRED_TYPES),
                       b["ordinal"]),
    )[:MAX_LINKS_PER_DOC]
    ordered.sort(key=lambda b: b["ordinal"])
    links = [{
        "block_id": b["block_id"],
        "block_type": b["block_type"],
        "text_preview": b["text"][:120],
        "locator": b["locator"],
        "quality": b["quality"],
        "evidence_url": "/api/kb/v1/evidence/%s" % b["block_id"],
        "source_version": version_id,
        "extraction_id": extraction["extraction_id"],
    } for b in ordered]
    return {
        "source": source, "doc_id": doc_id, "version_id": version_id,
        "extraction_id": extraction["extraction_id"],
        "extraction_status": extraction["status"],
        "links": links,
    }


def render_evidence_index_markdown(links: Dict[str, Any]) -> str:
    """Markdown fragment listing evidence links for one document.

    Consumed by the P6 app integration / card generator; written only to
    knowledge-owned generated directories, never the human vault.
    """
    title = "%s/%s" % (links.get("source"), links.get("doc_id"))
    lines = ["## 证据索引 - %s" % title, ""]
    if not links.get("links"):
        lines.append("- （暂无可用证据：%s）" % links.get("reason", "none"))
        return "\n".join(lines) + "\n"
    lines.append("- 源版本：`%s`" % links.get("version_id"))
    lines.append("- 提取：`%s`（%s）" % (links.get("extraction_id"),
                                        links.get("extraction_status")))
    lines.append("")
    for link in links["links"]:
        locator = link.get("locator") or {}
        where = ""
        if locator.get("kind") == "pdf" and locator.get("page"):
            where = "第 %d 页" % locator["page"]
        elif locator.get("kind") == "html":
            where = locator.get("dom_path", "")
        preview = link["text_preview"].replace("\n", " ")
        lines.append("- [%s|%s] %s (%s) → %s" % (
            link["block_type"], where or locator.get("kind", "?"), preview,
            link["quality"]["status"], link["evidence_url"]))
    return "\n".join(lines) + "\n"
