"""Server preparation for an explicitly authorized 9d1b04f production release.

Uses copies/SQLite backup API, no deletions, no production service changes.
Stops at a durable independent real-sample review gate before production cutover.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
import traceback

ROOT = Path('/vol2/1000/10.Develop/obsidian-sync')
OP = ROOT / 'operations/release-9d1b04f-20261006'
RELEASE = ROOT / 'releases/9d1b04f'
OLD = ROOT / 'releases/67c6985r2/deploy'
IMAGE = 'obsidian-sync:9d1b04f'
BASE = 'sha256:9318382ce31a74323fb48a279be4bb83712826c5ed4e3f1cc104c7df32381173'


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(name, data):
    path = OP / name
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def checkpoint(stage, **kw):
    data = dict(stage=stage, updated_at=time.time(), production_changed=False, **kw)
    save('host-status.json', data)
    print(json.dumps(data), flush=True)


def db_backup(src, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError('refuse overwrite of backup: ' + str(target))
    with sqlite3.connect('file:' + str(src) + '?mode=ro', uri=True) as source:
        with sqlite3.connect(target) as dest:
            source.backup(dest)
            assert dest.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    return {'file': str(target), 'sha256': digest(target), 'bytes': target.stat().st_size}


def main():
    OP.mkdir(parents=True, exist_ok=True)
    assert not (OP / 'backup-manifest.json').exists(), 'operation already prepared; resume from status'
    package = json.loads((OP / 'package.json').read_text())
    assert digest(OP / 'source.tar') == package['source_tar_sha256']
    for name, sha in package['scripts'].items():
        assert digest(OP / name) == sha
    checkpoint('backup')
    backup = OP / 'backup'
    backup.mkdir(exist_ok=True)
    databases = [db_backup(ROOT / 'catalog/catalog.sqlite3', backup / 'catalog/catalog.sqlite3'),
                 db_backup(ROOT / 'state/knowledge.sqlite3', backup / 'state/knowledge.sqlite3')]
    shutil.copytree(OLD / 'config', backup / 'config')
    shutil.copy2(OLD / 'migration-compose.json', backup / 'migration-compose.json')
    shutil.copytree(ROOT / 'vault', backup / 'vault')
    shutil.copytree(ROOT / 'state/snapshots', backup / 'snapshots')
    manifest = []
    for folder in ['vault', 'snapshots']:
        for path in sorted((backup / folder).rglob('*')):
            if path.is_file():
                manifest.append({'path': str(path.relative_to(backup)), 'sha256': digest(path),
                                 'bytes': path.stat().st_size})
    save('backup-manifest.json', {'databases': databases, 'files': manifest,
         'kind': 'online-preflight-copy; final frozen backup required at cutover'})
    # Independent restoration, never mount production state in the sample container.
    isolated = OP / 'isolated'
    shutil.copytree(backup / 'state', isolated / 'state')
    shutil.copytree(backup / 'catalog', isolated / 'catalog')
    shutil.copytree(backup / 'vault', isolated / 'vault')
    shutil.copytree(backup / 'config', isolated / 'config')
    cfgpath = isolated / 'config/knowledge.json'
    cfg = json.loads(cfgpath.read_text())
    cfg['analysis'] = dict(cfg.get('analysis') or {}, enabled=False)
    for provider in (cfg.get('providers') or {}).values():
        if isinstance(provider, dict):
            provider['egress_allowed'] = False
    cfg['ocr']['engine'] = 'local'
    cfg['ocr']['fallback'] = None
    cfgpath.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    build_and_sample(package, backup, isolated)


def build_and_sample(package, backup, isolated, resume=False):
    checkpoint('build', backup_manifest_sha256=digest(OP / 'backup-manifest.json'))
    assert digest(OP / 'source.tar') == package['source_tar_sha256']
    RELEASE.mkdir(parents=True, exist_ok=resume)
    with tarfile.open(OP / 'source.tar') as archive:
        for member in archive.getmembers():
            target = (RELEASE / member.name).resolve()
            assert target.is_relative_to(RELEASE.resolve()) and not member.issym() and not member.islnk()
            if resume and member.isfile():
                assert target.is_file() and digest(target) == hashlib.sha256(archive.extractfile(member).read()).hexdigest()
        if not resume:
            archive.extractall(RELEASE)
    # BuildKit treats a bare sha256 image ID in FROM as a registry name.
    # Bind a local tag to the inspected ID and use the offline legacy builder.
    base_tag = 'obsidian-sync:runtime-9318382ce31a'
    subprocess.run(['docker', 'tag', BASE, base_tag], check=True)
    inspected = json.loads(subprocess.check_output(['docker', 'image', 'inspect', base_tag]))[0]
    assert inspected['Id'] == BASE
    (RELEASE / 'Dockerfile.release').write_text('FROM ' + base_tag + '\nCOPY app/ /app/\n'
                 'LABEL org.opencontainers.image.revision="9d1b04fc1ae7fa8a6e067af46f65b842773a523e"\n')
    with (OP / 'build.log').open('w') as log:
        subprocess.run(['docker', 'build', '--network=none', '--pull=false', '-t', IMAGE,
                        '-f', str(RELEASE / 'Dockerfile.release'), str(RELEASE)],
                       stdout=log, stderr=subprocess.STDOUT, check=True,
                       env=dict(os.environ, DOCKER_BUILDKIT='0'))
    image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', IMAGE]))[0]
    save('release.json', {'image': IMAGE, 'image_id': image['Id'], 'base_image_id': BASE,
                         'source_sha': package['source_sha'], 'source_tar_sha256': package['source_tar_sha256']})
    checkpoint('isolated_sample_starting', image_id=image['Id'])
    name = 'obsidian-sync-sample-9d1b04f-20261006'
    cmd = ['docker', 'run', '-d', '--name', name, '--network', 'none', '--cpus', '1.5',
           '--memory', '2g', '--restart', 'no', '--workdir', '/',
           '-e', 'PYTHONPATH=/app', '-e', 'PYTHONUNBUFFERED=1',
           '-e', 'OMP_NUM_THREADS=1', '-e', 'OPENBLAS_NUM_THREADS=1']
    for src, dst, readonly in [
        (isolated / 'state', '/state', False),
        (isolated / 'catalog', '/catalog', True),
        (isolated / 'vault', '/vault', False),
        (isolated / 'config', '/app-config', True),
        (backup / 'snapshots', '/state/snapshots', True),
        (RELEASE, '/release', True), (OP, '/operation', False)]:
        cmd.extend(['-v', str(src) + ':' + dst + (':ro' if readonly else '')])
    cmd.extend([IMAGE, 'python', '/operation/ops_text_repair_20261006.py', '--mode', 'sample'])
    container = subprocess.check_output(cmd, text=True).strip()
    checkpoint('isolated_sample_running', container=container, container_name=name)


if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--resume-build']:
            build_and_sample(json.loads((OP / 'package.json').read_text()),
                             OP / 'backup', OP / 'isolated', resume=True)
        else:
            assert not sys.argv[1:]
            main()
    except Exception as exc:
        checkpoint('stopped_for_review', error_type=type(exc).__name__, error=str(exc))
        (OP / 'host-traceback.txt').write_text(traceback.format_exc())
        raise
