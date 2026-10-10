"""Release-edge counterexamples for chart CLI recovery behavior."""
import contextlib
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from fixtures import temp_dir
from knowledge.store import KnowledgeStore
from knowledge.content import POLICY, digest
from knowledge.chart_assets import put_asset
from test_knowledge_analysis import _doc, _version, _block


class ReleaseFixture:
    def setUp(self):
        self.root = Path(temp_dir())
        self.kb = KnowledgeStore(str(self.root/"knowledge.sqlite3"))
        stamp = "2026-10-01T00:00:00Z"
        self.kb.upsert_documents([_doc("reports","R1")],stamp)
        self.kb.upsert_versions([_version("reports","R1","v1","a"*64)],stamp)
        self.text = ("Narrative revenue grew 12%.\nFigure 1 Revenue trend\n"
                     "998877\n887766\naxisjunk\nTable 2\n"
                     "2025 revenue 240\n2026 revenue 268\n")
        self.kb.record_extraction({"extraction_id":"e1","source":"reports",
            "doc_id":"R1","version_id":"v1","snapshot_sha256":"a"*64,
            "parser_id":"test","parser_version":"1","config_digest":"cfg",
            "status":"ready","issues":[],"stats":{}},
            [_block("paragraph",self.text,{"kind":"pdf","page":1})])
        self.block = self.kb.get_blocks("e1")[0]
        self.bid = self.block["block_id"]
        from PIL import Image
        buffer=io.BytesIO(); Image.new("RGB",(40,30),"white").save(buffer,format="PNG")
        self.assets=self.root/"chart-assets"
        self.asset=put_asset(self.assets,buffer.getvalue())
        start=self.text.index("998877"); end=self.text.index("Table 2")
        self.manifest={"policy":POLICY,"review_state":"confirmed","reviewer":"fixture",
            "source":"reports","doc_id":"R1","version_id":"v1","extraction_id":"e1",
            "snapshot_sha256":"a"*64,"block_id":self.bid,"text_sha256":digest(self.text),
            "page":1,"coordinate_system":"normalized-top-left","mapping_method":"reviewed-exact-spans",
            "regions":[{"id":"chart1","kind":"chart","bbox":[.1,.2,.9,.6],
                "review_state":"confirmed","caption":"Figure 1 Revenue trend","asset":self.asset,
                "spans":[self.span(start,end,"exclude")]},
                {"id":"prose","kind":"narrative","bbox":[0,0,1,.2],
                 "spans":[self.span(0,start,"keep")]},
                {"id":"table","kind":"table","bbox":[0,.6,1,1],
                 "spans":[self.span(end,len(self.text),"keep")]}]}

    def span(self,start,end,action):
        return {"start":start,"end":end,"sha256":digest(self.text[start:end]),
                "action":action,"role":"unassigned_value"}

    def apply(self):
        from knowledge.content import activate
        return activate(self.kb,self.manifest,self.assets)

    def tearDown(self):
        self.kb.close()


