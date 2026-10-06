"""Authorized unattended release and repair. No application source changes.

Runs on the server in a detached session. Keeps backups and old files;
records failures, never deletes stores or silently restores over new writes.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import traceback
import urllib.request
from ops_release_20261006 import ROOT, OP, RELEASE, OLD, IMAGE, db_backup, digest

PROD = OP / 'production'
COMPOSE = RELEASE / 'deploy/production-compose.json'
NEW_CONFIG = RELEASE / 'deploy/config'


def save(stage, **kwargs):
    obj = dict(stage=stage, updated_at=time.time(), **kwargs)
    tmp = PROD / 'supervisor-status.tmp'
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, PROD / 'supervisor-status.json')
    print(json.dumps(obj), flush=True)


def call(args):
    with (PROD / 'commands.log').open('a') as log:
        subprocess.run(args, check=True, stdout=log, stderr=subprocess.STDOUT)


def compose(path, *args):
    call(['docker', 'compose', '-p', 'obsidian-sync', '-f', str(path), *args])


def health():
    for port, route, host in [(8765, '/healthz', '192.168.1.150'),
                               (8766, '/api/kb/v1/health', '127.0.0.1')]:
        with urllib.request.urlopen('http://%s:%d%s' % (host, port, route), timeout=8) as r:
            assert r.status == 200


def main():
    PROD.mkdir(exist_ok=False)
    save('preparing_cutover', source_sha='9d1b04fc1ae7fa8a6e067af46f65b842773a523e')
    release = json.loads((OP / 'release.json').read_text())
    image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', IMAGE]))[0]
    assert image['Id'] == release['image_id']
    shutil.copy2(OP / 'repair-members.json', PROD / 'repair-members.json')
    members = json.loads((PROD / 'repair-members.json').read_text())
    assert len(members['items']) == 458
    shutil.copytree(OLD / 'config', NEW_CONFIG)
    cfg = json.loads((NEW_CONFIG / 'knowledge.json').read_text())
    cfg['analysis'] = dict(cfg.get('analysis') or {}, enabled=False)
    for spec in cfg.get('providers', {}).values():
        if isinstance(spec, dict): spec['egress_allowed'] = False
    assert cfg['ocr']['engine'] == 'local' and not cfg['ocr'].get('fallback')
    (NEW_CONFIG / 'knowledge.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    original = json.loads((OLD / 'migration-compose.json').read_text())
    for name in ['library', 'knowledge-api', 'knowledge-worker']:
        svc = original['services'][name]
        svc['image'] = IMAGE
        svc['volumes'] = [v.replace(str(OLD / 'config'), str(NEW_CONFIG)) for v in svc['volumes']]
    COMPOSE.write_text(json.dumps(original, indent=2))
    # Freeze exact knowledge writers; existing online snapshots remain immutable.
    save('freezing_writers')
    call(['docker', 'stop', '-t', '60', 'obsidian-sync-knowledge-worker', 'obsidian-sync-knowledge-api'])
    backup = PROD / 'cutover-backup'
    backup.mkdir()
    backups = [db_backup(ROOT / 'state/knowledge.sqlite3', backup / 'knowledge.sqlite3'),
               db_backup(ROOT / 'catalog/catalog.sqlite3', backup / 'catalog.sqlite3')]
    shutil.copytree(ROOT / 'vault', backup / 'vault')
    shutil.copy2(OLD / 'migration-compose.json', backup / 'old-compose.json')
    manifest = {str(p.relative_to(backup / 'vault')): digest(p)
                for p in (backup / 'vault').rglob('*') if p.is_file()}
    (backup / 'vault-hashes.json').write_text(json.dumps(manifest, ensure_ascii=False))
    (backup / 'manifest.json').write_text(json.dumps({'databases': backups,
          'snapshot_backup': str(OP / 'backup/snapshots'), 'vault_files': len(manifest)}))
    save('starting_new_services', backup=str(backup))
    compose(COMPOSE, 'up', '-d', '--no-deps', 'library', 'knowledge-api')
    for attempt in range(24):
        try:
            health()
            break
        except Exception:
            if attempt == 23: raise
            time.sleep(5)
    # Dedicated network-isolated runner is the sole knowledge batch writer.
    name = 'obsidian-sync-repair-9d1b04f-20261006'
    cmd = ['docker', 'run', '-d', '--name', name, '--network', 'none', '--cpus', '1.5',
           '--memory', '2g', '--restart', 'no', '--workdir', '/',
           '-e', 'PYTHONPATH=/app', '-e', 'PYTHONUNBUFFERED=1',
           '-e', 'OMP_NUM_THREADS=1', '-e', 'OPENBLAS_NUM_THREADS=1']
    for src, dst, ro in [(ROOT / 'state', '/state', False),
                         (ROOT / 'catalog', '/catalog', True),
                         (ROOT / 'vault', '/vault', False),
                         (NEW_CONFIG, '/app-config', True),
                         (OP, '/operation', False)]:
        cmd.extend(['-v', str(src) + ':' + dst + (':ro' if ro else '')])
    cmd.extend([IMAGE, 'python', '/operation/ops_text_repair_20261006.py',
                '--mode', 'repair', '--out', '/operation/production'])
    container = subprocess.check_output(cmd, text=True).strip()
    save('production_repair_running', container=container, container_name=name,
         total=458, image_id=image['Id'], backup=str(backup))
    code = int(subprocess.check_output(['docker', 'wait', name], text=True).strip())
    result_path = PROD / 'repair-status.json'
    result = json.loads(result_path.read_text()) if result_path.exists() else {}
    with (PROD / 'repair-container.log').open('w') as log:
        subprocess.run(['docker', 'logs', name], stdout=log, stderr=subprocess.STDOUT)
    if code or result.get('stage') != 'repair_complete_pending_acceptance':
        save('repair_stopped_for_error', exit_code=code, result=result,
             note='APIs remain available; worker held to avoid retrying a failed batch automatically')
        return
    compose(COMPOSE, 'up', '-d', '--no-deps', 'knowledge-worker')
    health()
    changed = [name for name, sha in manifest.items()
               if not name.startswith('解析正文/') and
               (not (ROOT / 'vault' / name).is_file() or digest(ROOT / 'vault' / name) != sha)]
    (PROD / 'non-reading-changes.json').write_text(json.dumps(changed, ensure_ascii=False))
    save('repair_finished_worker_resumed', result=result,
         non_reading_changes=len(changed),
         note='Windows sync resumes when client starts; final semantic review and known CMap fix remain separate')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        PROD.mkdir(exist_ok=True)
        save('supervisor_failed', error_type=type(exc).__name__, error=str(exc))
        (PROD / 'supervisor-traceback.txt').write_text(traceback.format_exc())
        # Start the existing API if it was only stopped and never replaced.
        # Never restore a DB over newly written data or blindly restart batch writers.
        try:
            api = json.loads(subprocess.check_output(['docker', 'inspect', 'obsidian-sync-knowledge-api']))[0]
            if not api['State']['Running']:
                call(['docker', 'start', 'obsidian-sync-knowledge-api'])
        except Exception:
            pass
        raise
