> 历史 v3 原文包维护参考。当前 v4 新闻简报使用 news-brief-contract.md，不执行标题／正文原样复制。

# 原文保真与源快照

## 什么叫“一模一样”

`title.txt` 和 `body.txt` 与取得并人工核对的 AIHOT 标题／正文相同。仅容许 UTF-8 BOM 与 CRLF/LF 的文件序列化差异；不统一 Unicode、不合并空格、不换标点、不删链接、不改段序、不去 AI 味。HTML 可改变样式、嵌入图像，但文字必须相同。

取原文时分清文章内容和网页导航、推荐、工具提示、评论、广告。保存原始响应，记录具体字段或页面区域，再对照可见全文确认未截断。AIHOT Agent 当前说明不提供单篇全文；摘要只能记录为摘要，不能通过扩写或混合外站内容冒充全文。参考：[AIHOT Agent 使用说明](https://aihot.news/api/v1/agent)。

全文复制使用用户直接提供的文本、明确许可复用的文本或公有领域文本，并保留依据。机器响应已有的来源、canonical、权利信息原样保存；AIHOT 服务的公开访问不等于第三方文章和图片许可，Skill 的 MIT 许可也不覆盖这些内容。涉及公开再分发的用途按实际授权处理；未取得可用完整文本时保持 incomplete，不自动生成摘要代替。参考：[AIHOT 公开使用规则](https://aihot.news/terms)，核对日期 2026-10-19。

## 留存和复制

在文章目录生成：

```text
source/raw-response.txt       原始响应或用户给的原始文件字节
source/title.txt              人工核对后的完整标题
source/body.txt               人工核对后的完整正文
source-capture.json           来源、提取位置、使用依据、内容范围和三个文件哈希
title.txt                    source/title.txt 的文字副本
body.txt                     source/body.txt 的文字副本
caption.txt                  默认空
```

先准备真正取得的标题、正文和原始响应文件，再使用当前 Python 执行（角括号是待替换参数，不是固定路径）：

```text
python <skill目录>/scripts/capture_source.py <文章目录> --title-file <标题文件> --body-file <全文文件> --raw-file <原始响应> --source-url <AIHOT阅读页> --retrieved-at <含时区的ISO时间> --reuse-basis user_provided --reuse-note <实际依据> --extraction-note <实际页面区域或字段>
```

`reuse-basis` 可为 `user_provided`、`licensed`、`public_domain`，必须按实际情况选择，不把“可访问”填成授权。脚本只做本地复制，不抓网页、不生成任何文字；目标字段存在时拒绝覆盖。源文件和哈希只在首次捕获时生成，不因交付文字改动而重写源快照来消除差异。

`source-capture.json` 的 `content_kind` 必须为 `full_article`；仅摘要不满足完整文章交付。`reuse` 记录的是已核实的依据，不是脚本自动确认版权。`extraction_note` 必须指明标题、正文的实际提取区域及完整性检查。

## Caption 和 HTML

caption 默认空，保留单独复制区域即可。需要原文摘句时，把 `source-capture.json.caption_mode` 设为 `source_excerpt`，`caption.txt` 必须是正文中一个原样、连续的片段；不拼接散句，不新写钩子。摘句与正文重复是正常的，不删原文去满足旧去重门槛。

HTML 使用三个互不嵌套且唯一的 ID：`article-title`、`article-body`、`article-caption`。title 和 caption 可见文字分别与对应文本文件一致。正文按 `body.txt.split("\n\n")` 分为块，逐一用 `data-source-block="0"`、`"1"`……标记，块内保留准确空格和换行，重连用两个换行。推荐 `white-space: pre-wrap` 并正确转义 HTML 特殊字符；块内部不加入按钮、图注或新增文字。图片与 `<figcaption>` 可以插在块之间，复制按钮从原文文本或这些块取文字，不把图注复制进正文。

不要把原文链接变成研究附录；不新增研究外链，原有链接、归属和必要署名照留。新增图片与图注不算原文，视觉预览要能区分，图注不承担文章续写。

## 校验与人工检查

```text
python <skill目录>/scripts/validate_source.py <文章目录> --json
python <skill目录>/scripts/validate_delivery.py <批次目录> --json
```

检查源文件哈希、完整性声明、标题／正文精确比较、caption 来源、HTML 可见文字及额外正文混入。v3 不调用 validate_content 或 validate_prose；它们继续服务历史 v2，不将原文套话判成必须改写的问题。

哈希只证明文件未偏离该快照，不能证明提取本身完整、远程内容真实或声明的许可有效；要对照实际页面和原始响应检查。发现抓取漏段应重新捕获真实来源并留存原因，不能把自行创作内容写进 source 冒充原文。
