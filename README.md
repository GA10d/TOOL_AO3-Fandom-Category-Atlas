# AO3 Fandom Category Atlas

中文名：AO3 同人分类图谱

这是一个基于 Scrapy 的 AO3 数据抓取与分析项目。它从 AO3 搜索结果页提取作品元数据，导出 JSONL 和 Excel 数据集，并围绕 `icon_category_text` 分析不同 fandom 的类别构成，生成 CSV 汇总和可视化图表。

## 项目定位

这个仓库不是在开发 Scrapy 框架本身。`src/` 目录中保留了 Scrapy 源码副本，项目相关的自定义工作主要集中在以下部分：

- `src/extras/ao3_comments_tags_spider.py`：AO3 抓取 spider
- `src/main.ipynb`：运行抓取、检查输出、导出 Excel
- `src/icon_category_analysis.ipynb`：按 fandom 分析 `icon_category_text`
- `src/output/`：抓取结果、分析图表和统计表
- `ao3.xlsx`：抓取任务输入表

## 这个项目做什么

- 从 AO3 搜索页抓取作品卡片信息
- 提取标题、作者、fandom、摘要、字数、评论数、kudos、bookmarks、hits 等字段
- 解析 listing tags 和 icon 信息
- 导出 JSONL 原始结果与 Excel 分析表
- 将多值 `icon_category_text` 拆分后，统计不同 fandom 的 category 占比
- 输出热力图、堆叠条形图和多份 CSV 汇总

## 核心流程

### 1. 准备抓取任务

在根目录的 `ao3.xlsx` 中维护任务列表。当前 notebook 会把前两列读取为：

- `source_label`
- `start_url`

每一行对应一个抓取任务。

### 2. 运行抓取 notebook

打开 [src/main.ipynb](src/main.ipynb)，配置以下参数后运行：

- `MAX_PAGES`
- `MAX_WORKS`
- `COOKIE_HEADER`
- `LOG_LEVEL`

这个 notebook 会通过 `python -m scrapy runspider` 调用 [src/extras/ao3_comments_tags_spider.py](src/extras/ao3_comments_tags_spider.py)，然后：

- 把当前运行结果写入 `src/output/_ao3_current_run.jsonl`
- 汇总写入 `src/output/ao3_jujutsu_comments_tags.jsonl`
- 把作品数据展开后导出为 `src/output/ao3_jujutsu_comments_tags.xlsx`

### 3. 运行分析 notebook

打开 [src/icon_category_analysis.ipynb](src/icon_category_analysis.ipynb) 并运行全部单元。

它会读取 `src/output/ao3_jujutsu_comments_tags.xlsx`，重点分析 `icon_category_text`：

- 拆分多值 category
- 统计 overall category share
- 统计 top fandom 的 category share
- 生成热力图和堆叠条形图
- 输出多份 CSV 到 `src/output/icon_category_analysis/`

## 主要输出

抓取与分析完成后，关键输出包括：

- [src/output/ao3_jujutsu_comments_tags.jsonl](src/output/ao3_jujutsu_comments_tags.jsonl)
- [src/output/ao3_jujutsu_comments_tags.xlsx](src/output/ao3_jujutsu_comments_tags.xlsx)
- [src/output/icon_category_analysis/overall_category_share.csv](src/output/icon_category_analysis/overall_category_share.csv)
- [src/output/icon_category_analysis/fandom_work_counts.csv](src/output/icon_category_analysis/fandom_work_counts.csv)
- [src/output/icon_category_analysis/fandom_category_share_long.csv](src/output/icon_category_analysis/fandom_category_share_long.csv)
- [src/output/icon_category_analysis/fandom_category_share_wide.csv](src/output/icon_category_analysis/fandom_category_share_wide.csv)
- [src/output/icon_category_analysis/fandom_category_share_by_work.csv](src/output/icon_category_analysis/fandom_category_share_by_work.csv)
- [src/output/icon_category_analysis/fandom_category_heatmap.png](src/output/icon_category_analysis/fandom_category_heatmap.png)
- [src/output/icon_category_analysis/fandom_category_stacked_bar.png](src/output/icon_category_analysis/fandom_category_stacked_bar.png)

## 主要字段

Excel 输出里常见的字段包括：

- `work_id`
- `title`
- `authors`
- `work_url`
- `search_page`
- `published_or_updated`
- `summary`
- `fandoms`
- `series`
- `gift_recipients`
- `language`
- `words`
- `chapters`
- `collections`
- `comments_total`
- `kudos`
- `bookmarks`
- `hits`
- `icon_category_text`
- `tag_ratings`
- `tag_categories`
- `tag_warnings`
- `tag_relationships`
- `tag_characters`
- `tag_freeforms`
- `tag_fandoms`

## 目录结构

```text
.
|-- README.md
|-- ao3.xlsx
`-- src
    |-- extras
    |   `-- ao3_comments_tags_spider.py
    |-- main.ipynb
    |-- icon_category_analysis.ipynb
    |-- output
    |   |-- ao3_jujutsu_comments_tags.jsonl
    |   |-- ao3_jujutsu_comments_tags.xlsx
    |   `-- icon_category_analysis
    `-- scrapy
```

## 依赖建议

建议使用的 Python 环境：

- `scrapy`
- `pandas`
- `openpyxl`
- `matplotlib`
- `seaborn`
- `jupyter`

## 使用说明

- AO3 某些页面可能需要登录 cookie 或成人内容访问设置。
- `icon_category_text` 是多值字段；分析时会被拆分，因此一条作品可能同时贡献给多个 category。
- 当前仓库更适合研究或课程项目使用，文档和输出是围绕具体数据任务组织的，而不是一个已经封装完备的通用 Python 包。

## 后续可改进项

- 给 `ao3.xlsx` 增加字段说明模板
- 为 spider 输出补充更稳定的字段字典
- 把 notebook 流程整理成脚本化命令行入口
- 为项目补充许可证和数据使用说明
