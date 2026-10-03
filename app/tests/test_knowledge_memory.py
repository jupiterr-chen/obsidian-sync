"""P5 tests: claim/decision state machine, impact analysis, safe write-back."""

from __future__ import annotations

import os
import unittest

from fixtures import temp_dir

from knowledge.memory import (
    STATUS_ACCEPTED,
    STATUS_PROPOSED,
    STATUS_SUPERSEDED,
    create_claim,
    impact_analysis,
    record_decision,
    resolve_proposal,
    review_claim,
)
from knowledge.store import KnowledgeStore
from knowledge.writeback import (
    WriteBackError,
    export_claim_candidates,
    render_claim_candidate,
    write_candidate,
)


def _evidence(source="reports", doc_id="R1", version_id="v1", block_id="b1"):
    return [{"source": source, "doc_id": doc_id, "version_id": version_id,
             "block_id": block_id, "extraction_id": "extr-r1"}]


class ClaimStateMachineTest(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))

    def tearDown(self):
        self.kb.close()

    def test_full_review_history_is_preserved(self):
        created = create_claim(self.kb, "毛利率持续改善", _evidence(),
                               subject="EXAMPLE")
        claim_id = created["claim_id"]
        self.assertEqual(created["revision"], 1)
        self.assertEqual(self.kb.get_claim(claim_id)["status"], STATUS_PROPOSED)

        review_claim(self.kb, claim_id, "accept", reviewer="alice",
                     note="evidence solid")
        self.assertEqual(self.kb.get_claim(claim_id)["status"], STATUS_ACCEPTED)

        review_claim(self.kb, claim_id, "challenge", reviewer="bob",
                     note="counter evidence arrived")
        self.assertEqual(self.kb.get_claim(claim_id)["status"], "challenged")

        superseded = review_claim(
            self.kb, claim_id, "supersede", reviewer="alice",
            new_statement="毛利率改善但增速放缓",
            new_evidence=_evidence(version_id="v2", block_id="b2"))
        self.assertEqual(superseded["revision"], 4)
        self.assertEqual(self.kb.get_claim(claim_id)["status"], STATUS_SUPERSEDED)

        history = self.kb.claim_history(claim_id)
        self.assertEqual([r["revision"] for r in history], [1, 2, 3, 4])
        self.assertEqual([r["status"] for r in history],
                         [STATUS_PROPOSED, STATUS_ACCEPTED, "challenged",
                          STATUS_SUPERSEDED])
        # reviewers and notes recorded per revision (A19)
        self.assertEqual(history[1]["reviewer"], "alice")
        self.assertEqual(history[2]["review_note"], "counter evidence arrived")
        self.assertIsNone(history[2]["supersedes_revision"])
        self.assertEqual(history[3]["supersedes_revision"], 3)

        with self.assertRaises(ValueError):
            review_claim(self.kb, claim_id, "teleport", reviewer="x")

    def test_decision_freezes_claim_revisions(self):
        created = create_claim(self.kb, "营收增长稳健", _evidence(block_id="b1"))
        review_claim(self.kb, created["claim_id"], "accept", reviewer="alice")
        decision = record_decision(
            self.kb, "加仓观察池", "基于营收稳健判断",
            [{"claim_id": created["claim_id"]}])
        frozen = decision["claim_refs"][0]
        self.assertEqual(frozen["revision"], 2)
        # later claim revisions do not alter the frozen decision
        review_claim(self.kb, created["claim_id"], "supersede", reviewer="bob",
                     new_statement="营收增速下修")
        stored = self.kb.get_decision(decision["decision_id"])
        self.assertEqual(stored["claim_refs"][0]["revision"], 2)
        self.assertEqual(stored["claim_refs"][0]["statement"], "营收增长稳健")
        with self.assertRaises(ValueError):
            record_decision(self.kb, "x", "y", [{"claim_id": "clm-missing"}])

    def test_create_claim_is_idempotent(self):
        a = create_claim(self.kb, "同一陈述", _evidence())
        b = create_claim(self.kb, "同一陈述", _evidence())
        self.assertEqual(a["claim_id"], b["claim_id"])
        self.assertFalse(b["created"])
        self.assertEqual(len(self.kb.claim_history(a["claim_id"])), 1)

    def test_impact_analysis_proposes_but_never_overwrites(self):
        created = create_claim(self.kb, "毛利率改善", _evidence())
        review_claim(self.kb, created["claim_id"], "accept", reviewer="alice")
        # a new source version arrives for the cited document
        result = impact_analysis(self.kb, "reports", "R1", "v2")
        self.assertIn(created["claim_id"], result["affected_claims"])
        self.assertEqual(len(result["new_proposals"]), 1)
        # the accepted claim itself is untouched (A20)
        claim = self.kb.get_claim(created["claim_id"])
        self.assertEqual(claim["status"], STATUS_ACCEPTED)
        self.assertEqual(claim["current_revision"], 2)
        # rerunning the same impact is idempotent
        again = impact_analysis(self.kb, "reports", "R1", "v2")
        self.assertEqual(again["new_proposals"], [])
        # unrelated documents are not affected
        none = impact_analysis(self.kb, "discord", "D9", "v1")
        self.assertEqual(none["affected_claims"], [])

        proposals = self.kb.list_review_proposals()
        self.assertEqual(len(proposals), 1)
        outcome = resolve_proposal(self.kb, proposals[0]["proposal_id"],
                                   "dismiss", reviewer="alice")
        self.assertEqual(outcome["status"], "dismissed")
        self.assertEqual(self.kb.list_review_proposals(), [])
        with self.assertRaises(ValueError):
            resolve_proposal(self.kb, proposals[0]["proposal_id"], "dismiss",
                             reviewer="alice")


