# USYD Postgraduate Excel -> PostgreSQL

把当周的 USYD 研究生课程 Excel 导入 PostgreSQL，并通过本地查询后台进行筛选、查看、导出和官网招生信息核对。

这个项目已经实现：

- 一行 Excel = 一条 `courses` 记录
- 不按 `CRICOS` 去重
- 用 `source_row_hash` 做幂等导入键
- `Commencing Semester` 拆到 `course_intakes`
- `Duration (Years)` 拆成 `duration_min_years` / `duration_max_years`
- `IELTS Academic` 拆到 `course_admission_requirements`
- IELTS 小分拆成听力 / 阅读 / 口语 / 写作四列
- 官网爬虫会补全 `academic requirements`、`language tests`、`application details`
- 本地 Streamlit 页面可直接展示官网招生信息详情和来源链接
- 全流程在单个事务内执行
- 提供本地 Streamlit 查询后台

## 目录

```text
usyd_pg_import/
├─ pyproject.toml
├─ .env.example
├─ README.md
├─ migrations/
├─ src/
└─ tests/
```

## 文件说明

### 根目录

- `pyproject.toml`
  项目打包和依赖配置，定义 `psycopg`、`streamlit`、`pandas`、`Scrapy`、`Playwright` 等运行依赖。
- `.env.example`
  环境变量示例文件，主要给 `DATABASE_URL` 这类本地配置做模板。
- `README.md`
  当前项目说明文档，包含安装、导入、爬虫、前端和测试说明。

### `migrations/`

- `001_init.sql`
  初始化数据库主表，创建 `courses`、`course_intakes`、`course_admission_requirements` 等基础结构。
- `002_indexes.sql`
  为课程名、CRICOS、intake、admission 等常用查询字段补索引。
- `003_ielts_subscores.sql`
  给 `course_admission_requirements` 增加 IELTS 四项小分列，并把旧 `english_req_details` 数据回填进去。
- `004_admissions_crawl_schema.sql`
  为官网爬虫新增 JSONB 结构化字段、来源 fingerprint 和 `course_admission_dlq` 表。

### `src/`

- `src/cli.py`
  项目命令入口，负责 `migrate`、`import-excel`、`crawl-admissions` 这几个命令。
- `src/config.py`
  读取环境变量和运行配置。
- `src/db.py`
  管理 PostgreSQL 连接、事务和 SQL migration 执行。
- `src/dashboard.py`
  Streamlit 查询后台页面，负责筛选、导出和展示官网招生信息详情。

### `src/extract/`

- `src/extract/excel_reader.py`
  读取原始 Excel，并保留源文件名、sheet 名、行号等元信息。

### `src/transform/`

- `src/transform/normalize_course_name.py`
  标准化课程名称，减少 Excel 原始文本中的格式噪音。
- `src/transform/parse_duration.py`
  把 `Duration (Years)` 解析成 `duration_min_years` / `duration_max_years`。
- `src/transform/parse_intakes.py`
  把 `Commencing Semester` 拆成结构化 intake 月份列表。
- `src/transform/parse_english_requirement.py`
  从 Excel 里的 `IELTS Academic` 文本解析总分、最低小分和不规则小分。

### `src/models/`

- `src/models/dto.py`
  导入链路用的数据对象定义，比如课程记录、admission requirement、intake 等 DTO。

### `src/load/`

- `src/load/upsert_courses.py`
  把 Excel 行转换成课程主表记录，并做幂等写入。
- `src/load/upsert_intakes.py`
  把结构化 intake 数据写入 `course_intakes`。
- `src/load/upsert_admission_requirements.py`
  把 Excel 中已有的语言要求写入 `course_admission_requirements`。

### `src/crawl/`

- `src/crawl/spider.py`
  官网招生爬虫主体，负责课程页发现、抓取课程 JSON、提取 academic / language / application 信息。
- `src/crawl/parser.py`
  对抓到的招生原文做结构化解析，比如语言成绩、申请材料、academic signals、source fingerprint。
