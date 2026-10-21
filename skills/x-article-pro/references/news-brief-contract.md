# 新闻简报契约：保留主要事实，重新表述

本文件只约束当前 v4 新闻简报。标题、正文、caption 均不使用旧 v3 的原样复制规则；封面、插图及复制交付沿用原流程。

## 1. 先列事实，再写文字

阅读指定 AIHOT 条目，先列清主体、发生的事情、时间、版本、主要变化、关键数字和单位、适用条件、证据来源及重要限定。主要事实是影响读者理解“发生什么、有什么具体变化、何时对谁生效”的信息，不是原文的全部修辞和评价。不能先删成极短摘要，再把剩余句子声明为全部主要事实。

每项事实留一段内部来源片段、对应正文段落，以及需要精确保留的短字段。型号、数字、币种、计费单位、比较基线、测试框架、是否仅某个子集、可用渠道、预览／计划状态等不能随改写丢失。来源称“官方测试”就保留归属；宣布下月生效就不写成现已生效。标题只能概括正文已支持的事实，不新增“全面超越”“颠覆”等判断。

独立写作时以事实清单为输入，重新安排句子与信息组合，不一边看原文一边逐句换词。不保留特色比喻、排比、观点句和收尾。产品名、基准名、术语、版本、数值可以保持准确。完成后再回看源文本：既核对事实，也检查是否只是原句换词。直接引语不是默认路线；可用准确的间接转述保留归属。

来源只有摘要／节选时如实记录，不写“已获取全文”。已知事实足够支持有限简报就按实际材料写，不追求固定篇幅；缺少会改变事件理解的关键条件时保留 incomplete。核心事实存在矛盾时先核查，不用外站长文悄悄替换 AIHOT 主题。

## 2. 新闻体边界：限制分析，而非只删禁词

默认只写事实、必要归属、适用条件与时间。以下内容不进当前正文或 caption：作者个人看法、竞争格局判断、行业／社会意义扩展、趋势推演、对读者的使用建议、情绪化钩子、无事实增量的过渡与结尾。不能只删“我认为”等词，却保留同一段主观分析。

必要背景限于解释一个术语或测试口径，且要有来源；不是另起分析篇章。为了让“不要大段分析”可检查，背景总量取以下上限的最小值：**至多一个段落、120 个非空白字符、主新闻事实段字符数的 15%**。零背景完全正常。这些是上限而非写作目标；不要通过多标几个 core 段来躲过限制。主新闻本身没有最低字数。

caption 可空；需要时用不超过 160 个非空白字符独立概括事实，不摘原文、不重复正文整段，也不趁独立字段加入分析或新事实。

## 3. 相关新闻与最新进展的隔离

检查同事件的可靠原始来源，区分 AIHOT 已写到的主事实佐证与新增消息。佐证可支持主段的准确表述；新增事实只能进入正文结尾独立的「相关新闻与最新进展｜截至 YYYY-MM-DD」。每个补充段需写明实际事件日期（YYYY-MM-DD 或 M月D日），主体、变化与条件，来源保留内部 evidence。获取时间不是事件日期，已宣布的未来安排仍用将来时。

只收直接相关、已核实的材料，不混进无关热点，不靠旧闻制造“最新”。榜单、价格、活动时间等按本次截至时间核对。没有可靠新增消息时，公开稿省略该节，内部写清检查过哪些 URL 及结论。不伪造更新，也不必公开写一段“未找到最新进展”。

## 4. 内部来源记录（news-source.json）

先保存实际取得的文件；绝不把改写稿或自己补写的全文反填来源：

```text
source/title.txt          实际 AIHOT 标题
source/text.txt           实际取得的正文／摘要／节选
source/raw-response.txt   对应原始响应或用户提供的原始材料
```

`news-source.json` 顶层为 `version:1`、`mode:"aihot-news-brief"`、`aihot` 对象。aihot 必含：

| 字段 | 内容 |
|---|---|
| source_url | 实际 HTTPS AIHOT 条目／阅读页，不是首页或搜索页 |
| retrieved_at | 含时区的 ISO 读取时间 |
| source_date | 来源实际发布日期 YYYY-MM-DD；未知显式 null |
| content_kind | full_article、summary、excerpt 或 user_provided；照实填写 |
| extraction_note | 实际提取字段／页面区域、取得范围与完整性检查 |
| sha256 | 三个源文件各自的原始字节 SHA-256；键严格为 title.txt、text.txt、raw-response.txt |

