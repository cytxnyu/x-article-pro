#!/usr/bin/env python3
"""Synthetic offline behavioral fixtures only; no fetched news or image generation."""
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from validate_brief import CHECKS, MODE, digest, validate
from validate_delivery import Validator
from test_validate_source import fixture as original_fixture


def put_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def sync(article):
    """Test-only rebinding: deliberately isolate each invalid mutation from stale-hash errors."""
    review_path = article / 'brief-review.json'
    review = json.loads(review_path.read_text(encoding='utf-8'))
    review['text_sha256'] = {name: digest((article / name).read_bytes())
                             for name in ('title.txt', 'body.txt', 'caption.txt')}
    put_json(review_path, review)
    title, body, caption = ((article / name).read_text(encoding='utf-8')
                            for name in ('title.txt', 'body.txt', 'caption.txt'))
    blocks = ''.join(f'<p data-brief-block="{i}">{html.escape(p)}</p>'
                     for i, p in enumerate(body.split('\n\n')))
    page = ('<!doctype html><html><body><figure><img src="images/cover.png">'
            '<figcaption>编辑合成：仅用于结构测试。</figcaption></figure>'
            '<h1 id="article-title">' + html.escape(title) + '</h1><article id="article-body">'
            + blocks + '<figure><img src="images/original.png"><figcaption>合成图片夹具；不是真实新闻配图。</figcaption>'
            '</figure></article><section id="article-caption">' + html.escape(caption) + '</section></body></html>')
    (article / 'article.html').write_text(page, encoding='utf-8')


