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
- 爬虫长文本可切块、生成 embedding，并写入本地 ChromaDB 向量库
- 只读 USYD RAG + Agent MVP 推荐层，可输出 reach / match / safety / excluded 方案
- 课程画像特征层支持 JSONB 存储、规则生成、人工覆盖、用户画像匹配、Dashboard 展示/编辑和审计
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
- `005_admission_vector_chunks.sql`
  历史 pgvector 迁移，当前向量索引默认改为 ChromaDB 本地持久化 collection。
- `006_course_features.sql`
- `007_course_feature_overrides.sql`
  在 `courses` 表上新增可空 `course_feature_overrides` JSONB 字段，用于保存人工覆盖。

### `src/`

- `src/cli.py`
  项目命令入口，负责 `migrate`、`import-excel`、`crawl-admissions` 这几个命令。
- `src/config.py`
  读取环境变量和运行配置。
- `src/db.py`
  管理 PostgreSQL 连接、事务和 SQL migration 执行。
- `src/dashboard.py`
  Streamlit 查询后台页面，负责筛选、导出和展示官网招生信息详情。
- `src/api.py`
  FastAPI 推荐 API 入口，提供推荐、课程画像读取/生成/编辑、画像匹配和画像筛选接口。
- `src/recommendation/`
  只读推荐决策层，包含 Repository、RAG 检索、要求标准化、评分、分档、计划组装和单体 PlanningAgent。

### `src/recommendation/`

- `src/recommendation/service.py`
  推荐层服务入口，负责加载配置、创建数据库连接、组装默认 `PlanningAgent`，并把推荐流程结果包装成 `RecommendationResponse`。
- `src/recommendation/agent.py`
  单体 `PlanningAgent` 和固定工具封装，只负责按顺序编排用户画像解析、候选召回、要求标准化、评分和方案生成。
- `src/recommendation/profile.py`
  把 `RecommendationRequest` 解析成内部 `UserProfile`，并标准化 `preferred_intake`，例如 `S1`、`Feb`、`Semester 2`。
- `src/recommendation/query_builder.py`
  根据目标方向生成关键词查询和语义查询，当前内置计算机、数据分析、商科等方向映射。
- `src/recommendation/retrieval.py`
  Hybrid RAG 召回逻辑，包含关键词检索、向量检索、候选合并、证据片段保留和向量不可用时的降级标记。
- `src/recommendation/repository.py`
  推荐层只读 Repository，负责读取 `courses`、`course_intakes` 和 `course_admission_requirements`，并映射为检索/要求对象；语义召回由 ChromaDB collection 提供。
- `src/recommendation/requirements.py`
  招生要求标准化服务，负责从当前录取要求中解析 IELTS，并按悉尼大学国内院校口径生成可计算 GPA 阈值。
- `src/recommendation/scoring.py`
  GPA/IELTS 配置化评分和 `REACH`、`MATCH`、`SAFETY` 分档逻辑，同时把无法评分课程转入排除列表。
- `src/recommendation/plan.py`
  推荐方案组装器，按分档、检索相关度、预算、学制、intake 和 IELTS 小分硬门槛生成最终项目列表与排除原因。
- `src/recommendation/course_features.py`
  课程画像规则生成、人工覆盖合并、画像匹配、画像筛选和审计逻辑。
- `src/recommendation/feature_repository.py`
  课程画像读写、批量生成选择和审计数据读取。

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
- `src/models/recommendation.py`
  推荐链路用的 Pydantic schema，定义请求、用户画像、检索命中、候选课程、标准化要求、评分结果、推荐项目、排除项目和最终响应。
- `src/models/course_features.py`
  课程画像、用户画像、匹配结果和审计结果 schema，标签字段安全默认为空数组，0-5 分字段有范围校验。
- `src/models/feature_taxonomy.py`
  集中管理规则生成使用的标签关键词映射。

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

### `courses.course_features` / `courses.course_feature_overrides`

课程画像特征的可空 JSONB 字段。`course_features` 保存当前有效画像，`course_feature_overrides` 保存人工覆盖字段。规则生成会保留人工覆盖，除非调用方明确替换。

关键字段由 `CourseFeatureProfile` 约束：

- `discipline_tags`
- `knowledge_tags`
- `career_tags`
- `background_fit_tags`
- `math_intensity`
- `coding_intensity`
- `theory_intensity`
- `business_intensity`
- `ai_relevance`
- `data_relevance`
- `conversion_friendliness`
- `risk_level`

## 课程画像特征

批量生成缺失画像：

```bash
PYTHONPATH=. python -m src.cli generate-course-features
```

审计画像质量：

```bash
PYTHONPATH=. python -m src.cli audit-course-features
```

常用 API：

- `GET /courses/{course_id}/features`
- `POST /courses/{course_id}/generate-features`
- `PATCH /courses/{course_id}/features`
- `POST /courses/match`
- `GET /courses/filter-features`

上线顺序：

