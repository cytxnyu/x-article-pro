#!/usr/bin/env python3
"""Offline installation fixtures only; no article or voice-profile generation."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from resolve_dependencies import resolve


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.skill = self.root / "x-article-pro"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text("---\nname: x-article-pro\n---\n", encoding="utf-8")
        self.lock = {"schema_version": 1, "entry": "x-article-pro", "dependencies": []}
        for name in ["aihot", "cover-editorial-collage"]:
            directory = self.root / name
            (directory / "agents").mkdir(parents=True)
            files = {"SKILL.md": f"---\nname: {name}\n---\n",
                     "LICENSE": "Synthetic license fixture\n",
                     "agents/openai.yaml": "policy:\n  allow_implicit_invocation: false\n"}
            hashes = {}
            for relative, text in files.items():
                path = directory / relative
                path.write_text(text, encoding="utf-8")
                hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.lock["dependencies"].append({"name": name, "directory": name,
                                               "files": hashes, "revision": "fixture"})
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        (self.skill / "dependencies.lock.json").write_text(json.dumps(self.lock), encoding="utf-8")

    def test_valid_installation_resolves_actual_entries(self):
        result = resolve(self.skill)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(len(result["dependencies"]), 2)
        for item in result["dependencies"]:
            self.assertTrue(Path(item["entry_path"]).is_file())
            self.assertEqual(item["checked_files"], 3)

    def test_missing_entry_fails(self):
        (self.root / "aihot" / "SKILL.md").unlink()
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_content_drift_fails(self):
        (self.root / "cover-editorial-collage" / "SKILL.md").write_text("changed", encoding="utf-8")
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_name_mismatch_fails_even_with_updated_hash(self):
        path = self.root / "aihot" / "SKILL.md"
        path.write_text("---\nname: another-skill\n---\n", encoding="utf-8")
        self.lock["dependencies"][0]["files"]["SKILL.md"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.save()
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_stage_checks_only_its_dependency(self):
        (self.root / "aihot" / "SKILL.md").unlink()
        result = resolve(self.skill, stage="cover")
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual([item["name"] for item in result["dependencies"]], ["cover-editorial-collage"])

    def test_directory_traversal_fails(self):
        self.lock["dependencies"][0]["directory"] = "../elsewhere"
        self.save()
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_file_traversal_fails(self):
        self.lock["dependencies"][0]["files"]["../SKILL.md"] = "0" * 64
        self.save()
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_windows_absolute_path_fails(self):
        self.lock["dependencies"][0]["files"]["C:/outside.txt"] = "0" * 64
        self.save()
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_missing_license_manifest_fails(self):
        del self.lock["dependencies"][0]["files"]["LICENSE"]
        self.save()
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_duplicate_dependency_fails(self):
        self.lock["dependencies"].append(self.lock["dependencies"][0])
        self.save()
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_omitted_dependency_fails(self):
        self.lock["dependencies"].pop()
        self.save()
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_invalid_json_fails(self):
        (self.skill / "dependencies.lock.json").write_text("{", encoding="utf-8")
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_non_object_lock_fails(self):
        (self.skill / "dependencies.lock.json").write_text("[]", encoding="utf-8")
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_non_list_dependency_records_fail(self):
        self.lock["dependencies"] = {"aihot": {}}
        self.save()
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_unknown_stage_fails(self):
        self.assertEqual(resolve(self.skill, stage="invalid")["status"], "FAIL")

    def test_explicit_skills_root_is_supported(self):
        result = resolve(self.skill, skills_root=self.root, stage="discovery")
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["dependencies"][0]["name"], "aihot")

    def test_ui_policy_drift_fails(self):
        (self.root / "aihot" / "agents" / "openai.yaml").write_text(
            "policy:\n  allow_implicit_invocation: true\n", encoding="utf-8")
        self.assertEqual(resolve(self.skill)["status"], "FAIL")

    def test_cover_stage_resolves_only_the_requested_cover_skill(self):
        (self.root / "aihot" / "SKILL.md").unlink()
        result = resolve(self.skill, stage="cover")
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual([item["name"] for item in result["dependencies"]], ["cover-editorial-collage"])

    def test_missing_cover_has_no_alternative(self):
        (self.root / "cover-editorial-collage" / "SKILL.md").unlink()
        result = resolve(self.skill, stage="cover")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual([item["name"] for item in result["dependencies"]], ["cover-editorial-collage"])

    def test_changed_cover_source_fails(self):
        (self.root / "cover-editorial-collage" / "SKILL.md").write_text("different", encoding="utf-8")
        self.assertEqual(resolve(self.skill, stage="cover")["status"], "FAIL")

    def test_old_writing_stages_are_not_active(self):
        for stage in ("planning", "drafting", "review", "editing"):
            self.assertEqual(resolve(self.skill, stage=stage)["status"], "FAIL")

    def test_retired_pins_are_not_checked_or_loaded(self):
        self.lock["retired_dependencies"] = [{"name": "human-writing", "directory": "missing-history"}]
        self.save()
        result = resolve(self.skill)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual({d["name"] for d in result["dependencies"]}, {"aihot", "cover-editorial-collage"})

    def test_original_repository_cannot_relax_license_check_by_switching_pin_kind(self):
        self.lock["dependencies"][0]["pin_kind"] = "installed-snapshot"
        del self.lock["dependencies"][0]["files"]["LICENSE"]
        self.save()
        self.assertEqual(resolve(self.skill)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
