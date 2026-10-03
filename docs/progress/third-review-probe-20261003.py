"""Third review: synthetic local-only boundary probes; no network or cleanup.
Run from repo root: python docs/progress/third-review-probe-20261003.py
"""
import ast, hashlib, json, sqlite3, subprocess, sys, uuid, urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['app','app/tests']
from knowledge.store import KnowledgeStore, utc_now
from knowledge.budget import Budget,BudgetLedger
from knowledge.providers import Usage,OpenAICompatibleEmbedding
from knowledge.indexing import build_generation,search,SearchFilters,allowed_block_ids
from knowledge.kbapi import KbApi,KbApiError
from knowledge.analysis import budgeted_embed,ensure_block_embeddings,hybrid_search
from knowledge.extract import extract_pdf,extract_config_digest
from knowledge.ocr import OcrConfig
from test_knowledge_index_api import _doc,_version,_block
root=Path('runtime/review-third-20261003')/uuid.uuid4().hex[:8];root.mkdir(parents=True);out={}
def kb(name):return KnowledgeStore(str(root/(name+'.db')))
def seed(k,doc='D',version='v1',ext='e',text='needle',n=1,symbol='AAA',stamp='2026-01-01T00:00:00Z'):
 d=_doc('reports',doc,symbol,stamp);k.upsert_documents([d],stamp)
 v=_version('reports',doc,version,'a'*64);k.upsert_versions([v],stamp)
 k.record_extraction(dict(extraction_id=ext,source='reports',doc_id=doc,version_id=version,snapshot_sha256='a'*64,parser_id='test',parser_version='1',config_digest='cfg',status='ready',issues=[],stats={}),[_block('paragraph',text,dict(kind='pdf',page=i+1)) for i in range(n)])
