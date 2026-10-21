# AIHOT 独立表述新闻简报交付（v4）

## 文件与文字

批次保留 manifest.json；每篇保留 title.txt、body.txt、caption.txt、article.html、news-source.json、brief-review.json、source/、evidence.json、cover.json 和 images/。用户明确不要封面时才省略 cover.json 与 cover_path。

- title.txt：独立新闻标题，事实和限定由正文支持，不机械复制原标题。
- body.txt：独立表述的主新闻；有已核实补充时在结尾单列「相关新闻与最新进展｜截至 YYYY-MM-DD」。不含图注、复制控件、内部审校或研究附录。
- caption.txt：可空；非空时为独立简短事实摘要，不用原文摘句或额外分析，不整段塞回正文。
- article.html：继续独立标题、正文、caption 复制区，唯一且不嵌套的 id 分别为 article-title、article-body、article-caption。按 body.txt 的双换行分块，用 data-brief-block="0"、"1"……标记全部正文块（包括补充标题），顺序连续。保留准确空格／换行，推荐 white-space:pre-wrap 并转义 HTML 字符。图片／图注插在块外，不进入文字复制。三个区的可见文字和复制结果必须分别等于对应文件。
- 图片继续保存为独立本地文件；图片复制须写入实际图像数据，不能只复制路径。实际看图并测试文字、图片复制，脚本不会替你完成浏览器操作。
- news-source.json、source/、brief-review.json、evidence.json 是内部资料；详见 [简报契约](news-brief-contract.md)。不能用输出稿倒填来源或虚构审校。evidence.text_mode 为 aihot-news-brief，source_capture 为 news-source.json，claims 必须含已核实的事实记录；视觉记录不变。
- 不要求 v2 的内容策划／去 AI 味文件，不执行 v3 原文相等检查。不自动修改旧批次。

## manifest.json

```json
{
  "delivery_version": 4,
  "text_mode": "aihot-news-brief",
  "selected_at": "2026-10-19T13:00:00+08:00",
  "timezone": "Asia/Shanghai",
  "selection_url": "https://aihot.news/",
  "requested_count": 1,
  "cover_required": true,
  "body_links": "omit",
  "items": [{
    "rank": 1,
    "title": "填写实际独立表述后的标题",
    "source_url": "https://aihot.news/items/实际条目ID",
    "source_date": null,
    "status": "ready",
    "article_dir": "01-topic",
    "cover_path": "images/news-header.png",
    "issues": []
  }]
}
```

示例不是新闻或执行记录。source_url 与 news-source.json.aihot.source_url 相同；title 与 title.txt 相同，而非强行等于原标题。requested_count 以用户本次要求为准，ready 只在当前简报及完整视觉／复制验收后填写；缺关键事实、可靠来源、必要图片／封面或待核实问题时用 incomplete 并写 issues。

body_links 默认 omit，必要署名或用户需要链接时用 allow，不能为无链接偏好删去必需来源归属。只有用户明确不要封面时设 cover_required=false，同时记录 cover_omitted_by_user=true 与具体 cover_omission_reason；不能用它隐藏替代封面方案。

## 图片证据（原有视觉规则）

evidence.images 每项记录 path、kind、source_url、asset_url（有时）、caption。kind 仍为 official_image、screenshot、editorial_composite、ai_illustration；真实图须记录实际来源。合成图图注说明“编辑合成”，含生成式内容时加“含 AI 辅助示意”；纯生成图标“AI 生成示意图”，不计入每篇至少一张的真实图数量。保存和打开实际图片，图注不能替代看图。

## 新闻编辑式封面

文章封面只能通过 `cover-editorial-collage` 制作，执行方式见 [唯一封面入口](cover-workflow.md)。不再使用本入口自拟的通用封面提示词或其他封面 Skill；原始官网图继续用于正文与拼贴素材，不直接代替成品封面。

每篇 `cover.json` 保存以下实际结果；文件名可变，但三个位置的路径必须指向同一张图：本文件 `path`、manifest 条目 `cover_path`、`evidence.images[].path`。

