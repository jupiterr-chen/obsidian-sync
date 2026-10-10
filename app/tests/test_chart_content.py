"""Chart governance counterexamples: no private report text or model calls."""
import copy
import hashlib
import io
import json
import os
import sqlite3
import unittest
from pathlib import Path

from fixtures import temp_dir
from knowledge.store import KnowledgeStore
from knowledge.content import (POLICY, activate, canonical, consumer_blocks,
                               dependency_report, digest, is_stale, project_block,
                               revision, rollback, scan_new_blocks, validate_manifest)
from knowledge.chart_assets import put_asset
from knowledge.chart_governance import plan
from knowledge.indexing import build_generation, search
from knowledge.analysis import hybrid_search, execute_analysis_run
from knowledge.providers import MockEmbedder, ScriptedChat
from knowledge.reading import ReadingPublisher, current_reading_filename
from knowledge.summaries import ensure_schema, _entity_document_evidence, _entity_claim_evidence, record_summary
from knowledge.background import build_background_package
from test_knowledge_analysis import _doc, _version, _block


class ChartContentTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(temp_dir())
        self.kb = KnowledgeStore(str(self.root / "knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        self.kb.upsert_documents([_doc("reports", "R1")], stamp)
        self.kb.upsert_versions([_version("reports", "R1", "v1", "a"*64)], stamp)
        self.text = "Narrative revenue grew 12%.\nFigure 1 Revenue trend\n998877\n887766\naxisjunk\nTable 2\n2025 revenue 240\n2026 revenue 268\n"
        self.kb.record_extraction({"extraction_id":"e1", "source":"reports", "doc_id":"R1",
            "version_id":"v1", "snapshot_sha256":"a"*64, "parser_id":"test", "parser_version":"1",
            "config_digest":"cfg", "status":"ready", "issues":[], "stats":{}},
            [_block("paragraph", self.text, {"kind":"pdf", "page":1})])
        self.block = self.kb.get_blocks("e1")[0]
        self.bid = self.block["block_id"]
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (40,30), "white").save(buffer, format="PNG")
        self.assets = self.root / "chart-assets"
        self.asset = put_asset(self.assets, buffer.getvalue())
        start = self.text.index("998877")
        end = self.text.index("Table 2")
        self.manifest = {"policy":POLICY,"review_state":"confirmed","reviewer":"fixture-reviewer",
            "source":"reports","doc_id":"R1","version_id":"v1","extraction_id":"e1",
            "snapshot_sha256":"a"*64,"block_id":self.bid,"text_sha256":digest(self.text),
            "page":1,"coordinate_system":"normalized-top-left","mapping_method":"reviewed-exact-spans",
            "regions":[{"id":"chart1","kind":"chart","bbox":[0.1,0.2,0.9,0.6],
                "review_state":"confirmed","caption":"Figure 1 Revenue trend","asset":self.asset,
                "spans":[self.span(start,end,"exclude")]},
                {"id":"prose","kind":"narrative","bbox":[0,0,1,0.2],"spans":[self.span(0,start,"keep")]},
                {"id":"table","kind":"table","bbox":[0,0.6,1,1],"spans":[self.span(end,len(self.text),"keep")]}]}

    def span(self,start,end,action):
        return {"start":start,"end":end,"sha256":digest(self.text[start:end]),
                "action":action,"role":"unassigned_value"}

    def tearDown(self):
        self.kb.close()

    def apply(self):
        return activate(self.kb,self.manifest,self.assets)

    def test_mixed_page_keeps_prose_table_raw_and_rollback(self):
        initial = build_generation(self.kb)["generation_id"]
        pid = self.apply()["projection_id"]
        projected = consumer_blocks(self.kb,[self.block])[0]
        self.assertNotIn("998877",projected["text"])
        self.assertIn("revenue grew 12%",projected["text"])
        self.assertIn("2026 revenue 268",projected["text"])
        self.assertEqual(self.kb.get_blocks("e1")[0]["text"],self.text)
        self.assertNotEqual(build_generation(self.kb)["generation_id"],initial)
        rollback(self.kb,self.bid,pid)
        self.assertEqual(consumer_blocks(self.kb,[projected])[0]["text"],self.text)
        self.assertEqual(build_generation(self.kb)["generation_id"],initial)

    def test_stale_source_span_bbox_and_protected_overlap_rejected(self):
        cases=[]
        for field,value in [("snapshot_sha256","b"*64),("text_sha256","c"*64),("page",2),("source","elsewhere")]:
            m=copy.deepcopy(self.manifest); m[field]=value; cases.append(m)
        m=copy.deepcopy(self.manifest); m["regions"][0]["bbox"]=[0,0,2,1]; cases.append(m)
        m=copy.deepcopy(self.manifest); m["regions"][0]["spans"][0]["sha256"]="d"*64; cases.append(m)
        m=copy.deepcopy(self.manifest); m["regions"][0]["spans"]=[self.span(0,len(self.text),"exclude")]; cases.append(m)
        m=copy.deepcopy(self.manifest); m["regions"][0]["kind"]="unknown"; cases.append(m)
        m=copy.deepcopy(self.manifest); m["regions"][0]["caption"]="invented conclusion"; cases.append(m)
        for m in cases:
            with self.subTest(manifest=m):
                with self.assertRaises(ValueError): validate_manifest(self.kb._conn,m)

    def test_assets_and_activation_cas(self):
        m=copy.deepcopy(self.manifest); m["regions"][0]["asset"]["name"]="../secret.png"
        with self.assertRaises(ValueError): activate(self.kb,m,self.assets)
        with self.assertRaises(ValueError): activate(self.kb,self.manifest,self.assets,expected_revision="old")
        self.apply()
        with self.assertRaises(ValueError): rollback(self.kb,self.bid,"wrong-pid")
        (self.assets/self.asset["name"]).write_bytes(b"damaged")
        with self.assertRaises(ValueError): self.apply()

    def test_three_runs_idempotent_and_plan_read_only(self):
        self.kb._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before=hashlib.sha256(Path(self.kb.path).read_bytes()).hexdigest()
        self.assertTrue(plan(self.kb.path,self.manifest)["dry_run"])
        self.assertEqual(before,hashlib.sha256(Path(self.kb.path).read_bytes()).hexdigest())
        for i in range(3): self.assertEqual(self.apply()["changed"],i==0)
        self.assertEqual(self.kb._conn.execute("SELECT COUNT(*) FROM content_projection_events").fetchone()[0],1)
        self.assertEqual(self.kb._conn.execute("SELECT COUNT(*) FROM publish_outbox").fetchone()[0],1)

    def test_keyword_gate_prevents_stale_index_leak(self):
        build_generation(self.kb)
        self.assertTrue(search(self.kb,"998877")["hits"])
        self.apply()
        self.assertFalse(search(self.kb,"998877")["hits"])
        build_generation(self.kb)
        self.assertTrue(search(self.kb,"Revenue trend")["hits"])

    def test_vector_cache_and_custom_analysis_use_projection(self):
        class Capture(MockEmbedder):
            def __init__(self): super().__init__(); self.seen=[]
            def embed(self,texts): self.seen.extend(texts); return super().embed(texts)
        embedder=Capture()
        build_generation(self.kb)
        hybrid_search(self.kb,"revenue",embedder)
        self.apply(); embedder.seen=[]
        result=hybrid_search(self.kb,"revenue",embedder)
        self.assertFalse(any("998877" in t for t in embedder.seen))
        self.assertTrue(any("2026 revenue 268" in t for t in embedder.seen))
        self.assertIn("projection_id",result["hits"][0]["block"])
        class Chat(ScriptedChat):
            def complete(self,prompt,**kwargs):
                if "998877" in prompt: raise AssertionError("raw fragment reached model")
                return super().complete(prompt,**kwargs)
        run=self.kb.create_analysis_run("revenue")
        raw=dict(self.block,source="reports",doc_id="R1")
        result=execute_analysis_run(self.kb,run["run_id"],"revenue",Chat(replies=["Supported [1]."]),retriever=lambda q,k:[{"block":raw}])
        self.assertEqual(result["status"],"done",result)
        self.assertEqual(result["citations"][0]["projection_id"],self.apply()["projection_id"])

    def test_summary_and_background_do_not_reuse_stale_claims(self):
        ensure_schema(self.kb)
        from knowledge.memory import create_claim
        claim=create_claim(self.kb,"Claim 998877",subject="EXAMPLE",
            evidence=[{"block_id":self.bid,"source":"reports","doc_id":"R1","version_id":"v1","extraction_id":"e1"}])
        self.apply()
        cid=claim.get("claim_id",claim.get("claim",{}).get("claim_id"))
        self.assertTrue(is_stale(self.kb._conn,"claim",cid))
        self.assertFalse(_entity_claim_evidence(self.kb,"company","EXAMPLE"))
        evidence=_entity_document_evidence(self.kb,"company","EXAMPLE")
        self.assertTrue(evidence)
        self.assertFalse(any("998877" in e.get("text","") for e in evidence))
        self.assertFalse(build_background_package(self.kb,"company","EXAMPLE")["claims"])

    def test_reading_images_old_files_and_human_edits_survive(self):
        vault=self.root/"vault"
        publisher=ReadingPublisher(self.kb,str(vault))
        publisher.enqueue("reports","R1","v1","e1")
        publisher.consume()
        old=Path(publisher.output)/current_reading_filename(self.kb,"reports","R1","e1")
        old.write_text(old.read_text(encoding="utf-8")+"\nHuman note",encoding="utf-8")
        self.apply(); publisher.consume()
        new=Path(publisher.output)/current_reading_filename(self.kb,"reports","R1","e1")
        self.assertNotEqual(old,new)
        self.assertIn("Human note",old.read_text(encoding="utf-8"))
        content=new.read_text(encoding="utf-8")
        self.assertNotIn("998877",content)
        self.assertIn("图表资产/"+self.asset["name"],content)
        self.assertTrue((Path(publisher.output)/"图表资产"/self.asset["name"]).is_file())
        self.assertIn(new.name,(Path(publisher.output)/"开始阅读.md").read_text(encoding="utf-8"))

    def test_candidate_triage_not_automatic_deletion_and_optional_hold(self):
        from knowledge.content import chart_signals
        risk="Figure 2 Axis\n"+"\n".join(str(n) for n in range(30))
        self.assertTrue(chart_signals(risk)["requires_review"])
        self.assertFalse(chart_signals("图表目录\n"+risk)["requires_review"])
        self.assertEqual(scan_new_blocks(self.kb)["scanned"],1)
        self.assertEqual(scan_new_blocks(self.kb)["scanned"],0)
        self.assertEqual(consumer_blocks(self.kb,[self.block])[0]["text"],self.text)

    def test_new_candidate_held_before_queue_scan_table_released_by_all_keep(self):
        risk="Figure 2 Axis\n"+"\n".join(str(n) for n in range(30))
        with self.kb._tx() as conn:
            conn.execute("UPDATE blocks SET text=? WHERE block_id=?",(risk,self.bid))
            conn.execute("INSERT INTO content_settings VALUES('hold_candidates','true')")
        block=self.kb.get_blocks("e1")[0]
        build_generation(self.kb)
        self.assertFalse(search(self.kb,"Axis")["hits"])
        self.assertFalse(consumer_blocks(self.kb,[block]))
        m=copy.deepcopy(self.manifest); m["text_sha256"]=digest(risk)
        m["regions"]=[{"id":"reviewed-table","kind":"table","bbox":[0,0,1,1],
            "spans":[{"start":0,"end":len(risk),"action":"keep","sha256":digest(risk)}]}]
        activate(self.kb,m,self.assets)
        self.assertEqual(consumer_blocks(self.kb,[block])[0]["text"],risk)
        self.assertEqual(self.kb.get_blocks("e1")[0]["text"],risk)

    def test_old_database_migrates_and_projection_replay_survives_rollback(self):
        with self.kb._tx() as conn:
            for table in ('content_projection_heads','content_projection_events','content_invalidations','chart_review_queue','content_settings','content_projections'):
                conn.execute('DROP TABLE '+table)
            conn.execute("PRAGMA user_version=2")
        path=self.kb.path
        self.kb.close(); self.kb=KnowledgeStore(path)
        self.assertEqual(self.kb._conn.execute("PRAGMA user_version").fetchone()[0],3)
        pid=self.apply()["projection_id"]
        rollback(self.kb,self.bid,pid)
        from knowledge.kbapi import KbApi
        api=KbApi(self.kb,tokens={})
        result=api.evidence(self.bid,pid)
        self.assertEqual(result["projection_selection"],"explicit")
        self.assertNotIn("998877",result["default_projection"]["text"])
        self.assertNotIn("998877",result["evidence"]["text"])
        self.assertIn("998877",api.evidence(self.bid)["evidence"]["text"])
        blob=api.chart_asset(self.bid,self.asset["name"],pid)
        self.assertEqual(hashlib.sha256(blob["data"]).hexdigest(),self.asset["sha256"])
        from knowledge.kbapi import KbApiError
        with self.assertRaises(KbApiError): api.chart_asset(self.bid,'../knowledge.sqlite3',pid)
        self.assertEqual(self.kb.get_blocks("e1")[0]["text"],self.text)

    def test_transitive_summary_staleness_and_new_claim_revision(self):
        from knowledge.memory import create_claim,review_claim
        from knowledge.summaries import latest_summary
        cid=create_claim(self.kb,"Revenue grew",subject="EXAMPLE",evidence=[{"block_id":self.bid}])["claim_id"]
        record_summary(self.kb,"company","EXAMPLE","Old summary",[{"claim_id":cid,"revision":1}])
        self.apply()
        self.assertTrue(latest_summary(self.kb,"company","EXAMPLE")["content_stale"])
        review_claim(self.kb,cid,"revise","test",new_statement="Preserved prose revenue",
                     new_evidence=[{"block_id":self.bid,"projection_id":self.apply()["projection_id"]}])
        self.assertTrue(is_stale(self.kb._conn,"claim",cid,1))
        self.assertFalse(is_stale(self.kb._conn,"claim",cid,2))
        self.assertEqual(len(_entity_claim_evidence(self.kb,"company","EXAMPLE")),1)

    def test_single_document_executor_uses_projection_and_stale_partial_cannot_resume(self):
        from knowledge.analysis_tasks import register_ready_analysis_tasks,execute_analysis_tasks,claim_pending_analysis_tasks
        self.apply()
        register_ready_analysis_tasks(self.kb,model_identity="fake/test",blocked_reason=None)
        class Chat(ScriptedChat):
            def complete(self,prompt,**kwargs):
                if "998877" in prompt: raise AssertionError("raw coordinates in document analysis")
                return super().complete(prompt,**kwargs)
        result=execute_analysis_tasks(self.kb,Chat(replies=["Revenue [1]."]),limit=1)
        self.assertEqual(result["done"],1,result)
        with self.kb._tx() as conn: conn.execute("UPDATE analysis_tasks SET status='partial'")
        rollback(self.kb,self.bid,self.apply()["projection_id"])
        self.assertEqual(claim_pending_analysis_tasks(self.kb),[])

    def test_mid_model_projection_change_cannot_publish_stale_result(self):
        raw=dict(self.block,source="reports",doc_id="R1")
        fixture=self
        class ChangeDuringModel(ScriptedChat):
            def complete(self,prompt,**kwargs):
                fixture.apply()
                return super().complete(prompt,**kwargs)
        run=self.kb.create_analysis_run("revenue")
        result=execute_analysis_run(self.kb,run["run_id"],"revenue",ChangeDuringModel(replies=["Old [1]."]),retriever=lambda q,k:[{"block":raw}])
        self.assertEqual(result["status"],"stale")
        self.assertEqual(self.kb.get_analysis_run(run["run_id"])["status"],"stale")

    def test_crop_and_native_mapping_fail_closed_on_wrong_source_or_text(self):
        from knowledge.chart_assets import render_region,map_native_regions
        from PIL import Image
        pdf=self.root/'scan.pdf'
        Image.new('RGB',(100,100),'white').save(pdf,format='PDF')
        sha=hashlib.sha256(pdf.read_bytes()).hexdigest()
        asset=render_region(pdf,sha,1,[0,0,.5,.5],self.assets)
        self.assertTrue((self.assets/asset["name"]).is_file())
        with self.assertRaises(ValueError): render_region(pdf,'f'*64,1,[0,0,1,1],self.assets)
        with self.assertRaises(ValueError): map_native_regions(pdf,sha,1,'OCR has no native geometry',[])

    def test_chart_http_authentication_and_immutable_asset(self):
        import threading
        import urllib.request
        import urllib.error
        from knowledge.kbapi import build_kb_server
        pid=self.apply()["projection_id"]
        server=build_kb_server(self.kb,{"fixture-token":["research.read"]},host="127.0.0.1",port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url="http://127.0.0.1:%d/api/kb/v1/evidence/%s/charts/%s?projection=%s" % (server.server_address[1],self.bid,self.asset["name"],pid)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with self.assertRaises(urllib.error.HTTPError) as raised: opener.open(url,timeout=5)
            self.assertEqual(raised.exception.code,401)
            request=urllib.request.Request(url,headers={"Authorization":"Bearer fixture-token"})
            with opener.open(request,timeout=5) as response:
                self.assertEqual(response.headers['Content-Type'],'image/png')
                self.assertEqual(hashlib.sha256(response.read()).hexdigest(),self.asset['sha256'])
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)


if __name__ == "__main__": unittest.main()
