#!/usr/bin/env python3
"""Offline structural checks for one-news-item/one-article delivery packages.

This validates declared metadata and local assets, not factual truth, provenance,
copyright, remote availability, or successful publication. No network is used.
"""

import argparse
from collections import Counter
from datetime import date
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import struct
import sys
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname
from validate_prose import validate as validate_prose
from validate_content import validate as validate_content
from validate_source import validate as validate_source
from validate_brief import validate as validate_brief


SCOPE = "v4 独立表述新闻简报记录与语义审校门槛＋既有视觉检查；v3 历史原文一致性＋既有视觉检查；v2 结构＋内容工作记录＋逐句审校记录校验；v1 仅历史结构。均不证明事实真实、文章无 AI 感或已发布。"
PREFIX = "今日AI快讯："
REAL_IMAGE_KINDS = {"official_image", "screenshot"}
IMAGE_KINDS = REAL_IMAGE_KINDS | {"ai_illustration", "editorial_composite"}
REQUIRED_COVER_SKILL = "cover-editorial-collage"
AI_LABEL_RE = re.compile(r"AI\s*生成示意图")
AI_ASSIST_RE = re.compile(r"AI\s*辅助示意")
URL_RE = re.compile(r"https?://[^\s<>\"'\u3000]+", re.IGNORECASE)
PUBLIC_LINK_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"'\u3000]+"
    r"|(?<!!)\[[^\]\r\n]+\]\([^)\r\n]+\)"
    r"|^\s*\[[^\]\r\n]+\]:\s*\S+", re.IGNORECASE | re.MULTILINE)
PRIVATE_SECTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:配图与核验说明|配图和核验说明|核验说明|来源链接|参考资料)\s*[：:]?\s*$",
    re.MULTILINE)
OLD_PREFIX_RE = re.compile(r"^\s*(?:#{1,6}\s*)?今日\s*AI\s*快讯\s*[：:]", re.IGNORECASE)
SOURCE_LINE_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:(?:[^\n：:]{1,60}[：:]\s*)?"
    r"(?:官方帖文|官方工程博客|官方博客|官网动态|配套工程博客|原始论文|新闻媒体|官方公告|来源|参考来源|官方原文))"
    r"\s*(?:[：:｜|].*|$)", re.MULTILINE)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def http_url(value):
    if not nonempty(value):
        return False
    try:
        parsed = urlsplit(value.strip())
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def path_key(path):
    # Windows deliveries must not become distinct articles merely by changing case.
    return str(path).replace("\\", "/").casefold()


def raster_dimensions(path):
    """Read PNG/JPEG/WebP dimensions, not metadata supplied by the manifest.

    This is a container/header check, not a full image decoder or provenance test.
    """
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) >= 45 and data[12:16] == b"IHDR" and b"IDAT" in data and data[-8:-4] == b"IEND":
            return struct.unpack(">II", data[16:24])
    elif data.startswith(b"\xff\xd8"):
        offset = 2
        while offset < len(data):
            if data[offset] != 0xFF:
                break
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in {0xD9, 0xDA}:
                break
            if marker in {0x01, *range(0xD0, 0xD8)}:
                continue
            if offset + 2 > len(data):
                break
            length = int.from_bytes(data[offset:offset + 2], "big")
            if length < 2 or offset + length > len(data):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if length >= 7:
                    height, width = struct.unpack(">HH", data[offset + 3:offset + 7])
                    return width, height
                break
            offset += length
    elif len(data) >= 30 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if int.from_bytes(data[4:8], "little") + 8 > len(data):
            raise ValueError("WebP 文件截断")
        kind = data[12:16]
        if kind == b"VP8X":
            return (1 + int.from_bytes(data[24:27], "little"),
                    1 + int.from_bytes(data[27:30], "little"))
        if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            width, height = struct.unpack("<HH", data[26:30])
            return width & 0x3FFF, height & 0x3FFF
        if kind == b"VP8L" and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise ValueError("封面必须为可读取尺寸的 PNG、JPEG 或 WebP 文件")


class ImageReferences(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []
        self.has_base64 = False
        self.has_base = False
        self.text = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag.lower() in {"script", "style", "template", "noscript"}:
            self.hidden_depth += 1
        if tag.lower() == "base" and "href" in values:
            self.has_base = True
        if tag.lower() not in {"img", "source", "image", "input"}:
            return
        if tag.lower() == "input" and (values.get("type") or "").lower() != "image":
            return
        for name in ("src", "href", "xlink:href"):
            value = values.get(name)
            if value:
                self.references.append(value)
        srcset = values.get("srcset")
        if srcset:
            if re.search(r"data\s*:.*?;\s*base64", srcset, re.IGNORECASE):
                self.has_base64 = True
            else:
                self.references.extend(part.strip().split()[0]
                                       for part in srcset.split(",") if part.strip())

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "template", "noscript"}:
            self.hidden_depth = max(0, self.hidden_depth - 1)

    def handle_data(self, data):
        if not self.hidden_depth:
            self.text.append(data)


