#!/usr/bin/env python3
"""Offline editorial-work gate, NOT an AI-authorship or writing-quality detector.

--prepare writes a pending checklist, never approvals. Validation is read-only.
All text is synthetic in the companion tests; no source or publication calls.
"""
import argparse
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re


VERSION = 1
FILES = ("title.txt", "body.txt", "caption.txt", "article.html")
REPORT = "prose-review.json"
SCOPE = "逐句审校记录与已知套话拦截；不证明无 AI 感，不鉴定作者身份或事实真假。"
ROLES = {"fact", "explanation", "inference", "transition", "heading", "caption", "quote", "code", "ui"}
CATEGORIES = {"empty_preface", "fake_discovery", "abstract_judgment", "repetition", "awkward_syntax", "invented_voice", "fact_drift", "other"}
READTHROUGH = ("progression", "naturalness", "factual_fidelity", "title_caption")
# Narrow regressions, not a universal blacklist. Context is still reviewed for
# every unflagged sentence; quoting a phrase is distinct from using it as prose.
PATTERNS = {
    "empty_preface": re.compile(r"(?:这个|这一|这种)区别[^。！？\n]{0,35}(?:就|便)?很好理解|(?:先说结论|下面我们来看看|让我们一起来看)[，,：:]?"),
    "fake_discovery": re.compile(r"(?:官方)?模型卡[^。！？\n]{0,16}(?:很容易|容易被|容易让人)(?:略过|忽略)[^。！？\n]{0,10}细节|(?:还有|也有|藏着)一个?[^。！？\n]{0,10}(?:容易忽略|容易略过)的细节"),
    "abstract_judgment": re.compile(r"(?:这里|这次|其中)最让人[^。！？\n]{0,12}的[，,]?\s*是|(?:真正有意思|最值得玩味|更值得注意)的(?:地方)?(?:在于|是)"),
}
GENERIC = re.compile(r"^(?:PASS|OK|通过|自然|更自然|没问题|已检查|已审校|符合规则|保留原意|信息清楚|表达自然|语句通顺|无AI感|无AI味)[。！!\s]*$", re.I)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compact(text):
    return re.sub(r"\s+", "", text)


def useful(text):
    return isinstance(text, str) and bool(text.strip()) and not GENERIC.fullmatch(text.strip())


def local_file(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"{name}: 缺文件或路径越出文章目录")
    return path


class RenderedText(HTMLParser):
    """Read static visible text, copy fields, figcaptions and image alt text.

    CSS/JS-computed visibility and runtime clipboard payloads require a browser
    check. Script/style/template/head are excluded; hidden attributes are not
    a way to remove authored prose from the audit.
    """
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    BLOCK = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "figure", "figcaption", "header", "footer", "main", "aside", "pre", "nav", "button"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.public, self.alts, self.stack = [], [], []
        self.fields = {"title": [], "body": [], "caption": []}
        self.counts = Counter()
        self.active, self.excluded, self.figcaption = None, False, False

    def emit(self, text):
        if not self.excluded:
            self.public.append(text)
            if self.active and not self.figcaption:
                self.fields[self.active].append(text)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        previous = (self.active, self.excluded, self.figcaption)
        self.excluded |= tag in {"script", "style", "template", "head"}
        field = {"article-title": "title", "article-body": "body", "article-caption": "caption"}.get(values.get("id"))
        if tag == "h1" and self.active is None:
            field = field or "title"
        if field:
            self.active = field
            self.counts[field] += 1
        self.figcaption |= tag == "figcaption"
        if tag in self.BLOCK:
            self.emit("\n")
        if tag == "img" and values.get("alt") and not self.excluded:
            self.alts.append(values["alt"])
        if tag not in self.VOID:
            self.stack.append((tag, *previous))
        else:
            self.active, self.excluded, self.figcaption = previous

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.emit("\n")
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                _, self.active, self.excluded, self.figcaption = self.stack[i]
                del self.stack[i:]
                break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        self.emit(data)


def split_units(text):
    """Cover all nonblank characters, incl. headings and unpunctuated lines.

    Chinese/English sentence endings and newlines split review units. ASCII
    decimals, versions and URLs stay intact. Code is still covered, not edited.
    """
    boundary = re.compile(r"[。！？!?]+[”’\"')）】]*|\.(?=\s|$)[”’\"')）]*|\n+")
    start = 0
    for match in boundary.finditer(text):
        end = match.end()
        piece = text[start:end].strip()
        if piece:
            left = start + len(text[start:end]) - len(text[start:end].lstrip())
            yield left, left + len(piece), piece
        start = end
    if text[start:].strip():
        left = start + len(text[start:]) - len(text[start:].lstrip())
        yield left, len(text.rstrip()), text[start:].strip()