class ChartReleaseEdgesTest(unittest.TestCase):
    def test_rollback_cli_failure_recovers_with_idempotent_reindex_command(self):
        fixture = ReleaseFixture()
        fixture.setUp()
        try:
            from knowledge.chart_governance import main
            from knowledge.indexing import build_generation

            before = build_generation(fixture.kb)["generation_id"]
            active = fixture.apply()["projection_id"]
            build_generation(fixture.kb)
            args = ["rollback", "--db", fixture.kb.path, "--block-id", fixture.bid,
                    "--expected-projection", active, "--apply"]

            # Simulate a process failure after rollback committed its pointer,
            # before the CLI could rebuild the derived index.
            with patch("knowledge.indexing.build_generation", side_effect=RuntimeError("injected index failure")):
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaisesRegex(RuntimeError, "injected index failure"):
                        main(args)

            self.assertIsNone(fixture.kb._conn.execute(
                "SELECT projection_id FROM content_projection_heads WHERE block_id=?",
                (fixture.bid,)).fetchone())
            # The rollback committed its pointer but did not publish the
            # index. The original CAS command must stay strict; the dedicated
            # recovery operation rebuilds the derived index and is repeatable.
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "projection changed"):
                    main(args)
                main(["reindex", "--db", fixture.kb.path])
                main(["reindex", "--db", fixture.kb.path])
            self.assertEqual(fixture.kb._conn.execute(
                "SELECT projection_id FROM content_projection_heads WHERE block_id=?",
                (fixture.bid,)).fetchone(), None)
            self.assertEqual(build_generation(fixture.kb)["generation_id"], before)
            self.assertEqual(fixture.kb._conn.execute(
                "SELECT COUNT(*) FROM content_projection_events WHERE block_id=?",
                (fixture.bid,)).fetchone()[0], 2)
        finally:
            fixture.tearDown()

    def test_coarse_claims_fail_closed_only_for_projected_or_held_extractions(self):
        from knowledge.memory import create_claim
        from knowledge.summaries import _entity_claim_evidence

        fixture = ReleaseFixture()
        fixture.setUp()
        try:
            create_claim(fixture.kb, "coarse before projection",
                         [{"source":"reports", "doc_id":"R1",
                           "version_id":"v1", "extraction_id":"e1"}],
                         subject="R1")
            self.assertEqual(len(_entity_claim_evidence(fixture.kb,"company","R1")),1)
            fixture.apply()
            create_claim(fixture.kb, "coarse after projection",
                         [{"source":"reports", "doc_id":"R1",
                           "version_id":"v1", "extraction_id":"e1"}],
                         subject="R1")
            current = _entity_claim_evidence(fixture.kb,"company","R1")
            self.assertEqual([c["statement"] for c in current], [])

        finally:
            fixture.tearDown()

        held = ReleaseFixture()
        held.setUp()
        try:
            with held.kb._tx() as conn:
                conn.execute("INSERT INTO content_settings VALUES('hold_candidates','true')")
                conn.execute("UPDATE blocks SET text=? WHERE block_id=?",
                             ("Figure 2 Axis\n"+"\n".join(str(i) for i in range(30)), held.bid))
            create_claim(held.kb, "held block claim", [{"block_id":held.bid}], subject="EXAMPLE")
            self.assertEqual(_entity_claim_evidence(held.kb,"company","EXAMPLE"), [])
        finally:
            held.tearDown()

    def test_held_candidate_blocks_old_single_document_analysis_from_summary(self):
        from knowledge.analysis_tasks import register_ready_analysis_tasks, execute_analysis_tasks
        from knowledge.providers import ScriptedChat
        from knowledge.summaries import _entity_document_evidence

        fixture = ReleaseFixture()
        fixture.setUp()
        try:
            risk = "Figure 1 Growth\n"+"\n".join(str(i) for i in range(30))
            with fixture.kb._tx() as conn:
                conn.execute("UPDATE blocks SET text=? WHERE block_id=?", (risk, fixture.bid))
                conn.execute("INSERT INTO blocks(block_id,extraction_id,ordinal,block_type,text,locator_json,quality_status) VALUES(?,?,?,?,?,?,?)",
                             ("clean-block","e1",1,"paragraph","Ordinary narrative about 2026.",
                              '{"kind":"pdf","page":2}',"ready"))
            register_ready_analysis_tasks(fixture.kb, model_identity="fake/test",
                                          blocked_reason=None)
            result = execute_analysis_tasks(fixture.kb,
                ScriptedChat(replies=["Narrative [2]."]), limit=1)
            self.assertEqual(result["done"], 1, result)
            citations = fixture.kb._conn.execute(
                "SELECT r.citations_json FROM analysis_runs r JOIN analysis_tasks t"
                " ON t.run_id=r.run_id WHERE t.extraction_id='e1'").fetchone()[0]
            import json
            self.assertEqual([c["block_id"] for c in json.loads(citations)], ["clean-block"])
            with fixture.kb._tx() as conn:
                conn.execute("INSERT INTO content_settings VALUES('hold_candidates','true')")
            analyses = [item for item in _entity_document_evidence(
                fixture.kb,"company","EXAMPLE") if item["kind"] == "analysis"]
            self.assertEqual(analyses, [])
        finally:
            fixture.tearDown()

    def test_analysis_page_uses_citation_projection_and_bound_evidence_url(self):
        from knowledge.analysis_tasks import register_ready_analysis_tasks, execute_analysis_tasks
        from knowledge.providers import ScriptedChat
        from knowledge.analysis_publish import AnalysisPublisher

        fixture = ReleaseFixture()
        fixture.setUp()
        try:
            projection = fixture.apply()["projection_id"]
            register_ready_analysis_tasks(fixture.kb, model_identity="fake/test",
                                          blocked_reason=None)
            result = execute_analysis_tasks(fixture.kb,
                ScriptedChat(replies=["Revenue grew [1]."]), limit=1)
            self.assertEqual(result["done"], 1, result)
            publisher = AnalysisPublisher(fixture.kb, str(fixture.root/"vault"),
                                          base_url="https://kb.example")
            item = publisher.pending()[0]
            self.assertTrue(publisher._publish_page_for(item["task_key"]))
            task = fixture.kb._conn.execute(
                "SELECT publish_path FROM analysis_tasks WHERE task_key=?",
                (item["task_key"],)).fetchone()
            page = Path(publisher.output, task[0]).read_text(encoding="utf-8")
            self.assertNotIn("998877", page)
            self.assertIn("?projection="+projection, page)
            self.assertIn("2026 revenue 268", page)
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
