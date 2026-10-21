#!/usr/bin/env python3
"""Synthetic, offline fixtures; no real reporting, source images, or publication."""

import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from validate_delivery import Validator
from test_validate_prose import synthetic_review
from test_validate_content import synthetic_content_review


SCRIPT = Path(__file__).with_name("validate_delivery.py")


def png_1x1():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x80\x00")) + chunk(b"IEND", b""))


def synthetic_cover(width, height, seed):
    """Actual PNG pixels, used only for offline structure tests, not real covers."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    row = b"\x00" + bytes((seed % 256, 128, 220)) * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "run"
        self.root.mkdir()
        self.manifest = None

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, count=2, requested_count=None):
        self.manifest = {"requested_count": count if requested_count is None else requested_count, "items": []}
        for rank in range(1, count + 1):
            article_dir = f"{rank:02d}-synthetic-news"
            article = self.root / article_dir
            (article / "images").mkdir(parents=True)
            title = f"合成测试新闻 {rank}"
            (article / "title.txt").write_text(title, encoding="utf-8")
            (article / "body.txt").write_text(f"\ufeff  今日AI快讯：这是第 {rank} 条合成测试。\n\n来源：https://example.test/news/{rank}\n", encoding="utf-8")
            (article / "images" / "cover.png").write_bytes(png_1x1())
            (article / "article.html").write_text(f'<!doctype html><html><body><h1>{title}</h1><p>第 {rank} 条</p><img src="images/cover.png" alt="合成测试图"></body></html>', encoding="utf-8")
            evidence = {
                "claims": [{"claim": f"第 {rank} 条测试声明", "source_url": f"https://example.test/news/{rank}",
                            "source_date": "2026-10-06", "status": "verified"}],
                "images": [{"path": "images/cover.png", "kind": "official_image",
                            "source_url": f"https://example.test/assets/{rank}.png", "caption": "合成结构测试图；非真实新闻素材"}],
            }
            write_json(article / "evidence.json", evidence)
            self.manifest["items"].append({"rank": rank, "title": title, "source_url": f"https://example.test/news/{rank}",
                                           "status": "ready", "article_dir": article_dir, "issues": []})
        self.save_manifest()
        return self.root / self.manifest["items"][0]["article_dir"] if count else self.root

    def save_manifest(self):
        write_json(self.root / "manifest.json", self.manifest)

    def edit_evidence(self, article, mutate):
        path = article / "evidence.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        write_json(path, value)

    def validate(self):
        # Original structure regressions use synthetic, freshly bound records.
        # Strict-gate integration tests below call Validator directly instead.
        if self.manifest and self.manifest.get("delivery_version") == 2:
            for item in self.manifest.get("items", []):
                if isinstance(item, dict) and isinstance(item.get("article_dir"), str):
                    article = (self.root / item["article_dir"]).resolve()
                    if article.is_relative_to(self.root.resolve()):
                        try:
                            synthetic_review(article)
                            synthetic_content_review(article)
                        except (OSError, ValueError, UnicodeError):
                            pass  # malformed fixtures should be rejected by the validator
        return Validator(self.root, legacy_structure=True).validate()

    def assert_pass(self):
        result = self.validate()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["status"], "PASS")
        return result

    def assert_fail(self, fragment=None):
        result = self.validate()
        self.assertFalse(result["valid"], result)
        self.assertEqual(result["status"], "FAIL")
        if fragment:
            self.assertTrue(any(fragment in issue for issue in result["errors"]), result["errors"])
        return result

    def test_two_independent_articles_pass(self):
        self.fixture(2)
        result = self.assert_pass()
        self.assertEqual(result["summary"]["checked_articles"], 2)

    def test_ten_independent_articles_pass(self):
        self.fixture(10)
        self.assertEqual(self.assert_pass()["summary"]["checked_articles"], 10)

    def test_ten_items_combined_into_one_directory_fail(self):
        self.fixture(10)
        for item in self.manifest["items"]:
            item["article_dir"] = self.manifest["items"][0]["article_dir"]
        self.save_manifest()
        self.assert_fail("碰撞")

    def test_shared_directory_alias_fails(self):
        self.fixture(2)
        self.manifest["items"][1]["article_dir"] = "./" + self.manifest["items"][0]["article_dir"]
        self.save_manifest()
        self.assert_fail("碰撞")

    def test_duplicate_body_in_separate_directories_fails(self):
        article = self.fixture(2)
        second = self.root / self.manifest["items"][1]["article_dir"]
        (second / "body.txt").write_bytes((article / "body.txt").read_bytes())
        self.assert_fail("完全重复")

    def test_missing_image_fails(self):
        article = self.fixture()
        (article / "images" / "cover.png").unlink()
        self.assert_fail("图片文件不存在")

    def test_empty_image_fails(self):
        article = self.fixture()
        (article / "images" / "cover.png").write_bytes(b"")
        self.assert_fail("图片文件不存在")

    def test_wrong_opening_fails(self):
        article = self.fixture()
        (article / "body.txt").write_text("今日 AI 快讯：多了空格。", encoding="utf-8")
        self.assert_fail("必须以")

    def test_article_path_escape_fails(self):
        self.fixture()
        self.manifest["items"][0]["article_dir"] = "../outside"
        self.save_manifest()
        self.assert_fail("越出")

    def test_image_path_escape_fails_even_when_file_exists(self):
        article = self.fixture()
        (self.root / "outside.png").write_bytes(png_1x1())
        self.edit_evidence(article, lambda value: value["images"][0].update(path="../outside.png"))
        self.assert_fail("越出")

    def test_html_image_path_escape_fails(self):
        article = self.fixture()
        (article / "article.html").write_text('<img src="../../outside.png"><img src="images/cover.png">', encoding="utf-8")
        self.assert_fail("越出")

    def test_fewer_than_ten_is_incomplete(self):
        self.fixture(2, requested_count=10)
        self.assert_fail("要求 10")

    def test_one_combined_article_is_not_ten_articles(self):
        article = self.fixture(1, requested_count=10)
        (article / "body.txt").write_text("今日AI快讯：" + "\n".join(f"新闻 {rank}" for rank in range(1, 11)), encoding="utf-8")
        self.assert_fail("要求 10")

    def test_unverified_claim_fails(self):
        article = self.fixture()
        self.edit_evidence(article, lambda value: value["claims"][0].update(status="unverified"))
        self.assert_fail("未核实")

    def test_verified_plus_unverified_claim_still_fails(self):
        article = self.fixture()
        self.edit_evidence(article, lambda value: value["claims"].append({"claim": "尚未核实的额外声明", "source_url": "https://example.test/extra", "source_date": "2026-10-06", "status": "unverified"}))
        self.assert_fail("未核实")

    def test_verified_label_without_source_is_insufficient(self):
        article = self.fixture()
        self.edit_evidence(article, lambda value: value["claims"][0].update(source_url=None))
        self.assert_fail("缺少字段完整")

    def test_unknown_source_date_is_warning_not_invented(self):
        article = self.fixture()
        self.edit_evidence(article, lambda value: value["claims"][0].update(source_date=None))
        result = self.assert_pass()
        self.assertTrue(any("日期未知" in issue for issue in result["warnings"]))

    def test_invalid_source_date_fails(self):
        article = self.fixture()
        self.edit_evidence(article, lambda value: value["claims"][0].update(source_date="2026-02-30"))
        self.assert_fail("source_date 必须")

    def test_missing_source_date_field_fails(self):
        article = self.fixture()
        self.edit_evidence(article, lambda value: value["claims"][0].pop("source_date"))
        self.assert_fail("source_date 必须")

    def test_only_ai_image_fails(self):
        article = self.fixture()
        self.edit_evidence(article, lambda value: value["images"][0].update(kind="ai_illustration", source_url=None, caption="AI生成示意图"))
        self.assert_fail("真实来源图")

    def add_ai_image(self, article, caption):
        (article / "images" / "ai.png").write_bytes(png_1x1())
        with (article / "article.html").open("a", encoding="utf-8") as handle:
            handle.write(f'<figure><img src="images/ai.png"><figcaption>{caption}</figcaption></figure>')
        self.edit_evidence(article, lambda value: value["images"].append({"path": "images/ai.png", "kind": "ai_illustration", "source_url": None, "caption": caption}))

    def test_ai_image_without_label_fails(self):
        article = self.fixture()
        self.add_ai_image(article, "好看的示意图")
        self.assert_fail("AI生成示意图")

    def test_labeled_ai_image_plus_real_image_passes(self):
        article = self.fixture()
        self.add_ai_image(article, "AI生成示意图，仅作说明")
        self.assert_pass()

    def test_ai_caption_with_space_passes(self):
        article = self.fixture()
        self.add_ai_image(article, "AI 生成示意图，仅作说明")
        self.assert_pass()

    def test_ai_label_only_in_evidence_is_insufficient(self):
        article = self.fixture()
        self.add_ai_image(article, "AI 生成示意图")
        (article / "article.html").write_text('<img src="images/cover.png"><img src="images/ai.png" alt="AI 生成示意图">', encoding="utf-8")
        self.assert_fail("正文图注")

    def test_ai_label_in_script_does_not_count(self):
        article = self.fixture()
        self.add_ai_image(article, "AI 生成示意图")
        (article / "article.html").write_text('<img src="images/cover.png"><img src="images/ai.png"><script>const label = "AI 生成示意图";</script>', encoding="utf-8")
        self.assert_fail("正文图注")

    def test_invalid_kind_type_reports_failure_not_traceback(self):
        article = self.fixture()
        self.edit_evidence(article, lambda value: value["images"][0].update(kind=[]))
        self.assert_fail("kind 必须为字符串")

    def test_source_link_at_end_is_allowed(self):
        article = self.fixture()
        (article / "body.txt").write_text("今日AI快讯：合成测试内容。\n\n来源：https://example.test/official", encoding="utf-8")
        result = self.assert_pass()
        self.assertEqual(result["warnings"], [])

    def test_more_than_two_links_and_repetition_are_warnings(self):
        article = self.fixture()
        (article / "body.txt").write_text("今日AI快讯：测试。\nhttps://example.test/a\nhttps://example.test/b\nhttps://example.test/c\nhttps://example.test/a", encoding="utf-8")
        warnings = self.assert_pass()["warnings"]
        self.assertTrue(any("3 个去重外链" in value for value in warnings))
        self.assertTrue(any("重复出现" in value for value in warnings))

    def test_two_source_links_are_allowed(self):
        article = self.fixture()
        (article / "body.txt").write_text("今日AI快讯：测试。\n来源：https://example.test/a\n参考：https://example.test/b", encoding="utf-8")
        self.assertEqual(self.assert_pass()["warnings"], [])

    def test_absolute_html_image_reference_passes(self):
        article = self.fixture()
        path = article / "images" / "cover.png"
        (article / "article.html").write_text(f'<img src="{path}">', encoding="utf-8")
        self.assert_pass()

    def test_file_uri_reference_and_evidence_path_pass(self):
        article = self.fixture()
        uri = (article / "images" / "cover.png").as_uri()
        (article / "article.html").write_text(f'<img src="{uri}">', encoding="utf-8")
        self.edit_evidence(article, lambda value: value["images"][0].update(path=uri))
        self.assert_pass()

    def test_base64_html_image_fails(self):
        article = self.fixture()
        with (article / "article.html").open("a", encoding="utf-8") as handle:
            handle.write('<img src="data:image/png;base64,AAAA">')
        self.assert_fail("base64")

    def test_image_not_referenced_in_html_fails(self):
        article = self.fixture()
        (article / "article.html").write_text("<p>没有引用图像文件。</p>", encoding="utf-8")
        self.assert_fail("未在 article.html")

    def test_incomplete_item_fails_without_deleting_anything(self):
        self.fixture()
        self.manifest["items"][0]["status"] = "incomplete"
        self.manifest["items"][0]["issues"] = ["尚未取得官方图"]
        self.save_manifest()
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assert_fail("并非 ready")
        after = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_duplicate_rank_fails(self):
        self.fixture()
        self.manifest["items"][1]["rank"] = 1
        self.save_manifest()
        self.assert_fail("唯一且连续")

    def test_missing_title_body_or_html_fails(self):
        for filename in ("title.txt", "body.txt", "article.html"):
            with self.subTest(filename=filename):
                if self.manifest is None:
                    article = self.fixture()
                path = article / filename
                old = path.read_bytes()
                path.write_bytes(b"")
                self.assert_fail("文件内容为空")
                path.write_bytes(old)

    def test_invalid_manifest_json_fails(self):
        (self.root / "manifest.json").write_text("{bad json", encoding="utf-8")
        self.assert_fail("JSON 读取失败")

    def test_cli_text_success_ends_pass_and_exit_zero(self):
        self.fixture()
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(self.root), "--legacy-structure"], capture_output=True, encoding="utf-8", env=self.cli_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "PASS")
        self.assertIn("v1 仅历史结构", result.stdout)

    def test_cli_json_failure_exit_one_and_valid_json(self):
        self.fixture(2, requested_count=10)
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(self.root), "--json"], capture_output=True, encoding="utf-8", env=self.cli_env())
        self.assertEqual(result.returncode, 1, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "FAIL")
        self.assertFalse(value["valid"])

    def test_cli_text_failure_ends_fail_and_exit_one(self):
        self.fixture(2, requested_count=10)
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(self.root)], capture_output=True, encoding="utf-8", env=self.cli_env())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "FAIL")

    def test_cli_json_success_exit_zero_and_valid_json(self):
        self.fixture(10)
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--json", str(self.root), "--legacy-structure"], capture_output=True, encoding="utf-8", env=self.cli_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "PASS")
        self.assertEqual(value["summary"]["checked_articles"], 10)

    def add_covers(self, width=500, height=200, name="ai-header.png"):
        self.manifest["cover_required"] = True
        for item in self.manifest["items"]:
            article = self.root / item["article_dir"]
            local_path = "images/" + name
            (article / local_path).write_bytes(synthetic_cover(width, height, item["rank"]))
            item["cover_path"] = local_path
            metadata = {"path": local_path, "kind": "ai_illustration", "role": "x_header",
                        "width": width, "height": height, "alt": "合成测试概念封面，非官方截图",
                        "caption": "AI 生成示意图：合成结构测试", "prompt": f"第 {item['rank']} 篇合成测试，非真实生成"}
            write_json(article / "cover.json", metadata)
            self.edit_evidence(article, lambda value: value["images"].append(
                {"path": local_path, "kind": "ai_illustration", "source_url": None,
                 "caption": "AI 生成示意图：合成结构测试"}))
            path = article / "article.html"
            content = path.read_text(encoding="utf-8")
            path.write_text(content.replace("<body>", f'<body><figure><img src="{local_path}" alt="测试封面"><figcaption>AI 生成示意图</figcaption></figure>', 1), encoding="utf-8")
        self.save_manifest()

    def edit_cover(self, article, mutate):
        path = article / "cover.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        write_json(path, value)

    def test_ten_unique_five_two_covers_pass(self):
        self.fixture(10)
        self.add_covers()
        result = self.assert_pass()
        self.assertEqual(result["summary"]["checked_covers"], 10)

    def test_preferred_2560_1024_cover_passes(self):
        self.fixture(1)
        self.add_covers(2560, 1024)
        self.assert_pass()

    def test_native_1983_793_rounding_passes_with_actual_metadata(self):
        self.fixture(1)
        self.add_covers(1983, 793)
        self.assert_pass()

    def test_one_pixel_rounding_boundary_passes(self):
        self.fixture(1)
        self.add_covers(501, 200)
        self.assert_pass()

    def test_over_one_pixel_rounding_fails(self):
        self.fixture(1)
        self.add_covers(502, 200)
        self.assert_fail("实际比例须为 5:2")

    def test_cover_filename_is_not_hardcoded(self):
        self.fixture(1)
        self.add_covers(name="custom-topic-header.png")
        self.assert_pass()

    def test_legacy_package_without_cover_flag_passes(self):
        self.fixture(2)
        result = self.assert_pass()
        self.assertFalse(result["summary"]["cover_required"])
        self.assertEqual(result["summary"]["checked_covers"], 0)

    def test_explicit_no_cover_is_respected(self):
        self.fixture(2)
        self.manifest["cover_required"] = False
        self.save_manifest()
        self.assert_pass()

    def test_cover_required_must_be_boolean(self):
        self.fixture(1)
        self.manifest["cover_required"] = "false"
        self.save_manifest()
        self.assert_fail("cover_required 必须为布尔值")

    def test_required_cover_path_missing_fails(self):
        self.fixture(2)
        self.manifest["cover_required"] = True
        self.save_manifest()
        self.assert_fail("cover_path")

    def test_tenth_cover_missing_does_not_pass_ten_articles(self):
        self.fixture(10)
        self.add_covers()
        tenth = self.root / self.manifest["items"][9]["article_dir"]
        (tenth / "images" / "ai-header.png").unlink()
        self.assert_fail("封面文件不存在")

    def test_non_image_cover_file_fails(self):
        article = self.fixture(1)
        self.add_covers()
        (article / "images" / "ai-header.png").write_text("not an image", encoding="utf-8")
        self.assert_fail("实际尺寸读取失败")

    def test_bad_actual_cover_ratio_fails_even_with_fake_metadata(self):
        article = self.fixture(1)
        self.add_covers(500, 300)
        self.edit_cover(article, lambda value: value.update(height=200))
        result = self.assert_fail("实际比例须")
        self.assertTrue(any("实际像素" in error for error in result["errors"]))

    def test_native_dimensions_cannot_be_claimed_as_requested_size(self):
        article = self.fixture(1)
        self.add_covers(1983, 793)
        self.edit_cover(article, lambda value: value.update(width=2560, height=1024))
        self.assert_fail("不是请求尺寸")

    def test_cover_metadata_fields_required(self):
        article = self.fixture(1)
        self.add_covers()
        original = (article / "cover.json").read_bytes()
        for field in ("prompt", "alt", "kind", "role", "caption", "path", "width", "height"):
            with self.subTest(field=field):
                (article / "cover.json").write_bytes(original)
                self.edit_cover(article, lambda value: value.pop(field))
                self.assert_fail()

    def test_cover_metadata_file_missing_fails(self):
        article = self.fixture(1)
        self.add_covers()
        (article / "cover.json").unlink()
        self.assert_fail("cover.json")

    def test_cover_metadata_path_must_match_manifest(self):
        article = self.fixture(1)
        self.add_covers()
        self.edit_cover(article, lambda value: value.update(path="images/cover.png"))
        self.assert_fail("不一致")

    def test_cover_path_outside_article_fails(self):
        self.fixture(2)
        self.add_covers()
        self.manifest["items"][1]["cover_path"] = "../" + self.manifest["items"][0]["article_dir"] + "/images/ai-header.png"
        self.save_manifest()
        self.assert_fail("越出")

    def test_duplicate_cover_bytes_in_separate_directories_fail(self):
        first = self.fixture(2)
        self.add_covers()
        second = self.root / self.manifest["items"][1]["article_dir"]
        (second / "images" / "ai-header.png").write_bytes((first / "images" / "ai-header.png").read_bytes())
        self.assert_fail("每篇需要独立封面")

    def test_cover_must_be_declared_ai_in_evidence(self):
        article = self.fixture(1)
        self.add_covers()
        self.edit_evidence(article, lambda value: value["images"].pop())
        self.assert_fail("evidence.images 必须")

    def test_cover_must_be_first_html_image(self):
        article = self.fixture(1)
        self.add_covers()
        (article / "article.html").write_text('<img src="images/cover.png"><img src="images/ai-header.png"><p>AI 生成示意图</p>', encoding="utf-8")
        self.assert_fail("第一张图")

    def test_ai_cover_does_not_replace_required_real_image(self):
        article = self.fixture(1)
        self.add_covers()
        self.edit_evidence(article, lambda value: value["images"].pop(0))
        self.assert_fail("真实来源图")

    def fixture_v2(self, count=1):
        article = self.fixture(count)
        self.manifest.update(delivery_version=2, body_links="omit")
        for item in self.manifest["items"]:
            current = self.root / item["article_dir"]
            body = f"机构发布了第 {item['rank']} 项测试更新。\n\n该结果来自内部测试，统计时间为 2026 年 10 月。"
            caption = f"我更关注第 {item['rank']} 项更新在真实任务中的表现，内部测试的提升还需要和实际交付区分。"
            (current / "body.txt").write_text(body, encoding="utf-8")
            (current / "caption.txt").write_text(caption, encoding="utf-8")
            (current / "article.html").write_text(
                '<html><body><h1>' + (current / "title.txt").read_text(encoding="utf-8") + '</h1><article id="article-body"><p>' + body
                + '</p><img src="images/cover.png"></article><section id="article-caption">'
                + caption + '</section></body></html>', encoding="utf-8")
        self.save_manifest()
        return article

    def add_grounded_covers(self):
        self.add_covers(name="news-header.png")
        for item in self.manifest["items"]:
            article = self.root / item["article_dir"]
            source = f"https://example.test/assets/{item['rank']}.png"
            self.edit_cover(article, lambda value: value.update(
                kind="editorial_composite", caption="编辑合成：真实素材的结构测试", ai_assisted=False,
                generator_skill="cover-editorial-collage", prompt="合成测试：指定 Skill 的 5:2 编辑拼贴提示词",
                event_connection="主体是这项更新的产品界面，细节突出此次改动",
                design_notes="保留真实界面，使用对比色突出变化",
                source_assets=[{"path": "images/cover.png", "source_url": source, "usage": "产品界面主体"}]))
            self.edit_evidence(article, lambda value: value["images"][-1].update(
                kind="editorial_composite", caption="编辑合成：真实素材的结构测试"))
            path = article / "article.html"
            path.write_text(path.read_text(encoding="utf-8").replace("AI 生成示意图", "编辑合成"), encoding="utf-8")

    def test_v2_clean_body_independent_caption_and_grounded_cover_pass(self):
        self.fixture_v2()
        self.add_grounded_covers()
        result = self.assert_pass()
        self.assertEqual(result["summary"]["delivery_version"], 2)
        self.assertEqual(result["warnings"], [])

    def test_v2_ten_independent_articles_pass(self):
        self.fixture_v2(10)
        self.add_grounded_covers()
        self.assertEqual(self.assert_pass()["summary"]["checked_covers"], 10)

    def test_v2_missing_and_empty_caption_fail(self):
        article = self.fixture_v2()
        path = article / "caption.txt"
        path.write_text("", encoding="utf-8")
        self.assert_fail("caption.txt")
        path.unlink()
        self.assert_fail("caption.txt")

    def test_v2_legacy_publication_boilerplate_fails(self):
        article = self.fixture_v2()
        for value in (
            "今日AI快讯：\n新闻。", "今日 AI 快讯：新闻。",
            "ClaudeDevs：官方帖文｜2026 年 10 月 17 日\n新闻。",
            "新闻。\n\n官方帖文：\nhttps://example.test/post",
            "新闻。\n\n配套工程博客：\nhttps://example.test/blog",
        ):
            with self.subTest(value=value):
                (article / "body.txt").write_text(value, encoding="utf-8")
                self.assert_fail()

    def test_v2_fact_dates_and_attributed_facts_remain_allowed(self):
        article = self.fixture_v2()
        self.set_v2_body(article, "机构披露，2026 年 10 月 17 日发布了更新。这是内部基准结果。")
        self.assert_pass()

    def set_v2_body(self, article, body):
        from html import escape
        (article / "body.txt").write_text(body, encoding="utf-8")
        path = article / "article.html"
        prefix, rest = path.read_text(encoding="utf-8").split('<article id="article-body">', 1)
        _, suffix = rest.split('</article>', 1)
        path.write_text(prefix + '<article id="article-body"><p>' + escape(body)
                        + '</p><img src="images/cover.png"></article>' + suffix, encoding="utf-8")

    def test_v2_natural_author_views_in_body_and_html_pass(self):
        article = self.fixture_v2()
        self.set_v2_body(article, "机构发布一项更新，内部测试报告了改进。\n\n我更关注它是否缩短完整任务的等待时间，而不只看单项分数。\n\n假设生成环节变快、验证环节仍在排队，总交付时间未必同步缩短。\n\n在我看来，应把这个场景作为后续验证问题，而不是把假设当成已经发生的结果。")
        self.assert_pass()

    def test_v2_opinion_wording_is_not_a_structural_ban(self):
        article = self.fixture_v2()
        for start in ("我认为", "我觉得", "我更关注", "在我看来", "我的判断："):
            with self.subTest(start=start):
                self.set_v2_body(article, "机构公布了新进展。\n\n" + start + "任务中的真实取舍还需要进一步观察。")
                self.assert_pass()

    def test_v2_author_views_do_not_restore_legacy_dateline_or_links(self):
        article = self.fixture_v2()
        body = "机构公布了进展。\n\n我认为还应关注任务耗时。"
        self.set_v2_body(article, body + "\n\n官方帖文：\nhttps://example.test/post")
        self.assert_fail("来源")

    def test_v2_body_and_caption_can_share_a_position_without_verbatim_duplication(self):
        article = self.fixture_v2()
        self.set_v2_body(article, "内部测试是一个信号。\n\n我认为真实交付更值得作为检验标准，单项得分还回答不了这个问题。")
        self.assert_pass()

    def test_v2_full_caption_copy_in_html_still_fails_with_body_views_allowed(self):
        article = self.fixture_v2()
        self.set_v2_body(article, "机构发布了更新。\n\n我认为验证环节值得继续观察。")
        path = article / "article.html"
        content = path.read_text(encoding="utf-8")
        caption = (article / "caption.txt").read_text(encoding="utf-8")
        path.write_text(content.replace('</article>', '<p>' + caption + '</p></article>'), encoding="utf-8")
        self.assert_fail("混入完整评论")

    def test_v2_links_omitted_by_default_but_explicit_override_allowed(self):
        article = self.fixture_v2()
        self.set_v2_body(article, "机构发布了更新。详见 https://example.test/news")
        self.assert_fail("默认不含外链")
        self.manifest["body_links"] = "allow"
        self.save_manifest()
        self.assert_pass()

    def set_v2_caption(self, article, caption):
        from html import escape
        (article / "caption.txt").write_text(caption, encoding="utf-8")
        path = article / "article.html"
        prefix, rest = path.read_text(encoding="utf-8").split('<section id="article-caption">', 1)
        _, suffix = rest.split('</section>', 1)
        path.write_text(prefix + '<section id="article-caption">' + escape(caption)
                        + '</section>' + suffix, encoding="utf-8")

    def test_v2_personal_caption_does_not_require_literal_pronoun(self):
        article = self.fixture_v2()
        self.set_v2_caption(article, "代码写完就算干完活？这次底层改造，倒让人更想掰开看看后半程。")
        self.assert_pass()

    def test_v2_caption_is_not_just_title(self):
        article = self.fixture_v2()
        (article / "title.txt").write_text("我想看的新变化", encoding="utf-8")
        (article / "caption.txt").write_text("我想看的新变化", encoding="utf-8")
        self.assert_fail("完全重复")

    def test_v2_appendix_is_rejected_without_any_url(self):
        article = self.fixture_v2()
        body = (article / "body.txt").read_text(encoding="utf-8")
        self.set_v2_body(article, body + "\n\n## 配图与核验说明\n图片已经核验。")
        self.assert_fail("内部附录")
        self.set_v2_body(article, body)
        self.set_v2_caption(article, "我想问问后续变化。\n\n配图与核验说明：\n图片已经核验。")
        self.assert_fail("内部附录")

    def test_v2_appendix_outside_copy_regions_is_also_rejected(self):
        article = self.fixture_v2()
        path = article / "article.html"
        original = path.read_text(encoding="utf-8")
        for heading in ("配图与核验说明", "配图与<strong>核验说明</strong>"):
            with self.subTest(heading=heading):
                path.write_text(original.replace('</body>', '<footer><h2>' + heading
                                + '</h2><p>图片已经核验。</p></footer></body>'), encoding="utf-8")
                self.assert_fail("包括复制区之外")

    def test_v2_link_footer_is_rejected_even_when_copy_fields_are_clean(self):
        article = self.fixture_v2()
        path = article / "article.html"
        original = path.read_text(encoding="utf-8")
        for footer in (
            '<p>https://example.test/original</p>',
            '<a href="https://example.test/original">查看原文</a>',
            '<a href="//example.test/original">查看原文</a>',
        ):
            with self.subTest(footer=footer):
                path.write_text(original.replace('</body>', '<footer>' + footer + '</footer></body>'), encoding="utf-8")
                self.assert_fail("包括复制区之外")

    def test_v2_title_and_caption_links_are_rejected(self):
        article = self.fixture_v2()
        title = (article / "title.txt").read_text(encoding="utf-8")
        for link in ("https://example.test/post", "www.example.test/post", "[来源](notes.md)", "[来源]: notes.md"):
            with self.subTest(link=link):
                (article / "title.txt").write_text(title + "\n" + link, encoding="utf-8")
                self.assert_fail("默认不含外链")
                (article / "title.txt").write_text(title, encoding="utf-8")
                self.set_v2_caption(article, "我倒想问一句，后面呢？\n" + link)
                self.assert_fail("默认不含外链")
                self.set_v2_caption(article, "我倒想问一句，后面呢？")

    def test_v2_local_anchor_inside_copy_field_is_rejected(self):
        article = self.fixture_v2()
        path = article / "article.html"
        path.write_text(path.read_text(encoding="utf-8").replace('</article>',
                        '<a href="evidence.json">核验记录</a></article>'), encoding="utf-8")
        self.assert_fail("复制区默认不含链接锚点")

    def test_v2_local_image_download_control_remains_allowed(self):
        article = self.fixture_v2()
        path = article / "article.html"
        path.write_text(path.read_text(encoding="utf-8").replace('<body>',
                        '<body><nav><a href="images/cover.png" download>保存图片</a></nav>'), encoding="utf-8")
        result = self.assert_pass()
        self.assertEqual(result["summary"]["referenced_image_files"], 1)

    def test_v2_internal_evidence_keeps_sources_and_qa_notes(self):
        article = self.fixture_v2()
        self.edit_evidence(article, lambda value: value.update(
            editorial_note="配图与核验说明：仅内部留存 https://example.test/original"))
        self.assert_pass()

    def test_v2_caption_must_not_be_in_body(self):
        article = self.fixture_v2()
        with (article / "body.txt").open("a", encoding="utf-8") as handle:
            handle.write("\n\n" + (article / "caption.txt").read_text(encoding="utf-8"))
        self.assert_fail("混入 body.txt")

    def test_v2_body_must_not_repeat_title(self):
        article = self.fixture_v2()
        (article / "body.txt").write_text((article / "title.txt").read_text(encoding="utf-8") + "\n正文。", encoding="utf-8")
        self.assert_fail("标题须独立")

    def test_v2_html_copy_regions_are_required_and_separate(self):
        article = self.fixture_v2()
        path = article / "article.html"
        original = path.read_text(encoding="utf-8")
        path.write_text(original.replace('id="article-caption"', 'id="not-caption"'), encoding="utf-8")
        self.assert_fail("id=article-caption")
        path.write_text(original.replace('</article><section', '<section').replace('</section>', '</section></article>'), encoding="utf-8")
        self.assert_fail("不得相互嵌套")

    def test_v2_duplicate_html_copy_region_fails(self):
        article = self.fixture_v2()
        with (article / "article.html").open("a", encoding="utf-8") as handle:
            handle.write('<article id="article-body">额外正文</article>')
        self.assert_fail("且仅须一个")

    def test_v2_html_body_is_clean_even_if_body_txt_is_clean(self):
        article = self.fixture_v2()
        path = article / "article.html"
        path.write_text(path.read_text(encoding="utf-8").replace('<p>', '<p>今日AI快讯：'), encoding="utf-8")
        self.assert_fail("栏目抬头")

    def test_v2_html_text_link_is_detected(self):
        article = self.fixture_v2()
        path = article / "article.html"
        path.write_text(path.read_text(encoding="utf-8").replace('</article>', '<a href="https://example.test/blog">查看原文</a></article>'), encoding="utf-8")
        self.assert_fail("外链锚点")

    def test_v2_caption_html_matches_text(self):
        article = self.fixture_v2()
        (article / "caption.txt").write_text("我更在意另一件事。", encoding="utf-8")
        self.assert_fail("评论须与 caption.txt 一致")

    def test_v2_toolbar_and_hidden_script_not_copied(self):
        article = self.fixture_v2()
        path = article / "article.html"
        text = path.read_text(encoding="utf-8").replace('<body>', '<body><nav>复制正文 复制评论</nav>')
        text = text.replace('</article>', '<script>const old = "今日AI快讯：https://example.test";</script></article>')
        path.write_text(text, encoding="utf-8")
        self.assert_pass()

    def test_v2_invalid_version_and_link_mode_report_errors(self):
        self.fixture_v2()
        self.manifest["delivery_version"] = True
        self.save_manifest()
        self.assert_fail("delivery_version")
        self.manifest.update(delivery_version=2, body_links=[])
        self.save_manifest()
        self.assert_fail("body_links")

    def test_v2_pure_ai_cover_is_not_grounded_cover(self):
        self.fixture_v2()
        self.add_covers()
        self.assert_fail("纯 AI 概念图")

    def test_v2_grounded_cover_requires_event_design_and_assets(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        original = (article / "cover.json").read_bytes()
        for field in ("source_assets", "event_connection", "design_notes", "ai_assisted"):
            with self.subTest(field=field):
                (article / "cover.json").write_bytes(original)
                self.edit_cover(article, lambda value: value.pop(field))
                self.assert_fail(field)

    def test_v2_source_asset_must_match_real_evidence(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.edit_cover(article, lambda value: value["source_assets"][0].update(source_url="https://example.test/wrong"))
        self.assert_fail("匹配 evidence")

    def test_v2_source_asset_file_must_exist(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        (article / "images" / "cover.png").unlink()
        self.assert_fail("真实素材文件不存在")

    def test_v2_source_asset_path_cannot_escape(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.edit_cover(article, lambda value: value["source_assets"][0].update(path="../../outside.png"))
        self.assert_fail("越出")

    def test_v2_composite_cannot_reference_itself(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.edit_cover(article, lambda value: value["source_assets"][0].update(path="images/news-header.png"))
        self.assert_fail("不得把自身")

    def test_v2_composite_requires_truthful_label(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.edit_cover(article, lambda value: value.update(caption="官方实拍"))
        self.assert_fail("编辑合成")

    def enable_ai_assistance(self, article):
        self.edit_cover(article, lambda value: value.update(ai_assisted=True, caption="编辑合成，含 AI 辅助示意", prompt="仅生成非事实装饰"))
        self.edit_evidence(article, lambda value: value["images"][-1].update(caption="编辑合成，含 AI 辅助示意"))
        path = article / "article.html"
        path.write_text(path.read_text(encoding="utf-8").replace("编辑合成", "编辑合成，含 AI 辅助示意"), encoding="utf-8")

    def test_v2_labeled_ai_assisted_real_material_composite_passes(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.enable_ai_assistance(article)
        self.assert_pass()

    def test_v2_ai_assistance_requires_actual_prompt(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.enable_ai_assistance(article)
        self.edit_cover(article, lambda value: value.pop("prompt"))
        self.assert_fail("实际 prompt")

    def test_v2_ai_assistance_requires_visible_disclosure(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.enable_ai_assistance(article)
        path = article / "article.html"
        path.write_text(path.read_text(encoding="utf-8").replace("，含 AI 辅助示意", ""), encoding="utf-8")
        self.assert_fail("可见图注")

    def test_v2_official_source_cannot_replace_skill_collage_cover(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.edit_cover(article, lambda value: value.update(kind="official_image", caption="官方原图"))
        self.edit_evidence(article, lambda value: value["images"][-1].update(
            kind="official_image", source_url="https://example.test/assets/original", caption="官方原图"))
        self.assert_fail("不能用原图直出替代")

    def test_v2_missing_cover_skill_fails(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.edit_cover(article, lambda value: value.pop("generator_skill"))
        self.assert_fail("generator_skill")

    def test_v2_other_cover_skills_fail(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        for value in ("ai-news-to-x", "openai-editorial-cover", "imagegen", "", None, []):
            with self.subTest(value=value):
                self.edit_cover(article, lambda cover: cover.update(generator_skill=value))
                self.assert_fail("generator_skill")

    def test_v2_cover_prompt_required_without_ai_assistance(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.edit_cover(article, lambda value: value.pop("prompt"))
        self.assert_fail("完整 prompt")

    def test_v2_optional_cover_still_requires_the_only_cover_skill(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.manifest["cover_required"] = False
        self.save_manifest()
        self.edit_cover(article, lambda value: value.update(generator_skill="another-cover"))
        self.assert_fail("generator_skill")

    def test_v2_present_cover_metadata_cannot_bypass_validation(self):
        self.fixture_v2()
        self.add_grounded_covers()
        self.manifest["cover_required"] = False
        self.manifest["items"][0].pop("cover_path")
        self.save_manifest()
        self.assert_fail("cover_path")

    def test_v2_invalid_cover_kind_reports_error_not_exception(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.edit_cover(article, lambda value: value.update(kind=[]))
        self.assert_fail("kind 必须为字符串")

    def test_v2_generated_image_does_not_count_as_real_source_asset(self):
        article = self.fixture_v2()
        self.add_grounded_covers()
        self.edit_evidence(article, lambda value: value["images"][0].update(kind="ai_illustration", caption="AI 生成示意图"))
        self.assert_fail("匹配 evidence")

    @staticmethod
    def cli_env():
        import os
        return dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

    def test_prose_gate_missing_report_cannot_pass_ready(self):
        self.fixture_v2()
        result = Validator(self.root).validate()
        self.assertFalse(result["valid"])
        self.assertTrue(any("prose-review.json" in error for error in result["errors"]))

    def test_prose_gate_fresh_synthetic_record_passes(self):
        article = self.fixture_v2()
        synthetic_review(article)
        synthetic_content_review(article)
        result = Validator(self.root).validate()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["summary"]["checked_prose_reviews"], 1)

    def test_prose_gate_cannot_be_disabled_by_manifest(self):
        self.fixture_v2()
        self.manifest.update(prose_required=False, skip_prose=True)
        self.save_manifest()
        self.assertFalse(Validator(self.root).validate()["valid"])

    def test_prose_gate_known_bad_sentence_fails_despite_complete_record(self):
        article = self.fixture_v2()
        self.set_v2_body(article, "这个区别放进编程任务里就很好理解。")
        synthetic_review(article)
        result = Validator(self.root).validate()
        self.assertFalse(result["valid"])
        self.assertTrue(any("已知套话" in error for error in result["errors"]))

    def test_prose_gate_edit_after_review_is_rejected(self):
        article = self.fixture_v2()
        synthetic_review(article)
        self.set_v2_body(article, "机构新增导出入口。")
        result = Validator(self.root).validate()
        self.assertFalse(result["valid"])
        self.assertTrue(any("SHA256" in error for error in result["errors"]))

    def test_prose_gate_cli_failure_has_exit_one(self):
        self.fixture_v2()
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), str(self.root), "--json"], capture_output=True, encoding="utf-8", env=self.cli_env())
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "FAIL")

    def test_legacy_result_explicitly_does_not_claim_prose_review(self):
        self.fixture()
        result = Validator(self.root, legacy_structure=True).validate()
        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["summary"]["prose_required"])
        self.assertEqual(result["summary"]["checked_prose_reviews"], 0)

    def test_default_gate_rejects_version_downgrade(self):
        self.fixture()
        result = Validator(self.root).validate()
        self.assertFalse(result["valid"])
        self.assertTrue(any("默认验收要求" in error for error in result["errors"]))

    def test_legacy_flag_does_not_disable_v2_prose(self):
        self.fixture_v2()
        self.assertFalse(Validator(self.root, legacy_structure=True).validate()["valid"])

    def test_content_gate_missing_record_fails_despite_prose_ready(self):
        article = self.fixture_v2()
        synthetic_review(article)
        result = Validator(self.root).validate()
        self.assertFalse(result["valid"])
        self.assertTrue(any("content-review.json" in e for e in result["errors"]))
        self.assertEqual(result["summary"]["checked_prose_reviews"], 1)

    def test_content_gate_complete_synthetic_record_counts_both_checks(self):
        article = self.fixture_v2()
        synthetic_review(article)
        synthetic_content_review(article)
        result = Validator(self.root).validate()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["summary"]["checked_content_reviews"], 1)
        self.assertEqual(result["summary"]["checked_prose_reviews"], 1)

    def test_content_gate_cannot_be_disabled_by_manifest_or_legacy_flag(self):
        article = self.fixture_v2()
        synthetic_review(article)
        self.manifest.update(content_required=False, skip_content=True)
        self.save_manifest()
        result = Validator(self.root, legacy_structure=True).validate()
        self.assertFalse(result["valid"])
        self.assertTrue(result["summary"]["content_required"])

    def test_content_gate_open_issue_fails(self):
        article = self.fixture_v2()
        synthetic_review(article)
        record = synthetic_content_review(article)
        record["review"]["findings"] = [{"problem": "正文未解释测试口径。", "action": "等待补充。",
            "result_quote": "机构发布了第 1 项测试更新。", "status": "open"}]
        write_json(article / "content-review.json", record)
        result = Validator(self.root).validate()
        self.assertTrue(any("unresolved content" in e for e in result["errors"]))

    def test_content_gate_evidence_change_is_stale_even_when_prose_is_current(self):
        article = self.fixture_v2()
        synthetic_review(article)
        synthetic_content_review(article)
        self.edit_evidence(article, lambda value: value.update(new_note="证据改变，需要重新复核内容。"))
        result = Validator(self.root).validate()
        self.assertFalse(result["valid"])
        self.assertTrue(any(".content" in e and "SHA256" in e for e in result["errors"]))

    def test_legacy_never_claims_content_review(self):
        self.fixture()
        result = Validator(self.root, legacy_structure=True).validate()
        self.assertTrue(result["valid"])
        self.assertFalse(result["summary"]["content_required"])
        self.assertEqual(result["summary"]["checked_content_reviews"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
