import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from fixtures import make_config, temp_dir, write_file
from library.api import build_server
from library.locking import FileLock
from library.runtime import write_json_atomic


class ManualIngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = temp_dir()
        self.config, _, self.discord = make_config(self.tmp)
        self.server = build_server(self.config)
        self.controller = self.server.RequestHandlerClass.manual_ingest
        self.origin = 'http://127.0.0.1:%d' % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        if self.controller._thread:
            self.controller._thread.join(5)
        self.server.shutdown()
        self.server.server_close()
        self.server.RequestHandlerClass.catalog.close()

    def request(self, path='/api/v1/actions/ingest', body=b'{}', headers=None, method='POST'):
        actual = {'Origin': self.origin, 'Content-Type': 'application/json',
                  'X-ResearchKB-Action': 'ingest'} if headers is None else headers
        req = urllib.request.Request(self.origin + path, data=body if method == 'POST' else None,
                                     method=method, headers=actual)
        try:
            with self.opener.open(req, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def finished(self):
        self.controller._thread.join(5)
        self.assertFalse(self.controller._thread.is_alive())
        status, payload = self.request('/api/v1/status', method='GET')
        self.assertEqual(status, 200)
        return payload['manual_ingest']

    def test_real_incremental_ingest_preserves_notes_schedule_and_knowledge(self):
        self.controller.COOLDOWN_SECONDS = 0
        note = Path(self.config.vault_dir) / '公司研究' / '人工.md'
        write_file(str(note), '人工笔记不可覆盖'.encode())
        # Manual ingestion must not open a knowledge DB or wait on its lock.
        knowledge = Path(self.config.state_dir) / 'knowledge.sqlite3'
        write_file(str(knowledge), b'knowledge sentinel')
        scheduler = Path(self.config.state_dir) / 'scheduler.json'
        write_json_atomic(str(scheduler), {'state': 'idle', 'next_check_at': '2030-01-01T01:00:00Z'})
        before = {p: p.read_bytes() for p in (note, knowledge, scheduler)}
        code, first = self.request()
        self.assertEqual(code, 202)
        self.assertEqual(self.finished()['state'], 'succeeded')
        catalog = self.server.RequestHandlerClass.catalog
        total_before = catalog.counts()['documents_total']
        record = dict(self.discord['records'][0], doc_id='manual-new-document',
                      file_path='new/manual.pdf')
        record['sha256'] = write_file(os.path.join(self.discord['root'], record['file_path']), b'%PDF new')
        record['file_size'] = len(b'%PDF new')
        with open(os.path.join(self.discord['root'], 'index', 'documents.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps(record) + '\n')
        self.assertEqual(self.request()[0], 202)
        self.assertEqual(self.finished()['state'], 'succeeded')
        self.assertEqual(catalog.counts()['documents_total'], total_before + 1)
        self.assertTrue(any('manual-new-document' in str(p) for p in Path(self.config.vault_dir).rglob('*.md')))
        self.assertEqual(self.request()[0], 202)
        again = self.finished()
        self.assertEqual(again['state'], 'succeeded')
        self.assertEqual(again['changes'], 0)
        self.assertEqual(catalog.counts()['documents_total'], total_before + 1)
        for p, content in before.items():
            self.assertEqual(p.read_bytes(), content)

    def test_repeated_clicks_share_request_then_cooldown(self):
        entered, release = threading.Event(), threading.Event()
        def slow_run(_):
            entered.set()
            release.wait(5)
            return {'ok': True, 'sources': {}}
        with patch('library.manual_ingest.Ingestor.run', autospec=True, side_effect=slow_run) as run:
            try:
                code, first = self.request()
                self.assertEqual(code, 202)
                self.assertTrue(entered.wait(2))
                code, second = self.request()
                self.assertEqual(code, 202)
                self.assertEqual(first['request_id'], second['request_id'])
            finally:
                release.set()
            self.assertEqual(self.finished()['state'], 'succeeded')
            self.assertEqual(self.request()[0], 429)
            self.assertEqual(run.call_count, 1)

    def test_existing_ingest_lock_skips_without_duplicate_run(self):
        lock = FileLock(os.path.join(self.config.state_dir, 'ingest.lock'))
        self.assertTrue(lock.acquire())
        try:
            self.assertEqual(self.request()[0], 202)
            self.assertEqual(self.finished()['state'], 'busy')
            self.assertEqual(self.server.RequestHandlerClass.catalog.recent_runs(5), [])
        finally:
            lock.release()

    def test_request_guards_reject_cross_origin_host_rebinding_and_parameters(self):
        valid = {'Origin': self.origin, 'Content-Type': 'application/json',
                 'X-ResearchKB-Action': 'ingest'}
        cases = [({}, b'{}', 403),
                 (dict(valid, Origin='http://untrusted.test'), b'{}', 403),
                 (dict(valid, Host='untrusted.test'), b'{}', 403),
                 ({k:v for k,v in valid.items() if k != 'X-ResearchKB-Action'}, b'{}', 403),
                 (dict(valid, **{'Sec-Fetch-Site':'cross-site'}), b'{}', 403),
                 (dict(valid, **{'Content-Type':'text/plain'}), b'{}', 415),
                 (valid, b'{"command":"rebuild-index"}', 400),
                 (valid, b'{"path":"/"}', 400),
                 (valid, b'[]', 400), (valid, b'x' * 65, 400)]
        with patch.object(self.controller, 'request') as run:
            for headers, body, expected in cases:
                with self.subTest(headers=headers, body=body):
                    self.assertEqual(self.request(headers=headers, body=body)[0], expected)
            self.assertEqual(self.request(method='GET')[0], 404)
            self.assertEqual(self.request(path='/api/v1/actions/ocr')[0], 404)
            run.assert_not_called()

    def test_failure_is_visible_without_exposing_private_exception(self):
        with patch('library.manual_ingest.Ingestor.run', side_effect=OSError('secret-key /private/source')):
            self.assertEqual(self.request()[0], 202)
            result = self.finished()
        self.assertEqual(result['state'], 'failed')
        self.assertNotIn('secret-key', json.dumps(result))
        self.assertNotIn('/private/source', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