- `src/crawl/models.py`
  爬虫结果的 Pydantic 数据模型和校验规则，防止脏数据直接写库。
- `src/crawl/storage.py`
  把爬虫产出的结构化 admissions 数据写回 `course_admission_requirements`。
- `src/crawl/seed_loader.py`
  从数据库中挑选要抓的课程种子，支持只抓缺失课程或只重跑 DLQ。
- `src/crawl/runner.py`
  启动爬虫流程，串联 seed 读取、Scrapy 执行、成功入库和失败写 DLQ。
- `src/crawl/dlq.py`
  负责把抓取失败记录写入本地 JSONL 和数据库 `course_admission_dlq`。

### `tests/`

- `tests/test_parse_duration.py`
  验证学制解析逻辑。
- `tests/test_parse_intakes.py`
  验证 intake 解析逻辑。
- `tests/test_parse_english_requirement.py`
  验证 Excel 语言要求解析和 IELTS 小分拆分逻辑。
- `tests/test_import_idempotency.py`
  验证 Excel 导入不会因为重复执行而重复写脏数据。
- `tests/test_crawl_parser.py`
  验证官网招生爬虫的 parser、Pydantic 校验和 fingerprint 逻辑。

说明：

- `__init__.py` 主要用于把目录声明成 Python 包，本身通常不承载业务逻辑。
- `__pycache__/` 是 Python 运行时自动生成的缓存目录，不需要手动维护。

## 数据表

### `courses`

主表，一行对应 Excel 的一行课程。

关键字段：

- `course_name`
- `cricos`
- `duration_min_years`
- `duration_max_years`
- `duration_raw`
- `commencing_semester_raw`
- `tuition_fee_aud`
- `source_row_hash`

### `course_intakes`

把 `Commencing Semester` 拆成多行，方便按开学季筛选。

关键字段：

- `course_id`
- `intake_month`
- `sort_order`

### `course_admission_requirements`

存语言要求和官网补全后的录取要求。

关键字段：

- `requirement_source`
- `source_url`
- `academic_requirement_text`
- `academic_requirements_json`
- `raw_english_requirement`
- `ielts_overall`
- `ielts_min_band`
- `ielts_listening`
- `ielts_reading`
- `ielts_speaking`
- `ielts_writing`
- `english_req_details`
- `application_details_json`
- `supplementary_metadata_json`
- `source_map_json`
- `source_fingerprint`

### `course_admission_dlq`

存官网抓取时暂时失败或待复核的课程。

关键字段：

- `cricos`
- `course_name`
- `source_url`
- `stage`
- `error_code`
- `error_message`
- `raw_payload_json`
- `retryable`

## 安装

```bash
cd /Users/admin/Documents/liuxue_agent\ data/usyd_pg_import
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 配置

复制 `.env.example` 为 `.env`，或直接导出环境变量：

```bash
export DATABASE_URL='postgresql://admin@127.0.0.1:5432/usyd_courses'
```

当前这台机器已经在使用这个连接串：

```text
postgresql://admin@127.0.0.1:5432/usyd_courses
```

## 执行迁移

```bash
cd /Users/admin/Documents/liuxue_agent\ data/usyd_pg_import
PYTHONPATH=. python3 -m src.cli migrate
```

## 导入 Excel

```bash
cd /Users/admin/Documents/liuxue_agent\ data/usyd_pg_import
PYTHONPATH=. python3 -m src.cli import-excel \
  --file '/Users/admin/Documents/liuxue_agent data/USYD_Postgraduate_Courses_Perfect_纠正版.xlsx'
```

首次导入时可以一起跑迁移：

```bash
PYTHONPATH=. python3 -m src.cli import-excel \
  --file '/Users/admin/Documents/liuxue_agent data/USYD_Postgraduate_Courses_Perfect_纠正版.xlsx' \
  --migrate-first
