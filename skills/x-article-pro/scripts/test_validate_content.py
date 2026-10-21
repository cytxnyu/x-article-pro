#!/usr/bin/env python3
"""Synthetic record fixtures only, NOT actual use of the two editorial skills."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from validate_content import REPORT, bind, prepare, validate


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def synthetic_content_review(article):
    """TEST ONLY: construct structure fixtures, never approve real editorial work."""
    record = prepare(article)
    texts = {n: (article / n).read_text(encoding="utf-8-sig") for n in ("title.txt", "body.txt", "caption.txt")}
    body = texts["body.txt"].strip()
    first = body.split("\n\n", 1)[0]
    record["planning"].update(
        full_picture="合成夹具描述一次更新，仅用于检验记录结构。",
        reader_question="这项合成更新的记录能否绑定到当前正文？",
        added_value="夹具用正文锚点验证字段是否存在，不声称具有真实阅读价值。",
        structure="合成正文先写更新再注明测试条件。",
        coverage=[{"question": "夹具记录了什么更新？", "finding": "测试声明的来源使用 example.test。",
                   "decision": "included", "claim_indices": [0], "reason": "检验 evidence 引用及记录绑定。"}])
    record["review"].update(
        opening={"title_quote": texts["title.txt"].strip(), "caption_quote": texts["caption.txt"].strip(),
                 "body_quote": first, "expectation": "合成入口承诺描述一项测试更新。",
                 "readers": "仅供软件测试执行者检查字段，不作真实受众推断。"},
        payoffs=[{"quote": first, "why_it_matters": "测试夹具引用当前首段，以验证锚点变化可被发现。", "claim_indices": [0]}],
        findings=[], conclusion="合成结构占位，不是 dbs-content-value 的实际编辑评审。")
    record.update(status="reviewed", final_read="合成夹具已绑定当前文件；这段测试数据不是内容质量评审。")
    write_json(article / REPORT, record)
    return record


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name, text in {
            "title.txt": "合成测试更新",
            "body.txt": "机构在测试版本增加了本地导出。\n\n导出保留图注，测试中仍需人工核对图片。",
            "caption.txt": "合成版本新增本地导出，图注能否完整保存？",
            "article.html": "<p>合成结构测试页面</p>",
        }.items():
            (self.root / name).write_text(text, encoding="utf-8")
        write_json(self.root / "evidence.json", {"claims": [{"claim": "测试版本增加了本地导出", "status": "verified",
                                                            "source_url": "https://example.test/release"}]})
        self.record = synthetic_content_review(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        write_json(self.root / REPORT, self.record)

    def fail(self, fragment=None):
        result = validate(self.root)
        self.assertFalse(result["valid"], result)
        if fragment:
            self.assertTrue(any(fragment in e for e in result["errors"]), result["errors"])

    def test_complete_synthetic_record_passes_read_only(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertTrue(validate(self.root)["valid"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_missing_report_fails(self):
        (self.root / REPORT).unlink()
        self.fail(REPORT)

    def test_prepare_does_not_approve(self):
        self.record = prepare(self.root)
        self.save()
        self.assertEqual(self.record["status"], "pending")
        self.fail("not reviewed")

    def test_prepare_before_draft_is_supported(self):
        empty = self.root / "not-yet-written"
        empty.mkdir()
        record = prepare(empty)
        self.assertEqual(record["status"], "pending")
        self.assertTrue(all(v is None for v in record["hashes"].values()))

    def test_each_final_file_change_is_stale(self):
        for name in self.record["hashes"]:
            with self.subTest(name=name):
                p = self.root / name
                original = p.read_bytes()
                p.write_bytes(original + b" ")
                self.fail("SHA256")
                p.write_bytes(original)

    def test_missing_and_wrong_skill_receipts_fail(self):
        for stage in ("planning", "review"):
            for key, value in (("skill", "human-writing"), ("skill_sha256", "0" * 64)):
                with self.subTest(stage=stage, key=key):
                    original = self.record[stage][key]
                    self.record[stage][key] = value
                    self.save()
                    self.fail("expected locked")
                    self.record[stage][key] = original

    def test_planning_fields_are_required(self):
        for field in ("full_picture", "reader_question", "added_value", "structure"):
            original = self.record["planning"][field]
            self.record["planning"][field] = "PASS"
            self.save()
            self.fail(field)
            self.record["planning"][field] = original

    def test_blanket_pass_is_not_review(self):
        for target in (self.record["review"], self.record):
            key = "conclusion" if target is self.record["review"] else "final_read"
            target[key] = "通过。"
        self.save()
        self.fail("specific judgment")

    def test_opening_quotes_bind_the_actual_entry(self):
        for key in ("title_quote", "caption_quote", "body_quote"):
            original = self.record["review"]["opening"][key]
            self.record["review"]["opening"][key] = "不是当前开头"
            self.save()
            self.fail(key)
            self.record["review"]["opening"][key] = original

    def test_late_paragraph_cannot_substitute_for_opening(self):
        self.record["review"]["opening"]["body_quote"] = "导出保留图注，测试中仍需人工核对图片。"
        self.save()
        self.fail("body_quote")

    def test_missing_payoff_fails(self):
        self.record["review"]["payoffs"] = []
        self.save()
        self.fail("payoffs")

    def test_payoff_requires_real_body_quote(self):
        self.record["review"]["payoffs"][0]["quote"] = "虚构的演示过程"
        self.save()
        self.fail("quote")

    def test_payoff_requires_explanation(self):
        self.record["review"]["payoffs"][0]["why_it_matters"] = "很好"
        self.save()
        self.fail("why_it_matters")

    def test_duplicate_payoffs_fail(self):
        self.record["review"]["payoffs"].append(copy.deepcopy(self.record["review"]["payoffs"][0]))
        self.save()
        self.fail("duplicate payoff")

    def test_invalid_claim_indices_fail_without_crash(self):
        for value in ([], [1], [-1], [True], ["0"], [{}], [0, 0], "0"):
            self.record["review"]["payoffs"][0]["claim_indices"] = value
            self.save()
            self.fail("claim")

    def test_unverified_claim_is_not_value_evidence(self):
        write_json(self.root / "evidence.json", {"claims": [{"claim": "未知结果", "status": "unverified",
                                                            "source_url": "https://example.test/unknown"}]})
        self.record = bind(self.root)
        self.record.update(status="reviewed", final_read="合成测试重新绑定，但证据依然未核对。")
        self.save()
        self.fail("not a verified")

    def test_unknown_coverage_is_allowed_when_honest_and_not_only_material(self):
        self.record["planning"]["coverage"].append({"question": "是否公开全部演示过程？",
            "finding": "夹具不包含该过程。", "decision": "unavailable", "claim_indices": [],
            "reason": "保留未知，正文没有编造过程。"})
        self.save()
        self.assertTrue(validate(self.root)["valid"])

    def test_only_unknown_material_cannot_be_ready(self):
        self.record["planning"]["coverage"][0].update(decision="unavailable", claim_indices=[])
        self.save()
        self.fail("actually included")

    def test_unknown_coverage_still_needs_specific_reason(self):
        self.record["planning"]["coverage"].append({"question": "过程是否公开？", "finding": "尚未知。",
            "decision": "unavailable", "claim_indices": [], "reason": ""})
        self.save()
        self.fail("reason")

    def test_unresolved_findings_fail(self):
        self.record["review"]["findings"] = [{"problem": "标题承诺缺少正文支撑。", "action": "等待补充来源。",
            "result_quote": "机构在测试版本增加了本地导出。", "status": "open"}]
        self.save()
        self.fail("unresolved")

    def test_resolved_finding_requires_current_result_quote(self):
        self.record["review"]["findings"] = [{"problem": "旧标题夸大了导出能力。", "action": "标题改为当前版本事实。",
            "result_quote": "旧标题已不存在", "status": "resolved"}]
        self.save()
        self.fail("result_quote")

    def test_bind_preserves_work_and_resets_approval(self):
        result = bind(self.root)
        self.assertEqual(result["planning"], self.record["planning"])
        self.assertEqual(result["review"], self.record["review"])
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["final_read"], "")
        self.record = result
        self.save()
        self.fail("not reviewed")

    def test_malformed_records_fail_without_exception(self):
        for record in ([], None, {"schema_version": True}, {"planning": [], "review": "PASS"}):
            write_json(self.root / REPORT, record)
            self.fail()

    def test_malformed_nested_records_fail_without_exception(self):
        for stage, key in (("planning", "coverage"), ("review", "payoffs"), ("review", "findings")):
            original = self.record[stage][key]
            self.record[stage][key] = [None, [], "PASS"]
            self.save()
            self.fail()
            self.record[stage][key] = original

    def test_cli_prepare_refuses_overwrite(self):
        before = (self.root / REPORT).read_bytes()
        p = self.cli("--prepare")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(before, (self.root / REPORT).read_bytes())

    def test_cli_pending_exit_is_operation_success_not_approval(self):
        (self.root / REPORT).unlink()
        p = self.cli("--prepare")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["status"], "PENDING")
        p = self.cli()
        self.assertEqual(p.returncode, 1)
        self.assertEqual(json.loads(p.stdout)["status"], "FAIL")

    def test_cli_success_json(self):
        p = self.cli()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["status"], "PASS")

    def cli(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", "-B", str(Path(__file__).with_name("validate_content.py")),
                               str(self.root), *args, "--json"], capture_output=True, encoding="utf-8",
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1"))


if __name__ == "__main__":
    unittest.main()