1. 运行 migration。
2. 运行 `generate-course-features --dry-run` 检查生成数量。
3. 运行 `generate-course-features` 写入缺失画像。
4. 运行 `audit-course-features` 检查缺失、空标签、全零分数和高风险 outlier。

### ChromaDB collection: `course_admission_chunks`

存 RAG / 语义检索用的招生文本块和 embedding，默认持久化到 `var/chroma`。每条 record 的 document 是 chunk 正文，embedding 由外部 embedding client 生成，metadata 用来保留课程和招生来源信息。

关键 metadata：

- `course_id`
- `requirement_id`
- `chunk_kind`：`academic` / `english` / `application`
- `content_hash`
- `course_name`
- `cricos`
- `source_url`
- `embedding_model`
- `embedded_at`

## 安装

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 配置

复制 `.env.example` 为 `.env`，或直接导出环境变量：

```bash
export DATABASE_URL='postgresql://admin@127.0.0.1:5432/usyd_courses'
export OPENAI_API_KEY='sk-...'
```

当前这台机器已经在使用这个连接串：

```text
postgresql://admin@127.0.0.1:5432/usyd_courses
```

推荐层配置默认值如下，可在 `.env` 或环境变量中覆盖：

```bash
RECOMMENDATION_SCORING_GPA_WEIGHT=0.7
RECOMMENDATION_SCORING_IELTS_WEIGHT=0.3
RECOMMENDATION_BAND_REACH_UPPER=0.95
RECOMMENDATION_BAND_MATCH_UPPER=1.1
RECOMMENDATION_RETRIEVAL_KEYWORD_TOP_K=30
RECOMMENDATION_RETRIEVAL_VECTOR_TOP_K=30
RECOMMENDATION_RETRIEVAL_FINAL_CANDIDATE_LIMIT=50
RECOMMENDATION_OUTPUT_MAX_PROGRAMS_PER_BAND=5
RECOMMENDATION_RULES_ENABLE_IELTS_BAND_GATE=true
```

## 执行迁移

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
PYTHONPATH=. python3 -m src.cli migrate
```

## 导入 Excel

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
PYTHONPATH=. python3 -m src.cli import-excel \
  --file '/Users/admin/Documents/liuxue_agent real/data/usyd_postgraduate_courses_corrected.xlsx'
```

首次导入时可以一起跑迁移：

```bash
PYTHONPATH=. python3 -m src.cli import-excel \
  --file '/Users/admin/Documents/liuxue_agent real/data/usyd_postgraduate_courses_corrected.xlsx' \
  --migrate-first
```

## 查询后台

安装完依赖后可以直接启动本地查询后台：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
source .venv/bin/activate
streamlit run src/dashboard.py
```

如果你要跑官网招生信息爬虫，还需要安装 Playwright 浏览器：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
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
- 在首页搜索框按自然语言检索向量化后的录取要求
- 侧边栏关键词可同时搜索课程名、`CRICOS`、学术要求、语言要求和申请材料
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
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

## 提交到 GitHub

这个项目已经配置成通过 `SSH` 推送到 GitHub，远程仓库是：

```text
git@github.com:D0oby/liuxue_agent_data.git
```

### 日常提交

如果只是提交当前项目里的改动，直接运行：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
./scripts/git_quick_push.sh "你的提交说明"
```

这个脚本会自动执行：

- `git add .`
- `git commit -m "..."`
- `git push`

### 手动提交

如果你想自己分步执行：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
git status -sb
git add .
git commit -m "你的提交说明"
git push
```

### 首次 SSH 配置说明

当前这台机器已经完成以下配置：

- 生成 GitHub SSH key
- 在 `~/.ssh/config` 中指定 GitHub 使用专用 key
- 仓库 `origin` 已切换到 SSH remote
- Git 默认分支已设为 `main`

如果以后换新电脑，核心步骤就是：

1. 生成 SSH key
2. 把公钥加到 GitHub SSH keys
3. 把仓库 remote 设成 `git@github.com:D0oby/liuxue_agent_data.git`
4. 验证 `ssh -T git@github.com`

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
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
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

## 转成向量数据库

向量库使用 ChromaDB 本地持久化格式，默认写入 `var/chroma` 下的 `course_admission_chunks` collection。PostgreSQL 继续保存课程、intake 和招生要求等结构化数据，不再依赖 pgvector 扩展做语义召回。

可用环境变量：

- `CHROMA_PERSIST_DIRECTORY`：ChromaDB 本地持久化目录，默认 `var/chroma`
- `CHROMA_COLLECTION_NAME`：招生 chunk collection 名，默认 `course_admission_chunks`

先确认依赖和数据库迁移已就绪：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
source .venv/bin/activate
pip install -e .
PYTHONPATH=. python3 -m src.cli migrate
```

先做一次 dry run，确认会处理多少课程和文本块：

```bash
PYTHONPATH=. python3 -m src.cli vectorize-admissions --dry-run
```

