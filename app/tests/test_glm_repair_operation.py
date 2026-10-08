"""No real calls: test the bounded one-off GLM repair's operational safeguards."""
from concurrent.futures import ThreadPoolExecutor
import ast
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

PATH = Path(__file__).resolve().parents[2] / 'scripts/ops_glm_ocr_repair_20261008.py'
spec = importlib.util.spec_from_file_location('glm_repair', PATH)
op = importlib.util.module_from_spec(spec)
spec.loader.exec_module(op)


class GlmOperationTests(unittest.TestCase):
    def test_backup_digest_streams_bounded_reads(self):
        path = PATH.with_name('ops_glm_cutover_20261008.py')
        tree = ast.parse(path.read_text(encoding='utf-8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'digest')
        namespace = {'hashlib': hashlib, 'Path': mock.Mock()}
        content = b'a' * (2 * 1024 * 1024 + 71)
        class BoundedReader(BytesIO):
            def read(self, size=-1):
                self_test.assertGreater(size, 0)
                self_test.assertLessEqual(size, 1024 * 1024)
                return super().read(size)
        self_test = self
        namespace['Path'].return_value.open.return_value = BoundedReader(content)
        namespace['Path'].return_value.read_bytes.side_effect = AssertionError('unbounded backup read')
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
        self.assertEqual(namespace['digest']('backup.sqlite3'), hashlib.sha256(content).hexdigest())

    def test_known_dense_table_and_plain_numeric_matrix_rejected(self):
        self.assertEqual(op.reject_output('|' + '|'.join(['x'] * 10) + '|', 'end_turn'), 'dense_table')
        self.assertEqual(op.reject_output(' '.join(str(i) for i in range(250)), 'end_turn'), 'dense_table')
        self.assertIsNone(op.reject_output('| Revenue | 12 | 13 |\n| Cash | 45 | 67 |', 'end_turn'))

    def test_incomplete_empty_and_damaged_results_rejected(self):
        self.assertEqual(op.reject_output('some text', 'max_tokens'), 'incomplete_response')
        self.assertEqual(op.reject_output('', 'end_turn'), 'empty_response')
        self.assertEqual(op.reject_output('Revenue [unreadable]', 'end_turn'), 'unreadable_content')
        self.assertEqual(op.reject_output('abc\x01\x02\x03\x04', 'end_turn'), 'damaged_output')

    def test_single_physical_call_under_concurrent_duplicate_and_restart(self):
        calls = []
        def fake(payload):
            calls.append(payload['model'])
            time.sleep(0.02)
            return {'model': op.MODEL, 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'revenue 123'}]}
        with tempfile.TemporaryDirectory() as folder:
            cloud = op.CloudPages(folder, 'test-secret', transport=fake)
            with ThreadPoolExecutor(max_workers=4) as pool:
                rows = list(pool.map(cloud.recognize, [b'image'] * 4))
            again = op.CloudPages(folder, 'test-secret', transport=fake)
            self.assertEqual(again.recognize(b'image')['text'], 'revenue 123')
            self.assertEqual(len(calls), 1)
            self.assertTrue(all(r['fallback'] is None for r in rows))
            for f in Path(folder).rglob('*.json'):
                self.assertNotIn('test-secret', f.read_text())

    def test_unknown_dispatch_never_resent(self):
        with tempfile.TemporaryDirectory() as folder:
            cloud = op.CloudPages(folder, 'secret', transport=lambda _: self.fail('must not send'))
            (cloud.root / (cloud.identify(b'image') + '.dispatch.json')).write_text('{}')
            self.assertEqual(cloud.recognize(b'image')['fallback'], 'previous_request_outcome_unknown')

    def test_quota_failure_stops_further_dispatch(self):
        def quota(_):
            raise urllib.error.HTTPError(op.ENDPOINT, 429, 'limited', {}, None)
        with tempfile.TemporaryDirectory() as folder:
            cloud = op.CloudPages(folder, 'secret', transport=quota)
            self.assertEqual(cloud.recognize(b'one')['http_status'], 429)
            self.assertEqual(cloud.recognize(b'two')['fallback'], 'provider_disabled_or_request_limit')
            self.assertEqual(cloud.requests, 1)

    def test_budget_enforced_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            cloud = op.CloudPages(folder, 'secret', transport=lambda _: self.fail('budget'))
            cloud.requests = op.POLICY['max_physical_requests']
            self.assertEqual(cloud.recognize(b'image')['fallback'], 'provider_disabled_or_request_limit')

    def test_local_fallback_and_unknown_remote_confidence(self):
        from PIL import Image
        buf = BytesIO()
        Image.new('RGB', (10, 10), 'white').save(buf, format='PNG')
        png = buf.getvalue()
        class Local:
            def run(self, _):
                return 'local text', .96
        hybrid = op.CachedHybrid({op.sha(png): {'text': 'cloud text', 'fallback': None}}, Local())
        self.assertEqual(hybrid.run(png), ('cloud text', .5))
        fallback = op.CachedHybrid({op.sha(png): {'fallback': 'dense_table'}}, Local())
        self.assertEqual(fallback.run(png), ('local text', .96))
        self.assertEqual(fallback.local_pages, 1)

    def test_snapshot_hash_checked_before_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'blob').write_bytes(b'changed')
            item = {'version_sha256': op.sha(b'original'),
                    'snapshot': {'store_path': 'blob', 'sha256': op.sha(b'original'), 'bytes': 8}}
            with self.assertRaises(AssertionError):
                op.validated_raw(folder, item)

    def test_complete_runner_publishes_once_and_preserves_manual_note(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from PIL import Image
        from knowledge.store import KnowledgeStore, utc_now
        calls = []
        real_cloud = op.CloudPages
        def transport(_):
            calls.append(1)
            return {'model': op.MODEL, 'stop_reason': 'end_turn', 'content': [{'type': 'text',
                    'text': 'Revenue 123. This is a fully synthetic test page with enough words.'}]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            vault = root / 'vault'
            vault.mkdir()
            (vault / 'manual.md').write_text('human-owned note')
            snapshots = root / 'snapshots'
            snapshots.mkdir()
            buf = BytesIO()
            Image.new('RGB', (16, 16), 'white').save(buf, format='PNG')
            raw = buf.getvalue()
            digest = op.sha(raw)
            (snapshots / digest).write_bytes(raw)
            db = root / 'kb.sqlite3'
            kb = KnowledgeStore(str(db))
            stamp = utc_now()
            identity = {'source': 'discord', 'doc_id': 'test', 'version_id': digest}
            kb.upsert_documents([dict(identity, title='Synthetic', available=True)], stamp)
            kb.upsert_versions([dict(identity, sha256=digest, bytes=len(raw), media_type='image/png',
                                    ext='.png', rel_path='test.png', is_current=True)], stamp)
            kb.record_blob(digest, len(raw), digest, stamp)
            kb.record_snapshot('discord', 'test', digest, digest, len(raw), digest, stamp)
            snap = kb.get_snapshot('discord', 'test', digest)
            kb.close()
            op.save(root / 'manifest.json', {'batch_id': 'test', 'previously_completed': 0,
                    'runner_sha256': op.sha(PATH.read_bytes()),
                    'items': [dict(identity, version_sha256=digest, snapshot=snap, original_position=1)]})
            op.save(root / 'config.json', {'knowledge_db': str(db), 'snapshot_root': str(snapshots),
                                          'ocr': {'engine': 'local', 'render_dpi': 200}})
            op.save(root / 'secret.json', {'endpoint': op.ENDPOINT, 'model': op.MODEL, 'api_key': 'fake'})
            argv = ['runner', '--operation', str(root), '--config', str(root/'config.json'),
                    '--secret', str(root/'secret.json'), '--vault', str(vault)]
            with mock.patch('sys.argv', argv), mock.patch.object(op, 'CloudPages',
                    side_effect=lambda path, key: real_cloud(path, key, transport)), \
                    mock.patch('knowledge.ocr.LocalRapidOcr') as local, redirect_stdout(StringIO()):
                local.return_value.available.return_value = True
                op.main()
                op.main()
            self.assertEqual(calls, [1])
            self.assertEqual((vault/'manual.md').read_text(), 'human-owned note')
            self.assertEqual(len(list(vault.rglob('*-readable.md'))), 1)
            self.assertEqual(json.loads((root/'status.json').read_text())['stage'], 'complete_pending_acceptance')
            kb = KnowledgeStore(str(db))
            self.assertEqual(kb._conn.execute('SELECT count(*) FROM extractions').fetchone()[0], 1)
            self.assertEqual(kb._conn.execute('SELECT status FROM jobs').fetchone()[0], 'done')
            self.assertEqual(kb._conn.execute('SELECT status FROM extractions').fetchone()[0], 'review')
            kb.close()


if __name__ == '__main__':
    unittest.main()