```

## 查询后台

安装完依赖后可以直接启动本地查询后台：

```bash
cd /Users/admin/Documents/liuxue_agent\ data/usyd_pg_import
source .venv/bin/activate
streamlit run src/dashboard.py
```

如果你要跑官网招生信息爬虫，还需要安装 Playwright 浏览器：

```bash
cd /Users/admin/Documents/liuxue_agent\ data/usyd_pg_import
source .venv/bin/activate
pip install -e .
playwright install chromium
```

打开命令行里显示的本地地址，通常是：

```text
http://localhost:8501
```

当前页面风格更接近查询后台，而不是仪表盘。你可以直接做这些操作：

- 按课程名或 `CRICOS` 搜索
- 按开学季筛选
- 只看已经补齐官网招生信息的课程
- 按 `Limited places`、`Portfolio`、`References`、`Personal statement` 等申请特征筛选
- 按学费区间筛选
- 按学制区间筛选
- 按 `IELTS Overall` 筛选
- 按 `IELTS 最低小分` 筛选
- 按听力 / 阅读 / 口语 / 写作单项筛选
- 只看重复 `CRICOS`
- 只看不规则 IELTS 小分课程
- 按课程名、学费、IELTS、学制排序
- 查看单门课的学术要求原文、语言测试明细、申请材料、来源链接
- 导出当前筛选结果为 CSV

## 常用 SQL

查看课程数量：

```sql
select count(*) from courses;
```

查看某个开学季的课程：

```sql
select c.course_name, c.cricos, ci.intake_month
from courses c
join course_intakes ci on ci.course_id = c.id
where ci.intake_month = 'FEB'
order by c.course_name;
```

查看 IELTS 四项小分：

```sql
select c.course_name,
       car.ielts_overall,
       car.ielts_min_band,
       car.ielts_listening,
       car.ielts_reading,
       car.ielts_speaking,
       car.ielts_writing
from courses c
join course_admission_requirements car on car.course_id = c.id
order by c.course_name;
```

查看学制区间：

```sql
select course_name,
       duration_min_years,
       duration_max_years,
       duration_raw
from courses
order by duration_max_years desc, course_name;
```

## 测试

当前测试只依赖标准库：

```bash
cd /Users/admin/Documents/liuxue_agent\ data/usyd_pg_import
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

## 爬取官网招生信息并补全 SQL

新增了 `crawl-admissions` 命令，会从 PostgreSQL 中读取课程列表，去悉尼大学官网课程页抓取：

- `Academic Requirements`
- `Language Requirements`
- `Application Details`

抓取结果会回写到 `course_admission_requirements`：

- `requirement_source='usyd_web_crawl'`
- `academic_requirement_text`
- `academic_requirements_json`
- `raw_english_requirement`
- `source_url`
- `english_req_details`（含结构化语言成绩、申请材料、来源信息）
- `application_details_json`
- `supplementary_metadata_json`
- `source_map_json`

抓取失败或待复核的课程会进入 `course_admission_dlq`，并同步写本地 `JSONL`。

基础用法：

```bash
cd /Users/admin/Documents/liuxue_agent\ data/usyd_pg_import
source .venv/bin/activate
PYTHONPATH=. python3 -m src.cli crawl-admissions --limit 20
```

常用参数：

- `--limit 20`：最多抓取多少门课
- `--include-existing`：即使已经存在 `usyd_web_crawl` 快照也重新抓
- `--retry-dlq`：只重跑当前还停留在 DLQ 的课程
- `--dlq-file var/usyd_admissions_dlq.jsonl`：校验失败或抓取失败时写本地 DLQ

说明：

- 如果 `course_admission_requirements.source_url` 已有官网课程 URL，会优先使用。
- 如果没有 URL，会优先匹配悉尼大学课程 sitemap，再回退官网搜索结果。
- 课程页抓不到明确语言分数时，会回退到悉尼大学中央英语要求页补齐标准要求。
- 当前实现会把官网结构化结果写入多个 JSONB 字段，并在查询后台直接展示。
