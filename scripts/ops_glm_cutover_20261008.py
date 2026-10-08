"""User-authorized one-time handoff; copy/backup only, no deletions."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = Path('/vol2/1000/10.Develop/obsidian-sync')
OP = ROOT / 'operations/glm-ocr-20261008'
OLD = ROOT / 'operations/release-9d1b04f-20261006/production'
RELEASE = ROOT / 'releases/9d1b04f'
IMAGE = 'obsidian-sync:9d1b04f'
OLD_NAME = 'obsidian-sync-repair-9d1b04f-20261006'
OLD_ID = 'b51b9c358e1472540a3407c863ad8e001fb7c4cc723aa91fcf4e17a3664c99a2'
NEW_NAME = 'obsidian-sync-glm-ocr-20261008'


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def save(name, obj):
    path = OP / name
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def inspect(name):
    return json.loads(subprocess.check_output(['docker', 'inspect', name], text=True))[0]


def preflight():
    old = inspect(OLD_NAME)
    assert old['Id'] == OLD_ID and old['State']['Running'], 'old lane identity/state changed'
    assert not inspect('obsidian-sync-knowledge-worker')['State']['Running'], 'ordinary worker is running'
    assert inspect('obsidian-sync-library')['State']['Running']
    assert inspect('obsidian-sync-knowledge-api')['State']['Running']
    assert (OP / 'secret.json').is_file()
    secret = json.loads((OP / 'secret.json').read_text())
    assert secret['endpoint'] == 'https://open.bigmodel.cn/api/anthropic/v1/messages'
    assert secret['model'] == 'GLM-5.3-Flash' and secret['api_key']
    assert (OP / 'acceptance.json').is_file()
    acceptance = json.loads((OP / 'acceptance.json').read_text())
    assert acceptance['decision'] == 'hybrid_reading_ocr'
    assert acceptance['user_payload_approval'] is True
    assert acceptance['runner_sha256'] == digest(OP / 'scripts/ops_glm_ocr_repair_20261008.py')
    assert acceptance['cutover_sha256'] == digest(Path(__file__))
    assert not (OP / 'launch.json').exists(), 'already launched; inspect status, do not repeat'
    original = json.loads((OLD / 'repair-members.json').read_text())
    assert len(original['items']) == 458
    print(json.dumps({'preflight': 'pass', 'old_id': OLD_ID,
                      'completed_at_check': len(json.loads((OLD / 'repair-results.json').read_text())),
                      'source_members': 458}), flush=True)


def handoff():
    preflight()
    # This marker makes a partial handoff explicit, not silently rerunnable.
    (OP / 'handoff-started.json').open('x').write(json.dumps({'at': time.time(), 'old_id': OLD_ID}))
    save('handoff-status.json', {'stage': 'stopping_exact_old_lane', 'updated_at': time.time()})
    subprocess.run(['docker', 'stop', '-t', '60', OLD_ID], check=True, stdout=subprocess.DEVNULL)
    assert not inspect(OLD_NAME)['State']['Running']
    backup = OP / 'backup'
    backup.mkdir(exist_ok=False)
    for filename in ['repair-status.json', 'repair-results.json', 'repair-members.json', 'supervisor-status.json']:
        shutil.copy2(OLD / filename, backup / filename)
    # Hold the same POSIX advisory lock while reconciling the old lease.
    with (ROOT / 'state/knowledge.lock').open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        db = ROOT / 'state/knowledge.sqlite3'
        assert db.is_file()
        with sqlite3.connect('file:' + str(db) + '?mode=ro', uri=True) as src:
            with sqlite3.connect(backup / 'knowledge.sqlite3') as dst:
                src.backup(dst)
                assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        reading = ROOT / 'vault' / '\u89e3\u6790\u6b63\u6587'
        meta = backup / 'reading-meta'
        meta.mkdir()
        for filename in ['.knowledge-writeback.json', '\u5f00\u59cb\u9605\u8bfb.md', '\u540c\u6b65\u72b6\u6001.md']:
            path = reading / filename
            if path.is_file():
                shutil.copy2(path, meta / filename)
        original = json.loads((OLD / 'repair-members.json').read_text())
        old_results = json.loads((OLD / 'repair-results.json').read_text())
        completed = {(r['source'], r['doc_id'], r['version_id']) for r in old_results}
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            remaining = []
            # A committed extraction immediately before stop also counts;
            # repair-results.json may lag behind the SQLite transaction.
            for position, item in enumerate(original['items'], 1):
                identity = (item['source'], item['doc_id'], item['version_id'])
                exists = conn.execute('SELECT extraction_id,status FROM extractions WHERE source=? AND doc_id=? AND version_id=? AND config_digest=?', (*identity, original['recipe'])).fetchone()
                if identity in completed or (exists and exists['status'] != 'failed'):
                    completed.add(identity)
                    # Heal the tiny extraction/enqueue crash window without rerunning OCR.
                    if exists:
                        conn.execute("INSERT OR IGNORE INTO publish_outbox (source,doc_id,version_id,extraction_id,status,created_at) VALUES (?,?,?,?,'pending',strftime('%Y-%m-%dT%H:%M:%SZ','now'))", (*identity, exists['extraction_id']))
                    continue
                version = conn.execute('SELECT sha256,is_current FROM kb_versions WHERE source=? AND doc_id=? AND version_id=?', identity).fetchone()
                assert version and version['is_current'] and version['sha256'] == item['version_sha256']
                snap = conn.execute('SELECT * FROM snapshots WHERE source=? AND doc_id=? AND version_id=?', identity).fetchone()
                assert snap and snap['sha256'] == item['version_sha256'] and snap['state'] != 'corrupted'
                remaining.append(dict(item, snapshot=dict(snap), original_position=position))
            pending = [dict(r) for r in conn.execute("SELECT id,source,doc_id,version_id,config_digest,status FROM jobs WHERE stage='extract' AND status IN ('running','pending')")]
            frozen = {(r['source'], r['doc_id'], r['version_id']) for r in original['items']}
            for job in pending:
                identity = (job['source'], job['doc_id'], job['version_id'])
                assert job['config_digest'] == original['recipe'] and identity in frozen, 'unrelated pending job'
                new_status = 'done' if identity in completed else 'failed'
                conn.execute("UPDATE jobs SET status=?,lease_until=NULL,error=?,updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=? AND config_digest=?", (new_status, 'authorized GLM continuation; old recipe retained', job['id'], original['recipe']))
            save('old-job-reconciliation.json', pending)
        save('manifest.json', {'batch_id': 'glm-ocr-continuation-20261008-v1',
             'original_manifest_sha256': digest(OLD / 'repair-members.json'),
             'runner_sha256': digest(OP / 'scripts/ops_glm_ocr_repair_20261008.py'),
             'previously_completed': len(completed), 'items': remaining})
        save('backup.json', {'knowledge_db': str(backup / 'knowledge.sqlite3'),
                             'sha256': digest(backup / 'knowledge.sqlite3'),
                             'previously_completed': len(completed), 'remaining': len(remaining)})
    launch(len(completed), len(remaining))


def resume_after_backup_check():
    """Recover only the verified post-manifest, pre-launch checksum failure."""
    assert not (OP / 'launch.json').exists(), 'already launched'
    assert (OP / 'handoff-started.json').is_file()
    assert (OP / 'old-job-reconciliation.json').is_file()
    assert (OP / 'backup/reading-meta').is_dir()
    assert inspect(OLD_NAME)['Id'] == OLD_ID
    assert not inspect(OLD_NAME)['State']['Running']
    assert not inspect('obsidian-sync-knowledge-worker')['State']['Running']
    acceptance = json.loads((OP / 'acceptance.json').read_text())
    assert acceptance['user_payload_approval'] is True
    assert acceptance['decision'] == 'hybrid_reading_ocr'
    assert acceptance['cutover_sha256'] == digest(Path(__file__))
    manifest = json.loads((OP / 'manifest.json').read_text())
    assert manifest['runner_sha256'] == acceptance['runner_sha256'] == digest(OP / 'scripts/ops_glm_ocr_repair_20261008.py')
    assert manifest['original_manifest_sha256'] == digest(OLD / 'repair-members.json')
    assert manifest['previously_completed'] + len(manifest['items']) == 458
    backup = OP / 'backup/knowledge.sqlite3'
    assert backup.is_file() and backup.stat().st_size > 0
    # The original handoff creates manifest only after full integrity_check
    # and the exact old-job reconciliation commit. Never recreate that state.
    with (ROOT / 'state/knowledge.lock').open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        save('handoff-status.json', {'stage': 'streaming_backup_checksum', 'updated_at': time.time()})
        save('backup.json', {'knowledge_db': str(backup), 'sha256': digest(backup),
             'previously_completed': manifest['previously_completed'],
             'remaining': len(manifest['items']), 'integrity_check': 'ok_before_manifest',
             'checksum_recovery': 'streaming; original backup and reconciliation retained'})
    launch(manifest['previously_completed'], len(manifest['items']))


def launch(completed, remaining):
    assert not (OP / 'launch.json').exists()
    cmd = ['docker', 'run', '-d', '--name', NEW_NAME, '--network', 'bridge', '--cpus', '1.5',
           '--memory', '2g', '--restart', 'no', '--workdir', '/',
           '-e', 'PYTHONPATH=/app', '-e', 'PYTHONUNBUFFERED=1',
           '-e', 'OMP_NUM_THREADS=1', '-e', 'OPENBLAS_NUM_THREADS=1']
    for src, dst, readonly in [(ROOT / 'state', '/state', False),
                                (ROOT / 'state/snapshots', '/state/snapshots', True),
                                (ROOT / 'catalog', '/catalog', True),
                                (ROOT / 'vault', '/vault', False),
                                (RELEASE / 'deploy/config', '/app-config', True),
                                (OP, '/operation', False),
                                (OP / 'secret.json', '/run/glm-ocr.json', True)]:
        cmd.extend(['-v', str(src) + ':' + dst + (':ro' if readonly else '')])
    cmd.extend([IMAGE, 'python', '/operation/scripts/ops_glm_ocr_repair_20261008.py',
                '--operation', '/operation', '--config', '/app-config/knowledge.json',
                '--secret', '/run/glm-ocr.json', '--workers', '2'])
    container = subprocess.check_output(cmd, text=True).strip()
    save('launch.json', {'container': container, 'name': NEW_NAME, 'at': time.time(), 'workers': 2})
    with (OP / 'supervisor.log').open('a') as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'supervise'],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    save('handoff-status.json', {'stage': 'glm_continuation_started', 'container': container,
          'supervisor_pid': child.pid, 'previously_completed': completed,
          'remaining': remaining, 'updated_at': time.time()})
    print(json.dumps({'stage': 'started', 'previously_completed': completed,
                      'remaining': remaining, 'container': container, 'supervisor_pid': child.pid}), flush=True)


def supervise():
    launch = json.loads((OP / 'launch.json').read_text())
    assert inspect(NEW_NAME)['Id'] == launch['container']
    code = int(subprocess.check_output(['docker', 'wait', launch['container']], text=True).strip())
    state = json.loads((OP / 'status.json').read_text()) if (OP / 'status.json').exists() else {}
    if code == 0 and state.get('stage') == 'complete_pending_acceptance':
        subprocess.run(['docker', 'compose', '-p', 'obsidian-sync', '-f',
                        str(RELEASE / 'deploy/production-compose.json'),
                        'up', '-d', '--no-deps', 'knowledge-worker'], check=True)
        stage = 'batch_finished_local_incremental_worker_resumed'
    else:
        stage = 'batch_needs_review_worker_held'
    save('supervisor-status.json', {'stage': stage, 'exit_code': code,
                                   'batch': state, 'updated_at': time.time()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['preflight', 'handoff', 'supervise', 'resume-after-backup-check'])
    mode = parser.parse_args().mode
    if mode == 'preflight':
        preflight()
    elif mode == 'handoff':
        handoff()
    elif mode == 'resume-after-backup-check':
        resume_after_backup_check()
    else:
        supervise()
