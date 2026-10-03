"""Offline synthetic review probes. Run from repository root:
python docs/progress/re-review-probe-20261003.py
Requires project test dependencies and PyYAML. Outputs observations, not pass assertions.
Creates unique runtime/review-20261003 files; no cleanup, network or production access.
"""
import sys,json,uuid,threading,hashlib,os
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=['app','app/tests']
from knowledge.store import KnowledgeStore,utc_now
from knowledge.budget import Budget,BudgetLedger
from knowledge.providers import Usage
from knowledge.config import KnowledgeConfig
from knowledge.sync import SyncService
from knowledge.indexing import build_generation,search,SearchFilters
from knowledge.kbapi import KbApi
from knowledge.jobs import JobRunner
from knowledge.snapshot import SnapshotStore
from knowledge.writeback import write_candidate,register_write_root
from knowledge.extract import extract_pdf
from knowledge.ocr import OcrConfig
from test_knowledge_index_api import _doc,_version,_block
root=Path('runtime/review-20261003')/uuid.uuid4().hex[:8];root.mkdir(parents=True);out={}
def kb(name):return KnowledgeStore(str(root/(name+'.db')))
def seed(k,doc='D',version='v1',ext='e',text='needle',stamp='2026-01-01T00:00:00Z',current=True,n=1):
 d=_doc('reports',doc,'SYM',stamp);k.upsert_documents([d],stamp);v=_version('reports',doc,version,'a'*64);v['is_current']=current;k.upsert_versions([v],stamp)
 k.record_extraction(dict(extraction_id=ext,source='reports',doc_id=doc,version_id=version,snapshot_sha256='a'*64,parser_id='test',parser_version='1',config_digest='cfg',status='ready',issues=[],stats={}),[_block('paragraph',text,dict(kind='pdf',page=i+1)) for i in range(n)])
k=kb('budget-race');l=BudgetLedger(k,Budget(max_total_input_tokens=10));orig=l._totals;barrier=threading.Barrier(2);ans=[]
def synchronized_totals():
 r=orig();barrier.wait(timeout=5);return r
l._totals=synchronized_totals
def reserve():
 try:ans.append(l.reserve('chat',6))
 except Exception as e:ans.append(type(e).__name__)
ts=[threading.Thread(target=reserve) for _ in range(2)]
for t in ts:t.start()
for t in ts:t.join()
l._totals=orig;out['budget_atomicity']={'accepted_ids':ans,'reserved':l._totals()['input'],'cap':10};k.close()
k=kb('page-budget');l=BudgetLedger(k,Budget(max_pages_total=1));a=l.reserve('vision-page',20,counts_as_page=True);b=l.reserve('vision-page',20,counts_as_page=True);l.fail_unknown(a);c=l.reserve('vision-page',20,counts_as_page=True);out['page_cap']={'cap':1,'accepted':3,'totals':l._totals()};k.close()
k=kb('settlement');l=BudgetLedger(k,Budget(max_total_input_tokens=10));r=l.reserve('chat',8)
try:
 with patch.object(k,'record_usage',side_effect=RuntimeError('crash before usage')):l.settle(r,Usage('mock','m',8,1,'mock'))
except RuntimeError:pass
out['settlement_crash']={'remaining_after_billed_call':l.remaining(),'cap':10,'usage':k.usage_totals()};k.close()
k=kb('outbox');s=SyncService(k,KnowledgeConfig(register_stages=('extract',)));d=_doc('reports','D','SYM');v=_version('reports','D','v1','a'*64)
def stats():return dict(documents=0,new_documents=0,versions=0,new_versions=0,sources={},jobs_registered=0)
try:
 with patch.object(k,'enqueue_impact',side_effect=RuntimeError('crash at enqueue')):s._commit_document(d,[v],stats(),'cfg')
except RuntimeError:pass
st=stats();s._commit_document(d,[v],st,'cfg');out['outbox_crash']={'version_exists':k.get_version('reports','D','v1') is not None,'retry_new_versions':st['new_versions'],'pending':len(k.pending_impacts())};k.close()
folder=root/'write';folder.mkdir();register_write_root(str(folder));write_candidate(str(folder),'note.md','machine-v1');orig_replace=os.replace
def edit_then_replace(src,dst):
 if Path(dst).name=='note.md':Path(dst).write_text('human edit after last hash check',encoding='utf-8')
 return orig_replace(src,dst)
with patch('knowledge.writeback.os.replace',side_effect=edit_then_replace):result=write_candidate(str(folder),'note.md','machine-v2')
out['writeback_race']={'outcome':result['outcome'],'remaining_content':(folder/'note.md').read_text(encoding='utf-8')}
k=kb('public');seed(k);d=_doc('reports','D','SYM');d.update(report_date='2026-06-30',published_at='2026-08-20T12:00:00Z',filing_date='2026-08-20');k.upsert_documents([d],utc_now());build_generation(k);out['public_asof']={'cutoff':'2026-07-01','published_at':d['published_at'],'hits':len(search(k,'needle',SearchFilters(as_of='2026-07-01',as_of_mode='public'))['hits'])};k.close()
class CountingOcr:
 name='fake-ocr'
 def __init__(self):self.calls=0
 def run(self,raw):self.calls+=1;return ('Synthetic OCR text with sufficient characters for a readable result.',0.99)
