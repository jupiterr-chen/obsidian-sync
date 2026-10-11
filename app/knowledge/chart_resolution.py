"""Read-only diagnostics for GLM chart proposals; never confirms or activates them."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from .content import chart_signals
from .chart_batch import MODEL, ENDPOINT, validate_regions, _candidate_identity

REPORT_SCHEMA = "chart-batch-proposals/1"
CANDIDATE_SCHEMA = "chart-batch-candidates/1"
STATUS_SET = {"valid", "invalid_json_or_schema", "truncated", "unknown_dispatch",
              "provider_http_error", "wrong_model", "invalid_source", "runner_error"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return json.load(handle)


def _iou(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1-x0) * max(0.0, y1-y0)
    area_a = (a[2]-a[0]) * (a[3]-a[1]); area_b = (b[2]-b[0]) * (b[3]-b[1])
    return inter / (area_a + area_b - inter) if area_a + area_b > inter else 0.0


def _hungarian_max(weights):
    """Maximum-weight square assignment, O(n^3), deterministic on ties."""
    n = len(weights)
    if not n:
        return []
    max_w = max(max(row) for row in weights)
    # Hungarian minimum-cost implementation (1-indexed potentials).
    u = [0] * (n+1); v = [0] * (n+1); p = [0] * (n+1); way = [0] * (n+1)
    for i in range(1, n+1):
        p[0] = i; j0 = 0; minv = [float("inf")] * (n+1); used = [False] * (n+1)
        while True:
            used[j0] = True; i0 = p[j0]; delta = float("inf"); j1 = 0
            for j in range(1, n+1):
                if not used[j]:
                    cur = max_w - weights[i0-1][j-1] - u[i0] - v[j]
                    if cur < minv[j]: minv[j] = cur; way[j] = j0
                    if minv[j] < delta: delta = minv[j]; j1 = j
            for j in range(n+1):
                if used[j]: u[p[j]] += delta; v[j] -= delta
                else: minv[j] -= delta
            j0 = j1
            if p[j0] == 0: break
        while True:
            j1 = way[j0]; p[j0] = p[j1]; j0 = j1
            if j0 == 0: break
    result = [None] * n
    for j in range(1, n+1):
        if p[j]: result[p[j]-1] = j-1
    return result


def compare_regions(first, second):
    """Return diagnostic reasons using a global spatial assignment, not greedy order."""
    a, b = first.get("regions", []), second.get("regions", [])
    reasons = set()
    if len(a) != len(b): reasons.add("region_count_difference")
    n = max(len(a), len(b))
    if not n:
        return sorted(reasons), {"charts_consistent": True, "chart_pair_count": 0}
    weights = []
    for i in range(n):
        row = []
        for j in range(n):
            if i >= len(a) or j >= len(b):
                row.append(0)
            else:
                overlap = _iou(a[i]["bbox"], b[j]["bbox"])
                valid_pair = a[i]["kind"] == b[j]["kind"] and overlap >= .5
                row.append((1000000000 if valid_pair else 0) + round(overlap*10000))
        weights.append(row)
    assignment = _hungarian_max(weights)
    pairs = [(i, j) for i, j in enumerate(assignment) if i < len(a) and j is not None and j < len(b)]
    paired_charts_a, paired_charts_b = set(), set()
    chart_a = {i for i, r in enumerate(a) if r["kind"] == "chart"}
    chart_b = {j for j, r in enumerate(b) if r["kind"] == "chart"}
    for i, j in pairs:
        overlap = _iou(a[i]["bbox"], b[j]["bbox"])
        ka, kb = a[i]["kind"], b[j]["kind"]
        if ka == "chart" and kb == "chart" and overlap >= .5:
            paired_charts_a.add(i); paired_charts_b.add(j)
        if ka != kb:
            reasons.add("region_category_difference")
            if {ka, kb} == {"chart", "table"} and overlap >= .25:
                reasons.add("chart_table_conflict")
        elif overlap < .5:
            reasons.add("chart_location_difference" if ka == "chart" else "region_location_difference")
    # A category conflict must not disappear because the optimal same-kind
    # assignment paired each region with a different overlapping neighbor.
    for i in chart_a:
        for j, other in enumerate(b):
            if other["kind"] == "table" and _iou(a[i]["bbox"], other["bbox"]) >= .25:
                reasons.add("chart_table_conflict")
    for j in chart_b:
        for i, other in enumerate(a):
            if other["kind"] == "table" and _iou(other["bbox"], b[j]["bbox"]) >= .25:
                reasons.add("chart_table_conflict")
    if len(paired_charts_a) != len(chart_a) or len(paired_charts_b) != len(chart_b):
        if chart_a or chart_b:
            reasons.add("chart_location_difference" if len(chart_a) == len(chart_b) else "chart_count_difference")
    charts_consistent = len(paired_charts_a) == len(chart_a) == len(chart_b)
    if charts_consistent and (len(a) != len(b) or any(a[i]["kind"] != b[j]["kind"] or _iou(a[i]["bbox"], b[j]["bbox"]) < .5 for i,j in pairs)):
        reasons.add("chart_consistent_other_region_difference")
    if not chart_a and not chart_b and a and b and all(r["kind"] in {"table", "narrative", "navigation"} for r in a+b):
        reasons.add("no_chart_table_or_body_only")
    return sorted(reasons), {"charts_consistent": charts_consistent,
        "chart_pair_count": len(paired_charts_a), "matched_region_count": len(pairs)}


def _proposal_reasons(proposal):
    rounds = [proposal.get("round_1"), proposal.get("round_2")]
    reasons = set()
    valid = [r for r in rounds if isinstance(r, dict) and r.get("status") == "valid"]
    if len(valid) < 2:
        for r in rounds:
            if not isinstance(r, dict): reasons.add("missing_round")
            elif r.get("status") == "unknown_dispatch": reasons.add("unknown_dispatch")
            elif r.get("status") != "valid": reasons.add("invalid_or_truncated_round")
    if len(valid) == 2:
        diff, metrics = compare_regions(valid[0]["classification"], valid[1]["classification"])
        reasons.update(diff)
    else:
        metrics = {"charts_consistent": None, "chart_pair_count": None, "matched_region_count": None}
    return sorted(reasons), metrics


def discover_inputs(operation: Path):
    operation = Path(operation)
    reports = []
    pilot = sorted((operation/"pilot-run-v2").glob("proposals-*.json"))
    merged = operation/"remaining/continuation-v3/merged-batch-001.json"
    batch2 = operation/"remaining/continuation-v3/remaining/batch-002/run"
    if len(pilot) != 1: raise ValueError("expected exactly one pilot-run-v2 proposal report")
    if not merged.is_file(): raise ValueError("merged-batch-001 report missing")
    reports.extend(pilot); reports.append(merged)
    for ordinal in range(2, 10):
        base = (operation/"remaining/continuation-v3" if ordinal == 2 else operation/"remaining/continuation-v3-http")
        folder = base/"remaining"/("batch-%03d" % ordinal)/"run"
        found = sorted(folder.glob("proposals-*.json"))
        if len(found) != 1: raise ValueError("expected one proposal report for batch-%03d" % ordinal)
        reports.extend(found)
    return reports


def _manifest_for_report(path: Path, operation: Path):
    path = Path(path); candidates = []
    if path.name == "merged-batch-001.json":
        candidates = [operation/"remaining/batch-001/manifest.json"]
    elif path.parent.name == "run" and path.parent.parent.name.startswith("batch-"):
        candidates = [path.parent.parent/"manifest.json"]
    else:
        candidates = [path.parent/"manifest.json", path.parent/"pilot.json", operation/"pilot-run-v2/manifest.json", operation/"frozen/pilot.json", operation/"pilot.json"]
    existing = list(dict.fromkeys(p for p in candidates if p.is_file()))
    if not existing: raise ValueError("frozen manifest binding missing for proposal report")
    return existing


def load_and_validate_reports(candidate_manifest, reports, operation):
    items = candidate_manifest.get("items")
    if (candidate_manifest.get("schema") != CANDIDATE_SCHEMA or len(items or []) != 862
            or candidate_manifest.get("candidate_count_in_audit") != 862):
        raise ValueError("frozen 862-candidate manifest schema/count mismatch")
    candidates = {x.get("item_id"): x for x in items if isinstance(x, dict)}
    if len(candidates) != 862 or None in candidates or candidate_manifest.get("eligible_count") != 862 or candidate_manifest.get("skipped_count") != 0:
        raise ValueError("candidate identities/counts missing, duplicated, or incomplete")
    for item in items:
        text=item.get("text")
        if (not isinstance(text,str) or digest(text.encode("utf-8"))!=item.get("text_hash")
                or _candidate_identity(item)!=item.get("item_id")):
            raise ValueError("frozen candidate text or item identity hash invalid")
    seen = {}; file_hashes = []; report_scopes = []
    for report_path in reports:
        raw = Path(report_path).read_bytes(); report = json.loads(raw.decode("utf-8"))
        if (report.get("schema") != REPORT_SCHEMA
                or ("activation_allowed" in report and report.get("activation_allowed") is not False)):
            raise ValueError("proposal report schema/activation gate invalid")
        if report.get("model", MODEL) != MODEL or report.get("endpoint", ENDPOINT) != ENDPOINT:
            raise ValueError("proposal report provider identity changed")
        proposals = report.get("proposals")
        if not isinstance(proposals, list) or report.get("proposal_count") != len(proposals):
            raise ValueError("proposal report count invalid")
        matched_manifests = []
        for mp in _manifest_for_report(Path(report_path), Path(operation)):
            mr = mp.read_bytes(); manifest = json.loads(mr.decode("utf-8"))
            if digest(canonical(manifest)) == report.get("manifest_sha256"):
                matched_manifests.append(manifest)
        if len(matched_manifests) != 1: raise ValueError("proposal report manifest binding mismatch/ambiguous: "+Path(report_path).name)
        expected = {x.get("item_id") for x in matched_manifests[0].get("items", [])}
        local = set()
        for proposal in proposals:
            item_id = proposal.get("item_id")
            if item_id not in candidates or item_id in local or item_id in seen:
                raise ValueError("proposal identity missing, duplicated, or outside frozen candidates")
            local.add(item_id)
            item = candidates[item_id]
            if proposal.get("proposal_status") not in {"agreement", "disagreement", "invalid", "unknown_dispatch"}:
                raise ValueError("proposal raw comparison status invalid")
            fields = ("source", "doc_id", "version_id", "extraction_id", "block_id", "snapshot_sha256", "text_hash", "page", "source_category")
            if any(proposal.get(k) != item.get(k) for k in fields): raise ValueError("proposal identity differs from frozen candidate")
            if proposal.get("review_state") != "proposal_only" or proposal.get("activation_allowed") is not False:
                raise ValueError("proposal lost proposal-only state")
            for rn in (1,2):
                result = proposal.get("round_%d" % rn)
                if not isinstance(result, dict) or result.get("round") != rn or result.get("status") not in STATUS_SET:
                    raise ValueError("proposal round missing or invalid")
                ih=result.get("input_hash")
                if not isinstance(ih,str) or len(ih)!=64 or any(c not in "0123456789abcdef" for c in ih):
                    raise ValueError("proposal round input identity invalid")
                if result.get("status") == "valid":
                    classification=result.get("classification")
                    if not isinstance(classification,dict):raise ValueError("valid round lacks classification")
                    validate_regions(classification)
            seen[item_id] = (proposal, digest(raw));
        if local != expected: raise ValueError("report item set differs from its frozen manifest")
        file_hashes.append({"path":str(Path(report_path).name),"sha256":digest(raw),"count":len(local)})
        report_scopes.append(local)
    if set(seen) != set(candidates): raise ValueError("accepted reports do not cover exactly the frozen candidate set")
    return candidates, seen, file_hashes


def _connect_ro(db_path):
    path=Path(db_path).absolute()
    if not path.is_file():raise FileNotFoundError("database file missing")
    conn=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)
    conn.row_factory=sqlite3.Row;conn.execute("PRAGMA query_only=ON")
    if conn.execute("PRAGMA query_only").fetchone()[0] != 1: conn.close();raise RuntimeError("SQLite query_only unavailable")
    return conn


def _effective_ids(conn):
    from .effective import effective_extraction_ids
    return set(effective_extraction_ids(conn))


def audit_source(conn, item, snapshot_root, effective_ids, snapshot_cache, page_cache):
    row=conn.execute("SELECT b.text,b.locator_json,b.extraction_id,e.source,e.doc_id,e.version_id,e.stats_json,e.snapshot_sha256 AS exsha,v.sha256 AS vsha,v.is_current,v.media_type,v.ext,s.sha256 AS ssha,s.store_path,s.bytes AS n FROM blocks b JOIN extractions e ON e.extraction_id=b.extraction_id JOIN kb_versions v ON v.source=e.source AND v.doc_id=e.doc_id AND v.version_id=e.version_id LEFT JOIN snapshots s ON s.source=e.source AND s.doc_id=e.doc_id AND s.version_id=e.version_id WHERE b.block_id=?",(item["block_id"],)).fetchone()
    reasons=[]
    if row is None:return {"source_state":"missing_block","source_reasons":["block_missing"],"native_text":"not_checked"}
    for key,col in (("source","source"),("doc_id","doc_id"),("version_id","version_id"),("extraction_id","extraction_id"),("snapshot_sha256","ssha")):
        if item.get(key)!=row[col]: reasons.append(key+"_changed")
    if row["vsha"]!=item.get("snapshot_sha256") or row["exsha"]!=item.get("snapshot_sha256"): reasons.append("source_snapshot_binding_changed")
    if row["store_path"]!=item.get("store_path"): reasons.append("snapshot_store_path_changed")
    if row["media_type"]!=item.get("media_type") or row["ext"]!=item.get("ext"): reasons.append("source_media_type_changed")
    if row["is_current"]!=1: reasons.append("version_not_current")
    if row["extraction_id"] not in effective_ids: reasons.append("extraction_not_effective")
    if digest(row["text"].encode("utf-8"))!=item.get("text_hash"): reasons.append("block_text_changed")
    try: locator=json.loads(row["locator_json"] or "{}")
    except Exception: locator={}
    physical=locator.get("page") if type(locator.get("page")) is int else None
    if physical!=item.get("source_page",item.get("page")): reasons.append("physical_page_changed")
    if conn.execute("SELECT 1 FROM content_projection_heads WHERE block_id=?",(item["block_id"],)).fetchone(): reasons.append("projection_head_present")
    path=row["store_path"];ssha=row["ssha"];native="not_applicable"
    if not path or not ssha: reasons.append("snapshot_binding_missing")
    else:
        from .chart_batch import _snapshot_file, source_category
        try: snap=_snapshot_file(Path(snapshot_root),path)
        except Exception: snap=None; reasons.append("unsafe_snapshot_path")
        if snap is None:
            return {"source_state":"changed","source_reasons":sorted(set(reasons)),"native_text":native}
        db_category=source_category(row["stats_json"],item.get("source_page",item.get("page")),(row["media_type"] or "").startswith("image/"))
        if db_category != item.get("source_category"): reasons.append("source_category_changed")
        key=(ssha,path)
        if key not in snapshot_cache:
            try:
                before=snap.stat();h=hashlib.sha256();size=0
                with snap.open("rb") as handle:
                    for chunk in iter(lambda:handle.read(1024*1024),b""):
                        h.update(chunk);size+=len(chunk)
                after=snap.stat()
                valid=(before.st_size==after.st_size==size and before.st_mtime_ns==after.st_mtime_ns and h.hexdigest()==ssha and (row["n"] is None or size==row["n"]))
                snapshot_cache[key]=(valid,size,after.st_mtime_ns)
            except OSError:snapshot_cache[key]=(False,0,None)
        valid,size,mtime=snapshot_cache[key]
        try:
            current_stat=snap.stat()
            if current_stat.st_size!=size or current_stat.st_mtime_ns!=mtime:valid=False
        except OSError:valid=False
        if not valid: reasons.append("snapshot_hash_or_stat_changed")
        if reasons:
            native="not_checked_source_changed"
        elif item.get("source_category")=="native" and "pdf" in (row["media_type"] or "").lower():
            page=item.get("page");pk=(ssha,page)
            if pk not in page_cache:
                try:
                    import pypdfium2 as pdfium
                    doc=pdfium.PdfDocument(str(snap));pg=doc[page-1];tp=pg.get_textpage()
                    text=tp.get_text_range();tp.close();pg.close();doc.close()
                    page_cache[pk]="".join(text.split())
                except Exception:page_cache[pk]=None
            layer=page_cache[pk];block="".join(row["text"].split())
            if not layer:native="page_text_empty_or_unreadable"
            elif layer==block:native="page_text_nonempty_exact_page_block"
            elif block and layer.count(block)==1:native="page_text_nonempty_unique_exact_block"
            else:native="page_text_nonempty_block_not_exact"
    return {"source_state":"changed" if reasons else "current","source_reasons":sorted(set(reasons)),"native_text":native}


def _stratum_sample(diagnoses,limit=30,reviewed_ids=None):
    reviewed_ids=set(reviewed_ids or []); buckets=defaultdict(list)
    for row in diagnoses:
        if row["item_id"] in reviewed_ids: continue
        reasons=set(row["reasons"]); cat=row["source_category"]
        for bucket in ("chart_table_conflict" if "chart_table_conflict" in reasons else None,
                       "chart_location_difference" if "chart_location_difference" in reasons else None,
                       "region_count_difference" if "region_count_difference" in reasons else None,
                       "invalid_or_unknown" if reasons & {"unknown_dispatch","missing_round","invalid_or_truncated_round"} else None,
                       "chart_consistent_other_region_difference" if "chart_consistent_other_region_difference" in reasons else None,
                       "table_or_body_only" if "no_chart_table_or_body_only" in reasons else None,
                       "disagreement_other" if row["raw_proposal_status"]=="disagreement" else None):
            if bucket: buckets[(bucket,cat)].append(row)
    chosen={};used=set()
    for key in sorted(buckets):
        row=sorted(buckets[key],key=lambda x:hashlib.sha256(x["item_id"].encode()).hexdigest())[0]
        if row["item_id"] not in used and row["item_id"] not in reviewed_ids and row["source_state"] == "current":
            chosen[row["item_id"]]=row;used.add(row["item_id"])
    for row in sorted(diagnoses,key=lambda x:hashlib.sha256(x["item_id"].encode()).hexdigest()):
        if len(chosen)>=limit:break
        if row["item_id"] not in used and row["item_id"] not in reviewed_ids and row["source_state"] == "current":
            chosen[row["item_id"]]=row;used.add(row["item_id"])
    return [{"item_id":r["item_id"],"source_category":r["source_category"],"reasons":r["reasons"],"review_state":"proposal_only"} for r in list(chosen.values())[:limit]]


def run_audit(db_path, snapshot_root, candidate_path, reports, operation, out_dir, visual_review=None):
    out_dir=Path(out_dir).resolve();db=Path(db_path).absolute();snap=Path(snapshot_root).absolute()
    if not snap.is_dir():raise FileNotFoundError("snapshot root missing")
    if not db.is_file():raise FileNotFoundError("database file missing")
    if out_dir==db or db in out_dir.parents or out_dir==snap or snap in out_dir.parents:raise ValueError("output must be outside database and snapshot root")
    candidates_manifest=read_json(candidate_path);candidates,proposals,report_hashes=load_and_validate_reports(candidates_manifest,reports,operation)
    reviewed_ids=set()
    review_hash=None
    if visual_review:
        review_raw=Path(visual_review).read_bytes();review=read_json(visual_review);review_hash=digest(review_raw)
        if review.get("schema")!="codex-chart-pilot-visual-review/1" or review.get("activation_allowed") is not False:raise ValueError("visual review schema/activation gate invalid")
        review_items=review.get("items")
        if not isinstance(review_items,list) or len(review_items)!=review.get("reviewed_items"):
            raise ValueError("visual review item count invalid")
        reviewed_ids={x.get("item_id") for x in review_items if isinstance(x,dict)}
        if len(reviewed_ids)!=len(review_items) or not reviewed_ids.issubset(set(candidates)):
            raise ValueError("visual review identities invalid/outside frozen candidate set")
    db_before=(db.stat().st_size,db.stat().st_mtime_ns)
    conn=_connect_ro(db)
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0]!=3:raise ValueError("schema 3 required; audit will not migrate")
        conn.execute("BEGIN")
        effective=_effective_ids(conn);snapshot_cache={};page_cache={};diagnoses=[];raw_counts=Counter();proposal_counts=Counter();reason_counts=Counter();source_counts=Counter()
        for item_id,item in candidates.items():
            proposal,_=proposals[item_id];raw=proposal.get("proposal_status");proposal_counts[raw]+=1
            round_status=[proposal[f"round_{i}"]["status"] for i in (1,2)]
            for status in round_status:raw_counts[status]+=1
            reasons,metrics=_proposal_reasons(proposal)
            probe=audit_source(conn,item,snap,effective,snapshot_cache,page_cache);reasons+=[]
            reason_counts.update(reasons);source_counts[probe["source_state"]]+=1
            signals=chart_signals(item.get("text") or "")
            diagnoses.append({"item_id":item_id,"source":item.get("source"),"doc_id":item.get("doc_id"),"version_id":item.get("version_id"),"extraction_id":item.get("extraction_id"),"block_id":item.get("block_id"),"page":item.get("page"),"source_category":item.get("source_category"),"snapshot_sha256":item.get("snapshot_sha256"),"text_hash":item.get("text_hash"),"proposal_sha256":digest(canonical(proposal)),"raw_proposal_status":raw,"round_status":round_status,"reasons":sorted(set(reasons)),"region_diagnosis":metrics,"signals":signals,"source_state":probe["source_state"],"source_reasons":probe["source_reasons"],"native_text_check":probe["native_text"],"review_state":"proposal_only"})
    finally:conn.close()
    db_after=(db.stat().st_size,db.stat().st_mtime_ns)
    external_db_changed=db_before!=db_after
    statuses=Counter(d["raw_proposal_status"] for d in diagnoses);dual_valid=sum(d["round_status"]==["valid","valid"] for d in diagnoses)
    aggregate={"schema":"chart-resolution-audit/1","candidate_count":len(diagnoses),"dual_valid":dual_valid,"proposal_status_counts":dict(statuses),"round_status_counts":dict(raw_counts),"diagnosis_reason_counts":dict(reason_counts),"source_state_counts":dict(source_counts),"snapshot_files_verified":len(snapshot_cache),"native_page_checks":len(page_cache),"candidate_manifest_sha256":digest(Path(candidate_path).read_bytes()),"report_files":report_hashes,"database_query_only":True,"external_db_stat_changed_during_audit":external_db_changed,"activation_allowed":False,"review_state":"proposal_only"}
    by_id={x["item_id"]:x for x in diagnoses}
    selected=_stratum_sample(diagnoses,30,reviewed_ids)
    for entry in selected:
        d=by_id[entry["item_id"]];proposal=proposals[entry["item_id"]][0]
        entry.update({"source":d["source"],"doc_id":d["doc_id"],"version_id":d["version_id"],"extraction_id":d["extraction_id"],"block_id":d["block_id"],"page":d["page"],"snapshot_sha256":d["snapshot_sha256"],"text_hash":d["text_hash"],"proposal_sha256":d["proposal_sha256"],"round_input_hashes":[proposal["round_1"].get("input_hash"),proposal["round_2"].get("input_hash")]})
    plan={"schema":"chart-resolution-review-plan/1","review_state":"proposal_only","activation_allowed":False,"candidate_manifest_sha256":aggregate["candidate_manifest_sha256"],"report_hashes":report_hashes,"visual_review_sha256":review_hash,"items":selected}
    out_dir.mkdir(parents=True,exist_ok=True)
    for name,value in (("aggregate.json",aggregate),("diagnosis.json",{"schema":"chart-resolution-diagnosis/1","items":diagnoses,"activation_allowed":False}),("review-plan.json",plan)):
        with (out_dir/name).open("xb") as f:f.write(canonical(value)+b"\n");f.flush();os.fsync(f.fileno())
    return aggregate
