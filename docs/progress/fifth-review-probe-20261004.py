"""Independent synthetic probes; no network, private documents or cleanup.
Run from repository root. Evidence remains in a unique runtime directory.
"""
import json
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = ['app', 'app/tests']
from knowledge.store import KnowledgeStore, utc_now
from knowledge.budget import Budget, BudgetLedger
from knowledge.analysis import execute_analysis_run, budgeted_embed
from knowledge.providers import OpenAICompatibleChat, OpenAICompatibleVision, OpenAICompatibleEmbedding
from knowledge.ocr import VisionApiOcr
from knowledge.writeback import register_write_root, export_claim_candidates
from knowledge.indexing import build_generation, search, SearchFilters
from test_knowledge_index_api import _doc, _version, _block

root = Path('runtime/review-fifth-20261004') / uuid.uuid4().hex[:8]
root.mkdir(parents=True)
out = {}
common = dict(name='synthetic', model='test', base_url='https://synthetic.invalid',
              api_key='test-only', egress_allowed=True, max_retries=1)
response = {'choices': [{'message': {'content': 'unknown'}}],
            'data': [{'index': 0, 'embedding': [1., 0.]}],
            'usage': {'prompt_tokens': 5, 'completion_tokens': 2}}
for role, cls in [('chat', OpenAICompatibleChat), ('vision', OpenAICompatibleVision),
                  ('embedding', OpenAICompatibleEmbedding)]:
    kb = KnowledgeStore(str(root / (role + '.db')))
    ledger = BudgetLedger(kb, Budget(max_requests_total=1))
    provider = cls(**common, **({'dimensions': 2} if role == 'embedding' else {}))
    outcomes = []
    with patch.object(provider, '_transport', return_value=response) as tx:
        for i in range(2):
            try:
                if role == 'chat':
                    run = kb.create_analysis_run('test%d' % i)
                    result = execute_analysis_run(kb, run['run_id'], 'test%d' % i,
                                                  provider, retriever=lambda q, n: [], ledger=ledger)
                    outcomes.append(result['status'])
                elif role == 'vision':
                    VisionApiOcr(chat_provider=provider, ledger=ledger).run(b'synthetic')
                    outcomes.append('done')
                else:
                    budgeted_embed(provider, ['hello'], ledger=ledger)
                    outcomes.append('done')
            except Exception as exc:
                outcomes.append(type(exc).__name__)
        out[role + '_success_cap'] = dict(cap=1, attempts=tx.call_count,
                                          totals=ledger._totals(), outcomes=outcomes)
    kb.close()

state = root / 'reconcile-state'
state.mkdir()
manifest = root / 'manifest.json'
manifest.write_text(json.dumps({'samples': [dict(source='reports', doc_id='D',
    version_id='v2', split='blind', sha256='b'*64, recipe='expected')]}), encoding='utf-8')
def reconcile(name):
    report = root / (name + '.json')
    proc = subprocess.run([sys.executable, 'tools/shadow-acceptance/shadow_reconcile.py',
        '--manifest', str(manifest), '--state-dir', str(state), '--out', str(report)],
        capture_output=True, text=True)
    data = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
    return dict(exit=proc.returncode, db_exists=(state/'knowledge.sqlite3').exists(),
                report={k: v for k, v in data.items() if k != 'rows'})
out['reconcile_empty_state'] = reconcile('empty')
kb = KnowledgeStore(str(state/'knowledge.sqlite3'))
kb.upsert_documents([_doc('reports', 'D', 'AAA')], utc_now())
kb.upsert_versions([_version('reports', 'D', 'v2', 'a'*64)], utc_now())
kb.record_snapshot('reports', 'D', 'v2', 'a'*64, 99, str(state/'absent.pdf'), utc_now())
kb.record_extraction(dict(extraction_id='e', source='reports', doc_id='D', version_id='v2',
    snapshot_sha256='a'*64, parser_id='test', parser_version='1', config_digest='wrong-recipe',
    status='ready', issues=[], stats={}), [_block('paragraph', 'needle revised', dict(kind='pdf', page=1))])
kb.close()
out['reconcile_missing_blob_wrong_hash_recipe'] = reconcile('forged')

kb = KnowledgeStore(str(root/'legacy.db'))
doc = _doc('reports', 'D', 'AAA'); doc['published_at'] = '2026-01-01T00:00:00Z'
kb.upsert_documents([doc], utc_now()); version = _version('reports', 'D', 'v2', 'a'*64)
kb.upsert_versions([version], '2026-08-20T00:00:00Z')
with kb._tx() as conn:
    conn.execute("UPDATE kb_versions SET first_observed_at=NULL, public_available_at='2026-01-01T00:00:00Z', public_time_basis='published_at'")
kb.upsert_versions([version], '2026-10-04T00:00:00Z')
kb.record_extraction(dict(extraction_id='e', source='reports', doc_id='D', version_id='v2',
    snapshot_sha256='a'*64, parser_id='test', parser_version='1', config_digest='cfg',
    status='ready', issues=[], stats={}), [_block('paragraph', 'needle revised', dict(kind='pdf', page=1))])
build_generation(kb)
out['previously_misbound_legacy_time'] = dict(public_available_at=kb.get_version('reports','D','v2')['public_available_at'],
    july_hits=len(search(kb,'needle',SearchFilters(as_of='2026-07-01',as_of_mode='public'))['hits']))
kb.close()

kb = KnowledgeStore(str(root/'claim.db'))
claim = dict(claim_id='clm-synthetic', current_revision=1, subject='test', statement='same',
             status='accepted', author='test', prompt_version='1', evidence=[])
kb.upsert_claim(claim)
folder = root/'claims'; folder.mkdir(); register_write_root(str(folder))
for i in range(3):
    with patch('knowledge.writeback.utc_now', return_value='2026-10-04T00:00:0%dZ'%i):
        export_claim_candidates(kb, str(folder))
out['same_revision_three_exports'] = dict(files=len(list(folder.glob('*.md'))), expected=1)
claim.update(current_revision=2, statement='revision two'); kb.upsert_claim(claim)
with patch('knowledge.writeback._save_manifest', side_effect=OSError('simulated interruption')):
    try: export_claim_candidates(kb, str(folder))
    except OSError: pass
export_claim_candidates(kb, str(folder))
out['interrupted_revision_two'] = dict(revision_two_files=sum('rev 2' in p.read_text(encoding='utf-8') for p in folder.glob('*.md')), expected=1)
kb.close()
(root/'results.json').write_text(json.dumps(out, indent=2), encoding='utf-8')
print(json.dumps(out, indent=2))
