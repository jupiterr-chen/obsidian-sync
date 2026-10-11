import hashlib
import json
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"app"))
from knowledge import chart_resolution as cr


def box(kind,x0,x1): return {"kind":kind,"bbox":[x0,0,x1,1]}


class ChartResolutionTests(unittest.TestCase):
    def test_global_assignment_avoids_greedy_false_disagreement(self):
        a={"regions":[box("chart",0,.6),box("chart",.2,.8)]}
        b={"regions":[box("chart",.1,.7),box("chart",0,.4)]}
        reasons,metrics=cr.compare_regions(a,b)
        self.assertTrue(metrics["charts_consistent"])
        self.assertNotIn("chart_location_difference",reasons)
        self.assertIn("chart_table_conflict",cr.compare_regions({"regions":[box("chart",0,.5)]},{"regions":[box("table",0,.5)]})[0])
        self.assertIn("chart_table_conflict",cr.compare_regions({"regions":[box("table",0,.5)]},{"regions":[box("chart",0,.5)]})[0])

    def _fixture(self):
        root=ROOT/"runtime"/("chart-resolution-test-"+uuid.uuid4().hex);op=root/"operation";op.mkdir(parents=True)
        raw=b"synthetic snapshot; no source material";ssha=hashlib.sha256(raw).hexdigest();snap=root/"snapshots";snap.mkdir();(snap/"one.pdf").write_bytes(raw)
        items=[]
        for i in range(862):
            text="PRIVATE-SENTINEL-"+str(i)+" Figure 1"
            item={"item_id":None,"source":"src","doc_id":"doc","version_id":"v1","extraction_id":"e1","block_id":"b-%03d"%i,"snapshot_sha256":ssha,"text_hash":hashlib.sha256(text.encode()).hexdigest(),"page":i+1,"source_page":i+1,"source_category":"unknown","store_path":"one.pdf","media_type":"application/pdf","ext":"pdf","text":text,"signals":{"requires_review":True}}
            item["item_id"]=cr._candidate_identity(item);items.append(item)
        cm={"schema":cr.CANDIDATE_SCHEMA,"candidate_count_in_audit":862,"eligible_count":862,"skipped_count":0,"items":items};(op/"frozen").mkdir();cand=op/"frozen/candidates.json";cand.write_bytes(cr.canonical(cm)+b"\n")
        groups=[items[:30],items[30:130],items[130:230],items[230:330],items[330:430],items[430:530],items[530:630],items[630:730],items[730:830],items[830:]]
        report_paths=[]
        for idx,group in enumerate(groups):
            manifest={"schema":"chart-batch-pilot/1","items":group}
            if idx==0:
                folder=op/"pilot-run-v2";folder.mkdir();mp=folder/"manifest.json";rp=folder/("proposals-test-%02d.json"%idx)
            elif idx==1:
                folder=op/"remaining/batch-001";folder.mkdir(parents=True);mp=folder/"manifest.json";rp=op/"remaining/continuation-v3/merged-batch-001.json";rp.parent.mkdir(parents=True)
            else:
                batch_no=idx
                rootbase=op/"remaining/continuation-v3" if idx==2 else op/"remaining/continuation-v3-http"
                folder=rootbase/"remaining"/("batch-%03d"%batch_no);(folder/"run").mkdir(parents=True);mp=folder/"manifest.json";rp=folder/("run/proposals-test-%02d.json"%idx)
            mp.write_bytes(cr.canonical(manifest)+b"\n")
            props=[]
            for it in group:
                valid={"round":1,"status":"valid","input_hash":"a"*64,"classification":{"regions":[]}}
                valid2={"round":2,"status":"valid","input_hash":"b"*64,"classification":{"regions":[]}}
                props.append({"item_id":it["item_id"],**{k:it[k] for k in ("source","doc_id","version_id","extraction_id","block_id","snapshot_sha256","text_hash","page","source_category")},"round_1":valid,"round_2":valid2,"proposal_status":"agreement","review_state":"proposal_only","activation_allowed":False})
            report={"schema":cr.REPORT_SCHEMA,"manifest_sha256":cr.digest(cr.canonical(manifest)),"proposal_count":len(props),"proposals":props}
            if idx==1:report["activation_allowed"]=False
            rp.write_bytes(cr.canonical(report)+b"\n");report_paths.append(rp)
        db=root/"kb.sqlite";conn=sqlite3.connect(db)
        conn.executescript("CREATE TABLE blocks(block_id TEXT,text TEXT,locator_json TEXT,extraction_id TEXT);CREATE TABLE extractions(extraction_id TEXT,source TEXT,doc_id TEXT,version_id TEXT,stats_json TEXT,snapshot_sha256 TEXT);CREATE TABLE kb_versions(source TEXT,doc_id TEXT,version_id TEXT,sha256 TEXT,is_current INTEGER,media_type TEXT,ext TEXT);CREATE TABLE snapshots(source TEXT,doc_id TEXT,version_id TEXT,sha256 TEXT,store_path TEXT,bytes INTEGER);CREATE TABLE content_projection_heads(block_id TEXT,projection_id TEXT);")
        conn.execute("PRAGMA user_version=3")
        conn.execute("INSERT INTO extractions VALUES(?,?,?,?,?,?)",("e1","src","doc","v1",json.dumps({"page_ocr_status":["unknown"]*862}),ssha))
        conn.execute("INSERT INTO kb_versions VALUES(?,?,?,?,?,?,?)",("src","doc","v1",ssha,1,"application/pdf","pdf"))
        conn.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?)",("src","doc","v1",ssha,"one.pdf",len(raw)))
        for it in items: conn.execute("INSERT INTO blocks VALUES(?,?,?,?)",(it["block_id"],it["text"],json.dumps({"page":it["page"]}),"e1"))
        conn.commit();conn.close()
        return root,op,cand,report_paths,db,snap

    def test_full_862_readonly_outputs_are_private_and_proposal_only(self):
        root,op,cand,reports,db,snap=self._fixture();out=root/"audit"
        with patch.object(cr,"_effective_ids",return_value={"e1"}):
            result=cr.run_audit(db,snap,cand,reports,op,out)
        self.assertEqual(result["candidate_count"],862);self.assertEqual(result["dual_valid"],862)
        self.assertTrue(result["database_query_only"])
        self.assertFalse(result["activation_allowed"])
        self.assertEqual(len(cr.read_json(out/"review-plan.json")["items"]),30)
        for name in ("aggregate.json","diagnosis.json","review-plan.json"):
            content=(out/name).read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE-SENTINEL",content)
            self.assertNotIn('"text"',content)

    def test_frozen_identity_tampering_rejected(self):
        root,op,cand,reports,db,snap=self._fixture()
        report=cr.read_json(reports[0]);report["proposals"][0]["block_id"]="forged"
        reports[0].write_bytes(cr.canonical(report)+b"\n")
        cm=cr.read_json(cand)
        with self.assertRaisesRegex(ValueError,"identity differs"):
            cr.load_and_validate_reports(cm,reports,op)


if __name__=="__main__": unittest.main()