def scan(text):
    return sorted(name for name, pattern in PATTERNS.items() if pattern.search(text))


def snapshot(article):
    root = Path(article).resolve()
    hashes, texts = {}, {}
    for name in FILES:
        data = local_file(root, name).read_bytes()
        hashes[name] = digest(data)
        text = data.decode("utf-8-sig")
        if not text.strip():
            raise ValueError(f"{name}: 空文件")
        texts[name] = text
    parser = RenderedText()
    parser.feed(texts["article.html"])
    parser.close()
    errors = []
    for key in ("title", "body", "caption"):
        if parser.counts[key] != 1:
            errors.append(f"HTML {key} 必须且仅有一个对应区域（标题用 h1 或 article-title）")
        if compact("".join(parser.fields[key])) != compact(texts[key + ".txt"]):
            errors.append(f"HTML {key} 与 {key}.txt 不一致（正文图注单独审校）")
    fields = {key: texts[key + ".txt"] for key in ("title", "body", "caption")}
    fields["html_extra"] = "".join(parser.public) + "\n" + "\n".join(parser.alts)
    units, primary = [], set()
    for field, text in fields.items():
        for start, end, piece in split_units(text):
            # Identical rendered repeats are covered by the primary unit and
            # still bound by the complete HTML hash. Different text is not.
            if field == "html_extra" and compact(piece) in primary:
                continue
            units.append({"id": f"{field}:{start}:{end}", "field": field,
                          "text": piece, "flags": scan(piece)})
            if field != "html_extra":
                primary.add(compact(piece))
    return hashes, units, errors


def prepare(article):
    hashes, units, errors = snapshot(article)
    return {"schema_version": VERSION, "status": "pending", "files": hashes,
            "units": [dict(unit, decision="pending", role="", anchor="", reason="", exceptions=[]) for unit in units],
            "issues": [], "readthrough": {key: {"decision": "pending", "anchors": [], "note": ""} for key in READTHROUGH},
            "snapshot_errors": errors}


