#!/usr/bin/env python3
"""Check content-work records and final bindings, never score interest or write reviews.

--prepare creates pending scaffolding only. --bind preserves editorial work but
invalidates the final approval. Normal validation is offline and read-only.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


FILES = ("title.txt", "body.txt", "caption.txt", "article.html", "evidence.json")
REPORT = "content-review.json"
STAGES = {"planning": "dbs-content", "review": "dbs-content-value"}
SCOPE = "内容工作记录与定稿绑定检查；不证明内容有趣、事实真实或诊断已经诚实执行。"
EMPTY_JUDGMENTS = {"pass", "ok", "通过", "合格", "无问题", "已检查", "已审查", "很好", "内容丰富", "有趣", "待填写"}


def specific(value):
    return (isinstance(value, str) and bool(value.strip())
            and value.strip().rstrip("。.!！").casefold() not in EMPTY_JUDGMENTS)


def local(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f"{name}: path escapes article directory")
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locked_skills(skill_dir=None):
    skill = Path(skill_dir).resolve() if skill_dir else Path(__file__).resolve().parents[1]
    lock = json.loads((skill / "dependencies.lock.json").read_text(encoding="utf-8-sig"))
    if not isinstance(lock, dict) or not isinstance(lock.get("dependencies"), list):
        raise ValueError("Invalid dependency lock")
    archived = lock.get("retired_dependencies", [])
    if not isinstance(archived, list):
        raise ValueError("Invalid archived dependency lock")
    historical_entries = lock["dependencies"] + archived
    result = {}
    for name in STAGES.values():
        entries = [d for d in historical_entries if isinstance(d, dict) and d.get("name") == name]
        if len(entries) != 1 or not isinstance(entries[0].get("files"), dict):
            raise ValueError(f"Missing or duplicate locked content skill: {name}")
        sha = entries[0]["files"].get("SKILL.md")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError(f"Invalid locked SHA256: {name}")
        result[name] = sha
    return result


def prepare(article_dir, skill_dir=None):
    root = Path(article_dir).resolve()
    if not root.is_dir():
        raise ValueError("Article directory must exist")
    pins = locked_skills(skill_dir)
    hashes = {name: digest(local(root, name)) if local(root, name).is_file() else None for name in FILES}
    return {
        "schema_version": 1, "status": "pending", "hashes": hashes,
        "planning": {"skill": STAGES["planning"], "skill_sha256": pins[STAGES["planning"]],
                     "full_picture": "", "reader_question": "", "added_value": "", "structure": "",
                     "coverage": []},
        "review": {"skill": STAGES["review"], "skill_sha256": pins[STAGES["review"]],
                   "opening": {"title_quote": "", "caption_quote": "", "body_quote": "",
                               "expectation": "", "readers": ""},
                   "payoffs": [], "findings": [], "conclusion": ""},
        "final_read": "",
    }


def bind(article_dir):
    root = Path(article_dir).resolve()
    report = json.loads(local(root, REPORT).read_text(encoding="utf-8-sig"))
    if not isinstance(report, dict) or type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        raise ValueError("Invalid content-review.json schema")
    report["hashes"] = {name: digest(local(root, name)) for name in FILES}
    report["status"] = "pending"
    report["final_read"] = ""
    return report


def validate(article_dir, skill_dir=None):
    root = Path(article_dir).resolve()
    errors = []
    result = {"valid": False, "status": "FAIL", "scope": SCOPE,
              "article_directory": str(root), "errors": errors}
    try:
        paths = {name: local(root, name) for name in (*FILES, REPORT)}
        texts = {name: paths[name].read_text(encoding="utf-8-sig") for name in FILES}
        hashes = {name: digest(paths[name]) for name in FILES}
        report = json.loads(paths[REPORT].read_text(encoding="utf-8-sig"))
        evidence = json.loads(texts["evidence.json"])
        pins = locked_skills(skill_dir)
    except (OSError, ValueError, UnicodeError, RuntimeError) as exc:
        errors.append(f"content-review.json/input: {exc}")
        return result
    if not isinstance(report, dict):
        errors.append("content-review.json must be an object")
        return result
    if type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        errors.append("content-review.json schema_version must be 1")
    if report.get("status") != "reviewed":
        errors.append("content-review.json status is not reviewed")
    if report.get("hashes") != hashes:
        errors.append("content-review.json SHA256 binding missing or stale; rebind and reread final files")
    claims = evidence.get("claims") if isinstance(evidence, dict) else None
    if not isinstance(claims, list):
        errors.append("evidence.claims must be a list")
        return result

    def obj(value, label):
        if not isinstance(value, dict):
            errors.append(f"{label} must be an object")
            return {}
        return value

    def prose(value, label):
        if not specific(value):
            errors.append(f"{label} requires a specific judgment, not an empty/PASS statement")

    def entries(value, label, required=True):
        if not isinstance(value, list) or (required and not value):
            errors.append(f"{label} must be {'a nonempty' if required else 'a'} list")
            return []
        return value

    def refs(value, label, required=True):
        indices = entries(value, label, required)
        seen = set()
        for index in indices:
            if type(index) is not int or not 0 <= index < len(claims):
                errors.append(f"{label}: invalid evidence claim index")
                continue
            if index in seen:
                errors.append(f"{label}: duplicate evidence claim index")
            seen.add(index)
            claim = claims[index]
            if (not isinstance(claim, dict) or claim.get("status") != "verified"
                    or not specific(claim.get("claim")) or not isinstance(claim.get("source_url"), str)
                    or not re.match(r"https?://[^/\s]+", claim["source_url"])):
                errors.append(f"{label}: claim {index} is not a verified sourced claim")

    def anchor(value, target, label, exact=False):
        if not isinstance(value, str) or not value.strip() or (value.strip() != target.strip() if exact else value not in target):
            errors.append(f"{label}: quote does not match current text")

    for stage, name in STAGES.items():
        part = obj(report.get(stage), stage)
        if part.get("skill") != name or part.get("skill_sha256") != pins[name]:
            errors.append(f"{stage}: expected locked {name} skill and SHA256")

    planning = obj(report.get("planning"), "planning")
    for field in ("full_picture", "reader_question", "added_value", "structure"):
        prose(planning.get(field), f"planning.{field}")
    included = False
    for n, raw in enumerate(entries(planning.get("coverage"), "planning.coverage")):
        label = f"planning.coverage[{n}]"
        item = obj(raw, label)
        for field in ("question", "finding", "reason"):
            prose(item.get(field), f"{label}.{field}")
        decision = item.get("decision")
        if decision not in ("included", "context", "unavailable", "irrelevant"):
            errors.append(f"{label}: invalid coverage decision")
        if decision == "included":
            included = True
        refs(item.get("claim_indices"), f"{label}.claim_indices", decision in ("included", "context"))
    if not included:
        errors.append("planning.coverage needs the sourced material actually included in the article")

    review = obj(report.get("review"), "review")
    opening = obj(review.get("opening"), "review.opening")
    first = texts["body.txt"].strip().split("\n\n", 1)[0]
    for key, target in (("title_quote", texts["title.txt"]), ("caption_quote", texts["caption.txt"]), ("body_quote", first)):
        anchor(opening.get(key), target, f"review.opening.{key}", exact=True)
    for field in ("expectation", "readers"):
        prose(opening.get(field), f"review.opening.{field}")
    seen_quotes = set()
    for n, raw in enumerate(entries(review.get("payoffs"), "review.payoffs")):
        label = f"review.payoffs[{n}]"
        payoff = obj(raw, label)
        quote = payoff.get("quote")
        anchor(quote, texts["body.txt"], f"{label}.quote")
        if isinstance(quote, str):
            if quote in seen_quotes:
                errors.append(f"{label}: duplicate payoff quote")
            seen_quotes.add(quote)
        prose(payoff.get("why_it_matters"), f"{label}.why_it_matters")
        refs(payoff.get("claim_indices"), f"{label}.claim_indices")
    public = "\n".join(texts[name] for name in ("title.txt", "body.txt", "caption.txt"))
    for n, raw in enumerate(entries(review.get("findings"), "review.findings", required=False)):
        label = f"review.findings[{n}]"
        finding = obj(raw, label)
        if finding.get("status") != "resolved":
            errors.append(f"{label}: unresolved content finding")
        for field in ("problem", "action"):
            prose(finding.get(field), f"{label}.{field}")
        anchor(finding.get("result_quote"), public, f"{label}.result_quote")
    prose(review.get("conclusion"), "review.conclusion")
    prose(report.get("final_read"), "final_read")
    result.update(valid=not errors, status="FAIL" if errors else "PASS")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("article_directory", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true", help="Create pending scaffold only; never overwrite")
    mode.add_argument("--bind", action="store_true", help="Rebind final files and invalidate final approval")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.prepare or args.bind:
            root = args.article_directory.resolve()
            record = prepare(root) if args.prepare else bind(root)
            path = local(root, REPORT)
            with path.open("x" if args.prepare else "w", encoding="utf-8", newline="\n") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            result = {"status": "PENDING", "path": str(path), "scope": SCOPE,
                      "message": "Pending editorial review; no content approval was generated"}
            code = 0
        else:
            result = validate(args.article_directory)
            code = 0 if result["valid"] else 1
    except (OSError, ValueError, UnicodeError, RuntimeError) as exc:
        result = {"status": "FAIL", "scope": SCOPE, "errors": [str(exc)]}
        code = 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["status"])
        for error in result.get("errors", []):
            print(error, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
