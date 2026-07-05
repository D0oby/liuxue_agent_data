# USYD Postgraduate Import And Recommendation Console

English is the default project documentation entry point. For Chinese, see
[README.zh.md](README.zh.md).

This project imports University of Sydney postgraduate course data into
PostgreSQL, enriches it with official admissions information, builds local
admissions search assets, and provides a Streamlit dashboard for course search
and read-only recommendation workflows.

## What This Project Does

- Imports one Excel row as one `courses` record.
- Does not deduplicate by CRICOS.
- Uses `source_row_hash` as the idempotent import key.
- Splits commencing semesters into `course_intakes`.
- Parses duration and IELTS requirements into structured fields.
- Crawls official admissions pages for academic requirements, language tests,
  application details, and source metadata.
- Stores admissions chunks in local ChromaDB for hybrid RAG retrieval.
- Provides a read-only USYD RAG + Agent recommendation layer.
- Supports Course Feature Profile JSONB storage, rule generation, manual
  overrides, matching, dashboard display, and audit checks.
- Provides a Streamlit dashboard for recommendations, course search, feature
  inspection, and exports.

## Setup

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
```

Set `DATABASE_URL` in `.env`, then run migrations:

```bash
.venv/bin/python -m src.cli migrate
```

## Run The Dashboard

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
.venv/bin/python -m streamlit run src/dashboard.py --server.port 8502 --server.headless true
```

Open:

```text
http://localhost:8502
```

## Run Tests

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
.venv/bin/python -m unittest discover -s tests -v
```

Run the headed Playwright dashboard smoke test:

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
RUN_DASHBOARD_E2E=1 .venv/bin/python -m unittest tests.test_dashboard_bilingual_e2e -v
```

## Bilingual Dashboard UI

The dashboard UI Language is session-scoped. English is the default UI. Chinese
can be selected from the dashboard header. UI Language affects only
dashboard-authored copy such as labels, buttons, table headers, warnings, and
validation messages.

UI Language does not translate official course content, admissions requirement
source text, RAG evidence snippets, course names, CRICOS values, stored feature
tags, service response schemas, logs, or diagnostic details.

## Operator Guidance

- Course Feature Profile rollout smoke checks:
  [English](docs/runbooks/course-feature-profile-rollout-smoke-checks.md) |
  [中文](docs/runbooks/course-feature-profile-rollout-smoke-checks.zh.md)
- Recommendation runtime compatibility PRD:
  [docs/prds/recommendation-runtime-compatibility-and-search-diagnostics.md](docs/prds/recommendation-runtime-compatibility-and-search-diagnostics.md)

## Key Modules

- `src/dashboard.py`: Streamlit recommendation and course-query console.
- `src/api.py`: FastAPI recommendation and course feature endpoints.
- `src/recommendation/`: read-only recommendation, retrieval, scoring, planning,
  course feature, and repository modules.
- `src/models/`: Pydantic request/response and Course Feature Profile models.
- `src/crawl/`: official admissions crawler and storage pipeline.
- `src/vector_store/`: admissions chunking, embedding, and ChromaDB storage.
- `migrations/`: PostgreSQL schema migrations.
- `tests/`: unittest coverage for import, parsing, recommendation, course
  features, and dashboard helpers.

## Boundaries

- Do not deduplicate by CRICOS.
- Do not change `source_row_hash` idempotency behavior.
- Do not write ingestion tables from the recommendation layer.
- Do not let the Agent run SQL, query ChromaDB directly, or compute scoring
  formulas.
- Keep recommendation weights, thresholds, top-k values, and output counts in
  configuration rather than hardcoding them in Agent/API/controller code.