正式生成 embedding 并写入 ChromaDB collection：

```bash
export OPENAI_API_KEY='sk-...'
PYTHONPATH=. python3 -m src.cli vectorize-admissions
```

常用参数：

- `--limit 20`：先只向量化少量课程做测试
- `--source all`：不只处理爬虫数据，也处理 Excel seed 数据
- `--force`：即使已有相同文本块也重新生成 embedding
- `--max-chars 1200` / `--overlap-chars 160`：控制长文本切块大小和重叠

语义搜索验证：

```bash
PYTHONPATH=. python3 -m src.cli search-admissions "哪些课程需要作品集或个人陈述？" --top-k 5
```

## USYD RAG + Agent 推荐 API

推荐层只读现有 PostgreSQL 数据表：`courses`、`course_intakes`、`course_admission_requirements`；语义 evidence 从 ChromaDB `course_admission_chunks` collection 召回。它不会重建 Excel 导入或官网爬虫，也不会按 `CRICOS` 去重；候选课程合并主键是 `course_id`。

国内院校 GPA/均分按 `/Users/admin/Documents/澳大利亚八大硕士入学要求-2026.pdf` 中悉尼大学口径处理：使用所有科目的算术平均分。当前规则覆盖：

- 工程与计算机学院常见课程：`C9/Tier1/985/211 = 75%`，`双非/其他国内院校 = 80%`。
- 商学院核心课程（Commerce / Professional Accounting）：`C9/Tier1 = 65%`，`985/211 = 75%`，`双非/其他国内院校 = 87%`。
- 其他未细分课程默认沿用 `C9/Tier1/985/211 = 75%`，`双非/其他国内院校 = 80%`，并在推荐解释中保留“悉尼大学：所有科目的算术平均分”口径。

启动 API：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
source .venv/bin/activate
pip install -e .
PYTHONPATH=. uvicorn src.api:app --reload --port 8000
```

如果 `OPENAI_API_KEY` 或 ChromaDB collection 不可用，系统会降级为关键词检索，并在响应 `metadata.degraded_retrieval` 标记为 `true`。

请求示例：

```bash
curl -X POST http://127.0.0.1:8000/recommendations/usyd \
  -H 'Content-Type: application/json' \
  -d '{
    "target_major_keyword": "计算机",
    "gpa_user": 82,
    "ielts_overall_user": 7.0,
    "ielts_min_band_user": 6.5,
    "academic_background": "双非",
    "preferred_intake": ["FEB", "JUL"],
    "budget_range": {"min": 0, "max": 70000},
    "duration_preference": {"min": 1, "max": 2}
  }'
```

响应结构示例：

```json
{
  "user_profile": {
    "target_major_keyword": "计算机",
    "gpa_user": 82,
    "ielts_overall_user": 7.0,
    "ielts_min_band_user": 6.5,
    "academic_background": "双非",
    "preferred_intake": ["FEB", "JUL"],
    "budget_range": {"min": 0, "max": 70000},
    "duration_preference": {"min": 1, "max": 2}
  },
  "query_summary": {
    "keyword_query": "computer science OR information technology OR computing OR software engineering OR artificial intelligence OR data systems",
    "semantic_query": "Master programs related to computer science, IT, software engineering, AI and data systems",
    "candidate_count": 12,
    "degraded_retrieval": false
  },
  "reach_programs": [],
  "match_programs": [
    {
      "course_id": "uuid",
      "course_name": "Master of Computer Science",
      "cricos": "123456A",
      "duration": "1.5 years",
      "intakes": ["FEB", "JUL"],
      "tuition_fee_aud": 56000,
      "ielts_requirement": "IELTS 6.5 overall, minimum band 6",
      "academic_requirement_summary": "Admission requires a bachelor's degree...",
      "score": 1.0412,
      "band": "MATCH",
      "recommendation_reason": "GPA, IELTS, relevance, evidence and source explanation.",
      "evidence_snippets": [{"text": "Admission evidence...", "source_url": "https://www.sydney.edu.au/...", "source": "academic"}],
      "source_url": "https://www.sydney.edu.au/..."
    }
  ],
  "safety_programs": [],
  "excluded_programs": [
    {
      "course_id": "uuid",
      "course_name": "Course with missing data",
      "reason": "missing_requirement",
      "details": "Current admission requirement is missing for this course.",
      "source_url": null,
      "evidence_snippets": []
    }
  ],
  "metadata": {
    "request_id": "uuid",
    "model_version": "usyd-rag-agent-mvp-v1",
    "candidate_count": 12,
    "scored_candidate_count": 8,
    "degraded_retrieval": false,
    "scoring_config": {}
  },
  "explanation": "Generated reach, match and safety recommendations with explicit exclusions."
}
```

测试推荐层和现有链路：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
```

课程画像 rollout 验证步骤见
[`docs/runbooks/course-feature-profile-rollout-smoke-checks.md`](docs/runbooks/course-feature-profile-rollout-smoke-checks.md)。
