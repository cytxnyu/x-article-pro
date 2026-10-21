# X文章-pro

以指定 AIHOT 条目的主要事实为基础，用独立表述写中文新闻简报；保留事实、不照抄原文，相关新闻与最新进展单列。封面固定走 `cover-editorial-collage`。

显示名 **X文章-pro**，技术调用标识 `x-article-pro`，当前版本 2.1.0。

## 唯一默认模式

**AIHOT 主要事实 + 独立表述的新闻简报 + 单列的相关新闻与最新进展。**

| 部分 | 要求 |
| --- | --- |
| 主新闻 | 保留事件、主体、时间、版本、关键变化、数字与单位、适用范围与重要限定，但重新组织语言 |
| 相关新闻与最新进展 | 只收同事件、已核实、标明实际日期的补充；主新闻之后单列「相关新闻与最新进展｜截至 YYYY-MM-DD」，没有就省略，不造更新 |
| 封面 | 唯一入口 `cover-editorial-collage`，5:2 编辑拼贴（如 2560×1024），真实素材、实际 prompt、生成标签和看图验收 |

它不是全文复制器，也不走长篇分析、个人观点、行业趋势推演或"信息增量文章"路线；没有字数下限，不为凑长度扩写。

## 写稿约束

1. **主要事实不丢不变。** 先整理事实清单再独立组织语言，保留"官方称／测试显示／计划／预览／截至某日"等证据强度，不把发布方声明改写成公认结论。
2. **独立表述，不照抄。** 标题、正文和非空 caption 全部重新表述；按事实重组句子，不逐句替换同义词，不沿用原文特色比喻与收尾；产品名、基准名、必要术语和数字可准确保留。
3. **写新闻，不扩成评论。** 直接交代发生了什么、具体变化与适用条件，默认不写个人观点、宏大意义、行业趋势、竞争格局和读者建议。
4. **补充单列。** 补查的新事实只进独立补充节，不得混进主新闻，也不能假称 AIHOT 原文写到了。
5. **未通过就修正。** 逐项自查事实保留、独立表述、无大段分析、补充隔离，再绑定文字哈希运行 v4 校验；失败即修稿或保留 `incomplete`，不靠降低版本取得 PASS。机器检查不等于"零抄袭"认证，语义与事实仍需人工对照。

## 交付形态

一个批次保留 `manifest.json`；每篇保留 `title.txt`、`body.txt`、`caption.txt`、`article.html`、`news-source.json`、`brief-review.json`、`source/`、`evidence.json`、`cover.json` 和 `images/`。

- `delivery_version: 4`、`text_mode: aihot-news-brief`。
- 标题、正文、caption 是三个独立复制区（`article-title`、`article-body`、`article-caption`），可见文字与复制结果分别等于对应文件。
- 图片保存为独立本地文件，图注插在正文块外，不进入 `body.txt` 或正文文字复制。
- 不自动发布到 X，不建立定时任务；脚本 PASS 不代替看图、复制实测或真实来源核查。

## 安装

### 方式一：Skills CLI

```bash
npx -y skills add cytxnyu/x-article-pro --skill x-article-pro --agent codex -g -y
```

要装到其他 Agent 时去掉 `--agent codex` 和末尾的 `-y`，按安装器提示选择目标；不要用 `--all` 代替选择。

### 方式二：手动复制

先克隆仓库，再把 `skills/x-article-pro` 整个文件夹放进 Codex 的 `skills` 目录（默认 `~/.codex/skills/x-article-pro`；设置了 `CODEX_HOME` 时用其下的 `skills`）。

```powershell
git clone https://github.com/cytxnyu/x-article-pro.git
$skillHome = if ($env:CODEX_HOME) { Join-Path $env:CODEX_HOME 'skills' } else { Join-Path $HOME '.codex/skills' }
$target = Join-Path $skillHome 'x-article-pro'
if (Test-Path -LiteralPath $target) { throw '目标技能已存在，请先检查现有版本。' }
New-Item -ItemType Directory -Path $skillHome -Force | Out-Null
Copy-Item -LiteralPath './x-article-pro/skills/x-article-pro' -Destination $target -Recurse
```

### 依赖

必须把两个依赖 Skill 装到**同一个 skills 根目录**，否则开头的依赖解析会直接 FAIL：