def fixture(root):
    article = original_fixture(root)
    source_title = '合成测试：光点控制器 2.0 发布，批处理上限提高'
    source_parts = [
        '10月18日，示例团队发布了光点控制器 2.0，向全部测试账户开放。新版一次最多可以处理 8 个光点，旧版的上限则为 4 个光点。此次更新只改变测试装置中的批处理能力，并不涉及真实硬件的亮度或运行速度。',
        '示例团队还表示，基础测试的价格维持每次 2 元，适用次数仍为不超过 20 次。这里的测量结果来自内部台架，团队没有据此宣称外部环境下的性能也得到提高。'
    ]
    title = '合成装置更新：光点批处理数量增至 8 个，测试费未变'
    parts = [
        '示例团队把光点控制器更新到了 2.0。10月18日起，全部测试账户均可使用新版本：单次处理上限从 4 个光点增至 8 个光点。这里公布的是测试装置的批处理范围，真实硬件的亮度和运行速度并未纳入本次变更。',
        '基础测试仍按每次 2 元收费，适用次数不超过 20 次的条件也保持原状。示例团队说明，数据是在内部台架取得的，这不等于已经证实外部环境性能提升。',
        '相关新闻与最新进展｜截至 2026-10-19',
        '10月19日，示例团队另发维护通知：测试装置计划于10月20日暂停服务 1 小时，维护安排尚未开始。'
    ]
    for name, text in [('title.txt', source_title), ('text.txt', '\n\n'.join(source_parts)),
                       ('raw-response.txt', source_title + '\n' + '\n\n'.join(source_parts))]:
        (article / 'source' / name).write_text(text, encoding='utf-8')
    for name, text in [('title.txt', title), ('body.txt', '\n\n'.join(parts)),
                       ('caption.txt', '合成夹具用于验证新闻简报流程：检查事实映射、独立表述及更新分区。')]:
        (article / name).write_text(text, encoding='utf-8')
    source = {'version': 1, 'mode': MODE, 'aihot': {
        'source_url': 'https://aihot.news/synthetic-fixture', 'source_date': '2026-10-18',
        'retrieved_at': '2026-10-19T12:00:00+08:00', 'content_kind': 'summary',
        'extraction_note': 'Entire locally authored synthetic input; not an actual AIHOT response.',
        'sha256': {name: digest((article / 'source' / name).read_bytes())
                   for name in ('title.txt', 'text.txt', 'raw-response.txt')}}}
    put_json(article / 'news-source.json', source)
    evidence = json.loads((article / 'evidence.json').read_text(encoding='utf-8'))
    evidence.update(text_mode=MODE, source_capture='news-source.json', claims=[
        {'id': 'core1', 'role': 'aihot', 'claim': '合成更新与账户、数量范围。',
         'source_url': source['aihot']['source_url'], 'source_date': '2026-10-18',
         'retrieved_at': '2026-10-19T12:00:00+08:00', 'status': 'verified'},
        {'id': 'core2', 'role': 'aihot', 'claim': '合成价格与台架测量范围。',
         'source_url': source['aihot']['source_url'], 'source_date': '2026-10-18',
         'retrieved_at': '2026-10-19T12:00:00+08:00', 'status': 'verified'},
        {'id': 'update1', 'role': 'update', 'claim': '合成维护通知，非真实消息。',
         'source_url': 'https://example.test/notice', 'source_date': '2026-10-19',
         'event_date': '2026-10-19', 'retrieved_at': '2026-10-19T12:02:00+08:00', 'status': 'verified'}])
    put_json(article / 'evidence.json', evidence)
    notes = {
        'main_facts_complete': '合成输入的更新版本、账户、数量、价格、测量范围均映射到两个主段。',
        'factual_qualifiers_preserved': '合成数字 2.0、4、8、2 元、20 次与内部台架口径均保留。',
        'independent_expression': '合成源文与输出重新组织了版本、时间、账户和变化的句序，未逐句复制。',
        'no_extended_analysis': '夹具仅有两个主事实段，没有背景段或作者观点。',
        'updates_separated': '合成维护通知只在最后的更新节出现，标明公告日和计划日。',
        'title_supported': '合成标题的数量与价格分别对应事实 1 和 2。',
        'caption_supported': 'caption 明示合成校验用途；不是发布用真实新闻 caption。'
    }
    review = {'version': 1, 'mode': MODE, 'reviewer': 'synthetic-test-fixture-author',
              'reviewed_at': '2026-10-19T12:10:00+08:00', 'text_sha256': {},
              'literal_terms': ['光点控制器', '2.0', '内部台架'],
              'checks': {key: {'passed': True, 'note': notes[key]} for key in CHECKS},
              'aihot_facts': [
                  {'id': 'f1', 'fact': '合成更新的时间、版本、账户范围与处理数量。',
                   'source_excerpt': source_parts[0], 'body_blocks': [0],
                   'critical_details': ['10月18日', '2.0', '全部测试账户', '4 个光点', '8 个光点']},
                  {'id': 'f2', 'fact': '合成测试计费、次数及测量范围。',
                   'source_excerpt': source_parts[1], 'body_blocks': [1],
                   'critical_details': ['每次 2 元', '不超过 20 次', '内部台架']}],
              'blocks': [
                  {'index': 0, 'kind': 'core', 'evidence_ids': ['core1']},
                  {'index': 1, 'kind': 'core', 'evidence_ids': ['core2']},
                  {'index': 2, 'kind': 'updates_heading', 'evidence_ids': []},
                  {'index': 3, 'kind': 'update', 'evidence_ids': ['update1']}],
              'updates': {'status': 'verified', 'checked_at': '2026-10-19T12:05:00+08:00',
                          'checked_sources': ['https://example.test/notice'], 'note': 'Synthetic update fixture.'}}
    put_json(article / 'brief-review.json', review)
    manifest = json.loads((article.parent / 'manifest.json').read_text(encoding='utf-8'))
    manifest.update(delivery_version=4, text_mode=MODE, body_links='omit')
    manifest['items'][0]['title'] = title
    put_json(article.parent / 'manifest.json', manifest)
    sync(article)
    return article


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.article = fixture(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def change(self, name, fn):
        path = self.article / name
        obj = json.loads(path.read_text(encoding='utf-8'))
        fn(obj)
        put_json(path, obj)

    def body(self, fn):
        p = self.article / 'body.txt'
        p.write_text(fn(p.read_text(encoding='utf-8')), encoding='utf-8')
        sync(self.article)

    def fails(self, needle):
        result = validate(self.article)
        self.assertFalse(result['valid'], result)
        self.assertTrue(any(needle in e for e in result['errors']), result['errors'])

    def test_complete_brief_and_original_visual_pipeline_pass(self):
        result = validate(self.article)
        self.assertTrue(result['valid'], result['errors'])
        package = Validator(self.article.parent, current=True).validate()
        self.assertTrue(package['valid'], package['errors'])
        self.assertEqual(package['summary']['checked_brief_reviews'], 1)
        self.assertEqual(package['summary']['checked_covers'], 1)
        self.assertFalse(package['summary']['prose_required'])
        self.assertFalse(package['summary']['source_required'])

    def test_summary_is_usable_without_pretending_to_have_full_text(self):
        self.assertEqual(validate(self.article)['source_kind'], 'summary')
        self.assertTrue(validate(self.article)['valid'])

    def test_no_new_developments_requires_no_public_heading(self):
        self.change('brief-review.json', lambda r: r.update(blocks=r['blocks'][:2],
                    updates=dict(r['updates'], status='none', note='Only the synthetic original was found.')))
        self.body(lambda b: '\n\n'.join(b.split('\n\n')[:2]))
        self.assertTrue(validate(self.article)['valid'], validate(self.article)['errors'])

    def test_empty_caption_is_supported(self):
        (self.article / 'caption.txt').write_text('', encoding='utf-8')
        sync(self.article)
        self.assertTrue(Validator(self.article.parent, current=True).validate()['valid'])

    def test_verbatim_source_body_is_rejected_even_after_rebinding(self):
        source = (self.article / 'source/text.txt').read_text(encoding='utf-8')
        self.change('brief-review.json', lambda r: r.update(blocks=r['blocks'][:2],
                    updates=dict(r['updates'], status='none', note='Test copy mutation.')))
        self.body(lambda b: source)
        self.fails('source wording')

    def test_source_title_cannot_be_copied(self):
        (self.article / 'title.txt').write_bytes((self.article / 'source/title.txt').read_bytes())
        sync(self.article)
        self.fails('Title copies')

    def test_unchanged_factual_terms_are_not_plagiarism_flags(self):
        result = validate(self.article)
        self.assertTrue(result['valid'], result['errors'])

    def test_source_snapshot_hash_drift_fails(self):
        (self.article / 'source/raw-response.txt').write_text('changed source', encoding='utf-8')
        self.fails('Source SHA-256')

    def test_stale_final_review_hash_fails(self):
        with (self.article / 'body.txt').open('a', encoding='utf-8') as out:
            out.write('改动')
        self.fails('Review hashes')

    def test_all_seven_semantic_checks_are_mandatory(self):
        original = (self.article / 'brief-review.json').read_bytes()
        for key in CHECKS:
            with self.subTest(check=key):
                (self.article / 'brief-review.json').write_bytes(original)
                self.change('brief-review.json', lambda r: r['checks'][key].update(passed=False))
                self.fails(key)

    def test_missing_main_fact_inventory_fails(self):
        self.change('brief-review.json', lambda r: r.update(aihot_facts=[]))
        self.fails('main-fact inventory')

    def test_fake_source_excerpt_fails(self):
        self.change('brief-review.json', lambda r: r['aihot_facts'][0].update(source_excerpt='没有这段原文。'))
        self.fails('actual internal source excerpt')

    def test_missing_main_fact_mapping_fails(self):
        self.change('brief-review.json', lambda r: r['aihot_facts'].pop())
        self.fails('Every core paragraph')

    def test_changed_numbers_fail_despite_updated_hash_and_html(self):
        self.body(lambda b: b.replace('8 个光点', '9 个光点'))
        self.fails('Critical fact detail missing/changed')

    def test_no_analysis_block_is_accepted(self):
        self.change('brief-review.json', lambda r: r['blocks'][1].update(kind='analysis'))
        self.fails('Analysis/opinion')

    def test_long_context_is_rejected(self):
        self.change('brief-review.json', lambda r: r.update(blocks=[
            r['blocks'][0], {'index': 1, 'kind': 'context', 'evidence_ids': ['core1']},
            *[dict(b, index=b['index'] + 1) for b in r['blocks'][1:]]]))
        self.change('brief-review.json', lambda r: r['aihot_facts'][1].update(body_blocks=[2]))
        self.body(lambda b: b.split('\n\n')[0] + '\n\n' + '背景说明需要来源，不能扩写为长篇观点。' * 12
                  + '\n\n' + '\n\n'.join(b.split('\n\n')[1:]))
        self.fails('Context exceeds')

    def test_short_sourced_context_passes(self):
        self.change('brief-review.json', lambda r: r.update(blocks=[
            r['blocks'][0], {'index': 1, 'kind': 'context', 'evidence_ids': ['core1']},
            *[dict(b, index=b['index'] + 1) for b in r['blocks'][1:]]]))
        self.change('brief-review.json', lambda r: r['aihot_facts'][1].update(body_blocks=[2]))
        self.body(lambda b: b.split('\n\n')[0] + '\n\n批处理指一次处理多个测试对象。\n\n'
                  + '\n\n'.join(b.split('\n\n')[1:]))
        self.assertTrue(validate(self.article)['valid'], validate(self.article)['errors'])

    def test_new_facts_cannot_be_relabeled_as_core(self):
        self.change('brief-review.json', lambda r: r['blocks'][3].update(kind='core'))
        self.fails('Supplemental facts must be isolated')

    def test_update_heading_date_must_match_check_date(self):
        self.body(lambda b: b.replace('截至 2026-10-19', '截至 2026-10-18'))
        self.fails('actual checked-through date')

    def test_update_without_explicit_event_date_fails(self):
        self.body(lambda b: b.replace('10月19日，', '稍后，'))
        self.fails('show its actual event date')

    def test_update_moved_before_heading_fails(self):
        self.change('brief-review.json', lambda r: r.update(blocks=r['blocks'][:2] + [
            dict(r['blocks'][3], index=2), dict(r['blocks'][2], index=3)]))
        self.body(lambda b: '\n\n'.join(b.split('\n\n')[:2] + b.split('\n\n')[2:][::-1]))
        self.fails('must follow the single final update heading')

    def test_no_update_source_record_fails(self):
        self.change('brief-review.json', lambda r: r['updates'].update(checked_sources=[]))
        self.fails('actual URLs checked')

    def test_unknown_evidence_id_fails(self):
        self.change('brief-review.json', lambda r: r['blocks'][0].update(evidence_ids=['missing']))
        self.fails('unknown evidence')

    def test_unverified_claim_fails(self):
        self.change('evidence.json', lambda r: r['claims'][2].update(status='unverified'))
        self.fails('verified statement')

    def test_source_retrieved_after_review_fails(self):
        self.change('evidence.json', lambda r: r['claims'][2].update(retrieved_at='2026-10-19T13:00:00+08:00'))
        self.fails('Claim retrieved after review')

    def test_html_mutation_and_unmarked_extra_text_fail(self):
        p = self.article / 'article.html'
        p.write_text(p.read_text(encoding='utf-8').replace('</article>', '<p>额外观点。</p></article>'), encoding='utf-8')
        self.fails('outside source blocks')

    def test_html_caption_mismatch_fails(self):
        p = self.article / 'article.html'
        p.write_text(p.read_text(encoding='utf-8').replace('合成夹具用于验证', 'HTML被修改'), encoding='utf-8')
        self.fails('HTML text differs')

    def test_current_gate_rejects_version_downgrade_even_with_legacy_flag(self):
        self.change('../manifest.json', lambda m: m.update(delivery_version=3, text_mode='aihot-original'))
        result = Validator(self.article.parent, current=True, legacy_structure=True).validate()
        self.assertFalse(result['valid'])
        self.assertTrue(any('--current' in e for e in result['errors']))

    def test_current_gate_rejects_missing_mode(self):
        self.change('../manifest.json', lambda m: m.pop('text_mode'))
        self.assertFalse(Validator(self.article.parent, current=True).validate()['valid'])

    def test_missing_review_cannot_be_bypassed_by_manifest_flag(self):
        (self.article / 'brief-review.json').unlink()
        self.change('../manifest.json', lambda m: m.update(brief_required=False))
        self.assertFalse(Validator(self.article.parent, current=True).validate()['valid'])

    def test_wrong_cover_skill_is_still_rejected(self):
        self.change('cover.json', lambda c: c.update(generator_skill='other-skill'))
        self.assertFalse(Validator(self.article.parent, current=True).validate()['valid'])

    def test_wrong_cover_ratio_is_still_rejected(self):
        from test_validate_delivery import synthetic_cover
        (self.article / 'images/cover.png').write_bytes(synthetic_cover(500, 210, 42))
        self.assertFalse(Validator(self.article.parent, current=True).validate()['valid'])

    def test_real_body_image_is_still_required(self):
        self.change('evidence.json', lambda e: e.update(images=e['images'][1:]))
        self.assertFalse(Validator(self.article.parent, current=True).validate()['valid'])

    def test_cover_cannot_be_silently_disabled(self):
        self.change('../manifest.json', lambda m: m.update(cover_required=False))
        self.assertFalse(Validator(self.article.parent, current=True).validate()['valid'])

    def test_cli_is_read_only_and_has_meaningful_exit_codes(self):
        env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
        script = Path(__file__).with_name('validate_brief.py')
        command = [sys.executable, '-B', str(script), str(self.article), '--json']
        result = subprocess.run(command, capture_output=True, encoding='utf-8', env=env)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(json.loads(result.stdout)['valid'])
        self.body(lambda b: b.replace('8 个光点', '9 个光点'))
        before = {p.name: digest(p.read_bytes()) for p in self.article.iterdir() if p.is_file()}
        result = subprocess.run(command, capture_output=True, encoding='utf-8', env=env)
        self.assertEqual(result.returncode, 1)
        after = {p.name: digest(p.read_bytes()) for p in self.article.iterdir() if p.is_file()}
        self.assertEqual(before, after)

    def test_malformed_records_fail_without_tracebacks(self):
        path = self.article / 'brief-review.json'
        for data in ([], {}, {'version': 1, 'mode': MODE, 'blocks': 'bad'}):
            with self.subTest(data=data):
                put_json(path, data)
                self.assertFalse(validate(self.article)['valid'])


if __name__ == '__main__':
    unittest.main()
