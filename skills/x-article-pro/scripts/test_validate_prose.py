#!/usr/bin/env python3
"""Synthetic offline regression tests. Approval fixtures are test data ONLY."""
import copy
from html import escape
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from validate_prose import REPORT, prepare, scan, snapshot, split_units, validate


SCRIPT = Path(__file__).with_name("validate_prose.py")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def synthetic_review(article):
    """Not a reviewing tool: filled records exercise schema with synthetic text.

    Production code must NEVER import or use this function for actual articles.
    Integration regressions below deliberately bypass it after any mutation.
    """
    value = prepare(article)
    value["status"] = "reviewed"
    for row in value["units"]:
        row.update(decision="keep", role="fact", anchor=row["text"],
                   reason=f"合成夹具 {row['id']} 中的“{row['text']}”用于测试逐句记录绑定，不是真实编辑评语。")
    first = value["units"][0]
    for key, row in value["readthrough"].items():
        row.update(decision="reviewed", anchors=[first["id"]],
                   note=f"合成夹具 {key} 的句文锚点：“{first['text']}”；这里只测试通读记录字段。")
    write_json(Path(article) / REPORT, value)
    return value


class ProseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.write_article()

    def tearDown(self):
        self.temp.cleanup()

    def write_article(self, body="测试机构新增批量导出。\n\n管理员可以导出已选文件，测试不含网络请求。", extra=""):
        values = {"title": "测试机构新增批量导出", "body": body,
                  "caption": "测试机构开放导出入口，选择范围会影响结果。"}
        for field, text in values.items():
            (self.root / (field + ".txt")).write_text(text, encoding="utf-8")
        (self.root / "article.html").write_text(
            '<html><head><title>页面元数据</title></head><body><h1>' + values["title"]
            + '</h1><article id="article-body"><p>' + escape(body) + '</p>' + extra
            + '</article><section id="article-caption">' + values["caption"]
            + '</section></body></html>', encoding="utf-8")

    def approve(self):
        return synthetic_review(self.root)

    def edit(self, mutate):
        path = self.root / REPORT
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        write_json(path, value)

    def fail(self, fragment):
        result = validate(self.root)
        self.assertFalse(result["valid"], result)
        self.assertTrue(any(fragment in error for error in result["errors"]), result)

    def test_missing_report_fails(self):
        self.fail(REPORT)

    def test_prepare_is_pending_not_an_approval(self):
        write_json(self.root / REPORT, prepare(self.root))
        self.fail("未完成")

    def test_complete_synthetic_record_passes(self):
        self.approve()
        self.assertTrue(validate(self.root)["valid"])

    def test_all_three_prior_failures_are_blocked_even_with_keep(self):
        for body in ("这里最让人想试的，是需求可以提到多大。", "这个区别放进编程任务里就很好理解。", "官方模型卡里也有个很容易略过的细节。"):
            with self.subTest(body=body):
                self.write_article(body)
                self.approve()
                self.fail("已知套话")

    def test_wording_variants_are_flagged(self):
        for body in ("这一差异。这个区别放到任务里便很好理解。", "这次最让人在意的是流程。", "模型卡还写了很容易忽略的细节。", "真正有意思的地方在于改变。"):
            with self.subTest(body=body):
                self.assertTrue(scan(body))

    def test_necessary_contrast_and_technical_values_are_not_banned(self):
        self.write_article("新增的不是模型接口，而是导出入口。版本 v1.2 的上限是 3.5 MB。命令为 `export --format json`。")
        self.approve()
        self.assertTrue(validate(self.root)["valid"])

    def test_post_audit_changes_to_each_file_fail_hash(self):
        for name in ("title.txt", "body.txt", "caption.txt", "article.html"):
            with self.subTest(name=name):
                self.write_article()
                self.approve()
                path = self.root / name
                path.write_text(path.read_text(encoding="utf-8") + "\n新增句子。", encoding="utf-8")
                self.fail("SHA256")

    def test_forged_hash_does_not_fix_stale_units(self):
        self.approve()
        self.write_article("测试机构删除导出入口。")
        self.edit(lambda value: value.update(files=snapshot(self.root)[0]))
        self.fail("覆盖")

    def test_missing_duplicate_or_reordered_units_fail(self):
        for mutate in (lambda v: v["units"].pop(), lambda v: v["units"].append(v["units"][0]), lambda v: v["units"].reverse()):
            with self.subTest(mutate=mutate):
                self.approve()
                self.edit(mutate)
                self.fail("覆盖")

    def test_erased_flags_fail(self):
        self.write_article("这里最让人想试的，是导出范围。")
        self.approve()
        self.edit(lambda value: [row.update(flags=[]) for row in value["units"]])
        self.fail("flags")

    def test_pending_rewrite_and_delete_are_not_completion(self):
        for decision in ("pending", "rewrite", "delete", "approved", True):
            self.approve()
            self.edit(lambda value: value["units"][0].update(decision=decision))
            self.fail("未完成决定")

    def test_global_pass_cannot_replace_sentences(self):
        self.approve()
        self.edit(lambda value: value.update(units=[], status="reviewed"))
        self.fail("覆盖")

    def test_generic_reason_and_wrong_anchor_fail(self):
        for changes in ({"reason": "通过"}, {"anchor": "另一篇文章"}, {"role": []}):
            self.approve()
            self.edit(lambda value: value["units"][0].update(changes))
            self.assertFalse(validate(self.root)["valid"])

    def test_bulk_identical_reasons_fail(self):
        self.approve()
        self.edit(lambda value: [row.update(anchor="测试", reason="测试只是统一盖章句，没有逐句解释。") for row in value["units"]])
        self.fail("批量盖章")

    def test_readthrough_is_required_and_bound(self):
        for changes in ({"decision": "pending"}, {"anchors": ["absent:1"]}, {"note": "通过"}):
            self.approve()
            self.edit(lambda value: value["readthrough"]["naturalness"].update(changes))
            self.fail("readthrough.naturalness")

    def test_unresolved_issue_fails(self):
        self.approve()
        self.edit(lambda value: value["issues"].append({"status": "open"}))
        self.fail("未解决")

    def test_fake_rewrite_and_fake_deletion_fail(self):
        for issue in (
            {"action": "rewrite", "before": "原来的导读句。", "after": "未写入的修改。"},
            {"action": "delete", "before": "测试机构新增批量导出。", "after": ""},
        ):
            self.approve()
            self.edit(lambda value: value["issues"].append(dict(issue, field="body", category="empty_preface", status="resolved", reason="删除导读前缀，直接写导出动作。")))
            self.fail("未落实")

    def test_actual_rewrite_and_deletion_records_pass(self):
        self.approve()
        self.edit(lambda value: value["issues"].extend([
            {"field": "body", "category": "empty_preface", "status": "resolved", "action": "rewrite", "before": "先说结论，测试机构新增批量导出。", "after": "测试机构新增批量导出。", "reason": "移除导读，保留更新事实。"},
            {"field": "body", "category": "repetition", "status": "resolved", "action": "delete", "before": "重复说明导出这件事情。", "after": "", "reason": "前句已经交代导出动作，此句没有新信息。"}]))
        self.assertTrue(validate(self.root)["valid"])

    def test_html_text_mismatch_fails_even_with_fresh_review(self):
        path = self.root / "body.txt"
        path.write_text("另一份正文。", encoding="utf-8")
        self.approve()
        self.fail("HTML body")

    def test_html_title_mismatch_fails(self):
        (self.root / "title.txt").write_text("另一个标题", encoding="utf-8")
        self.approve()
        self.fail("HTML title")

    def test_extra_figcaption_is_audited_without_body_mismatch(self):
        self.write_article(extra='<figure><img src="x.png" alt="导出按钮"><figcaption>图注描述导出按钮。</figcaption></figure>')
        value = self.approve()
        self.assertTrue(any(row["text"] == "图注描述导出按钮。" for row in value["units"]))
        self.assertTrue(any(row["text"] == "导出按钮" for row in value["units"]))
        self.assertTrue(validate(self.root)["valid"])

    def test_bad_phrase_in_figcaption_or_alt_also_fails(self):
        for extra in ('<figcaption>这里最让人想试的，是导出范围。</figcaption>', '<img src="x.png" alt="这里最让人想试的，是导出范围。">'):
            self.write_article(extra=extra)
            self.approve()
            self.fail("已知套话")

    def test_inline_markup_does_not_hide_bad_phrase(self):
        self.write_article("这里最让人想试的，是导出范围。")
        path = self.root / "article.html"
        path.write_text(path.read_text(encoding="utf-8").replace("这里最让人", "这里<strong>最让</strong>人"), encoding="utf-8")
        self.approve()
        self.fail("已知套话")

    def test_quoted_wording_exception_requires_real_markers_and_context(self):
        phrase = "这里最让人想试的，是导出范围"
        self.write_article(f"编辑删去了“{phrase}”这句导读。")
        value = self.approve()
        row = next(row for row in value["units"] if row["flags"])
        row["exceptions"] = [{"rule": "abstract_judgment", "basis": "discussed_wording", "protected_text": phrase, "context": "新闻在讨论删除导读的编辑动作，不在用这句包装产品。", "reason": "保留被删除的原句，读者才知道编辑改了什么。"}]
        write_json(self.root / REPORT, value)
        self.assertTrue(validate(self.root)["valid"], validate(self.root))
        row["exceptions"][0]["basis"] = "sounds_natural"
        write_json(self.root / REPORT, value)
        self.fail("例外仅限")

    def test_bare_waiver_does_not_rescue_ordinary_prose(self):
        self.write_article("这里最让人想试的，是导出范围。")
        value = self.approve()
        row = next(row for row in value["units"] if row["flags"])
        row["exceptions"] = [{"rule": "abstract_judgment", "basis": "quotation", "protected_text": row["text"], "source": "内部测试引语", "context": "测试引语的语境", "reason": "测试原话保留规则"}]
        write_json(self.root / REPORT, value)
        self.fail("引号或代码")

    def test_one_quote_cannot_waive_another_unquoted_hit(self):
        phrase = "这里最让人想试的，是导出范围"
        self.write_article(f"编辑说“{phrase}”，而{phrase}。")
        value = self.approve()
        row = next(row for row in value["units"] if row["flags"])
        row["exceptions"] = [{"rule": "abstract_judgment", "basis": "discussed_wording", "protected_text": phrase, "context": "合成测试引用语境", "reason": "合成测试保护原措辞"}]
        write_json(self.root / REPORT, value)
        self.fail("未被引语")

    def test_splitter_covers_headings_numbers_urls_and_unpunctuated_tail(self):
        text = "标题\n版本 v1.2 为 3.5 MB。\nhttps://example.test/a.b\n没有句号的尾行"
        units = list(split_units(text))
        self.assertEqual("".join(part for part in text if not part.isspace()), "".join(part for _, _, unit in units for part in unit if not part.isspace()))
        self.assertTrue(any("3.5" in unit for _, _, unit in units))
        self.assertTrue(any("example.test" in unit for _, _, unit in units))

    def test_malformed_schema_reports_failure_not_crash(self):
        for mutate in (lambda v: v.update(schema_version=True), lambda v: v.update(units=[None]), lambda v: v.update(issues=[[]]), lambda v: v["units"][0].update(exceptions=[{"rule": []}]), lambda v: v.update(readthrough=[])):
            self.approve()
            self.edit(mutate)
            self.assertFalse(validate(self.root)["valid"])

    def test_validation_is_read_only(self):
        self.approve()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        validate(self.root)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_cli_prepare_does_not_overwrite_and_check_returns_one(self):
        cmd = [sys.executable, "-X", "utf8", "-B", str(SCRIPT), str(self.root)]
        result = subprocess.run(cmd + ["--prepare"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0)
        self.assertIn("PENDING", result.stdout)
        before = (self.root / REPORT).read_bytes()
        result = subprocess.run(cmd + ["--prepare"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(before, (self.root / REPORT).read_bytes())
        result = subprocess.run(cmd + ["--json"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