快照只用于内部证据和对照，不进入公开稿或复制结果。哈希证明文件与记录一致，不证明远程内容或事实真实；保留原始快照，不因新稿未通过而改快照来消除差异。

## 5. 审校记录（brief-review.json）

读完来源与最终成稿后再填写，不预填通过项或倒造过程。记录实际 reviewer、含时区 reviewed_at，以及最终 title.txt、body.txt、caption.txt 的原始字节 SHA-256。改任何文字须重读受影响事实并更新记录；不要只自动刷新哈希。

顶层字段：

| 字段 | 要求 |
|---|---|
| version / mode | 1 / aihot-news-brief |
| reviewer / reviewed_at | 实际审校执行者及时间，晚于材料读取 |
| text_sha256 | 恰好三个输出文件名及其最终字节哈希 |
| aihot_facts | 完整主要事实数组；每项含唯一 id、fact、源文本中实际连续 source_excerpt、对应 core 段索引 body_blocks、非空 critical_details 短字段数组 |
| blocks | 与 body.txt 按双换行切分的所有块一一对应；index 从 0 连续，kind 及 evidence_ids 如下 |
| literal_terms | 可选短术语数组，仅限源文中的产品名、基准名、版本及必要事实字段；不得填完整句子、修辞碎片或大量拆句来清空重合检查 |
| updates | status 为 verified 或 none；checked_at 为实际含时区查证截止时间；checked_sources 记录实际查过的 URL；无新增时 note 说明结果 |
| checks | 下表七项，每项含 passed 布尔值和具体 note；所有项实际通过才能 ready |

`blocks.kind` 只接受：
- `core`：AIHOT 主要事实；必须映射到事实清单和已有 evidence id。
- `context`：必要且有来源的短背景；必须满足第 2 节上限。
- `updates_heading`：唯一补充标题，evidence_ids 为 []；位于所有主新闻／背景之后。
- `update`：新增事实；只能位于补充标题之后，并连续占据正文尾部。

不存在 analysis、opinion 或自由发挥块；更换标签不能让主观分析变成事实。

七项逐项审校，不用“已检查／全部通过”代替具体判断：

| checks 键 | note 应说明什么 |
|---|---|
| main_facts_complete | 对照了哪些主要事实，是否遗漏会改变理解的信息 |
| factual_qualifiers_preserved | 数字、单位、范围、基线和条件如何保留；歧义如何解决 |
| independent_expression | 哪些句子重组了，是否沿用源文特色表达或仅换词 |
| no_extended_analysis | 是否含观点／推演／建议；背景块及实际长度 |
| updates_separated | 新事实在哪一节；没有新增时核查结论 |
| title_supported | 标题各项判断由哪些事实支持，有无夸张 |
| caption_supported | caption 是否独立、简短、有依据；留空则记录留空 |

`evidence.json` 保留既有 images 结构，并声明 `text_mode:"aihot-news-brief"`、`source_capture:"news-source.json"`。每条 claims 含唯一 id、claim、source_url、source_date（未知 null）、retrieved_at、status:"verified" 与 role。role 为 aihot、corroboration、update；aihot 的 URL 须匹配快照；update 另含 event_date。正文每段的 evidence_ids 引用这些 id；update 事实不得映射到 core/context。verified 是真实核验后的记录，不是脚本替你确认。

`scripts/test_validate_brief.py` 的 fixture 展示完整可执行的离线格式，里面的新闻、图片与来源都是明确合成测试材料，不能作为真实取材或生图记录。

## 6. 验收与修正

1. 对照来源完成事实清单和七项语义审校。
2. 运行 validate_brief.py；它检查源哈希、最终文字绑定、事实映射与关键短字段、明显连续原文重合、背景篇幅、补充段隔离及 HTML 同步。
3. 运行 validate_delivery.py --current；继续执行既有真实插图、唯一封面入口、5:2 原生尺寸、图注标识及独立目录检查。
4. 打开图文并实际测试文字与图片复制。只把全部实际完成的条目标 ready。

重合检测会忽略正确记录的短术语，但对明显连续照搬报错；这只是返工信号，不是“抄袭判定／原创认证”。没有重合也可能是逐句换词或事实失真，必须继续语义审校。修改表达要保持事实准确；不要改数字、删重要限定、伪造审核、滥加 literal_terms 或降级历史模式来取得 PASS。
