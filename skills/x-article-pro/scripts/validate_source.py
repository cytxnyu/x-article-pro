#!/usr/bin/env python3
"""Read-only, offline AIHOT source-snapshot and rendered-text fidelity checks."""
import argparse
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

SOURCE_FILES = ('raw-response.txt', 'title.txt', 'body.txt')
FIELDS = ('article-title', 'article-body', 'article-caption')


def canonical(text):
    """Only file encoding/line-ending normalization; no textual editing."""
    return text.removeprefix('\ufeff').replace('\r\n', '\n').replace('\r', '\n')


def digest(data):
    return hashlib.sha256(data).hexdigest()


class SourceHTML(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.counts = dict.fromkeys(FIELDS, 0)
        self.text = {name: [] for name in FIELDS}
        self.blocks = []
        self.errors = []
        self.stack = []
        self.field = None
        self.block = None
        self.figure = False
        self.hidden = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict(attrs)
        prior = (self.field, self.block, self.figure, self.hidden)
        field = a.get('id')
        if field in FIELDS:
            self.counts[field] += 1
            if self.field:
                self.errors.append('HTML copy fields must not overlap')
            self.field = field
        self.figure |= tag in {'figure', 'figcaption'}
        self.hidden |= tag in {'script', 'style', 'template', 'noscript'} or 'hidden' in a or bool(
            re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', a.get('style', ''), re.I))
        if 'data-source-block' in a:
            if self.field != 'article-body' or self.block is not None or self.figure or self.hidden:
                self.errors.append('Source blocks must be visible, non-nested body text')
            if a['data-source-block'] != str(len(self.blocks)):
                self.errors.append('Source blocks must have consecutive indices starting at 0')
            self.block = len(self.blocks)
            self.blocks.append([])
        if self.hidden and self.field:
            self.errors.append('Copy fields must not include hidden/script text')
        if tag == 'br' and self.field and not self.hidden:
            if self.block is not None:
                self.blocks[self.block].append('\n')
            elif self.field != 'article-body':
                self.text[self.field].append('\n')
        if tag not in self.VOID:
            self.stack.append((tag, prior))
        else:
            self.field, self.block, self.figure, self.hidden = prior

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag.lower():
                self.field, self.block, self.figure, self.hidden = self.stack[i][1]
                del self.stack[i:]
                return

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if not self.field or self.hidden:
            return
        if self.field != 'article-body':
            self.text[self.field].append(data)
        elif self.block is not None:
            self.blocks[self.block].append(data)
        elif not self.figure and data.strip():
            self.errors.append('HTML body contains added text outside source blocks')


def validate(article):
    root = Path(article).resolve()
    errors = []
    result = {'valid': False, 'status': 'FAIL', 'mode': 'aihot-original', 'errors': errors}

    def read(name):
        path = (root / name).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError(f'{name}: path escapes article')
        return path.read_bytes()

    try:
        capture = json.loads(read('source-capture.json').decode('utf-8-sig'))
        if not isinstance(capture, dict):
            raise ValueError('source-capture.json must be an object')
        if capture.get('version') != 1 or capture.get('mode') != 'aihot-original':
            errors.append('Source capture version/mode mismatch')
        if capture.get('content_kind') != 'full_article':
            errors.append('A summary is not a full article')
        url = capture.get('source_url')
        parsed = urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != 'https' or parsed.hostname != 'aihot.news':
            errors.append('source_url must be the actual HTTPS AIHOT reading URL')
        result['source_url'] = url
        timestamp = capture.get('retrieved_at')
        try:
            if not isinstance(timestamp, str) or datetime.fromisoformat(timestamp.replace('Z', '+00:00')).utcoffset() is None:
                raise ValueError()
        except (ValueError, TypeError):
            errors.append('retrieved_at must be an ISO timestamp with timezone')
        if not isinstance(capture.get('extraction_note'), str) or not capture['extraction_note'].strip():
            errors.append('extraction_note must identify the actual text region and completeness check')
        reuse = capture.get('reuse')
        if (not isinstance(reuse, dict) or reuse.get('basis') not in ('user_provided', 'licensed', 'public_domain')
                or not isinstance(reuse.get('note'), str) or not reuse['note'].strip()):
            errors.append('Reuse basis and actual supporting note are required')
        hashes = capture.get('sha256')
        if not isinstance(hashes, dict) or set(hashes) != set(SOURCE_FILES):
            errors.append('Source file hash manifest must contain exactly the three source files')
            hashes = {}
        raw = {}
        for name in SOURCE_FILES:
            raw[name] = read('source/' + name)
            if not raw[name] or hashes.get(name) != digest(raw[name]):
                errors.append(f'source/{name}: missing bytes or source SHA-256 changed')
        title = canonical(raw['title.txt'].decode('utf-8-sig'))
        body = canonical(raw['body.txt'].decode('utf-8-sig'))
        result['title'] = title
        if not title.strip() or not body.strip():
            errors.append('Original title and body must be nonempty')
        for name, expected in (('title.txt', title), ('body.txt', body)):
            if canonical(read(name).decode('utf-8-sig')) != expected:
                errors.append(f'{name}: differs from original source text')
        caption = canonical(read('caption.txt').decode('utf-8-sig'))
        mode = capture.get('caption_mode')
        if mode == 'empty':
            if caption:
                errors.append('caption must be empty in empty mode')
        elif mode == 'source_excerpt':
            if not caption.strip() or caption not in body:
                errors.append('caption must be one unchanged continuous body excerpt')
        else:
            errors.append('caption_mode must be empty or source_excerpt')
        parser = SourceHTML()
        parser.feed(read('article.html').decode('utf-8-sig'))
        parser.close()
        errors.extend(parser.errors)
        for name in FIELDS:
            if parser.counts[name] != 1:
                errors.append(f'HTML requires exactly one {name} field')
        for field, expected in (('article-title', title), ('article-caption', caption)):
            if canonical(''.join(parser.text[field])) != expected:
                errors.append(f'HTML {field} differs from the source-based text file')
        html_body = '\n\n'.join(''.join(block) for block in parser.blocks)
        if not parser.blocks or canonical(html_body) != body:
            errors.append('HTML body differs from original source text/paragraphs')
    except (OSError, ValueError, UnicodeError, TypeError, RuntimeError) as exc:
        errors.append(f'Source validation input error: {exc}')
    result.update(valid=not errors, status='FAIL' if errors else 'PASS')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('article_directory', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    result = validate(args.article_directory)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
          result['status'] + ' source-fidelity' + ''.join('\n' + e for e in result['errors']))
    return 0 if result['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
