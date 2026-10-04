"""Publish existing extraction text to a separate generated Obsidian directory.

No extraction, model calls or DB writes. Original cards and human notes are
untouched. Extraction-specific filenames and stable content make reruns safe.
"""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote, unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from knowledge.writeback import register_write_root, write_candidate


def literal(text):
    text = str(text).replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return re.sub(r'([\\`*_{}\[\]()<>#!|$~])', r'\\\1', text)


def publish_note(output, name, content):
    # Compare exact bytes: the shared writer reads with universal newlines,
    # which otherwise treats source OCR CRLF as a human edit on every rerun.
    target = output / name
    if target.is_file() and not target.is_symlink() and target.read_bytes() == content.encode('utf-8'):
        return {'outcome': 'unchanged', 'path': str(target)}
    return write_candidate(str(output), name, content, owner='existing-text-export')


def publish(db, vault, base_url):
    db, vault = Path(db).resolve(), Path(vault).resolve()
    if not db.is_file() or not vault.is_dir():
        raise ValueError('existing database and Vault required')
    output = vault / '解析正文'
    if output.is_symlink():
        raise ValueError('output must not be a symlink')
    if output.exists() and not (output / '.knowledge-writeback.json').is_file():
        raise ValueError('existing unregistered output directory; refusing to adopt')
    output.mkdir(exist_ok=True)
    register_write_root(str(output))
    conn = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA query_only=ON')
    conn.execute('BEGIN')
    entries, absent, summary = [], [], dict(published=0, without_text=0,
        ready=0, review=0, failed=0, other=0, blocks=0, chars=0, outcomes={})
    try:
        versions = conn.execute(
            'SELECT v.source,v.doc_id,v.version_id,d.title FROM kb_versions v '
            'JOIN kb_documents d ON d.source=v.source AND d.doc_id=v.doc_id '
            'WHERE v.is_current=1 ORDER BY v.source,v.doc_id').fetchall()
        for version in versions:
            source, doc_id, version_id = (version[k] for k in ('source', 'doc_id', 'version_id'))
            extraction = conn.execute(
                'SELECT * FROM extractions WHERE source=? AND doc_id=? AND version_id=? '
                'ORDER BY created_at DESC,extraction_id DESC LIMIT 1',
                (source, doc_id, version_id)).fetchone()
            title = unquote(version['title'] or doc_id)
            original = '%s/api/v1/files/%s/%s?version=%s' % (
                base_url.rstrip('/'), quote(source, safe=''), quote(doc_id, safe=''),
                quote(version_id, safe=''))
            blocks = conn.execute('SELECT * FROM blocks WHERE extraction_id=? ORDER BY ordinal',
                                  (extraction['extraction_id'],)).fetchall() if extraction else []
            blocks = [b for b in blocks if b['text'].strip()]
            if not blocks:
                summary['without_text'] += 1
                state = extraction['status'] if extraction else '未提取'
                absent.append('- %s — %s；[原文](%s)' % (literal(title), state, original))
                continue
            eid, status = extraction['extraction_id'], extraction['status']
            identity = hashlib.sha256(('%s\0%s\0%s' % (source, doc_id, eid)).encode()).hexdigest()
            filename = 'text-' + identity + '-readable.md'
            meta = dict(generated=True, source=source, doc_id=doc_id,
                        source_version=version_id, extraction_id=eid,
                        extraction_status=status, extracted_at=extraction['created_at'])
            lines = ['---'] + [k + ': ' + json.dumps(v, ensure_ascii=False) for k, v in meta.items()]
            lines += ['---', '', '# ' + literal(title), '',
                '> 已有提取结果的阅读副本，不是新生成的研究结论。OCR 可能有错字、漏字；数字和表格请对照原文。',
                '', '- 解析状态：`%s`（ready 仅为机器状态，不代表人工验收）' % status,
                '- [打开这一版本原文](%s)' % original,
                '- 提取版本：`%s`' % eid, '']
            hidden = sum(len(re.findall(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', b['text'])) for b in blocks)
            if hidden:
                lines += ['> 此阅读副本省略了 %d 个不可显示的控制字符；数据库原文未改动。这不是 OCR 修复，请对照 PDF 复核。' % hidden, '']
            page = None
            for block in blocks:
                locator = json.loads(block['locator_json'] or '{}')
                current_page = locator.get('page')
                if current_page is not None and current_page != page:
                    lines += ['## 第 %s 页' % current_page,
                              '[对照 PDF 本页](%s#page=%s)' % (original, current_page), '']
                    page = current_page
                lines += [literal(block['text']), '', '^' + block['block_id'], '']
            content = '\n'.join(lines)
            outcome = publish_note(output, filename, content)
            result = outcome['outcome']; summary['outcomes'][result] = summary['outcomes'].get(result, 0) + 1
            summary['published'] += 1
            summary[status if status in ('ready', 'review', 'failed') else 'other'] += 1
            summary['blocks'] += len(blocks)
            summary['chars'] += sum(len(b['text']) for b in blocks)
            entries.append('- [%s](%s) — %s' % (literal(title), filename, status))
        lines = ['# 解析正文目录', '',
            '这里显示服务器已经保存的最新提取正文；不会重新 OCR，也不会调用模型。',
            '原来的“资料目录”卡片仍负责元数据和原文访问。人工研究请写在原人工区，不要直接改本生成区。', '',
            '**正文 %d 份；当前版本缺少正文 %d 份。**' % (summary['published'], summary['without_text']), '',
            'ready：机器检查通过；review：需要复核；failed：提取失败或不完整。它们都不等于人工确认正确。', '',
            '## 已有正文', ''] + entries + ['', '## 当前没有正文', ''] + absent + ['']
        publish_note(output, '开始阅读.md', '\n'.join(lines))
        return summary
    finally:
        conn.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--db', required=True)
    p.add_argument('--vault', required=True)
    p.add_argument('--base-url', required=True)
    a = p.parse_args()
    print(json.dumps(publish(a.db, a.vault, a.base_url), ensure_ascii=False, indent=2))