def validate(article):
    errors = []
    total, reviewed = 0, 0
    try:
        hashes, expected, layout_errors = snapshot(article)
        errors.extend(layout_errors)
        total = len(expected)
        report = json.loads(local_file(Path(article).resolve(), REPORT).read_text(encoding="utf-8-sig"))
        if not isinstance(report, dict):
            raise ValueError("prose-review.json 顶层必须为对象")
        if type(report.get("schema_version")) is not int or report["schema_version"] != VERSION:
            errors.append("审校 schema_version 错误")
        if report.get("status") != "reviewed":
            errors.append("审校 status 未完成；prepare 不会自动批准")
        if report.get("files") != hashes:
            errors.append("审校 SHA256 已过期或不完整：定稿改动后须重新逐句审校")
        entries = report.get("units")
        if not isinstance(entries, list) or not all(isinstance(row, dict) for row in entries):
            raise ValueError("units 必须为逐句对象数组")
        ids = [row.get("id") for row in entries]
        if ids != [unit["id"] for unit in expected]:
            errors.append("逐句覆盖不完整、重复、乱序或 id 过期")
        reasons = []
        for wanted, row in zip(expected, entries):
            label = wanted["id"]
            if any(row.get(key) != wanted[key] for key in ("id", "field", "text", "flags")):
                errors.append(f"{label}: 句文或 flags 被改写，须重建待审表")
            if row.get("decision") != "keep":
                errors.append(f"{label}: 仍有 pending/rewrite/delete 等未完成决定")
            else:
                reviewed += 1
            if row.get("role") not in tuple(ROLES):
                errors.append(f"{label}: 缺少有效句子作用 role")
            anchor, reason = row.get("anchor"), row.get("reason")
            if not isinstance(anchor, str) or not anchor.strip() or anchor not in wanted["text"]:
                errors.append(f"{label}: anchor 须来自本句")
            if not useful(reason) or not isinstance(anchor, str) or anchor not in reason:
                errors.append(f"{label}: reason 须引用 anchor 并说明本句在上下文中的具体作用，不能只写通过")
            if isinstance(reason, str):
                reasons.append(reason.strip())
            exceptions = row.get("exceptions")
            if not isinstance(exceptions, list) or not all(isinstance(exc, dict) for exc in exceptions):
                errors.append(f"{label}: exceptions 必须为数组")
                continue
            if [exc.get("rule") for exc in exceptions] != wanted["flags"]:
                errors.append(f"{label}: 已知套话未删除/改写，也没有逐条有效语境例外")
            for exc in exceptions:
                rule, basis = exc.get("rule"), exc.get("basis")
                if not isinstance(rule, str) or rule not in PATTERNS:
                    errors.append(f"{label}: 未知例外规则")
                    continue
                quote = exc.get("protected_text")
                if (not isinstance(quote, str) or not quote or quote not in wanted["text"]
                        or not PATTERNS[rule].search(quote)):
                    errors.append(f"{label}: 例外没有绑定实际命中的原文")
                if basis not in ("quotation", "literal_code", "discussed_wording"):
                    errors.append(f"{label}: 例外仅限必要原话、代码字面量或被讨论的措辞；自然/有趣不算理由")
                if not useful(exc.get("reason")) or not useful(exc.get("context")):
                    errors.append(f"{label}: 例外须解释准确语境与保留必要性")
                # A bare waiver must not turn authored boilerplate into a quote.
                if isinstance(quote, str) and quote:
                    ranges = []
                    for a, b in (("“", "”"), ("「", "」"), ('"', '"'), ("`", "`")):
                        for match in re.finditer(re.escape(a + quote + b), wanted["text"]):
                            ranges.append((match.start() + len(a), match.end() - len(b)))
                    if not ranges:
                        errors.append(f"{label}: 例外片段须以引号或代码标记明确标示，不能给普通叙述套例外")
                    elif any(not any(left <= hit.start() and hit.end() <= right for left, right in ranges)
                             for hit in PATTERNS[rule].finditer(wanted["text"])):
                        errors.append(f"{label}: 同句仍有未被引语/代码覆盖的套话命中")
                if basis == "quotation" and not useful(exc.get("source")):
                    errors.append(f"{label}: 引语例外缺少内部 source 依据")
        if len(reasons) != len(set(reasons)):
            errors.append("多句复用相同审校理由；不能批量盖章")
        issues = report.get("issues")
        if not isinstance(issues, list):
            errors.append("issues 必须为数组")
        else:
            all_text = {field: "\n".join(unit["text"] for unit in expected if unit["field"] == field) for field in ("title", "body", "caption", "html_extra")}
            for issue in issues:
                if not isinstance(issue, dict):
                    errors.append("issue 必须为对象")
                    continue
                field, action = issue.get("field"), issue.get("action")
                if issue.get("status") != "resolved" or action not in ("rewrite", "delete"):
                    errors.append("issue 未解决；须实际 rewrite/delete 后关闭，保留例外记在对应句子")
                if issue.get("category") not in tuple(CATEGORIES) or field not in tuple(all_text):
                    errors.append("issue category/field 无效")
                    continue
                before, after = issue.get("before"), issue.get("after")
                if not useful(before) or not useful(issue.get("reason")):
                    errors.append("issue 缺具体原句或修改理由")
                if action == "rewrite" and (not useful(after) or after == before or after not in all_text[field]):
                    errors.append("issue 的改写结果未落实到当前文本")
                if action == "delete" and (after != "" or (isinstance(before, str) and before in all_text[field])):
                    errors.append("issue 的删除未落实到当前文本")
        readthrough = report.get("readthrough")
        unit_text = {unit["id"]: unit["text"] for unit in expected}
        if not isinstance(readthrough, dict):
            errors.append("缺少全文通读 readthrough")
        else:
            for key in READTHROUGH:
                item = readthrough.get(key)
                if not isinstance(item, dict) or item.get("decision") != "reviewed":
                    errors.append(f"readthrough.{key}: 未完成")
                    continue
                anchors, note = item.get("anchors"), item.get("note")
                if (not isinstance(anchors, list) or not anchors or not all(isinstance(a, str) and a in unit_text for a in anchors)
                        or not useful(note) or not any(unit_text.get(a, "\0") in note for a in anchors if isinstance(a, str))):
                    errors.append(f"readthrough.{key}: 须绑定当前句子并引用具体句文，不能只填总 PASS")
    except (OSError, ValueError, UnicodeError, RuntimeError) as exc:
        errors.append(f"审校读取失败 ({type(exc).__name__}): {exc}")
    return {"valid": not errors, "status": "PASS" if not errors else "FAIL", "scope": SCOPE,
            "sentences": total, "reviewed": reviewed, "errors": errors}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("article_directory")
    parser.add_argument("--prepare", action="store_true", help="新建 pending 表；已有报告时拒绝覆盖")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    if args.prepare:
        try:
            root = Path(args.article_directory).resolve()
            report = prepare(root)
            path = root / REPORT
            with path.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            print("PENDING: 已生成逐句待审表，未完成审校；请逐句处理后另行运行校验。")
            return 0  # success of file creation, explicitly not editorial PASS
        except (OSError, ValueError, UnicodeError, RuntimeError) as exc:
            print(f"FAIL: {exc}")
            return 1
    result = validate(args.article_directory)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(SCOPE)
        print(f"Sentences: {result['reviewed']}/{result['sentences']}")
        for error in result["errors"]:
            print(f"ERROR: {error}")
        print(result["status"])
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
