#!/usr/bin/env python3
"""Original synthetic texts and images only; no remote content or publication."""
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from capture_source import capture
from validate_source import validate, digest
from validate_delivery import Validator
import test_validate_delivery as visual_fixtures


def fixture(root, caption=None, cover=True):
    root = Path(root)
    inputs = root / 'inputs'
    inputs.mkdir(parents=True)
    title = '合成保真测试：光点的三次移动'
    body = '测试装置把光点移动了三次。\n\n第一步保留  2 个空格。A < B & C。\n这是同一段的第二行。\n\n最后，光点停在原处。'
    for name, text in [('title.txt', title), ('body.txt', body), ('raw.txt', title + '\n\n' + body)]:
        (inputs / name).write_text(text, encoding='utf-8', newline='\n')
    article = root / 'run' / '01-source'
    capture(article, inputs / 'title.txt', inputs / 'body.txt', inputs / 'raw.txt',
            'https://aihot.news/synthetic-fixture', '2026-10-19T12:00:00+08:00',
            'user_provided', 'Original synthetic text authored solely for offline tests.',
            'Title and all three synthetic body paragraphs checked against raw.txt.', caption)
    (article / 'images').mkdir()
    (article / 'images/original.png').write_bytes(visual_fixtures.png_1x1())
    source = 'https://example.test/synthetic-image'
    image = {'path': 'images/original.png', 'kind': 'official_image', 'source_url': source,
             'caption': '合成图片夹具；不是真实新闻配图。'}
    images = [image]
    first_image = ''
    if cover:
        (article / 'images/cover.png').write_bytes(visual_fixtures.synthetic_cover(500, 200, 42))
        meta = {'path': 'images/cover.png', 'generator_skill': 'cover-editorial-collage',
                'prompt': 'Synthetic test metadata, not evidence of real image generation.',
                'kind': 'editorial_composite', 'role': 'x_header', 'width': 500, 'height': 200,
                'alt': 'Synthetic cover fixture', 'caption': '编辑合成：仅用于结构测试。',
                'ai_assisted': False, 'event_connection': 'Synthetic moving dot fixture.',
                'design_notes': 'Synthetic color patch for ratio verification only.',
                'source_assets': [{'path': image['path'], 'source_url': source, 'usage': 'Synthetic structure fixture'}]}
        (article / 'cover.json').write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
        images.append({'path': meta['path'], 'kind': meta['kind'], 'source_url': None, 'caption': meta['caption']})
        first_image = '<figure><img src="images/cover.png"><figcaption>编辑合成：仅用于结构测试。</figcaption></figure>'
    blocks = ''.join(f'<p data-source-block="{i}">{html.escape(p)}</p>' for i, p in enumerate(body.split('\n\n')))
    page = ('<!doctype html><html><head><style>[data-source-block]{white-space:pre-wrap}</style></head><body>'
            + first_image + '<h1 id="article-title">' + html.escape(title) + '</h1><article id="article-body">'
            + blocks + '<figure><img src="images/original.png"><figcaption>' + image['caption']
            + '</figcaption></figure></article><section id="article-caption">' + html.escape(caption or '') + '</section></body></html>')
    (article / 'article.html').write_text(page, encoding='utf-8', newline='\n')
    evidence = {'text_mode': 'source_preserved', 'source_capture': 'source-capture.json', 'claims': [], 'images': images}
    (article / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False), encoding='utf-8')
    item = {'rank': 1, 'title': title, 'source_url': 'https://aihot.news/synthetic-fixture',
            'status': 'ready', 'article_dir': '01-source', 'issues': []}
    if cover:
        item['cover_path'] = 'images/cover.png'
    manifest = {'delivery_version': 3, 'text_mode': 'aihot-original', 'body_links': 'preserve-source',
                'requested_count': 1, 'cover_required': cover, 'items': [item]}
    (article.parent / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
    return article


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.article = fixture(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def change_json(self, name, change):
        path = self.article / name
        obj = json.loads(path.read_text(encoding='utf-8'))
        change(obj)
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')

    def test_exact_copy_and_visual_package_pass_without_writing_reviews(self):
        result = Validator(self.article.parent).validate()
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(result['summary']['checked_source_captures'], 1)
        self.assertFalse(result['summary']['content_required'])
        self.assertFalse(result['summary']['prose_required'])
        self.assertEqual(result['summary']['checked_covers'], 1)
        self.assertFalse((self.article / 'prose-review.json').exists())

    def test_every_textual_change_fails(self):
        p = self.article / 'body.txt'
        original = p.read_text(encoding='utf-8')
        for changed in [original.replace('三次', '四次'), original.replace('  ', ' '),
                        original.replace('。', '.'), original + '\n作者认为这很重要。',
                        original.split('\n\n')[0], original.replace('A', 'Ａ')]:
            with self.subTest(changed=changed):
                p.write_text(changed, encoding='utf-8')
                self.assertFalse(validate(self.article)['valid'])

    def test_bom_and_crlf_are_only_allowed_serialization_changes(self):
        for name in ('title.txt', 'body.txt'):
            p = self.article / name
            p.write_bytes(b'\xef\xbb\xbf' + p.read_bytes().replace(b'\n', b'\r\n'))
        self.assertTrue(validate(self.article)['valid'])

    def test_title_rewrite_fails(self):
        (self.article / 'title.txt').write_text('新标题', encoding='utf-8')
        self.assertFalse(validate(self.article)['valid'])

    def test_source_hash_drift_and_rewriting_both_copies_fails(self):
        for name in ('body.txt', 'source/body.txt'):
            (self.article / name).write_text('两个文件被一起重写。', encoding='utf-8')
        result = validate(self.article)
        self.assertFalse(result['valid'])
        self.assertTrue(any('SHA-256' in e for e in result['errors']))

    def test_raw_response_hash_drift_fails(self):
        (self.article / 'source/raw-response.txt').write_text('different source', encoding='utf-8')
        self.assertFalse(validate(self.article)['valid'])

    def test_summary_cannot_be_promoted_to_full_article(self):
        self.change_json('source-capture.json', lambda x: x.update(content_kind='summary'))
        self.assertFalse(validate(self.article)['valid'])

    def test_missing_capture_and_invalid_metadata_fail_cleanly(self):
        p = self.article / 'source-capture.json'
        for value in [[], {}, {'version': 1}, {'mode': []}, {'reuse': []}]:
            p.write_text(json.dumps(value), encoding='utf-8')
            self.assertFalse(validate(self.article)['valid'])
        p.unlink()
        self.assertFalse(validate(self.article)['valid'])

    def test_new_caption_rejected_and_continuous_source_excerpt_passes(self):
        (self.article / 'caption.txt').write_text('新写的钩子', encoding='utf-8')
        self.assertFalse(validate(self.article)['valid'])
        excerpt = '测试装置把光点移动了三次。'
        a = fixture(self.root / 'excerpt', caption=excerpt)
        self.assertTrue(validate(a)['valid'])
        self.assertTrue(Validator(a.parent).validate()['valid'])

    def test_html_modified_or_added_text_fails(self):
        p = self.article / 'article.html'
        original = p.read_text(encoding='utf-8')
        for value in [original.replace('三次', '四次'), original.replace('</article>', '<p>新增结论。</p></article>'),
                      original.replace('data-source-block="1"', 'data-source-block="2"'),
                      original.replace('data-source-block="0"', 'hidden data-source-block="0"'),
                      original.replace('id="article-caption"', 'id="article-body"')]:
            p.write_text(value, encoding='utf-8')
            self.assertFalse(validate(self.article)['valid'])

    def test_capture_refuses_to_overwrite_originals(self):
        inputs = self.root / 'inputs'
        before = {p.relative_to(self.article).as_posix(): digest(p.read_bytes()) for p in self.article.rglob('*') if p.is_file()}
        with self.assertRaises(ValueError):
            capture(self.article, inputs / 'title.txt', inputs / 'body.txt', inputs / 'raw.txt',
                    'https://aihot.news/synthetic-fixture', '2026-10-19T12:00:00+08:00',
                    'user_provided', 'Synthetic', 'Synthetic')
        after = {p.relative_to(self.article).as_posix(): digest(p.read_bytes()) for p in self.article.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_source_gate_cannot_be_disabled_by_manifest_or_legacy_flag(self):
        (self.article / 'source-capture.json').unlink()
        self.change_json('../manifest.json', lambda x: x.update(source_required=False, require_source_fidelity=False))
        self.assertFalse(Validator(self.article.parent, legacy_structure=True).validate()['valid'])

    def test_version_downgrade_with_source_mode_is_rejected(self):
        self.change_json('../manifest.json', lambda x: x.update(delivery_version=2))
        self.assertFalse(Validator(self.article.parent).validate()['valid'])

    def test_manifest_source_and_title_must_match(self):
        self.change_json('../manifest.json', lambda x: x['items'][0].update(source_url='https://aihot.news/other', title='Different'))
        self.assertFalse(Validator(self.article.parent).validate()['valid'])

    def test_v3_retains_only_cover_skill_and_actual_ratio_checks(self):
        self.change_json('cover.json', lambda x: x.update(generator_skill='other-skill'))
        self.assertFalse(Validator(self.article.parent).validate()['valid'])
        self.change_json('cover.json', lambda x: x.update(generator_skill='cover-editorial-collage'))
        (self.article / 'images/cover.png').write_bytes(visual_fixtures.synthetic_cover(500, 210, 42))
        self.assertFalse(Validator(self.article.parent).validate()['valid'])

    def test_v3_still_requires_a_real_body_image(self):
        self.change_json('evidence.json', lambda x: x.update(images=x['images'][1:]))
        self.assertFalse(Validator(self.article.parent).validate()['valid'])

    def test_source_validator_cli_exit_and_read_only(self):
        script = Path(__file__).with_name('validate_source.py')
        env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-B', str(script), str(self.article), '--json'], capture_output=True, encoding='utf-8', env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['valid'])
        (self.article / 'body.txt').write_text('changed', encoding='utf-8')
        before = (self.article / 'body.txt').read_bytes()
        result = subprocess.run([sys.executable, '-B', str(script), str(self.article), '--json'], capture_output=True, encoding='utf-8', env=env)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)['valid'])
        self.assertEqual(before, (self.article / 'body.txt').read_bytes())


if __name__ == '__main__':
    unittest.main()
