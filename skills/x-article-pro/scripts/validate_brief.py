#!/usr/bin/env python3
"""Read-only v4 news-brief record checks; not a factual or plagiarism certification."""
import argparse
from datetime import date, datetime
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from validate_source import SourceHTML, canonical

MODE = 'aihot-news-brief'
SOURCE_FILES = ('title.txt', 'text.txt', 'raw-response.txt')
OUTPUT_FILES = ('title.txt', 'body.txt', 'caption.txt')
CHECKS = ('main_facts_complete', 'factual_qualifiers_preserved', 'independent_expression',
          'no_extended_analysis', 'updates_separated', 'title_supported', 'caption_supported')
SCOPE = 'Checks local records, obvious source overlap and text/HTML consistency; semantic review remains required.'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def url(value, aihot=False):
    if not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        return p.scheme in ('http', 'https') and bool(p.hostname) and (not aihot or (
            p.scheme == 'https' and p.hostname == 'aihot.news' and p.path not in ('', '/')))
    except ValueError:
        return False


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('ISO timestamp with timezone required')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('ISO timestamp with timezone required')
    return result


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('YYYY-MM-DD date required')
    return date.fromisoformat(value)


def normalized(text):
    return ''.join(c for c in text.casefold() if c.isalnum())


def literal(text):
    return re.sub(r'\s+', '', text).casefold()


def size(text):
    return len(re.sub(r'\s+', '', text))


class BriefHTML(SourceHTML):
    def handle_starttag(self, tag, attrs):
        if any(k == 'data-source-block' for k, _ in attrs):
            self.errors.append('v4 uses data-brief-block, not legacy source-copy blocks')
        super().handle_starttag(tag, [('data-source-block' if k == 'data-brief-block' else k, v)
                                     for k, v in attrs])