k=kb('image');raw=b'fake image';sha=hashlib.sha256(raw).hexdigest();blobs=SnapshotStore(str(root/'blobs'));path=Path(blobs.blob_abs_path(sha));path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);k.upsert_documents([_doc('reports','I','SYM')],utc_now());v=_version('reports','I','v1',sha);v.update(media_type='image/png',ext='png',bytes=len(raw));k.upsert_versions([v],utc_now());rel=blobs.blob_rel_path(sha).replace('\\','/');k.record_blob(sha,len(raw),rel,utc_now());k.record_snapshot('reports','I','v1',sha,len(raw),rel,utc_now());r=JobRunner(k,KnowledgeConfig(snapshot_root=blobs.root),None,blobs);engine=CountingOcr();r.ocr_engine=lambda:engine;r.fallback_ocr_engine=lambda:None
job=dict(source='reports',doc_id='I',version_id='v1');e1=r._execute_extract(job);e2=r._execute_extract(job);out['image_duplicate_ocr']={'ocr_calls':engine.calls,'same_extraction':e1==e2}
api=KbApi(k,{},snapshot_root=blobs.root);old_verify=SnapshotStore.verify_blob
def mutate_after_verify(obj,*args,**kwargs):
 valid=old_verify(obj,*args,**kwargs);path.write_bytes(b'EVIL IMAGE');return valid
with patch.object(SnapshotStore,'verify_blob',mutate_after_verify):res=api.snapshot_bytes('reports','I','v1')
out['snapshot_read_race']={'returned_text':res['data'].decode(),'etag_matches_returned':res['etag']=='"'+hashlib.sha256(res['data']).hexdigest()+'"'};k.close()
class LowOcr:
 name='low'
 def run(self,raw):return ('OCR text has lots of characters but confidence is extremely low.',0.1)
with patch('knowledge.extract.extractor_info',return_value=('pypdfium2','test')),patch('knowledge.extract._pdfium_page_texts',return_value=['']):
 e=extract_pdf(b'fake pdf',ocr=LowOcr(),ocr_config=OcrConfig(min_confidence=0.6),renderer=lambda *a,**k:b'image')
out['low_confidence_pdf']={'status':e.status,'block_quality':[b.quality.status for b in e.blocks],'issues':e.issues}
# Metadata mutations do not invalidate an issued cursor; the second page silently skips a hit.
k=kb('cursor');seed(k,doc='A',ext='a',n=2);seed(k,doc='B',ext='b',n=2);build_generation(k);api=KbApi(k,{});first=api.do_search(dict(query='needle',limit=2));doc=first['hits'][0]['doc_id'];d=_doc('reports',doc,'SYM');d['available']=False;k.upsert_documents([d],utc_now());second=api.do_search(dict(query='needle',limit=2,cursor=first['next_cursor']));out['cursor_metadata']={'first':len(first['hits']),'second':len(second['hits']),'second_next':second['next_cursor'],'remaining_visible':len(search(k,'needle')['hits'])};k.close()
import yaml
out['compose_parse']={f:'PASS' if yaml.safe_load(Path(f).read_text(encoding='utf-8')) else 'EMPTY' for f in ['deploy/docker-compose.full.yml','deploy/docker-compose.knowledge.yml']}

from knowledge.analysis import hybrid_search
class SemanticMock:
 name='offline-review'
 model='semantic-review-v1'
 dimensions=2
 def embed(self,texts):
  return [([1.0,0.0] if t in ('needle','semantic synonym') else [0.0,1.0]) for t in texts],Usage(self.name,self.model,1,0,'mock')
k=kb('semantic');seed(k,doc='K',ext='kw',text='needle literal');seed(k,doc='S',ext='semantic',text='semantic synonym');build_generation(k)
h=hybrid_search(k,'needle',SemanticMock(),limit=10)
out['independent_semantic_recall']={'returned_docs':[hit['block']['doc_id'] for hit in h['hits']], 'missing_semantic_doc':'S'};k.close()
full=yaml.safe_load(Path('deploy/docker-compose.full.yml').read_text(encoding='utf-8'))
image_cmd=next(line for line in Path('Dockerfile.knowledge').read_text().splitlines() if line.startswith('CMD '))
out['library_effective_command']={'service_command':full['services']['library'].get('command'),'inherited_image_cmd':image_cmd}

print(json.dumps(out,ensure_ascii=False,indent=2));root.joinpath('results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
