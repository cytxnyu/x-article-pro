#!/usr/bin/env python3
"""Resolve pinned sibling skills. Read-only, offline, standard-library only."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys


EXPECTED = {"aihot", "cover-editorial-collage"}
STAGES = {"discovery": "aihot", "cover": "cover-editorial-collage"}


def within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def frontmatter_name(path):
    text = path.read_text(encoding="utf-8-sig")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not match:
        return None
    field = re.search(r"^name:\s*([^\r\n]+)$", match.group(1), re.M)
    return field.group(1).strip().strip('\"\'') if field else None


def resolve(skill_dir, skills_root=None, stage="all"):
    skill_dir = Path(skill_dir).resolve()
    skills_root = Path(skills_root).resolve() if skills_root else skill_dir.parent
    result = {"status": "FAIL", "entry": "x-article-pro", "stage": stage,
              "skills_root": str(skills_root), "dependencies": [], "errors": []}
    errors = result["errors"]
    if stage not in {"all", *STAGES}:
        errors.append("Unknown stage")
        return result
    try:
        lock = json.loads((skill_dir / "dependencies.lock.json").read_text(encoding="utf-8"))
        if not isinstance(lock, dict) or lock.get("schema_version") != 1 or lock.get("entry") != "x-article-pro":
            raise ValueError("Unsupported dependency lock")
        if frontmatter_name(skill_dir / "SKILL.md") != "x-article-pro":
            raise ValueError("Entrypoint name mismatch")
        entries = lock["dependencies"]
        if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
            raise ValueError("Dependency records must be a list of objects")
        names = [item["name"] for item in entries]
        if len(names) != len(set(names)) or set(names) != EXPECTED:
            raise ValueError("Dependency set must contain exactly the two active source/cover skills")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
        return result

    selected = entries if stage == "all" else [item for item in entries if item["name"] == STAGES[stage]]
    for item in selected:
        name = item["name"]
        directory = item.get("directory")
        if directory != name:
            errors.append(f"{name}: directory must match the skill name")
            continue
        root = (skills_root / directory).resolve()
        if not within(root, skills_root) or root == skills_root:
            errors.append(f"{name}: dependency escapes the skills root")
            continue
        entry = root / "SKILL.md"
        record = {"name": name, "entry_path": str(entry), "status": "FAIL",
                  "repository": item.get("repository"), "revision": item.get("revision"),
                  "pin_kind": item.get("pin_kind", "repository"), "checked_files": 0}
        result["dependencies"].append(record)
        start_errors = len(errors)
        try:
            if frontmatter_name(entry) != name:
                errors.append(f"{name}: frontmatter name mismatch")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{name}: unreadable entrypoint ({exc})")
        required = {"SKILL.md", "agents/openai.yaml", "LICENSE"}
        if item.get("pin_kind", "repository") != "repository":
            errors.append(f"{name}: active repository dependency must retain its original pin kind")
        files = item.get("files")
        if not isinstance(files, dict) or not required.issubset(files):
            errors.append(f"{name}: incomplete file manifest")
            continue
        for relative, expected_hash in sorted(files.items()):
            pure = PurePosixPath(relative)
            if pure.is_absolute() or ".." in pure.parts or "\\" in relative or ":" in relative:
                errors.append(f"{name}: invalid locked file path {relative}")
                continue
            path = (root / Path(*pure.parts)).resolve()
            if not within(path, root) or path == root:
                errors.append(f"{name}: file escapes dependency {relative}")
                continue
            if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                errors.append(f"{name}: invalid SHA-256 for {relative}")
                continue
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                errors.append(f"{name}: unreadable {relative} ({exc})")
                continue
            record["checked_files"] += 1
            if actual != expected_hash:
                errors.append(f"{name}: SHA-256 mismatch for {relative}")
        if len(errors) == start_errors:
            record["status"] = "PASS"
    result["status"] = "PASS" if not errors else "FAIL"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, help="Sibling skills root; defaults to this skill's parent")
    parser.add_argument("--stage", choices=["all", *STAGES], default="all")
    parser.add_argument("--json", action="store_true", help="Print machine-readable results")
    args = parser.parse_args(argv)
    result = resolve(Path(__file__).resolve().parents[1], args.skills_root, args.stage)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"{result['status']} dependencies={len(result['dependencies'])} stage={args.stage}")
        for item in result["dependencies"]:
            print(f"{item['status']} {item['name']} {item['entry_path']}")
        for error in result["errors"]:
            print(error, file=sys.stderr)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
