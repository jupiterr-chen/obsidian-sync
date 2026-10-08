"""Bounded, authorized GLM OCR continuation. Immutable cache, one KB writer.

Uses the accepted application image without changing online service config.
Only manifest-bound snapshot pages may leave the server. Dense tables,
incomplete outputs and provider failures fall back to the existing local OCR.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import urllib.error
import urllib.request

MODEL = 'GLM-5.3-Flash'
ENDPOINT = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
PROMPT = ('Transcribe this document page faithfully into Markdown. Preserve all visible text, '
          'headings, table row/column relationships, numbers, signs, decimals, dates, units and footnotes. '
          'Do not summarize, analyze, correct figures, or invent missing text. '
          'For unreadable text use [unreadable]. Output only the transcription, no preamble or code fence.')
POLICY = {'version': 1, 'model': MODEL, 'endpoint': ENDPOINT,
          'prompt_sha256': hashlib.sha256(PROMPT.encode()).hexdigest(),
          'dpi': 200, 'max_output_tokens': 8192, 'timeout_seconds': 180,
          'dense_table_columns': 10, 'dense_table_numeric_cells': 160,
          'plain_numeric_tokens': 250,
          'unknown_confidence': 0.5, 'automatic_model_retries': 0,
          'max_physical_requests': 2500, 'fallback': 'local-rapidocr'}


def save(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def reject_output(text, stop_reason):
    import re
    if stop_reason != 'end_turn':
        return 'incomplete_response'
    if not text.strip():
        return 'empty_response'
    if '[unreadable]' in text.lower():
        return 'unreadable_content'
    rows = [line for line in text.splitlines() if line.strip().startswith('|')]
    if any(len(line.strip().strip('|').split('|')) >= POLICY['dense_table_columns'] for line in rows):
        return 'dense_table'
    if (sum(len(re.findall(r'\d[\d,.]*', row)) for row in rows) >= POLICY['dense_table_numeric_cells']
            or len(re.findall(r'\d[\d,.]*', text)) >= POLICY['plain_numeric_tokens']):
        return 'dense_table'
    # Match the existing damage fingerprints; never repair by deleting bytes.
    from knowledge.quality import damaged_reasons
    if damaged_reasons(text):
        return 'damaged_output'
    return None


class CloudPages:
    def __init__(self, operation, key, transport=None):
        self.root = Path(operation) / 'pages'
        self.root.mkdir(parents=True, exist_ok=True)
        self.key = key
        self.transport = transport
        self.guard = threading.Lock()
        self.inflight = {}
        self.disabled = False
        self.requests = len(list(self.root.glob('*.dispatch.json')))

    def identify(self, png):
        return sha(json.dumps(POLICY, sort_keys=True).encode() + b'\0' + png)

    def recognize(self, png):
        identity = self.identify(png)
        result_path = self.root / (identity + '.json')
        with self.guard:
            event = self.inflight.get(identity)
            if event is None:
                event = threading.Event()
                self.inflight[identity] = event
                owner = True
            else:
                owner = False
        if not owner:
            event.wait(POLICY['timeout_seconds'] + 20)
            return json.loads(result_path.read_text()) if result_path.exists() else {'fallback': 'unknown_inflight'}
        try:
            if result_path.exists():
                return json.loads(result_path.read_text())
            marker = self.root / (identity + '.dispatch.json')
            if marker.exists():
                return {'fallback': 'previous_request_outcome_unknown'}
            with self.guard:
                if self.disabled or self.requests >= POLICY['max_physical_requests']:
                    return {'fallback': 'provider_disabled_or_request_limit'}
                # No credential, header or full request body is logged.
                with marker.open('x', encoding='utf-8') as handle:
                    json.dump({'at': time.time(), 'image_sha256': sha(png),
                               'model': MODEL, 'endpoint': ENDPOINT}, handle)
                self.requests += 1
            started = time.monotonic()
            result = {'image_sha256': sha(png)}
            try:
                payload = {'model': MODEL, 'max_tokens': POLICY['max_output_tokens'],
                           'messages': [{'role': 'user', 'content': [
                               {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                 'data': base64.b64encode(png).decode('ascii')}},
                               {'type': 'text', 'text': PROMPT}]}]}
                if self.transport:
                    response = self.transport(payload)
                else:
                    req = urllib.request.Request(ENDPOINT, json.dumps(payload).encode(), method='POST',
                          headers={'Content-Type': 'application/json', 'x-api-key': self.key,
                                   'anthropic-version': '2023-06-01'})
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(req, timeout=POLICY['timeout_seconds']) as reply:
                        response = json.loads(reply.read())
                text = '\n'.join(b.get('text', '') for b in response.get('content', []) if b.get('type') == 'text')
                result.update(text=text, model=response.get('model'), usage=response.get('usage'),
                              stop_reason=response.get('stop_reason'),
                              fallback=reject_output(text, response.get('stop_reason')))
                if str(response.get('model', '')).lower() != MODEL.lower():
                    result['fallback'] = 'unexpected_model'
            except urllib.error.HTTPError as exc:
                result.update(fallback='http_error', http_status=exc.code)
                # Quota/auth failures stop cloud dispatch for this invocation;
                # no retry storm or switch to a separately billed endpoint.
                if exc.code in (401, 402, 403, 429):
                    with self.guard:
                        self.disabled = True
            except Exception as exc:
                result.update(fallback='transport_or_parse_error', error_type=type(exc).__name__)
            result['seconds'] = round(time.monotonic() - started, 2)
            save(result_path, result)
            return result
        finally:
            event.set()


class CachedHybrid:
    name = 'glm-5.3-flash-cached-with-local-fallback'

    def __init__(self, results, local):
        self.results = results
        self.local = local
        self.remote_pages = 0
        self.local_pages = 0
        self.reasons = []

    def run(self, raw):
        from PIL import Image
        # The image extractor may supply JPEG; CloudPages only sends PNG.
        image = Image.open(BytesIO(raw)).convert('RGB')
        buf = BytesIO()
        image.save(buf, format='PNG')
        png = buf.getvalue()
        result = self.results.get(sha(png))
        if result and not result.get('fallback'):
            self.remote_pages += 1
            return result['text'], POLICY['unknown_confidence']
        self.local_pages += 1
        self.reasons.append((result or {}).get('fallback', 'cache_miss'))
        return self.local.run(png)


def page_images(raw, fmt, config):
    """Render sequentially (PDFium is not thread safe); send only OCR candidates."""
    from PIL import Image
    from knowledge.extract import _pdfium_page_texts
    from knowledge.quality import route_page_to_ocr
    from knowledge.ocr import render_page_to_png
    pages = {}
    if fmt == 'pdf':
        texts = list(_pdfium_page_texts(raw) or [])
        for number, text in enumerate(texts, 1):
            wants, _ = route_page_to_ocr(len(text or ''), text or '', parser_id='pypdfium2', engine_kind='page-tree')
            if wants and len(pages) < config.max_pages_per_doc:
                pages[number] = render_page_to_png(raw, number, dpi=config.render_dpi)
    elif fmt == 'img':
        pages[1] = raw
    normalized = {}
    for number, image in pages.items():
        im = Image.open(BytesIO(image)).convert('RGB')
        buf = BytesIO()
        im.save(buf, format='PNG')
        normalized[number] = buf.getvalue()
    return normalized


def validated_raw(root, item):
    path = Path(root) / item['snapshot']['store_path']
    assert path.resolve().is_relative_to(Path(root).resolve()), 'snapshot outside root'
    raw = path.read_bytes()
    assert sha(raw) == item['version_sha256'] == item['snapshot']['sha256']
    assert len(raw) == item['snapshot']['bytes']
    return raw


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--operation', required=True)
    p.add_argument('--config', required=True)
    p.add_argument('--secret', required=True)
    p.add_argument('--vault', default='/vault')
    p.add_argument('--workers', type=int, default=2, choices=[1, 2, 4])
    args = p.parse_args()
    from knowledge.config import KnowledgeConfig
    from knowledge.store import KnowledgeStore
    from knowledge.extract import compute_extraction_id, effective_extract_config, extract_pdf, get_extractor
    from knowledge.sampling import format_of
    from knowledge.ocr import LocalRapidOcr
    from knowledge.repair import register_reprocess_batch
    from knowledge.reading import ReadingPublisher
    from knowledge.indexing import build_generation
    from knowledge.quality import damaged_reasons
    from library.locking import FileLock

    op = Path(args.operation)
    manifest = json.loads((op / 'manifest.json').read_text())
    runner_sha = sha(Path(__file__).read_bytes())
    assert runner_sha == manifest['runner_sha256'], 'runner changed since manifest freeze'
    config = KnowledgeConfig.load(args.config).resolve('/app-config')
    assert config.ocr_config().engine == 'local' and not config.ocr_config().fallback
    assert not config.extra.get('analysis', {}).get('enabled', False)
    secret = json.loads(Path(args.secret).read_text())
    assert secret['endpoint'] == ENDPOINT and secret['model'] == MODEL
    ocr_config = config.ocr_config()
    assert ocr_config.render_dpi == POLICY['dpi']
    recipe = sha(json.dumps({'base': effective_extract_config(ocr_config),
                            'operational_policy': POLICY, 'runner_sha256': runner_sha}, sort_keys=True).encode())
    frozen_path = op / 'recipe.json'
    if frozen_path.exists():
        assert json.loads(frozen_path.read_text())['digest'] == recipe
    else:
        save(frozen_path, {'digest': recipe, 'policy': POLICY})
    cloud = CloudPages(op, secret['api_key'])
    local = LocalRapidOcr(languages=ocr_config.languages, min_confidence=ocr_config.min_confidence)
    assert local.available(), 'local fallback is required'
    lock = FileLock(str(Path(config.knowledge_db).parent / 'knowledge.lock'))
    assert lock.acquire(blocking=False), 'another knowledge writer is active'
    kb = KnowledgeStore(config.knowledge_db)
    status = {'stage': 'starting', 'started_at': time.time(), 'workers': args.workers,
              'total': len(manifest['items']), 'previously_completed': manifest['previously_completed'],
              'completed': 0, 'failed': 0, 'remote_pages': 0, 'local_fallback_pages': 0}

    def checkpoint(stage, **extra):
        status.update(extra, stage=stage, updated_at=time.time(), model_requests=cloud.requests)
        save(op / 'status.json', status)
        print(json.dumps(status), flush=True)

    try:
        # Handoff marks only the precisely identified old running job failed.
        # Other old pending jobs or writers are an error, never silently drained.
        pending = kb._conn.execute("SELECT id FROM jobs WHERE stage='extract' AND status IN ('pending','running') AND config_digest<>?", (recipe,)).fetchall()
        assert not pending, 'unreconciled foreign extract jobs'
        registered = register_reprocess_batch(kb, recipe, manifest['items'], manifest['batch_id'])
        assert not registered.get('refused'), registered
        publisher = ReadingPublisher(kb, args.vault, config.extra.get('public_base_url', 'http://192.168.1.150:8765'))
        # Publish already completed old documents before starting new calls.
        publisher.consume(limit=2000)
        old_hashes_path = op / 'evidence-before.json'
        if not old_hashes_path.exists():
            save(old_hashes_path, {r['block_id']: sha(r['text'].encode()) for r in kb._conn.execute('SELECT block_id,text FROM blocks')})
        errors = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for number, item in enumerate(manifest['items'], 1):
                begin = time.monotonic()
                checkpoint('extracting', current=number, original_position=item['original_position'], source=item['source'], doc_id=item['doc_id'])
                job = kb._conn.execute("SELECT * FROM jobs WHERE source=? AND doc_id=? AND version_id=? AND stage='extract' AND config_digest=?", (item['source'], item['doc_id'], item['version_id'], recipe)).fetchone()
                assert job
                job = dict(job)
                version = kb.get_version(item['source'], item['doc_id'], item['version_id'])
                assert version and version['is_current'] and version['sha256'] == item['version_sha256']
                existing = kb._conn.execute('SELECT extraction_id FROM extractions WHERE source=? AND doc_id=? AND version_id=? AND config_digest=?', (item['source'], item['doc_id'], item['version_id'], recipe)).fetchone()
                if existing:
                    publisher.enqueue(item['source'], item['doc_id'], item['version_id'], existing[0])
                    kb.finish_job(job['id'], ok=True)
                    status['completed'] += 1
                    continue
                with kb._tx() as conn:
                    conn.execute("UPDATE jobs SET status='running',attempts=attempts+1 WHERE id=?", (job['id'],))
                try:
                    raw = validated_raw(config.snapshot_root, item)
                    fmt = format_of(version['media_type'], version['ext'])
                    images = page_images(raw, fmt, ocr_config)
                    checkpoint('recognizing_pages', current_pages=len(images))
                    outcomes = list(pool.map(cloud.recognize, images.values()))
                    hybrid = CachedHybrid({sha(image): result for image, result in zip(images.values(), outcomes)}, local)
                    if fmt == 'pdf':
                        result = extract_pdf(raw, ocr=hybrid, ocr_config=ocr_config,
                                             renderer=lambda data, page, dpi: images[page])
                    else:
                        result = get_extractor(fmt)(raw, ocr=hybrid, ocr_config=ocr_config)
                    if result.status == 'failed' or any(damaged_reasons(block.text) for block in result.blocks):
                        raise RuntimeError('text_quality_failed')
                    if any(int(result.stats.get(k) or 0) for k in ['unmet_ocr_pages', 'missing_content_pages']):
                        raise RuntimeError('incomplete_page_coverage')
                    if any(s in ['ocr_failed', 'needs_ocr_unmet', 'missing_content', 'ocr_empty_after_fallback'] for s in result.stats.get('page_ocr_status', [])):
                        raise RuntimeError('incomplete_ocr')
                    eid = compute_extraction_id(item['source'], item['doc_id'], item['version_id'], item['version_sha256'], result.parser_id, result.parser_version, recipe)
                    result.stats.update(glm_pages=hybrid.remote_pages, local_fallback_pages=hybrid.local_pages,
                                        fallback_reasons=hybrid.reasons, model=MODEL)
                    blocks = [{'block_type': b.block_type, 'text': b.text, 'locator': b.locator,
                               'quality': {'status': b.quality.status, 'issues': b.quality.issues}} for b in result.blocks]
                    kb.record_extraction({'extraction_id': eid, 'source': item['source'], 'doc_id': item['doc_id'],
                        'version_id': item['version_id'], 'snapshot_sha256': item['version_sha256'],
                        'parser_id': result.parser_id, 'parser_version': result.parser_version,
                        'config_digest': recipe, 'status': result.status, 'issues': result.issues, 'stats': result.stats}, blocks)
                    kb.emit_event('extraction.completed', item['source'], item['doc_id'], item['version_id'],
                                  {'extraction_id': eid, 'status': result.status, 'model': MODEL}, event_id='evt-extr-' + eid[:32])
                    publisher.enqueue(item['source'], item['doc_id'], item['version_id'], eid)
                    kb.finish_job(job['id'], ok=True)
                    save(op / ('item-%04d.json' % number), {'original_position': item['original_position'],
                         'source': item['source'], 'doc_id': item['doc_id'], 'extraction_id': eid,
                         'status': result.status, 'stats': result.stats, 'seconds': round(time.monotonic() - begin, 2)})
                    status['completed'] += 1
                    status['remote_pages'] += hybrid.remote_pages
                    status['local_fallback_pages'] += hybrid.local_pages
                except Exception as exc:
                    # Keep successful other documents moving; never publish a broken result.
                    kb.finish_job(job['id'], ok=False, error=type(exc).__name__, max_attempts=0)
                    errors.append({'original_position': item['original_position'], 'error_type': type(exc).__name__})
                    status['failed'] += 1
                    save(op / 'errors.json', errors)
                # Reading notes every document; full search generation every 20.
                checkpoint('publishing', publish=publisher.consume(limit=2000))
                if number % 20 == 0:
                    checkpoint('indexing', index=build_generation(kb))
        checkpoint('indexing', index=build_generation(kb), publish=publisher.consume(limit=2000))
        before = json.loads(old_hashes_path.read_text())
        changed = []
        for block_id, expected in before.items():
            row = kb._conn.execute('SELECT text FROM blocks WHERE block_id=?', (block_id,)).fetchone()
            if not row or sha(row[0].encode()) != expected:
                changed.append(block_id)
        assert not changed, 'historical evidence changed'
        checkpoint('complete_with_errors' if status['failed'] else 'complete_pending_acceptance',
                   evidence_blocks_preserved=len(before))
    except BaseException as exc:
        checkpoint('stopped_for_review', error_type=type(exc).__name__)
        raise
    finally:
        kb.close()
        lock.release()


if __name__ == '__main__':
    main()
