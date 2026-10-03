"""Fourth-review local synthetic probes. No real network or source data.
Run from repository root; leaves unique runtime evidence directories intact.
"""
import ast,json,sqlite3,subprocess,sys,uuid,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['app','app/tests']
from knowledge.store import KnowledgeStore,utc_now
from knowledge.budget import Budget,BudgetLedger
from knowledge.analysis import execute_analysis_run,budgeted_embed
from knowledge.providers import OpenAICompatibleChat,OpenAICompatibleVision,OpenAICompatibleEmbedding
from knowledge.ocr import VisionApiOcr
from knowledge.writeback import register_write_root,export_claim_candidates
from knowledge.indexing import build_generation,search,SearchFilters
from test_knowledge_index_api import _doc,_version,_block
root=Path('runtime/review-fourth-20261003')/uuid.uuid4().hex[:8];root.mkdir(parents=True);out={}
def kb(name):return KnowledgeStore(str(root/(name+'.db')))
old=subprocess.check_output(['git','show','0a473d9:app/knowledge/store.py'],text=True,encoding='utf-8')
schema=next(ast.literal_eval(n.value) for n in ast.parse(old).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in n.targets))
p=root/'old.db';c=sqlite3.connect(p);c.executescript(schema);c.close();k=KnowledgeStore(str(p))
try:BudgetLedger(k,Budget(max_total_input_tokens=100)).reserve('chat',10);out['old_db_budget']={'opened':True,'budget_ok':True}
except Exception as e:out['old_db_budget']={'opened':True,'budget_ok':False,'error':str(e),'missing_usage_counts_request':'counts_request' not in [r[1] for r in k._conn.execute('pragma table_info(usage_events)')]}
k.close()
common=dict(name='synthetic',model='test',base_url='https://synthetic.invalid',api_key='test-only',egress_allowed=True,max_retries=1)
k=kb('chat');l=BudgetLedger(k,Budget(max_requests_total=1));chat=OpenAICompatibleChat(**common);run=k.create_analysis_run('test')
with patch.object(chat,'_transport',side_effect=urllib.error.URLError('synthetic timeout')) as tx:
 r=execute_analysis_run(k,run['run_id'],'test',chat,retriever=lambda q,n:[],ledger=l)
 out['chat_retry_cap']={'cap':1,'http_attempts':tx.call_count,'result':r['status'],'accounted_requests':l._totals()['requests']}
k.close()
k=kb('vision');l=BudgetLedger(k,Budget(max_requests_total=1));vision=OpenAICompatibleVision(**common);engine=VisionApiOcr(chat_provider=vision,ledger=l)
with patch.object(vision,'_transport',side_effect=urllib.error.URLError('synthetic timeout')) as tx:
 try:engine.run(b'synthetic image')
 except Exception:pass
 out['vision_retry_cap']={'cap':1,'http_attempts':tx.call_count,'accounted_requests':l._totals()['requests']}
k.close()
k=kb('embedding');l=BudgetLedger(k,Budget(max_requests_total=1));e=OpenAICompatibleEmbedding(**common,dimensions=2)
with patch.object(e,'_transport',return_value={'data':[{'index':0,'embedding':[1.,0.]}],'usage':{'prompt_tokens':5}}):budgeted_embed(e,['hello'],ledger=l)
out['embedding_success_attempt_lifecycle']={'reservations':[dict(r) for r in k._conn.execute('SELECT kind,status,est_input FROM budget_reservations')],'totals':l._totals()};k.close()
k=kb('historical');d=_doc('reports','D','AAA');d.update(published_at='2026-01-01T00:00:00Z');k.upsert_documents([d],utc_now());v=_version('reports','D','v2','a'*64);k.upsert_versions([v],'2026-08-20T00:00:00Z')
with k._tx() as c:c.execute('UPDATE kb_versions SET first_observed_at=NULL,public_available_at=NULL,public_time_basis=NULL')
k.upsert_versions([v],'2026-10-03T00:00:00Z')
k.record_extraction(dict(extraction_id='e',source='reports',doc_id='D',version_id='v2',snapshot_sha256='a'*64,parser_id='test',parser_version='1',config_digest='cfg',status='ready',issues=[],stats={}),[_block('paragraph','needle revised text',dict(kind='pdf',page=1))]);build_generation(k)
out['legacy_unknown_public_time']={'first_observed_at':k.get_version('reports','D','v2')['first_observed_at'],'public_available_at':k.get_version('reports','D','v2')['public_available_at'],'july_hits':len(search(k,'needle',SearchFilters(as_of='2026-07-01',as_of_mode='public'))['hits'])};k.close()
k=kb('claim');k.upsert_claim(dict(claim_id='clm-synthetic',current_revision=1,subject='test',statement='same statement',status='accepted',author='test',prompt_version='1',evidence=[]));folder=root/'claim-export';folder.mkdir();register_write_root(str(folder))
for i in range(3):
 with patch('knowledge.writeback.utc_now',return_value='2026-10-03T00:00:0%dZ'%i):export_claim_candidates(k,str(folder))
out['unchanged_claim_export']={'revision':1,'exports':3,'markdown_files':len(list(folder.glob('*.md')))};k.close()
(root/'results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