class WriteBackTest(unittest.TestCase):
    def setUp(self):
        from knowledge.writeback import register_write_root

        self.dir = os.path.join(temp_dir(), "vault-generated")
        register_write_root(self.dir)

    def test_write_preserves_human_edits_and_conflicts(self):
        first = write_candidate(self.dir, "clm-a.md", "# v1 content")
        self.assertEqual(first["outcome"], "written")
        second = write_candidate(self.dir, "clm-a.md", "# v1 content")
        self.assertEqual(second["outcome"], "unchanged")
        # our own regeneration with new content is allowed (hash matches ours)
        third = write_candidate(self.dir, "clm-a.md", "# v2 content")
        self.assertEqual(third["outcome"], "written")
        with open(os.path.join(self.dir, "clm-a.md"), "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "# v2 content")
        # human edit: our next write must NOT overwrite, candidate saved instead
        with open(os.path.join(self.dir, "clm-a.md"), "a", encoding="utf-8") as fh:
            fh.write("\n人工批注：需要注意。")
        fourth = write_candidate(self.dir, "clm-a.md", "# v3 content")
        self.assertEqual(fourth["outcome"], "preserved_with_candidate")
        with open(os.path.join(self.dir, "clm-a.md"), "r", encoding="utf-8") as fh:
            self.assertIn("人工批注", fh.read())  # original preserved
        self.assertTrue(os.path.isfile(fourth["candidate_path"]))

    def test_conflict_marked_names_rejected(self):
        with self.assertRaises(WriteBackError):
            write_candidate(self.dir, "note.sync-conflict-20261001.md", "x")
        with self.assertRaises(WriteBackError):
            write_candidate(self.dir, "../escape.md", "x")
        with self.assertRaises(WriteBackError):
            write_candidate(self.dir, ".hidden", "x")

    def test_claim_candidate_export_end_to_end(self):
        kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        try:
            stamp = "2026-10-01T00:00:00Z"
            kb.upsert_documents([{
                "source": "reports", "doc_id": "R1", "title": "R1",
                "available": True, "first_seen_at": stamp, "last_seen_at": stamp,
            }], stamp)
            kb.upsert_versions([{
                "source": "reports", "doc_id": "R1", "version_id": "v1",
                "sha256": "a" * 64, "bytes": 10, "media_type": "application/pdf",
                "ext": "pdf", "rel_path": "x", "is_current": True,
                "state": "ready", "content_changed_at": None,
            }], stamp)
            kb.record_extraction({
                "extraction_id": "extr-r1", "source": "reports", "doc_id": "R1",
                "version_id": "v1", "snapshot_sha256": "a" * 64,
                "parser_id": "t", "parser_version": "1", "config_digest": "c",
                "status": "ready", "issues": [], "stats": {},
            }, [{
                "block_type": "paragraph", "text": "毛利率 30%，提升 3.2pp",
                "locator": {"kind": "pdf", "page": 2},
                "quality": {"status": "ready", "issues": []},
            }])
            created = create_claim(
                kb, "毛利率持续改善",
                [{"source": "reports", "doc_id": "R1", "version_id": "v1",
                  "block_id": "extr-r1-b0000", "extraction_id": "extr-r1"}],
                subject="EXAMPLE")
            review_claim(kb, created["claim_id"], "accept", reviewer="alice")
            result = export_claim_candidates(kb, self.dir, status="accepted")
            self.assertEqual(result["count"], 1)
            path = os.path.join(self.dir, "%s.md" % created["claim_id"])
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("待审核", text)
            self.assertIn("毛利率持续改善", text)
            self.assertIn("毛利率 30%", text)  # evidence quote embedded
            self.assertIn("extr-r1-b0000", text)
            # idempotent second export
            second = export_claim_candidates(kb, self.dir, status="accepted")
            self.assertEqual(second["outcomes"], ["unchanged"])
        finally:
            kb.close()

    def test_render_claim_candidate_markdown(self):
        claim = {
            "claim_id": "clm-x", "current_revision": 2, "status": "accepted",
            "subject": "EXAMPLE", "author": "mock", "prompt_version": "pv1",
            "statement": "陈述内容",
            "evidence": [{"block_id": "b1", "source": "reports",
                          "doc_id": "R1", "version_id": "v1"}],
            "counterevidence": [{"block_id": "b2", "source": "reports",
                                 "doc_id": "R2", "version_id": "v1"}],
        }
        text = render_claim_candidate(claim, {"b1": "证据原文"})
        self.assertIn("## 陈述", text)
        self.assertIn("## 反证", text)
        self.assertIn("证据原文", text)


if __name__ == "__main__":
    unittest.main()


class MemoryApiTest(unittest.TestCase):
    TOKEN = "memory-token"

    def setUp(self):
        self.kb = KnowledgeStore(os.path.join(temp_dir(), "knowledge.sqlite3"))
        from knowledge.kbapi import KbApi

        self.api = KbApi(self.kb, {self.TOKEN: ["research.read", "memory.review"]})

    def tearDown(self):
        self.kb.close()

    def test_claims_and_review_routes(self):
        created = create_claim(self.kb, "毛利率改善",
                               _evidence(), subject="EXAMPLE")
        claim_id = created["claim_id"]
        listed = self.api.list_claims()
        self.assertEqual(listed["claims"][0]["claim_id"], claim_id)
        detail = self.api.get_claim(claim_id)
        self.assertEqual(len(detail["history"]), 1)
        outcome = self.api.review_claim_route(claim_id, {
            "action": "accept", "reviewer": "alice", "note": "ok"})
        self.assertEqual(outcome["status"], STATUS_ACCEPTED)
        detail = self.api.get_claim(claim_id)
        self.assertEqual(len(detail["history"]), 2)
        with self.assertRaises(Exception):
            self.api.get_claim("clm-missing")

    def test_proposal_review_route(self):
        created = create_claim(self.kb, "营收稳健", _evidence())
        impact_analysis(self.kb, "reports", "R1", "v2")
        proposals = self.kb.list_review_proposals()
        outcome = self.api.review_proposal_route(
            proposals[0]["proposal_id"], {"action": "dismiss", "reviewer": "bob"})
        self.assertEqual(outcome["status"], "dismissed")

    def test_review_requires_memory_scope(self):
        from knowledge.kbapi import KbApi, KbApiError

        api = KbApi(self.kb, {self.TOKEN: ["research.read"]})
        # scope enforcement lives at the transport layer; the logic-level
        # contract is that authenticate() rejects missing scopes with 403
        self.assertEqual(api.authenticate(self.TOKEN, "research.read"),
                         "research.read")
        with self.assertRaises(KbApiError) as ctx:
            api.authenticate(self.TOKEN, "memory.review")
        self.assertEqual(ctx.exception.status, 403)
        with self.assertRaises(KbApiError) as ctx:
            api.authenticate(None, "memory.review")
        self.assertEqual(ctx.exception.status, 401)