```json
{
  "path": "images/news-header.png",
  "generator_skill": "cover-editorial-collage",
  "prompt": "此处记录经该 Skill 形成、实际用于本次生图的完整提示词；示例不是实际执行记录",
  "kind": "editorial_composite",
  "role": "x_header",
  "width": 2560,
  "height": 1024,
  "alt": "编辑合成封面：官方产品界面与本篇关键图表的组合。",
  "caption": "编辑合成，含 AI 辅助示意：基于本条新闻真实素材制作，非官方原图。",
  "ai_assisted": true,
  "event_connection": "画面中的具体界面、人物、变化或数据，如何对应本篇新闻",
  "design_notes": "主次层级、关键裁切、配色和信息组织；不是仅有 Logo 与背景",
  "source_assets": [
    {
      "path": "images/official-cover.png",
      "source_url": "https://example.com/official-post",
      "usage": "保留真实产品界面，作为封面主体"
    }
  ]
}
```

`width`、`height` 填实际像素，目标 5:2，优先 2560×1024；允许 `abs(width - 2.5 * height) <= 1` 的原生舍入差。PNG、JPEG、WebP 可由脚本读取尺寸，HTML 裁切或拉伸不代替文件比例。

本入口的 v2/v3/v4 封面必须为 `editorial_composite`，`generator_skill` 必须严格等于 `cover-editorial-collage`，并保存实际完整 `prompt`。不以官方原图直出、截图直出或纯 AI 概念画替代指定 Skill 的编辑拼贴。`ai_assisted` 按实际工具使用填写：使用生成式图像工具时写 `true`，在 cover、evidence 和可见 HTML 图注同时标「含 AI 辅助示意」；未使用生成式工具才写 `false`。不要把重绘的截图称作原始画面。入口字段只核对声明，执行过程与成图还需实际复核。

`source_assets` 至少记录一张真正参与封面的本条新闻素材，路径及 URL 对应 `evidence.images` 中的真实来源图；拼贴封面不能把自身列为原始素材，正文中另留未被替代的真实原图。纯 Logo 虽可作辅助识别，不能单独充当新闻内容锚点。`event_connection` 和 `design_notes` 记录实际设计，不用“炫酷科技感”等空话糊弄；脚本只检查字段与引用，不判断设计优劣。

设计示例：工程新闻用真实代码审查界面＋关键流程细节；模型发布用真实产品演示＋有口径的测评图；科学研究用论文图／真实实验设备＋研究对象。材料由当前新闻决定，不套一张换字模板。

提示词只能由 `cover-editorial-collage` 的当前工作流形成。使用 [封面接入](cover-workflow.md) 中的内部调用参数，不保留另一份通用生图模板与它竞争。该 Skill 默认返回调用模板，内部须显式使用 `--out-type prompt`，再实际生成图片；只拿到模板或提示词不算完成。

实际调用图像工具时，真实素材须传入参考图参数，不能只列文件名却从零生成。打开成图与原图对照，检查事件识别、标题文字、数值、5:2 原生像素及手机缩略图焦点。重做仍使用同一个 Skill，缺依赖或失败时记录未完成，不切换封面方案。



## 执行校验

```text
python <skill目录>/scripts/validate_brief.py <文章目录> --json
python <skill目录>/scripts/validate_delivery.py <批次目录> --current --json
```

当前 v4 必须通过简报审校、来源快照、独立表述风险、主要事实映射、背景篇幅、补充隔离、文字哈希和 HTML 对应检查，以及既有封面／真实图门槛。`--current` 明确只接受 v4，不接受删 text_mode、旧版或 legacy 开关绕过。失败码 1，通过码 0，脚本只读不自动修文。

脚本可以发现漏记录、文字漂移、明显连续照抄和格式违规；不能独立证明主要事实全被识别、语义不变、没有近义改写抄袭、资料真实或审校确实执行。必须阅读来源和成稿，对每项检查留下具体结论；不把 PASS 宣称为抄袭检测认证。

历史 v2/v3 仍可不传 --current 按原契约检查，v1 另需 --legacy-structure；这些结果不是当前新稿验收。封面实际 5:2 像素、唯一 Skill、真实素材、编辑合成和 AI 标签、首图及引用关系检查不变。
