"""Versioned chart-content projections. Raw blocks remain immutable.

Classification is a proposal, never permission to erase a page. Activation
accepts only reviewed, source/hash-bound character spans and image assets.
All default consumers use project_block; historical evidence reads stay raw.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone

POLICY = "chart-content-v1"
CONTENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_projections (
 projection_id TEXT PRIMARY KEY, block_id TEXT NOT NULL REFERENCES blocks(block_id),
 manifest_json TEXT NOT NULL, text_sha256 TEXT NOT NULL, projected_text TEXT NOT NULL,
 created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS content_projection_heads (
 block_id TEXT PRIMARY KEY REFERENCES blocks(block_id), projection_id TEXT NOT NULL
 REFERENCES content_projections(projection_id), updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS content_projection_events (
 event_id INTEGER PRIMARY KEY, block_id TEXT NOT NULL, old_projection_id TEXT,
 new_projection_id TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS content_invalidations (
 kind TEXT NOT NULL, object_id TEXT NOT NULL, event_id INTEGER NOT NULL,
 reason TEXT NOT NULL, PRIMARY KEY(kind,object_id,event_id));
CREATE TABLE IF NOT EXISTS chart_review_queue (
 block_id TEXT PRIMARY KEY REFERENCES blocks(block_id), text_sha256 TEXT NOT NULL,
 signals_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS content_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def now():
    return datetime.now(timezone.utc).isoformat()


def has_table(conn, name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                             (name,)).fetchone())


def revision(conn):
    if not has_table(conn, "content_projection_heads"):
        return ""
    rows = conn.execute("SELECT block_id,projection_id FROM content_projection_heads"
                        " ORDER BY block_id").fetchall()
    return digest(canonical([list(r) for r in rows])) if rows else ""


def chart_signals(text):
    """Bounded triage only; false positives (especially tables) are expected."""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if re.search(r"图表目录|圖表目錄|list of (?:figures|tables)", text, re.I):
        return {"kind": "navigation", "requires_review": False}
    captions = len(re.findall(r"(?im)^\s*(?:图(?:表)?|圖(?:表)?|figure|fig\.?|chart|exhib[iIl]t)\s*\d+", text))
    numeric = [bool(len(x) <= 30 and re.fullmatch(r"[\s\d.,%％+−\-–—()（）:/年月日]+", x)) for x in lines]
    run = longest = 0
    for flag in numeric:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    count = sum(numeric)
    risk = (captions > 0 and count >= 8) or (count >= 24 and longest >= 8)
    return {"kind": "chart_or_table_candidate" if risk else "unclassified",
            "requires_review": risk, "caption_count": captions,
            "numeric_lines": count, "longest_numeric_run": longest}


def validate_manifest(conn, manifest):
    """Pure read; reject stale identities, ambiguous edits and unsafe assets."""
    m = json.loads(canonical(manifest))
    if m.get("policy") != POLICY or m.get("review_state") != "confirmed" or not m.get("reviewer"):
        raise ValueError("projection requires confirmed reviewer and policy")
    row = conn.execute("SELECT b.*,e.source,e.doc_id,e.version_id,e.snapshot_sha256"
                       " FROM blocks b JOIN extractions e ON e.extraction_id=b.extraction_id"
                       " WHERE b.block_id=?", (m.get("block_id"),)).fetchone()
    if row is None:
        raise ValueError("unknown block")
    raw = dict(row)
    for key in ("source", "doc_id", "version_id", "extraction_id", "snapshot_sha256"):
        if m.get(key) != raw[key]:
            raise ValueError("source identity mismatch: " + key)
    text = raw["text"]
    if m.get("text_sha256") != digest(text):
        raise ValueError("stale block text")
    loc = json.loads(raw["locator_json"])
    if type(m.get("page")) is not int or m["page"] < 1 or m["page"] != loc.get("page"):
        raise ValueError("physical page mismatch")
    if m.get("mapping_method") not in ("reviewed-exact-spans", "visually-reviewed-exact-spans", "pdf-character-bbox-exact-whitespace-normalized"):
        raise ValueError("reviewed text mapping method required")
    if m.get("coordinate_system") != "normalized-top-left":
        raise ValueError("unknown coordinate system")
    regions = m.get("regions") or []
    if not regions:
        raise ValueError("regions required")
    ids = set(); excluded = []; protected = []; assets = []
    for region in regions:
        rid = region.get("id")
        if not rid or rid in ids:
            raise ValueError("duplicate or missing region id")
        ids.add(rid)
        kind = region.get("kind")
        if kind not in ("chart", "table", "narrative", "navigation", "unknown"):
            raise ValueError("invalid region kind")
        bbox = region.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4 or not all(
                type(x) in (int, float) and math.isfinite(x) for x in bbox):
            raise ValueError("invalid bbox")
        if not (0 <= bbox[0] < bbox[2] <= 1 and 0 <= bbox[1] < bbox[3] <= 1):
            raise ValueError("bbox outside page")
        for span in region.get("spans", []):
            start, end = span.get("start"), span.get("end")
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                raise ValueError("invalid character span")
            if span.get("sha256") != digest(text[start:end]):
                raise ValueError("span hash mismatch")
            action = span.get("action", "keep")
            if action == "exclude":
                if kind != "chart" or region.get("review_state") != "confirmed":
                    raise ValueError("only confirmed chart fragments may be excluded")
                if span.get("role") not in ("axis", "legend", "unassigned_value"):
                    raise ValueError("unknown chart fragment role")
                excluded.append((start, end))
            elif action == "keep":
                protected.append((start, end))
            else:
                raise ValueError("invalid span action")
        asset = region.get("asset")
        if kind == "chart":
            if not asset or not re.fullmatch(r"[0-9a-f]{64}", asset.get("sha256", "")):
                raise ValueError("chart image required")
            if asset.get("name") != asset["sha256"] + ".png":
                raise ValueError("asset must use content-addressed PNG name")
            caption = region.get("caption", "")
            if not caption or caption not in text:
                raise ValueError("caption must be an exact source-text excerpt")
            assets.append({**asset, "caption": caption, "region_id": rid,
                           "bbox": bbox, "page": m["page"]})
    excluded.sort()
    if any(a[1] > b[0] for a, b in zip(excluded, excluded[1:])):
        raise ValueError("overlapping exclusions")
    if any(a < d and c < b for a, b in excluded for c, d in protected):
        raise ValueError("exclusion overlaps protected prose or table")
    pieces = []; pos = 0
    for start, end in excluded:
        pieces.extend((text[pos:start], "\n")); pos = end
    pieces.append(text[pos:])
    projected = "".join(pieces)
    # A chart remains discoverable even when its caption lived in the
    # excluded range; this is verbatim source metadata, never invented data.
    for asset in assets:
        if asset["caption"] not in projected:
            projected += "\n" + asset["caption"]
    return {"manifest": m, "projection_id": "cp-" + digest(canonical(m)),
            "text": projected, "assets": assets, "excluded_characters": sum(b-a for a,b in excluded)}


def _references(value, block_id, extraction_id):
    if isinstance(value, dict):
        if value.get("block_id") == block_id or value.get("extraction_id") == extraction_id:
            return True
        return any(_references(v, block_id, extraction_id) for v in value.values())
    if isinstance(value, list):
        return any(_references(v, block_id, extraction_id) for v in value)
    return False


def _invalidate(conn, block_id, event_id):
    eid = conn.execute("SELECT extraction_id FROM blocks WHERE block_id=?", (block_id,)).fetchone()[0]
    targets = [("analysis_runs", "run_id", "citations_json", "analysis"),
               ("claims", "claim_id", "evidence_json", "claim"),
               ("claims", "claim_id", "counterevidence_json", "claim"),
               ("summaries", "id", "evidence_claim_revisions_json", "summary")]
    for table, identity, evidence, kind in targets:
        if not has_table(conn, table):
            continue
        columns = {r[1] for r in conn.execute("PRAGMA table_info(" + table + ")")}
        if not {identity, evidence} <= columns:
            continue
        version_column = ",current_revision" if kind == "claim" else ""
        for row in conn.execute("SELECT " + identity + "," + evidence + version_column + " FROM " + table).fetchall():
            if _references(json.loads(row[1] or "[]"), block_id, eid):
                conn.execute("INSERT OR IGNORE INTO content_invalidations VALUES(?,?,?,?)",
                             (kind, str(row[0]) + ("@"+str(row[2]) if kind == "claim" else ""), event_id, "chart_content_changed"))
    if has_table(conn, "analysis_tasks"):
        for r in conn.execute("SELECT run_id FROM analysis_tasks WHERE extraction_id=? AND run_id IS NOT NULL", (eid,)):
            conn.execute("INSERT OR IGNORE INTO content_invalidations VALUES(?,?,?,?)",
                         ("analysis", r[0], event_id, "chart_content_changed"))
        conn.execute("UPDATE analysis_tasks SET status='blocked',blocked_reason='content_changed',lease_until=NULL WHERE extraction_id=? AND status NOT IN ('done','partial')", (eid,))
    # Summaries can cite a claim/run without repeating its block identity.
    if has_table(conn, "summaries"):
        stale = {(r[0], str(r[1])) for r in conn.execute(
            "SELECT kind,object_id FROM content_invalidations")}
        for r in conn.execute("SELECT id,evidence_claim_revisions_json FROM summaries").fetchall():
            evidence = json.loads(r[1] or "[]")
            if any(("claim", str(e.get("claim_id"))+"@"+str(e.get("revision"))) in stale or
                   ("analysis", str(e.get("run_id"))) in stale for e in evidence):
                conn.execute("INSERT OR IGNORE INTO content_invalidations VALUES(?,?,?,?)",
                             ("summary", str(r[0]), event_id, "chart_dependency_changed"))
    # Re-render through the existing guarded publisher; crash recovery can
    # resume pending work. Assets must be verified before this transaction.
    conn.execute("INSERT OR IGNORE INTO publish_outbox(source,doc_id,version_id,extraction_id,status,created_at) SELECT source,doc_id,version_id,extraction_id,'pending',? FROM extractions WHERE extraction_id=?", (now(), eid))
    conn.execute("UPDATE publish_outbox SET status='pending',consumed_at=NULL WHERE extraction_id=?", (eid,))


def activate(kb, manifest, asset_root, expected_revision=None):
    from pathlib import Path
    with kb._tx() as conn:
        if expected_revision is not None and revision(conn) != expected_revision:
            raise ValueError("content revision changed since dry-run")
        plan = validate_manifest(conn, manifest)
        root = Path(asset_root).resolve()
        if root != (Path(kb.path).resolve().parent / "chart-assets"):
            raise ValueError("assets must live beside this database in chart-assets")
        for asset in plan["assets"]:
            path = root / asset["name"]
            if path.resolve().parent != root or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
                raise ValueError("missing or changed chart asset")
            from PIL import Image
            with Image.open(path) as image:
                if image.format != "PNG":
                    raise ValueError("asset is not PNG")
                image.verify()
        bid = manifest["block_id"]; pid = plan["projection_id"]
        old = conn.execute("SELECT projection_id FROM content_projection_heads WHERE block_id=?", (bid,)).fetchone()
        if old and old[0] == pid:
            return {"projection_id": pid, "changed": False}
        conn.execute("INSERT OR IGNORE INTO content_projections VALUES(?,?,?,?,?,?)",
                     (pid, bid, canonical(plan["manifest"]), manifest["text_sha256"], plan["text"], now()))
        conn.execute("INSERT INTO content_projection_heads VALUES(?,?,?) ON CONFLICT(block_id) DO UPDATE SET projection_id=excluded.projection_id,updated_at=excluded.updated_at", (bid,pid,now()))
        event = conn.execute("INSERT INTO content_projection_events(block_id,old_projection_id,new_projection_id,created_at) VALUES(?,?,?,?)", (bid,old[0] if old else None,pid,now())).lastrowid
        _invalidate(conn,bid,event)
        conn.execute("UPDATE chart_review_queue SET status='resolved' WHERE block_id=?",(bid,))
    return {"projection_id": pid, "changed": True}


def rollback(kb, block_id, expected_projection_id):
    """CAS rollback of the pointer only; later edits never get overwritten."""
    with kb._tx() as conn:
        row=conn.execute("SELECT projection_id FROM content_projection_heads WHERE block_id=?",(block_id,)).fetchone()
        if not row or row[0] != expected_projection_id:
            raise ValueError("projection changed since rollback was planned")
        event=conn.execute("SELECT old_projection_id FROM content_projection_events WHERE block_id=? AND new_projection_id=? ORDER BY event_id DESC LIMIT 1",(block_id,row[0])).fetchone()
        previous=event[0] if event else None
        if previous:
            conn.execute("UPDATE content_projection_heads SET projection_id=?,updated_at=? WHERE block_id=?",(previous,now(),block_id))
        else:
            conn.execute("DELETE FROM content_projection_heads WHERE block_id=?",(block_id,))
        eid=conn.execute("INSERT INTO content_projection_events(block_id,old_projection_id,new_projection_id,created_at) VALUES(?,?,?,?)",(block_id,row[0],previous,now())).lastrowid
        _invalidate(conn,block_id,eid)
    return {"restored_projection_id":previous,"changed":True}


def extraction_has_held_candidate(conn, extraction_id):
    """Whether hold mode blocks any unprojected candidate in this extraction."""
    if not has_table(conn, "content_settings"):
        return False
    setting=conn.execute("SELECT value FROM content_settings WHERE key='hold_candidates'").fetchone()
    if not setting or setting[0] != "true":
        return False
    rows=conn.execute("SELECT b.block_id,b.text FROM blocks b WHERE b.extraction_id=?",(extraction_id,)).fetchall()
    return any(not (has_table(conn,"content_projection_heads") and conn.execute(
        "SELECT 1 FROM content_projection_heads WHERE block_id=?",(r[0],)).fetchone())
        and chart_signals(r[1])["requires_review"] for r in rows)


def project_block(conn, block, as_of=None, projection_id=None):
    item=dict(block)
    if not has_table(conn,"content_projection_heads"):
        return item
    row=conn.execute("SELECT p.* FROM content_projection_heads h JOIN content_projections p ON p.projection_id=h.projection_id WHERE h.block_id=?",(item["block_id"],)).fetchone()
    if as_of:
        event=conn.execute("SELECT new_projection_id FROM content_projection_events WHERE block_id=? AND julianday(created_at)<=julianday(?) ORDER BY event_id DESC LIMIT 1",(item["block_id"],as_of)).fetchone()
        row=conn.execute("SELECT * FROM content_projections WHERE projection_id=?",(event[0],)).fetchone() if event and event[0] else None
    if projection_id:
        row=conn.execute("SELECT * FROM content_projections WHERE projection_id=? AND block_id=?",(projection_id,item["block_id"])).fetchone()
        if row is None:
            raise ValueError("projection does not belong to this block")
    if not row:
        return item
    if digest(item.get("text", "")) != row["text_sha256"] and not (
            item.get("projection_id") == row["projection_id"] and
            item.get("text") == row["projected_text"]):
        raise ValueError("projection source changed")
    m=json.loads(row["manifest_json"])
    item["text"]=row["projected_text"]
    item["projection_id"]=row["projection_id"]
    item["raw_text_sha256"]=row["text_sha256"]
    item["chart_assets"]=[{**r["asset"],"caption":r["caption"],"bbox":r["bbox"],"page":m["page"]} for r in m["regions"] if r["kind"]=="chart"]
    for asset in item["chart_assets"]:
        asset["url"] = "/api/kb/v1/evidence/%s/charts/%s?projection=%s" % (item["block_id"], asset["name"], row["projection_id"])
    item["content_policy"]=POLICY
    return item


def project_blocks(conn, blocks, as_of=None):
    return [project_block(conn,b,as_of=as_of) for b in blocks]


def is_stale(conn, kind, object_id, version=None):
    if not has_table(conn,"content_invalidations"):
        return False
    identity = str(object_id) + ("@"+str(version) if version is not None else "")
    if kind == "claim" and version is None:
        return bool(conn.execute("SELECT 1 FROM content_invalidations WHERE kind='claim' AND (object_id=? OR substr(object_id,1,?)=?) LIMIT 1", (identity, len(identity)+1, identity+'@')).fetchone())
    return bool(conn.execute("SELECT 1 FROM content_invalidations WHERE kind=? AND object_id=? LIMIT 1",(kind,identity)).fetchone())


def evidence_current(conn, value):
    """Reject evidence that cannot be tied to the currently safe content."""
    if isinstance(value, dict):
        if value.get("block_id"):
            if has_table(conn, "content_projection_heads"):
                row=conn.execute("SELECT projection_id FROM content_projection_heads WHERE block_id=?", (value["block_id"],)).fetchone()
                if value.get("projection_id") != (row[0] if row else None):
                    return False
            setting=conn.execute("SELECT value FROM content_settings WHERE key='hold_candidates'").fetchone() if has_table(conn,"content_settings") else None
            if setting and setting[0] == "true" and not value.get("projection_id"):
                row=conn.execute("SELECT text FROM blocks WHERE block_id=?",(value["block_id"],)).fetchone()
                if row and chart_signals(row[0])["requires_review"]:
                    return False
        elif value.get("extraction_id") or value.get("source") and value.get("doc_id"):
            # A coarse reference cannot prove that it avoids a projected
            # block or a page held for review. Fail closed only when one of
            # its identified extractions actually contains such a block.
            clauses=[]; params=[]
            if value.get("extraction_id"):
                clauses.append("e.extraction_id=?"); params.append(value["extraction_id"])
            else:
                clauses.extend(("e.source=?","e.doc_id=?")); params.extend((value["source"],value["doc_id"]))
                if value.get("version_id"):
                    clauses.append("e.version_id=?"); params.append(value["version_id"])
            rows=conn.execute("SELECT b.block_id,b.text,b.extraction_id FROM blocks b JOIN extractions e USING(extraction_id) WHERE " + " AND ".join(clauses),params).fetchall()
            if rows:
                projected=has_table(conn,"content_projection_heads") and any(
                    conn.execute("SELECT 1 FROM content_projection_heads WHERE block_id=?",(r[0],)).fetchone() for r in rows)
                setting=conn.execute("SELECT value FROM content_settings WHERE key='hold_candidates'").fetchone() if has_table(conn,"content_settings") else None
                held=bool(setting and setting[0] == "true" and any(chart_signals(r[1])["requires_review"] for r in rows))
                if projected or held:
                    return False
        return all(evidence_current(conn, v) for v in value.values())
    if isinstance(value,list):
        return all(evidence_current(conn, v) for v in value)
    return True


def scan_new_blocks(kb, limit=500):
    """Idempotent review queue for newly extracted pages; no guessed removal."""
    with kb._tx() as conn:
        rows=conn.execute("SELECT b.block_id,b.text FROM blocks b LEFT JOIN chart_review_queue q ON q.block_id=b.block_id WHERE q.block_id IS NULL ORDER BY b.rowid LIMIT ?", (max(1,min(int(limit),5000)),)).fetchall()
        pending=0
        for row in rows:
            signals=chart_signals(row["text"])
            state="pending" if signals["requires_review"] else "not_flagged"
            conn.execute("INSERT INTO chart_review_queue VALUES(?,?,?,?,?)",(row["block_id"],digest(row["text"]),canonical(signals),state,now()))
            pending+=state=="pending"
    return {"scanned":len(rows),"new_pending":pending}


def consumer_blocks(kb, blocks):
    """One gate for default factual consumers, including custom retrievers.

    Reload authoritative bytes before projection: a stale caller/cache must
    neither bypass a new head nor cause a double-projection hash error.
    Optional hold mode triages unreviewed pages synchronously, so a bounded
    queue scan is never a window during which new fragments enter a model.
    """
    from .quality import block_evidence_usable
    result = []
    with kb._lock:
        setting = kb._conn.execute("SELECT value FROM content_settings WHERE key='hold_candidates'").fetchone()
        hold = bool(setting and setting[0] == 'true')
        for block in blocks:
            item = dict(block)
            raw = kb._conn.execute("SELECT text FROM blocks WHERE block_id=?", (item["block_id"],)).fetchone()
            if raw is None:
                continue
            item["text"] = raw[0]
            for key in ("projection_id", "chart_assets", "content_policy", "raw_text_sha256"):
                item.pop(key, None)
            item = project_block(kb._conn, item)
            if not block_evidence_usable(item["text"])[0]:
                continue
            if hold and not item.get("projection_id") and chart_signals(item["text"])["requires_review"]:
                # A confirmed all-keep manifest is the way to release a table
                # false positive; no source text is removed or rewritten.
                continue
            result.append(item)
    return result


def evidence_url(block):
    url = "/api/kb/v1/evidence/" + block["block_id"]
    return url + "?projection=" + block["projection_id"] if block.get("projection_id") else url


def context_current(kb, blocks):
    current = consumer_blocks(kb, blocks)
    return [(b["block_id"], digest(b["text"])) for b in current] == [
        (b["block_id"], digest(b["text"])) for b in blocks]


def dependency_report(conn):
    return [dict(r) for r in conn.execute(
        "SELECT kind,object_id,event_id,reason FROM content_invalidations ORDER BY event_id,kind,object_id")]
