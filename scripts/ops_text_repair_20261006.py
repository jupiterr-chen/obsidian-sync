"""Release 9d1b04f: offline, bounded server-side sample/repair runner.

Operational wrapper only; application source is the accepted immutable image.
All full-text outputs/manifests stay in the private operation directory.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import traceback

from knowledge.config import KnowledgeConfig
from knowledge.jobs import JobRunner
from knowledge.store import KnowledgeStore
from knowledge.readonly import open_read_only
from knowledge.text_quality import build_inventory
from knowledge.repair import register_reprocess_batch, select_reprocess_items
from knowledge.quality import damaged_reasons
from knowledge.indexing import build_generation
from knowledge.reading import ReadingPublisher
from library.config import Config
from library.locking import FileLock


def save(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['sample', 'repair'], required=True)
    parser.add_argument('--config', default='/app-config/knowledge.json')
    parser.add_argument('--out', default='/operation')
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    status = {'mode': args.mode, 'stage': 'starting', 'completed': 0,
              'started_at': time.time(), 'model_calls': 0}

    def checkpoint(stage, **data):
        status.update(data, stage=stage, updated_at=time.time())
        save(out / (args.mode + '-status.json'), status)
        print(json.dumps(status, ensure_ascii=False), flush=True)

    config = KnowledgeConfig.load(args.config).resolve('/app-config')
    assert config.ocr_config().engine == 'local'
    assert config.ocr_config().fallback is None
    assert not config.extra.get('analysis', {}).get('enabled', False)
    assert not any(v.get('egress_allowed', False) for v in
                   config.extra.get('providers', {}).values() if isinstance(v, dict))
    # No implicit historical/new job registration in this operator-controlled lane.
    config.register_stages = ('snapshot',)
    kb = KnowledgeStore(config.knowledge_db)
    lock = FileLock(str(Path(config.knowledge_db).parent / 'knowledge.lock'))
    if not lock.acquire(blocking=False):
        raise RuntimeError('knowledge writer active; no concurrent repair allowed')
    try:
        runner = JobRunner(kb, config, Config.load(config.library_config))
        recipe = runner.extract_digest
        checkpoint('inventory', recipe=recipe)
        with open_read_only(config.knowledge_db) as ro:
            inventory = build_inventory(ro, reading_dir='/vault/解析正文',
                                        include_history=True,
                                        snapshot_root=config.snapshot_root)
        save(out / (args.mode + '-inventory-before.json'), inventory)
        if args.mode == 'sample':
            spec = importlib.util.spec_from_file_location('sample_selector',
                                      '/release/tools/text-quality/sample_measure.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            items = module.select_sample(inventory, 0)
            candidates = select_reprocess_items(inventory, max_items=100000)
            save(out / 'repair-members.json', {'recipe': recipe,
                 'inventory_manifest': inventory['manifest_hash'], 'items': candidates})
        else:
            frozen = json.loads((out / 'repair-members.json').read_text())
            assert frozen['recipe'] == recipe, 'frozen recipe differs'
            items = frozen['items']
        save(out / (args.mode + '-members.json'), {'recipe': recipe, 'items': items})
        checkpoint('extracting', total=len(items), candidates=(len(candidates)
                   if args.mode == 'sample' else len(items)))
        # No touching unrelated pending jobs, including a pre-existing lease.
        pending = kb._conn.execute("SELECT count(*) FROM jobs WHERE stage='extract'"
                                   " AND status IN ('pending','running')").fetchone()[0]
        if pending:
            raise RuntimeError('existing extract jobs need reconciliation: %s' % pending)
        old_hashes = {r['block_id']: hashlib.sha256(r['text'].encode()).hexdigest()
                      for r in kb._conn.execute('SELECT block_id,text FROM blocks')}
        results = []
        publisher = ReadingPublisher(kb, '/vault',
                         config.extra.get('public_base_url', 'http://192.168.1.150:8765'))
        for pos, item in enumerate(items):
            # Record exact snapshot binding and reject version drift before registration.
            version = kb.get_version(item['source'], item['doc_id'], item['version_id'])
            assert version and version['sha256'] == item['version_sha256']
            assert version['is_current'], 'version changed since freeze'
            snap = kb.get_snapshot(item['source'], item['doc_id'], item['version_id'])
            assert snap and snap['sha256'] == item['version_sha256']
            assert runner.blobs.verify_blob(snap['store_path'], snap['sha256'], snap['bytes'])
            checkpoint('extracting', current=pos + 1, source=item['source'], doc_id=item['doc_id'])
            begin = time.monotonic()
            # Single-member frozen units give an exact resume cursor without changing recipe.
            batch = 'release-9d1b04f-20261006-%s-%04d' % (args.mode, pos + 1)
            registered = register_reprocess_batch(kb, recipe, [item], batch)
            assert not registered.get('refused'), registered
            result = runner.run_extract_jobs(limit=1)
            assert not result['failed'] and not result.get('recipe_refused'), result
            extraction = kb.latest_extraction(item['source'], item['doc_id'], item['version_id'])
            assert extraction and extraction['config_digest'] == recipe
            blocks = kb.get_blocks(extraction['extraction_id'])
            damaged = sum(bool(damaged_reasons(b['text'])) for b in blocks)
            row = {'position': pos + 1, 'source': item['source'], 'doc_id': item['doc_id'],
                   'version_id': item['version_id'], 'extraction_id': extraction['extraction_id'],
                   'layer': item.get('layer'), 'before_damaged': item.get('pages_damaged'),
                   'damaged_after': damaged, 'seconds': round(time.monotonic() - begin, 2),
                   'extraction': extraction, 'job_result': result}
            # Private evidence enables real first/problem/last-page and numeric comparisons.
            save(out / ('%s-item-%04d.json' % (args.mode, pos + 1)),
                 dict(row, blocks=blocks, snapshot=snap))
            results.append(row)
            save(out / (args.mode + '-results.json'), results)
            # A failed/glyph result is held for review, never batch-published.
            if extraction['status'] == 'failed' or damaged:
                raise RuntimeError('sample/batch quality stop at item %d' % (pos + 1))
            publisher.enqueue(item['source'], item['doc_id'], item['version_id'],
                              extraction['extraction_id'])
            if (pos + 1) % 20 == 0 or pos + 1 == len(items):
                checkpoint('publishing', completed=pos + 1,
                           index=build_generation(kb), publish=publisher.consume(limit=2000))
        # Check all old evidence blocks, not a sample. No text is rewritten in place.
        for block_id, digest in old_hashes.items():
            row = kb._conn.execute('SELECT text FROM blocks WHERE block_id=?', (block_id,)).fetchone()
            assert row and hashlib.sha256(row[0].encode()).hexdigest() == digest
        with open_read_only(config.knowledge_db) as ro:
            after = build_inventory(ro, reading_dir='/vault/解析正文',
                        include_history=True, snapshot_root=config.snapshot_root)
        save(out / (args.mode + '-inventory-after.json'), after)
        checkpoint('awaiting_independent_sample_review' if args.mode == 'sample'
                   else 'repair_complete_pending_acceptance', completed=len(items),
                   evidence_blocks_preserved=len(old_hashes), actions_after=after['action_counts'])
    except Exception as exc:
        checkpoint('stopped_for_review', error_type=type(exc).__name__, error=str(exc))
        (out / (args.mode + '-traceback.txt')).write_text(traceback.format_exc())
        raise
    finally:
        lock.release()
        kb.close()


if __name__ == '__main__':
    main()