class PublishingFields(HTMLParser):
    """Read copy areas and visible preview text, excluding hidden/script content."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    BLOCK = {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "figure", "figcaption", "header", "footer", "main", "aside"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields = {"article-body": [], "article-caption": []}
        self.counts = {name: 0 for name in self.fields}
        self.links = {name: [] for name in self.fields}
        self.public = []
        self.public_links = []
        self.stack = []
        self.active = None
        self.hidden = False
        self.overlap = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        values = dict(attrs)
        previous = (self.active, self.hidden)
        field = values.get("id")
        if field in self.fields:
            self.counts[field] += 1
            self.overlap |= self.active is not None
            self.active = field
        self.hidden |= tag in {"script", "style", "template", "noscript"} or "hidden" in values
        if not self.hidden:
            if tag in self.BLOCK:
                self.public.append("\n")
            if tag == "a" and values.get("href"):
                self.public_links.append(values["href"])
        if self.active and not self.hidden:
            if tag in self.BLOCK:
                self.fields[self.active].append("\n")
            if tag == "a" and values.get("href"):
                self.links[self.active].append(values["href"])
        if tag not in self.VOID:
            self.stack.append((tag, *previous))
        else:
            self.active, self.hidden = previous

    def handle_endtag(self, tag):
        tag = tag.lower()
        if not self.hidden and tag in self.BLOCK:
            self.public.append("\n")
        if self.active and not self.hidden and tag in self.BLOCK:
            self.fields[self.active].append("\n")
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                _, self.active, self.hidden = self.stack[index]
                del self.stack[index:]
                break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if not self.hidden:
            self.public.append(data)
        if self.active and not self.hidden:
            self.fields[self.active].append(data)


class Validator:
    def __init__(self, run_directory, legacy_structure=False, current=False):
        self.root = Path(run_directory).expanduser().resolve()
        self.errors = []
        self.warnings = []
        self.requested_count = None
        self.item_count = 0
        self.checked_articles = 0
        self.image_count = 0
        self.seen_bodies = {}
        self.cover_required = False
        self.cover_count = 0
        self.seen_cover_hashes = {}
        self.delivery_version = 1
        self.body_links = "omit"
        self.prose_count = 0
        self.content_count = 0
        self.source_count = 0
        self.brief_count = 0
        self.current = current
        self.legacy_structure = legacy_structure

    def error(self, label, message):
        self.errors.append(f"{label}: {message}")

    def warning(self, label, message):
        self.warnings.append(f"{label}: {message}")

    def read_json(self, path, label):
        try:
            if not inside(path.resolve(), self.root):
                self.error(label, "JSON 路径越出 run 根目录")
                return None
            with path.open("r", encoding="utf-8-sig") as handle:
                value = json.load(handle)
            if not isinstance(value, dict):
                self.error(label, "JSON 顶层必须为对象")
                return None
            return value
        except (OSError, ValueError, RuntimeError) as exc:
            self.error(label, f"JSON 读取失败 ({type(exc).__name__}): {exc}")
            return None

    def local_path(self, raw, article_root, label, html_reference=False):
        if not nonempty(raw):
            self.error(label, "本地路径必须为非空字符串")
            return None
        value = raw.strip()
        try:
            # A Windows drive prefix is a filesystem path, not a URL scheme.
            windows_absolute = PureWindowsPath(value).is_absolute()
            if windows_absolute:
                candidate = Path(value)
            else:
                parsed = urlsplit(value)
                scheme = parsed.scheme.lower()
                if scheme in {"http", "https"}:
                    if html_reference:
                        return None  # A remote URL never counts as a local asset.
                    self.error(label, "图片 path 必须指向本地文件，而非网络 URL")
                    return None
                if scheme == "data":
                    self.error(label, "内嵌 data/base64 图片不属于可下载的独立文件")
                    return None
                if scheme == "file":
                    if parsed.netloc not in {"", "localhost"}:
                        self.error(label, "file URI 仅允许本机路径")
                        return None
                    if parsed.query or parsed.fragment:
                        self.error(label, "file URI 不得包含 query 或 fragment")
                        return None
                    candidate = Path(url2pathname(parsed.path))
                elif scheme:
                    self.error(label, f"不支持的图片路径协议: {scheme}")
                    return None
                else:
                    if parsed.netloc:
                        self.error(label, "不接受网络路径或协议相对路径")
                        return None
                    # HTML URL escaping is distinct from literal JSON file paths.
                    value = unquote(parsed.path) if html_reference else value
                    candidate = Path(value.replace("\\", "/"))
            if not candidate.is_absolute():
                candidate = article_root / candidate
            result = candidate.resolve()
            if not inside(result, self.root) or not inside(result, article_root):
                self.error(label, "路径越出 run 根目录或文章根目录")
                return None
            return result
        except (OSError, ValueError, RuntimeError) as exc:
            self.error(label, f"路径解析失败 ({type(exc).__name__}): {exc}")
            return None

    def read_text(self, article, name, label):
        path = self.local_path(name, article, label)
        if path is None:
            return None
        try:
            if not path.is_file():
                self.error(label, "文件不存在或不是普通文件")
                return None
            value = path.read_text(encoding="utf-8-sig").strip()
            if not value:
                self.error(label, "文件内容为空")
                return None
            return value
        except (OSError, UnicodeError, ValueError) as exc:
            self.error(label, f"文本读取失败 ({type(exc).__name__}): {exc}")
            return None

    def check_links(self, body, label):
        urls = [match.rstrip(".,;:!?，。；：！？、）】》)]}")
                for match in URL_RE.findall(body)]
        counts = Counter(urls)
        if len(counts) > 2:
            self.warning(label, f"正文包含 {len(counts)} 个去重外链；通常保留 1 个，必要时 1–2 个")
        for url, count in sorted(counts.items()):
            if count > 1:
                self.warning(label, f"同一来源链接重复出现 {count} 次: {url}")

    def check_clean_text(self, value, label):
        if OLD_PREFIX_RE.search(value):
            self.error(label, "v2 文本须直接进入内容，删除今日 AI 快讯栏目抬头")
        if SOURCE_LINE_RE.search(value):
            self.error(label, "v2 文本不得包含来源／日期独立行或来源链接区；证据另存")
        if PRIVATE_SECTION_RE.search(value):
            self.error(label, "v2 公开稿不得附配图与核验说明等内部附录；证据另存")
        if self.body_links == "omit" and PUBLIC_LINK_RE.search(value):
            self.error(label, "v2 公开文本默认不含外链；完整 URL 保留在 evidence.json")

    def check_publishing_fields(self, title, body, caption, html, label):
        compact = lambda value: re.sub(r"\s+", "", value or "")
        if title:
            self.check_clean_text(title, f"{label}.title.txt")
        if body:
            self.check_clean_text(body, f"{label}.body.txt")
            if title and body.splitlines()[0].strip() == title.strip():
                self.error(label, "标题须独立，不重复放在正文首行")
        if caption:
            self.check_clean_text(caption, f"{label}.caption.txt")
            # Personal voice is a semantic editorial check, not a pronoun count.
            if compact(caption) in {compact(title), compact(body)}:
                self.error(label, "caption 不得与标题或正文完全重复")
            if body and compact(caption) in compact(body):
                self.error(label, "caption 必须独立于正文，不得整段混入 body.txt")
        if html:
            parser = PublishingFields()
            parser.feed(html)
            public_text = "".join(parser.public)
            if PRIVATE_SECTION_RE.search(public_text):
                self.error(label, "HTML 公开预览不得附配图与核验说明等内部附录，包括复制区之外")
            if self.body_links == "omit":
                if PUBLIC_LINK_RE.search(public_text):
                    self.error(label, "HTML 公开预览默认不含外链文本，包括复制区之外")
                if any(http_url(link) or link.strip().startswith("//") for link in parser.public_links):
                    self.error(label, "HTML 公开预览默认不含外链锚点，包括复制区之外")
            if parser.overlap:
                self.error(label, "HTML 正文与评论复制区不得相互嵌套")
            for field in ("article-body", "article-caption"):
                if parser.counts[field] != 1:
                    self.error(label, f"HTML 须且仅须一个 id={field} 的独立复制区")
                value = "".join(parser.fields[field]).strip()
                if not value:
                    self.error(label, f"HTML {field} 复制区为空")
                else:
                    self.check_clean_text(value, f"{label}.html.{field}")
                if self.body_links == "omit" and parser.links[field]:
                    self.error(label, f"HTML {field} 复制区默认不含链接锚点")
            html_body = compact("".join(parser.fields["article-body"]))
            html_caption = compact("".join(parser.fields["article-caption"]))
            if caption and html_caption != compact(caption):
                self.error(label, "HTML 评论须与 caption.txt 一致")
            if caption and compact(caption) in html_body:
                self.error(label, "HTML 正文复制区混入完整评论")

    def check_claims(self, evidence, label):
        claims = evidence.get("claims")
        if not isinstance(claims, list) or not claims:
            self.error(label, "claims 必须包含至少一条事实证据")
            return
        verified = 0
        for index, claim in enumerate(claims, 1):
            claim_label = f"{label}.claims[{index}]"
            if not isinstance(claim, dict):
                self.error(claim_label, "证据必须为对象")
                continue
            fields_valid = True
            if not nonempty(claim.get("claim")):
                self.error(claim_label, "claim 必须为非空字符串")
                fields_valid = False
            if not http_url(claim.get("source_url")):
                self.error(claim_label, "事实证据必须包含 HTTP(S) source_url")
                fields_valid = False
            source_date = claim.get("source_date")
            if source_date is None and "source_date" in claim:
                self.warning(claim_label, "source_date 为 null：原文日期未知；请勿编造日期")
            else:
                try:
                    if not isinstance(source_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", source_date):
                        raise ValueError("date format")
                    date.fromisoformat(source_date)
                except (ValueError, TypeError):
                    self.error(claim_label, "source_date 必须为有效的 YYYY-MM-DD 日期，原文未知时显式填 null")
                    fields_valid = False
            status = claim.get("status")
            if status == "verified" and fields_valid:
                verified += 1
            elif status == "unverified":
                self.error(claim_label, "事实证据仍标记为 unverified（未核实）")
            elif status != "verified":
                self.error(claim_label, "status 必须为 verified 或 unverified")
        if not verified:
            self.error(label, "缺少字段完整且标记为 verified 的事实证据；标记本身不代表真实性已验证")

    def check_images(self, article, evidence, html, label):
        image_dir = self.local_path("images", article, f"{label}.images/")
        if image_dir is not None and not image_dir.is_dir():
            self.error(label, "缺少 images/ 目录")
        parser = ImageReferences()
        if html:
            parser.feed(html)
            if parser.has_base or re.search(r"<base\b", html, re.IGNORECASE):
                self.error(label, "article.html 不得使用改变本地引用解析的 <base> 标签")
            if parser.has_base64 or re.search(r"data\s*:[^\s\"'<>]*;\s*base64", html, re.IGNORECASE):
                self.error(label, "article.html 包含 base64 内嵌图片；请保存为独立图像文件")
        references = set()
        for index, raw in enumerate(parser.references, 1):
            image_path = self.local_path(raw, article, f"{label}.html_image[{index}]", html_reference=True)
            if image_path is not None:
                references.add(path_key(image_path))
        images = evidence.get("images")
        if not isinstance(images, list) or not images:
            self.error(label, "images 必须包含至少一张真实来源图的元数据")
            return
        real_images = 0
        seen = set()
        for index, entry in enumerate(images, 1):
            image_label = f"{label}.images[{index}]"
            if not isinstance(entry, dict):
                self.error(image_label, "图片元数据必须为对象")
                continue
            kind = entry.get("kind")
            if not isinstance(kind, str):
                self.error(image_label, "kind 必须为字符串")
                kind = ""
            if kind not in IMAGE_KINDS:
                self.error(image_label, "kind 必须为 official_image、screenshot、editorial_composite 或 ai_illustration")
            if kind in REAL_IMAGE_KINDS and not http_url(entry.get("source_url")):
                self.error(image_label, "真实来源图必须包含 HTTP(S) source_url")
            if kind == "ai_illustration":
                if not isinstance(entry.get("caption"), str) or not AI_LABEL_RE.search(entry["caption"]):
                    self.error(image_label, "AI 图 caption 必须含“AI 生成示意图”（亦接受无空格的 AI生成示意图）")
                if not AI_LABEL_RE.search(" ".join(parser.text)):
                    self.error(image_label, "article.html 正文图注须包含“AI 生成示意图”，仅 evidence 标注或图片 alt 不算正文图注")
                if entry.get("source_url") is not None and not http_url(entry.get("source_url")):
                    self.error(image_label, "AI 图 source_url 应为 null 或 HTTP(S) URL")
            elif kind == "editorial_composite":
                if "编辑合成" not in str(entry.get("caption", "")):
                    self.error(image_label, "合成图 caption 必须标明编辑合成")
                if "编辑合成" not in " ".join(parser.text):
                    self.error(image_label, "HTML 可见图注须标明编辑合成")
            elif not nonempty(entry.get("caption")):
                self.error(image_label, "图片 caption 必须为非空字符串")
            image_path = self.local_path(entry.get("path"), article, image_label)
            if image_path is None:
                continue
            key = path_key(image_path)
            if key in seen:
                self.error(image_label, "同一图片路径在 evidence.json 中重复")
            seen.add(key)
            try:
                if not image_path.is_file() or image_path.stat().st_size == 0:
                    self.error(image_label, "图片文件不存在、不是普通文件或为空")
                    continue
            except OSError as exc:
                self.error(image_label, f"图片文件读取失败: {exc}")
                continue
            if key not in references:
                self.error(image_label, "图片未在 article.html 的图像元素中引用")
                continue
            self.image_count += 1
            if kind in REAL_IMAGE_KINDS and http_url(entry.get("source_url")):
                real_images += 1
        if not real_images:
            self.error(label, "每篇至少需要一张实际存在且在 HTML 引用的真实来源图（official_image 或 screenshot）")

    def check_article(self, item, article, label):
        title = self.read_text(article, "title.txt", f"{label}.title.txt")
        body = self.read_text(article, "body.txt", f"{label}.body.txt")
        html = self.read_text(article, "article.html", f"{label}.article.html")
        if self.delivery_version == 2:
            caption = self.read_text(article, "caption.txt", f"{label}.caption.txt")
            self.check_publishing_fields(title, body, caption, html, label)
            content = validate_content(article)
            for error in content["errors"]:
                self.error(f"{label}.content", error)
            if content["valid"]:
                self.content_count += 1
            prose = validate_prose(article)
            for error in prose["errors"]:
                self.error(f"{label}.prose", error)
            if prose["valid"]:
                self.prose_count += 1
        if self.delivery_version == 3:
            source = validate_source(article)
            for error in source["errors"]:
                self.error(f"{label}.source", error)
            if source["valid"]:
                self.source_count += 1
            if source.get("source_url") != item.get("source_url"):
                self.error(label, "manifest source_url 与源快照不一致")
            if source.get("title") != item.get("title"):
                self.error(label, "manifest title 与原标题不一致")
        if self.delivery_version == 4:
            brief = validate_brief(article)
            for error in brief["errors"]:
                self.error(f"{label}.brief", error)
            if brief["valid"]:
                self.brief_count += 1
            if brief.get("source_url") != item.get("source_url"):
                self.error(label, "manifest source_url 与 AIHOT 简报来源不一致")
            if brief.get("title") != item.get("title"):
                self.error(label, "manifest title 与独立表述后的标题不一致")
            caption_path = self.local_path("caption.txt", article, label)
            caption = caption_path.read_text(encoding="utf-8-sig") if caption_path and caption_path.is_file() else ""
            for value in (title, body, caption):
                if value:
                    self.check_clean_text(value, label)
            if html:
                public = PublishingFields()
                public.feed(html)
                if PRIVATE_SECTION_RE.search("".join(public.public)):
                    self.error(label, "HTML 不混入公开核验附录")
                if self.body_links == "omit" and (PUBLIC_LINK_RE.search("".join(public.public)) or
                        any(http_url(link) or link.strip().startswith("//") for link in public.public_links)):
                    self.error(label, "HTML 公开文本默认不含外链，必要署名或用户要求时用 allow")
        if body is not None:
            if self.delivery_version == 1 and not body.startswith(PREFIX):
                self.error(label, f"body.txt 去除 BOM 和前后空白后必须以“{PREFIX}”开头")
            if self.delivery_version == 1:
                self.check_links(body, label)
            if body in self.seen_bodies:
                self.error(label, f"正文与 {self.seen_bodies[body]} 完全重复；复制同一篇文章不构成独立交付")
            else:
                self.seen_bodies[body] = label
        evidence_path = self.local_path("evidence.json", article, f"{label}.evidence.json")
        evidence = self.read_json(evidence_path, f"{label}.evidence.json") if evidence_path else None
        if evidence is not None:
            if self.delivery_version == 3:
                if evidence.get("text_mode") != "source_preserved" or evidence.get("source_capture") != "source-capture.json":
                    self.error(label, "v3 evidence 必须声明 source_preserved 与 source-capture.json")
                if evidence.get("claims") != []:
                    self.check_claims(evidence, label)
            else:
                self.check_claims(evidence, label)
            self.check_images(article, evidence, html, label)
        if self.cover_required or (self.delivery_version in {2, 3, 4} and
                                   ("cover_path" in item or (article / "cover.json").exists())):
            self.check_cover(item, article, evidence, html, label)
        self.checked_articles += 1

    def check_cover(self, item, article, evidence, html, label):
        cover_label = f"{label}.cover"
        image_path = self.local_path(item.get("cover_path"), article, f"{cover_label}.cover_path")
        metadata_path = self.local_path("cover.json", article, f"{cover_label}.cover.json")
        metadata = self.read_json(metadata_path, f"{cover_label}.cover.json") if metadata_path else None
        if image_path is None or metadata is None:
            return
        if not image_path.is_file():
            self.error(cover_label, "封面文件不存在或不是普通文件")
            return
        try:
            width, height = raster_dimensions(image_path)
        except (OSError, ValueError, struct.error) as exc:
            self.error(cover_label, f"封面实际尺寸读取失败: {exc}")
            return
        if width < 1 or height < 1:
            self.error(cover_label, "封面实际像素必须大于零")
        elif abs(2 * width - 5 * height) > 2:
            self.error(cover_label, f"封面实际比例须为 5:2（原生舍入横向容差 1 像素），实际 {width}×{height}")
        for field, actual in (("width", width), ("height", height)):
            if type(metadata.get(field)) is not int or metadata[field] != actual:
                self.error(cover_label, f"cover.json {field} 必须记录实际像素 {actual}，不是请求尺寸")
        if metadata.get("role") != "x_header":
            self.error(cover_label, "cover.json 必须声明 role=x_header")
        if self.delivery_version == 1 and metadata.get("kind") != "ai_illustration":
            self.error(cover_label, "v1 cover.json 必须声明 kind=ai_illustration")
        fields = ("prompt", "alt") if self.delivery_version == 1 else ("alt", "caption")
        for field in fields:
            if not nonempty(metadata.get(field)):
                self.error(cover_label, f"cover.json {field} 必须非空")
        if self.delivery_version == 1 and (not isinstance(metadata.get("caption"), str) or not AI_LABEL_RE.search(metadata["caption"])):
            self.error(cover_label, "cover.json caption 必须包含 AI 生成示意图")
        if self.delivery_version in {2, 3, 4}:
            self.check_grounded_cover(metadata, image_path, article, evidence, html, cover_label)
        metadata_image = self.local_path(metadata.get("path"), article, f"{cover_label}.metadata_path")
        if metadata_image is not None and path_key(metadata_image) != path_key(image_path):
            self.error(cover_label, "cover.json path 与 manifest cover_path 不一致")
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if digest in self.seen_cover_hashes:
            self.error(cover_label, f"封面内容与 {self.seen_cover_hashes[digest]} 完全重复；每篇需要独立封面")
        else:
            self.seen_cover_hashes[digest] = label
        declared = False
        if isinstance(evidence, dict) and isinstance(evidence.get("images"), list):
            for entry in evidence["images"]:
                if not isinstance(entry, dict):
                    continue
                path = self.local_path(entry.get("path"), article, f"{cover_label}.evidence_path")
                if path is not None and path_key(path) == path_key(image_path):
                    declared = (entry.get("kind") == metadata.get("kind")
                                and nonempty(entry.get("caption")))
                    if self.delivery_version == 1:
                        declared = declared and AI_LABEL_RE.search(entry["caption"]) is not None
                    elif metadata.get("ai_assisted") is True:
                        declared = declared and AI_ASSIST_RE.search(entry["caption"]) is not None
                    break
        if not declared:
            self.error(cover_label, "evidence.images 必须以一致的 kind 声明同一封面，并包含对应合成／AI 图注")
        parser = ImageReferences()
        if html:
            parser.feed(html)
        first = (self.local_path(parser.references[0], article, f"{cover_label}.first_html_image", html_reference=True)
                 if parser.references else None)
        if first is None or path_key(first) != path_key(image_path):
            self.error(cover_label, "开篇封面必须作为 article.html 第一张图引用")
        self.cover_count += 1

    def check_grounded_cover(self, metadata, image_path, article, evidence, html, label):
        if metadata.get("generator_skill") != REQUIRED_COVER_SKILL:
            self.error(label, f"generator_skill 必须为 {REQUIRED_COVER_SKILL}；文章封面只用此 Skill")
        if not nonempty(metadata.get("prompt")):
            self.error(label, "封面须保存来自指定 Skill 且实际使用的完整 prompt")
        kind = metadata.get("kind")
        if not isinstance(kind, str):
            self.error(label, "封面 kind 必须为字符串")
            kind = ""
        if kind not in REAL_IMAGE_KINDS | {"editorial_composite"}:
            self.error(label, "v2 封面须基于真实新闻素材，不以纯 AI 概念图作为封面")
        if kind in REAL_IMAGE_KINDS:
            self.error(label, "v2 封面必须是指定 Skill 制作的 editorial_composite，不能用原图直出替代")
        if type(metadata.get("ai_assisted")) is not bool:
            self.error(label, "ai_assisted 必须为布尔值")
        if kind in REAL_IMAGE_KINDS and metadata.get("ai_assisted") is True:
            self.error(label, "AI 辅助合成不可声明成未经编辑的真实来源图")
        for field in ("event_connection", "design_notes"):
            if not nonempty(metadata.get(field)):
                self.error(label, f"{field} 必须记录封面与事件及真实素材的具体联系")
        if kind == "editorial_composite" and "编辑合成" not in str(metadata.get("caption", "")):
            self.error(label, "合成封面 caption 须标明编辑合成")
        if metadata.get("ai_assisted") is True:
            if not nonempty(metadata.get("prompt")):
                self.error(label, "AI 辅助封面须保存实际 prompt")
            parser = ImageReferences()
            parser.feed(html or "")
            if not AI_ASSIST_RE.search(str(metadata.get("caption", ""))) or not AI_ASSIST_RE.search(" ".join(parser.text)):
                self.error(label, "AI 辅助封面须在元数据及可见图注标明 AI 辅助示意")
        assets = metadata.get("source_assets")
        if not isinstance(assets, list) or not assets:
            self.error(label, "source_assets 至少包含一张实际参与封面的真实新闻素材")
            return
        originals = {}
        if isinstance(evidence, dict) and isinstance(evidence.get("images"), list):
            for entry in evidence["images"]:
                if isinstance(entry, dict) and isinstance(entry.get("kind"), str) and entry["kind"] in REAL_IMAGE_KINDS:
                    path = self.local_path(entry.get("path"), article, f"{label}.source_evidence")
                    if path is not None:
                        originals[path_key(path)] = entry
        seen = set()
        for index, asset in enumerate(assets, 1):
            asset_label = f"{label}.source_assets[{index}]"
            if not isinstance(asset, dict):
                self.error(asset_label, "素材记录必须为对象")
                continue
            if not http_url(asset.get("source_url")) or not nonempty(asset.get("usage")):
                self.error(asset_label, "真实素材须有 source_url 与具体 usage")
            path = self.local_path(asset.get("path"), article, asset_label)
            if path is None:
                continue
            key = path_key(path)
            if key in seen:
                self.error(asset_label, "同一真实素材引用重复")
            seen.add(key)
            if not path.is_file() or not path.stat().st_size:
                self.error(asset_label, "真实素材文件不存在或为空")
            if kind == "editorial_composite" and key == path_key(image_path):
                self.error(asset_label, "合成封面不得把自身声明为原始素材")
            original = originals.get(key)
            if original is None or original.get("source_url") != asset.get("source_url"):
                self.error(asset_label, "素材路径及来源须匹配 evidence 中的真实来源图")

    def validate(self):
        manifest = self.read_json(self.root / "manifest.json", "manifest.json")
        if manifest is None:
            return self.result()
        version = manifest.get("delivery_version", 1)
        if type(version) is not int or version not in {1, 2, 3, 4}:
            self.error("manifest.json", "delivery_version 必须为 1、2、3 或 4；当前新闻简报用 4")
        else:
            self.delivery_version = version
            if version == 1 and not self.legacy_structure:
                self.error("manifest.json", "默认验收要求 delivery_version: 2、内容记录与逐句审校；历史 v1 仅可用 --legacy-structure 查看旧包结构，不算新稿验收")
        if self.current and version != 4:
            self.error("manifest.json", "--current 仅接受 delivery_version: 4 的新闻简报，不接受旧版降级")
        if self.delivery_version == 4:
            if manifest.get("text_mode") != "aihot-news-brief":
                self.error("manifest.json", "v4 text_mode 必须为 aihot-news-brief")
            if manifest.get("body_links", "omit") not in ("omit", "allow"):
                self.error("manifest.json", "v4 body_links 必须为 omit 或 allow")
            if manifest.get("cover_required") is not True and not (
                    manifest.get("cover_required") is False and manifest.get("cover_omitted_by_user") is True
                    and nonempty(manifest.get("cover_omission_reason"))):
                self.error("manifest.json", "v4 默认需要封面；省略须记录用户明确要求及原因")
        elif manifest.get("text_mode") == "aihot-news-brief":
            self.error("manifest.json", "aihot-news-brief 必须使用 delivery_version: 4")
        self.body_links = manifest.get("body_links", "omit")
        if self.delivery_version == 2 and self.body_links not in ("omit", "allow"):
            self.error("manifest.json", "body_links 必须为 omit 或 allow")
        if self.delivery_version == 3:
            if manifest.get("text_mode") != "aihot-original":
                self.error("manifest.json", "v3 text_mode 必须为 aihot-original")
            if self.body_links != "preserve-source":
                self.error("manifest.json", "v3 body_links 必须为 preserve-source")
        elif manifest.get("text_mode") == "aihot-original":
            self.error("manifest.json", "aihot-original 必须使用 delivery_version: 3")
        if "cover_required" in manifest and type(manifest["cover_required"]) is not bool:
            self.error("manifest.json", "cover_required 必须为布尔值")
        self.cover_required = manifest.get("cover_required") is True
        requested = manifest.get("requested_count")
        if type(requested) is not int or requested < 1:
            self.error("manifest.json", "requested_count 必须为正整数")
        else:
            self.requested_count = requested
        items = manifest.get("items")
        if not isinstance(items, list):
            self.error("manifest.json", "items 必须为数组")
            return self.result()
        self.item_count = len(items)
        if self.requested_count is not None and len(items) != requested:
            self.error("manifest.json", f"交付未完整匹配：要求 {requested} 篇独立文章，实际 {len(items)} 条")
        ranks = []
        seen_dirs = {}
        for index, item in enumerate(items, 1):
            label = f"items[{index}]"
            if not isinstance(item, dict):
                self.error(label, "条目必须为对象")
                continue
            rank = item.get("rank")
            if type(rank) is not int:
                self.error(label, "rank 必须为整数")
            else:
                ranks.append(rank)
            if not nonempty(item.get("title")):
                self.error(label, "新闻标题必须为非空字符串")
            if not http_url(item.get("source_url")):
                self.error(label, "新闻 source_url 必须为 HTTP(S) URL")
            if item.get("status") != "ready":
                self.error(label, f"条目状态并非 ready: {item.get('status')!r}")
            issues = item.get("issues")
            if not isinstance(issues, list):
                self.error(label, "issues 必须为数组")
            elif issues:
                self.error(label, "条目仍有未解决 issues: " + json.dumps(issues, ensure_ascii=False))
            raw_dir = item.get("article_dir")
            if not nonempty(raw_dir):
                self.error(label, "article_dir 必须为非空相对目录")
                continue
            try:
                if Path(raw_dir).is_absolute() or PureWindowsPath(raw_dir).drive or ":" in raw_dir:
                    self.error(label, "article_dir 必须为 run 根目录下的相对目录")
                    continue
                article = (self.root / raw_dir.replace("\\", "/")).resolve()
                if article == self.root or not inside(article, self.root):
                    self.error(label, "article_dir 路径越出 run 根目录或指向 run 根目录")
                    continue
            except (OSError, ValueError, RuntimeError) as exc:
                self.error(label, f"article_dir 路径解析失败: {exc}")
                continue
            key = path_key(article)
            if key in seen_dirs:
                self.error(label, f"article_dir 与 {seen_dirs[key][1]} 碰撞：每条新闻必须对应独立文章目录")
                continue
            # Nested article roots may otherwise share their asset trees.
            if any(inside(article, other) or inside(other, article) for other, _ in seen_dirs.values()):
                self.error(label, "文章目录不得相互嵌套或共享目录树")
                continue
            seen_dirs[key] = (article, label)
            if not article.is_dir():
                self.error(label, f"文章目录不存在: {raw_dir}")
                continue
            self.check_article(item, article, label)
        if len(ranks) != len(items) or sorted(ranks) != list(range(1, len(items) + 1)):
            self.error("manifest.json", "rank 必须唯一且连续覆盖 1..len(items)")
        return self.result()

    def result(self):
        return {
            "valid": not self.errors,
            "status": "FAIL" if self.errors else "PASS",
            "scope": SCOPE,
            "run_directory": str(self.root),
            "summary": {
                "requested_count": self.requested_count,
                "item_count": self.item_count,
                "checked_articles": self.checked_articles,
                "referenced_image_files": self.image_count,
                "cover_required": self.cover_required,
                "checked_covers": self.cover_count,
                "delivery_version": self.delivery_version,
                "prose_required": self.delivery_version == 2,
                "checked_prose_reviews": self.prose_count,
                "content_required": self.delivery_version == 2,
                "checked_content_reviews": self.content_count,
                "source_required": self.delivery_version == 3,
                "checked_source_captures": self.source_count,
                "brief_required": self.delivery_version == 4,
                "checked_brief_reviews": self.brief_count,
                "current_mode_required": self.current,
                "legacy_structure_only": self.delivery_version == 1,
            },
            "errors": self.errors,
            "warnings": self.warnings,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", help="包含 manifest.json 和独立文章目录的交付根目录")
    parser.add_argument("--json", action="store_true", dest="as_json", help="输出单个机器可读 JSON 对象")
    parser.add_argument("--legacy-structure", action="store_true", help="仅兼容检查历史 v1 结构；不跳过 v2 内容与逐句审校，不用于新稿")
    parser.add_argument("--current", action="store_true", help="当前新稿必选：强制 v4 新闻简报，不接受历史版本")
    args = parser.parse_args(argv)
    try:
        result = Validator(args.run_directory, legacy_structure=args.legacy_structure, current=args.current).validate()
    except (OSError, ValueError, RuntimeError) as exc:
        result = {"valid": False, "status": "FAIL", "scope": SCOPE,
                  "errors": [f"目录读取失败 ({type(exc).__name__}): {exc}"], "warnings": []}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(SCOPE)
        summary = result.get("summary", {})
        print(f"Articles: {summary.get('item_count', 0)}/{summary.get('requested_count', '?')}; "
              f"checked: {summary.get('checked_articles', 0)}")
        for warning in result["warnings"]:
            print(f"WARNING: {warning}")
        for error in result["errors"]:
            print(f"ERROR: {error}")
        print(result["status"])
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