old_store=subprocess.check_output(['git','show','0a473d9:app/knowledge/store.py'],text=True,encoding='utf-8')
schema=next(ast.literal_eval(node.value) for node in ast.parse(old_store).body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCHEMA' for t in node.targets))
old_path=root/'upgrade.db';conn=sqlite3.connect(old_path);conn.executescript(schema);conn.close()
try:
 migrated=KnowledgeStore(str(old_path));migrated.close();out['old_database_upgrade']={'opened':True}
except Exception as exc:out['old_database_upgrade']={'opened':False,'error':str(exc)}
k=kb('unknown');l=BudgetLedger(k,Budget(max_total_input_tokens=10));r=l.reserve('chat',8)
try:
 with patch.object(k,'record_usage',side_effect=RuntimeError('crash after status commit')):l.fail_unknown(r)
except RuntimeError:pass
out['unknown_settlement_crash']={'remaining':l.remaining(),'usage':k.usage_totals(),'expected_max_remaining':2};k.close()
k=kb('unknown-repeat');l=BudgetLedger(k,Budget(max_total_input_tokens=30));r=l.reserve('chat',8);l.fail_unknown(r);l.fail_unknown(r)
out['unknown_replay']={'usage':k.usage_totals(),'expected_input':8};k.close()
class BadVector:
 name='mock';model='m';dimensions=2
 def embed(self,texts):return [[1]],Usage('mock','m',5,0,'mock-billed')
k=kb('bad-vector');l=BudgetLedger(k,Budget(max_total_input_tokens=100))
try:budgeted_embed(BadVector(),['hello'],ledger=l)
except ValueError:pass
out['paid_bad_vector_release']={'remaining':l.remaining(),'usage':k.usage_totals()};k.close()
k=kb('retry');l=BudgetLedger(k,Budget(max_requests_total=1));p=OpenAICompatibleEmbedding(name='test',model='m',base_url='https://synthetic.invalid',api_key='synthetic',egress_allowed=True,dimensions=2,max_retries=1)
with patch('urllib.request.urlopen',side_effect=urllib.error.URLError('synthetic timeout')) as http:
 try:budgeted_embed(p,['hello'],ledger=l)
 except Exception:pass
 out['retry_request_cap']={'cap':1,'mock_http_attempts':http.call_count,'accounted_requests':l._totals()['requests']}
k.close()
k=kb('public-revision');d=_doc('reports','D','AAA');d.update(published_at='2026-01-01T00:00:00Z',report_date='2025-12-31');k.upsert_documents([d],utc_now())
old_v=_version('reports','D','v1','b'*64);old_v['is_current']=False;k.upsert_versions([old_v],'2026-01-01T00:00:00Z')
v=_version('reports','D','v2','a'*64);v['content_changed_at']='2026-08-20T00:00:00Z';k.upsert_versions([v],'2026-08-20T00:00:00Z')
k.record_extraction(dict(extraction_id='v2e',source='reports',doc_id='D',version_id='v2',snapshot_sha256='a'*64,parser_id='test',parser_version='1',config_digest='cfg',status='ready',issues=[],stats={}),[_block('paragraph','needle revision only known in August',dict(kind='pdf',page=1))]);build_generation(k)
out['public_revision_inherits_old_date']={'version_public_at':k.get_version('reports','D','v2')['public_available_at'],'cutoff':'2026-07-01','hits':len(search(k,'needle',SearchFilters(as_of='2026-07-01',as_of_mode='public'))['hits'])};k.close()
k=kb('epoch');seed(k,doc='A',ext='a',n=2);seed(k,doc='B',ext='b',n=2);build_generation(k);api=KbApi(k,{});payload={'query':'needle','limit':2,'filters':{'symbols':['AAA']}};first=api.do_search(payload);before=api.metadata_epoch();doc=first['hits'][0]['doc_id'];d=_doc('reports',doc,'BBB','2026-01-01T00:00:00Z');k.upsert_documents([d],utc_now());after=api.metadata_epoch()
try:
 second=api.do_search(dict(payload,cursor=first['next_cursor']));result={'status':200,'second_hits':len(second['hits']),'next':second['next_cursor']}
except KbApiError as exc:result={'status':exc.status}
out['same_length_metadata_cursor']={'same_epoch':before==after,'first_hits':len(first['hits']),'second':result,'visible_remaining':len(search(k,'needle',SearchFilters(symbols=['AAA']))['hits'])};k.close()
class EmptyOcr:
 name='empty'
 def run(self,raw):return '',0.0
class BadFallback:
 name='bad'
 def run(self,raw):raise RuntimeError('mock fallback failed')
with patch('knowledge.extract.extractor_info',return_value=('pypdfium2','test')),patch('knowledge.extract._pdfium_page_texts',return_value=['','Long valid second page with sufficient text for the document to pass length checks.','Long valid third page containing more reliable extracted data from the text layer.']):
 e=extract_pdf(b'fake',ocr=EmptyOcr(),ocr_config=OcrConfig(),renderer=lambda *a,**k:b'image',fallback_ocr=BadFallback())
out['empty_ocr_multi_page']={'status':e.status,'unmet_ocr_pages':e.stats['unmet_ocr_pages'],'page_ocr_status':e.stats['page_ocr_status'],'issues':e.issues}
old_extract=subprocess.check_output(['git','show','0a473d9:app/knowledge/extract.py'],text=True,encoding='utf-8');old_ns={'__name__':'knowledge.review_old_extract','__package__':'knowledge'}
import types
old_module=types.ModuleType(old_ns['__name__']);sys.modules[old_module.__name__]=old_module;old_module.__dict__.update(old_ns);old_ns=old_module.__dict__
exec(compile(old_extract,'baseline-extract','exec'),old_ns)
out['processing_identity_upgrade']={'old_digest':old_ns['extract_config_digest'](OcrConfig()),'new_digest':extract_config_digest(OcrConfig()),'same':old_ns['extract_config_digest'](OcrConfig())==extract_config_digest(OcrConfig())}
class CacheMock:
 model='shared-name';dimensions=2
 def __init__(self,name,vec):self.name=name;self.vec=vec;self.calls=0
 def embed(self,texts):self.calls+=1;return [self.vec for _ in texts],Usage(self.name,self.model,1,0,'mock')
k=kb('cache');seed(k);bid=k._conn.execute('SELECT block_id FROM blocks').fetchone()[0];a=CacheMock('provider-a',[1.,0.]);b=CacheMock('provider-b',[0.,1.]);ensure_block_embeddings(k,a,[bid]);ensure_block_embeddings(k,b,[bid]);out['cross_provider_cache']={'provider_a_calls':a.calls,'provider_b_calls':b.calls,'stored_vector':k.get_embedding('shared-name',bid,dimensions=2)};k.close()
k=kb('recall');seed(k,n=205,text='semantic unique evidence');build_generation(k);allowed=allowed_block_ids(k,None);target=allowed[-1]
# In this synthetic DB each block is independently mutable test setup; no real evidence touched.
with k._tx() as conn:conn.execute('UPDATE blocks SET text=? WHERE block_id=?',('target semantic synonym',target))
class TargetMock:
 name='offline';model='target';dimensions=2
 def embed(self,texts):return [([1.,0.] if t in ('needle','target semantic synonym') else [0.,1.]) for t in texts],Usage(self.name,self.model,1,0,'mock')
h=hybrid_search(k,'needle',TargetMock(),limit=20)
out['semantic_after_first_200']={'allowed_blocks':len(allowed),'target_position':205,'returned_target':any(hit['block']['block_id']==target for hit in h['hits']),'returned_count':len(h['hits'])};k.close()
from knowledge.writeback import register_write_root,write_candidate
folder=root/'writeback';folder.mkdir();register_write_root(str(folder));write_candidate(str(folder),'doc.md','v1')
for _ in range(3):write_candidate(str(folder),'doc.md','v2')
files=list(folder.glob('*.md'));out['writeback_repeat_new_revision']={'markdown_files':len(files),'v2_copies':sum(p.read_text(encoding='utf-8')=='v2' for p in files),'expected_v2_copies':1}

(root/'results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
