# USYD 研究生课程导入与推荐工作台

英文是默认项目文档入口。英文文档见 [README.md](README.md)。

本项目把悉尼大学研究生课程 Excel 数据导入 PostgreSQL，使用官网招生信息做补全，构建本地招生检索资产，并提供 Streamlit Dashboard 用于课程查询和只读推荐流程。

## 项目能力

- 一行 Excel 对应一条 `courses` 记录。
- 不按 CRICOS 去重。
- 使用 `source_row_hash` 作为幂等导入键。
- 将开学季拆分到 `course_intakes`。
- 将学制和 IELTS 要求解析成结构化字段。
- 爬取官网招生页，补全学术要求、语言要求、申请材料和来源元数据。
- 将招生文本切块并写入本地 ChromaDB，用于 Hybrid RAG 召回。
- 提供只读 USYD RAG + Agent 推荐层。
- 支持 Course Feature Profile JSONB 存储、规则生成、人工覆盖、匹配、Dashboard 展示和审计。
- 提供 Streamlit Dashboard，用于推荐方案、课程查询、画像查看和导出。

## 环境准备

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
```

在 `.env` 中配置 `DATABASE_URL`，然后执行 migration：

```bash
.venv/bin/python -m src.cli migrate
```

## 运行 Dashboard

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
.venv/bin/python -m streamlit run src/dashboard.py --server.port 8502 --server.headless true
```

打开：

```text
http://localhost:8502
```

## 运行测试

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
.venv/bin/python -m unittest discover -s tests -v
```

运行 headed Playwright Dashboard 烟测：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
RUN_DASHBOARD_E2E=1 .venv/bin/python -m unittest tests.test_dashboard_bilingual_e2e -v
```

## Dashboard 双语 UI

Dashboard UI Language 是 session 级状态。默认语言是英文，用户可以在 Dashboard header 中切换到中文。UI Language 只影响 Dashboard 自己写的界面文案，例如标签、按钮、表头、提示和校验信息。

UI Language 不翻译官方课程内容、招生要求原文、RAG evidence、课程名、CRICOS、已存储画像标签、服务响应 schema、日志或诊断细节。

## 运维说明

- Course Feature Profile rollout smoke checks：
  [English](docs/runbooks/course-feature-profile-rollout-smoke-checks.md) |
  [中文](docs/runbooks/course-feature-profile-rollout-smoke-checks.zh.md)
- Hermetic E2E regression suite：
  [English](docs/runbooks/e2e-regression-suite.md) |
  [中文](docs/runbooks/e2e-regression-suite.zh.md)
- Recommendation runtime compatibility PRD：
  [docs/prds/recommendation-runtime-compatibility-and-search-diagnostics.md](docs/prds/recommendation-runtime-compatibility-and-search-diagnostics.md)

## 关键模块

- `src/dashboard.py`：Streamlit 推荐和课程查询工作台。
- `src/api.py`：FastAPI 推荐和课程画像接口。
- `src/recommendation/`：只读推荐、召回、评分、计划组装、课程画像和 repository。
- `src/models/`：Pydantic 请求/响应和 Course Feature Profile model。
- `src/crawl/`：官网招生爬虫和入库链路。
- `src/vector_store/`：招生文本切块、embedding 和 ChromaDB 存储。
- `migrations/`：PostgreSQL schema migration。
- `tests/`：导入、解析、推荐、课程画像和 Dashboard helper 的 unittest 覆盖。

## 边界

- 不按 CRICOS 去重。
- 不修改 `source_row_hash` 幂等规则。
- 推荐层不写 ingestion 表。
- 不让 Agent 直接执行 SQL、直接查询 ChromaDB 或计算评分公式。
- 推荐权重、阈值、Top-K 和输出数量必须来自配置，不能硬编码在 Agent/API/controller 中。