def validate(article):
    root = Path(article).resolve()
    errors, warnings = [], []
    result = {'valid': False, 'status': 'FAIL', 'mode': MODE, 'scope': SCOPE,
              'errors': errors, 'warnings': warnings}

    def read(name):
        path = (root / name).resolve()
        if path == root or not path.is_relative_to(root):
            raise ValueError('Path escapes article: ' + name)
        return path.read_bytes()

    def obj(name):
        data = json.loads(read(name).decode('utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError(name + ' must be an object')
        return data

    try:
        source = obj('news-source.json')
        review = obj('brief-review.json')
        evidence = obj('evidence.json')
        if type(source.get('version')) is not int or source['version'] != 1 or source.get('mode') != MODE:
            errors.append('news-source version/mode mismatch')
        aihot = source.get('aihot')
        if not isinstance(aihot, dict):
            raise ValueError('news-source.aihot must be an object')
        if not url(aihot.get('source_url'), aihot=True):
            errors.append('AIHOT source_url must be the actual HTTPS item/reading URL')
        result['source_url'] = aihot.get('source_url')
        retrieved = timestamp(aihot.get('retrieved_at'))
        if 'source_date' not in aihot:
            errors.append('Record source_date, explicitly null when unknown')
        elif aihot['source_date'] is not None and valid_date(aihot['source_date']) > retrieved.date():
            errors.append('Source publication date is later than retrieval')
        if aihot.get('content_kind') not in ('full_article', 'summary', 'excerpt', 'user_provided'):
            errors.append('Record actual source content_kind')
        if not nonempty(aihot.get('extraction_note')):
            errors.append('extraction_note must describe the actual fields/region and content extent')
        hashes = aihot.get('sha256')
        if not isinstance(hashes, dict) or set(hashes) != set(SOURCE_FILES):
            errors.append('AIHOT SHA-256 manifest must include exactly three source files')
            hashes = {}
        src = {}
        for name in SOURCE_FILES:
            raw = read('source/' + name)
            if not raw or hashes.get(name) != digest(raw):
                errors.append('Source SHA-256 changed or empty: ' + name)
            src[name] = canonical(raw.decode('utf-8-sig'))
        if any(not value.strip() for value in src.values()):
            errors.append('Source files must contain actual nonempty material')
        output = {name: read(name) for name in OUTPUT_FILES}
        texts = {name: canonical(raw.decode('utf-8-sig')) for name, raw in output.items()}
        title, body, caption = (texts[name] for name in OUTPUT_FILES)
        result['title'] = title
        if not title.strip() or not body.strip():
            errors.append('Title and body must be nonempty')
        if title != title.strip() or '\n' in title:
            errors.append('Title must be one clean standalone line')
        if body != body.strip() or any(not p.strip() for p in body.split('\n\n')):
            errors.append('Body must contain nonempty double-newline-separated blocks')
        if normalized(title) == normalized(src['title.txt']):
            errors.append('Title copies the source title; write independently')
        if caption and (size(caption) > 160 or literal(caption) == literal(title) or literal(caption) in literal(body)):
            errors.append('Caption must be brief and independent, not repeated in title/body')
        if type(review.get('version')) is not int or review['version'] != 1 or review.get('mode') != MODE:
            errors.append('brief-review version/mode mismatch')
        if review.get('text_sha256') != {name: digest(raw) for name, raw in output.items()}:
            errors.append('Review hashes do not bind the final title/body/caption')
        reviewed = timestamp(review.get('reviewed_at'))
        if reviewed < retrieved or not nonempty(review.get('reviewer')):
            errors.append('Actual reviewer and review time after retrieval required')
        checks = review.get('checks')
        if not isinstance(checks, dict):
            checks = {}
        for key in CHECKS:
            check = checks.get(key)
            if not isinstance(check, dict) or check.get('passed') is not True or not nonempty(check.get('note')):
                errors.append('Missing/failed semantic review: ' + key)

        terms = review.get('literal_terms', [])
        if not isinstance(terms, list):
            raise ValueError('literal_terms must be an array of short factual names/terms')
        for term in terms:
            if (not nonempty(term) or size(term) > 80 or len(re.findall(r'[\u3400-\u9fff]', term)) > 16
                    or literal(term) not in literal(src['title.txt'] + src['text.txt'])):
                errors.append('literal_terms may only exclude short factual names/terms actually in source')
        def prose_only(text):
            for term in sorted((t for t in terms if isinstance(t, str)), key=len, reverse=True):
                text = text.replace(term, '')
            return normalized(text)
        source_prose = prose_only(src['text.txt'])
        for index, paragraph in enumerate(body.split('\n\n') + ([caption] if caption else [])):
            candidate = prose_only(paragraph)
            if not candidate:
                continue
            match = SequenceMatcher(None, source_prose, candidate, autojunk=False).find_longest_match()
            if (len(candidate) >= 24 and candidate in source_prose) or match.size >= 40:
                errors.append(f'Obvious source wording overlap at paragraph/caption {index}; revise expression, not facts')
        if normalized(body) == normalized(src['text.txt']) or (prose_only(body) and prose_only(body) == source_prose):
            errors.append('Body copies the source wording')

        if evidence.get('text_mode') != MODE or evidence.get('source_capture') != 'news-source.json':
            errors.append('evidence must reference current news-brief mode and news-source.json')
        claim_list = evidence.get('claims')
        if not isinstance(claim_list, list) or not claim_list:
            raise ValueError('Nonempty evidence.claims required')
        claims = {}
        for claim in claim_list:
            if not isinstance(claim, dict) or not nonempty(claim.get('id')):
                raise ValueError('Each claim needs an id')
            cid = claim['id']
            if cid in claims:
                errors.append('Duplicate evidence id: ' + cid)
            claims[cid] = claim
            if not nonempty(claim.get('claim')) or claim.get('status') != 'verified' or not url(claim.get('source_url')):
                errors.append('Claim needs a verified statement and actual URL: ' + cid)
            if claim.get('role') not in ('aihot', 'corroboration', 'update'):
                errors.append('Claim role must be aihot/corroboration/update: ' + cid)
            if claim.get('role') == 'aihot' and claim.get('source_url') != aihot.get('source_url'):
                errors.append('AIHOT claim URL must match the source snapshot: ' + cid)
            when = timestamp(claim.get('retrieved_at'))
            if when > reviewed:
                errors.append('Claim retrieved after review: ' + cid)
            if 'source_date' not in claim:
                errors.append('Claim must explicitly record source_date or null: ' + cid)
            elif claim['source_date'] is not None and valid_date(claim['source_date']) > when.date():
                errors.append('Claim source date later than retrieval: ' + cid)
        paragraphs = body.split('\n\n')
        blocks = review.get('blocks')
        if not isinstance(blocks, list) or len(blocks) != len(paragraphs):
            raise ValueError('Review blocks must cover every body paragraph including headings')
        core, context, updates, headings = [], [], [], []
        for index, (paragraph, block) in enumerate(zip(paragraphs, blocks)):
            if not isinstance(block, dict) or type(block.get('index')) is not int or block['index'] != index:
                raise ValueError('Review block indices must be consecutive from zero')
            kind = block.get('kind')
            if kind not in ('core', 'context', 'update', 'updates_heading'):
                errors.append('Analysis/opinion block kind is not allowed')
                continue
            {'core': core, 'context': context, 'update': updates, 'updates_heading': headings}[kind].append(index)
            ids = block.get('evidence_ids')
            if not isinstance(ids, list) or any(not isinstance(cid, str) or cid not in claims for cid in ids):
                errors.append('Block has missing/unknown evidence ids')
                continue
            if kind == 'updates_heading':
                if ids:
                    errors.append('Heading is not a factual paragraph')
                continue
            if not ids:
                errors.append('Every factual block needs evidence ids')
            for cid in ids:
                claim = claims[cid]
                if (kind == 'update') != (claim.get('role') == 'update'):
                    errors.append('Supplemental facts must be isolated from the core/context')
                if kind == 'update':
                    event = valid_date(claim.get('event_date'))
                    if event.isoformat() not in paragraph and f'{event.month}月{event.day}日' not in literal(paragraph):
                        errors.append('Every update must show its actual event date')
        if not core:
            errors.append('At least one AIHOT main-fact paragraph required')
        core_size = sum(size(paragraphs[i]) for i in core)
        context_size = sum(size(paragraphs[i]) for i in context)
        if len(context) > 1 or context_size > min(120, core_size * .15):
            errors.append('Context exceeds one paragraph / 120 characters / 15% of main-fact text')

        facts = review.get('aihot_facts')
        if not isinstance(facts, list) or not facts:
            raise ValueError('Complete AIHOT main-fact inventory required')
        fact_ids, covered = set(), set()
        for fact in facts:
            if not isinstance(fact, dict) or not nonempty(fact.get('id')) or not nonempty(fact.get('fact')):
                raise ValueError('Each main fact needs an id and factual statement')
            if fact['id'] in fact_ids:
                errors.append('Duplicate main-fact id')
            fact_ids.add(fact['id'])
            excerpt = fact.get('source_excerpt')
            if not nonempty(excerpt) or excerpt not in src['text.txt']:
                errors.append('Main fact must cite an actual internal source excerpt')
            indices = fact.get('body_blocks')
            if not isinstance(indices, list) or not indices or any(type(i) is not int or i not in core for i in indices):
                errors.append('Main fact must map to core body blocks')
                continue
            covered.update(indices)
            details = fact.get('critical_details')
            if not isinstance(details, list) or not details or any(not nonempty(x) for x in details):
                errors.append('Main fact needs critical names/numbers/units/qualifiers')
                continue
            mapped = '\n'.join(paragraphs[i] for i in indices)
            for detail in details:
                if literal(detail) not in literal(mapped) or literal(detail) not in literal(excerpt or ''):
                    errors.append('Critical fact detail missing/changed: ' + detail)
        if set(core) != covered:
            errors.append('Every core paragraph must map back to AIHOT main facts')

        extra = review.get('updates')
        if not isinstance(extra, dict):
            raise ValueError('updates check record required, including when no news was found')
        checked = timestamp(extra.get('checked_at'))
        if checked > reviewed or checked < retrieved:
            errors.append('Update check must be between source retrieval and review')
        checked_sources = extra.get('checked_sources')
        if not isinstance(checked_sources, list) or not checked_sources or not all(url(v) for v in checked_sources):
            errors.append('Record the actual URLs checked for related/latest developments')
        if updates:
            if extra.get('status') != 'verified' or len(headings) != 1:
                errors.append('Verified updates require exactly one separate heading')
            else:
                heading = headings[0]
                expected = '相关新闻与最新进展｜截至 ' + checked.date().isoformat()
                if paragraphs[heading] != expected:
                    errors.append('Update heading must state the actual checked-through date')
                if heading <= max(core + context) or any(i <= heading for i in updates) or updates != list(range(heading + 1, len(blocks))):
                    errors.append('All and only update paragraphs must follow the single final update heading')
            for i in updates:
                for cid in blocks[i].get('evidence_ids', []):
                    if cid in claims and timestamp(claims[cid]['retrieved_at']) > checked:
                        errors.append('Update source must be read by the checked-through time')
        elif headings or extra.get('status') != 'none' or not nonempty(extra.get('note')):
            errors.append('No verified updates: omit public heading and record checked result internally')
        parser = BriefHTML()
        parser.feed(read('article.html').decode('utf-8-sig'))
        parser.close()
        errors.extend(parser.errors)
        for field in ('article-title', 'article-body', 'article-caption'):
            if parser.counts[field] != 1:
                errors.append('HTML requires exactly one independent ' + field)
        for field, expected in (('article-title', title), ('article-caption', caption)):
            if canonical(''.join(parser.text[field])) != expected:
                errors.append('HTML text differs from output: ' + field)
        if '\n\n'.join(''.join(b) for b in parser.blocks) != body:
            errors.append('HTML body differs from final text/paragraph order')
        result.update(main_fact_count=len(facts), core_blocks=len(core), update_blocks=len(updates),
                      context_characters=context_size, source_kind=aihot.get('content_kind'))
    except (OSError, ValueError, UnicodeError, TypeError, KeyError, RuntimeError) as exc:
        errors.append('Brief validation input error: ' + str(exc))
    result.update(valid=not errors, status='FAIL' if errors else 'PASS')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('article_directory', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    result = validate(args.article_directory)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
          result['status'] + ' news-brief' + ''.join('\n' + e for e in result['errors']))
    return 0 if result['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
