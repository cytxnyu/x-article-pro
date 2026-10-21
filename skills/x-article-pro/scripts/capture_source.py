#!/usr/bin/env python3
"""Capture already acquired and checked source text; no fetching or prose generation."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import urlsplit
from validate_source import canonical, digest


def capture(article, title_file, body_file, raw_file, source_url, retrieved_at,
            reuse_basis, reuse_note, extraction_note, caption_excerpt=None):
    root = Path(article).resolve()
    parsed = urlsplit(source_url)
    if parsed.scheme != 'https' or parsed.hostname != 'aihot.news':
        raise ValueError('Use the actual HTTPS AIHOT reading URL')
    if datetime.fromisoformat(retrieved_at.replace('Z', '+00:00')).utcoffset() is None:
        raise ValueError('Timestamp must include timezone')
    if reuse_basis not in ('user_provided', 'licensed', 'public_domain') or not reuse_note.strip() or not extraction_note.strip():
        raise ValueError('Actual reuse basis and extraction note are required')
    title = canonical(Path(title_file).read_text(encoding='utf-8-sig'))
    body = canonical(Path(body_file).read_text(encoding='utf-8-sig'))
    raw = Path(raw_file).read_bytes()
    if not title.strip() or not body.strip() or not raw:
        raise ValueError('Complete title, body and raw input must be nonempty')
    caption = '' if caption_excerpt is None else canonical(caption_excerpt)
    if caption_excerpt is not None and (not caption.strip() or caption not in body):
        raise ValueError('Caption must be one unchanged continuous body excerpt')
    sources = {'raw-response.txt': raw, 'title.txt': title.encode('utf-8'), 'body.txt': body.encode('utf-8')}
    metadata = {'version': 1, 'mode': 'aihot-original', 'source_url': source_url,
                'retrieved_at': retrieved_at, 'content_kind': 'full_article',
                'extraction_note': extraction_note,
                'reuse': {'basis': reuse_basis, 'note': reuse_note},
                'caption_mode': 'empty' if caption_excerpt is None else 'source_excerpt',
                'sha256': {k: digest(v) for k, v in sources.items()}}
    outputs = {'source/' + k: v for k, v in sources.items()}
    outputs.update({'title.txt': sources['title.txt'], 'body.txt': sources['body.txt'],
                    'caption.txt': caption.encode('utf-8'),
                    'source-capture.json': (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode('utf-8')})
    for name in outputs:
        target = (root / name).resolve()
        if not target.is_relative_to(root) or target.exists():
            raise ValueError(f'Refusing to replace existing source/output or escape article: {name}')
    (root / 'source').mkdir(parents=True, exist_ok=True)
    for name, data in outputs.items():
        with (root / name).open('xb') as handle:
            handle.write(data)
    return metadata


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('article_directory', type=Path)
    for name in ('title-file', 'body-file', 'raw-file', 'source-url', 'retrieved-at', 'reuse-basis', 'reuse-note', 'extraction-note'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--caption-excerpt')
    args = vars(p.parse_args())
    article = args.pop('article_directory')
    try:
        capture(article, **args)
    except (OSError, ValueError, UnicodeError) as exc:
        print(f'FAIL capture: {exc}')
        return 1
    print('PASS captured title/body unchanged; caption=empty-or-source-excerpt')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