| 依赖 | 来源仓库 | 本包锁定修订 | 用途 |
| --- | --- | --- | --- |
| `aihot` | [KKKKhazix/khazix-skills](https://github.com/KKKKhazix/khazix-skills) → `aihot` | `322346ded8129436b3f64707789a73e732ae24d9` | 取指定条目的真实材料、URL、日期与采集时间 |
| `cover-editorial-collage` | [imartinstudio/cover-prompt-skills](https://github.com/imartinstudio/cover-prompt-skills) → `plugins/cover-editorial-collage/skills/cover-editorial-collage` | `4f5bb6d93bbba18bd9f85cdea83a38a2a4bf16cb` | 唯一封面生成入口 |

安装后自检：

```bash
python skills/x-article-pro/scripts/resolve_dependencies.py --json
```

返回对两个依赖逐文件校验 SHA-256 的结果，`status` 为 `PASS` 才继续写作。

## 直接这样用

```text
用 $x-article-pro 处理我指定的 AIHOT 新闻。
保留主要事实、数字、适用范围和重要限定，用独立表述，不照抄或逐句换词。
写清新闻本身，不加大段分析、个人观点、趋势推演或凑字数的结尾。
相关新闻和最新进展核实后，在主新闻之后单列并标明截至日期；没有就不编。
封面继续只用 cover-editorial-collage，真实插图、5:2 画幅和复制交付流程保持不变。
标题、正文、caption 分开；完成 v4 简报审校和 --current 校验后交付。
```

也可以只说"把这条 AIHOT 新闻写成 X 文章""续接上一批继续写""只重做这篇的封面"。

## 工作方式

1. 运行 `scripts/resolve_dependencies.py --json`，按 [依赖路由](skills/x-article-pro/references/dependency-routing.md) 读取两个依赖的绝对入口。
2. 用 `aihot` 的当前说明取指定条目，留存源文本、原始响应、URL、日期、采集时间与内容范围。
3. 先做主要事实清单，再按 [简报契约](skills/x-article-pro/references/news-brief-contract.md) 独立表述；复核数字、限定与发布状态。
4. 同事件补查与真实插图按 [取材与配图](skills/x-article-pro/references/reporting.md) 执行，新信息只进独立补充节。
5. 封面按 [封面接入](skills/x-article-pro/references/cover-workflow.md) 走 `cover-editorial-collage`；最后按 [交付格式](skills/x-article-pro/references/delivery-format.md) 打包、校验并实测复制。

批次任务一条新闻一个独立目录；只改图时文字与图片字节不动，只改文字且要求图不变时保留图片字节与封面记录；只拿到摘要时如实记录范围，不冒充取得全文。

## 校验与测试

脚本只做结构性检查，语义与事实仍需逐项对照。

```bash
# 依赖与哈希
python skills/x-article-pro/scripts/resolve_dependencies.py --json

# 单篇简报契约（v4）
python skills/x-article-pro/scripts/validate_brief.py <article_dir>

# 整批交付，新稿必选 --current
python skills/x-article-pro/scripts/validate_delivery.py <run_dir> --current
```

另有 `validate_source.py`、`validate_content.py`、`validate_prose.py` 分层校验来源、内容与文字。离线测试（Python 3.12 下 258 项全部通过）：

```bash
cd skills/x-article-pro
python -m unittest discover -s scripts -p "test_*.py" -t scripts
```

运行环境：Python 3.10+，仅标准库，无第三方依赖。

## 目录结构

```text
x-article-pro/
├── README.md
├── LICENSE
└── skills/
    └── x-article-pro/
        ├── SKILL.md                  # 入口与硬约束
        ├── dependencies.lock.json    # 依赖仓库、修订与逐文件 SHA-256
        ├── agents/openai.yaml        # Codex 接口信息
        ├── references/               # 简报契约、取材配图、封面接入、交付格式等
        └── scripts/                  # 依赖解析、来源采集、分层校验与离线测试
```

[Skill 入口](skills/x-article-pro/SKILL.md) · [简报契约](skills/x-article-pro/references/news-brief-contract.md) · [交付格式](skills/x-article-pro/references/delivery-format.md)

## 许可

本仓库为 MIT。`aihot` 与 `cover-editorial-collage` 属第三方作品，按其仓库各自许可使用，本仓库不重新分发它们的代码。
