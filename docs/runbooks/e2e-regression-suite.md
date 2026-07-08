# Hermetic E2E Regression Suite

English is the default entry document. Chinese pair:
[e2e-regression-suite.zh.md](e2e-regression-suite.zh.md).

## Default Command

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
E2E_DATABASE_URL='postgresql://localhost/usyd_pg_import_e2e' \
  .venv/bin/python -m src.cli e2e-regression
```

`E2E_DATABASE_URL` must point to an isolated E2E database. The suite never
falls back to normal `DATABASE_URL`; if no explicit E2E database is provided,
the run fails at `database_guard`.

## What The Suite Runs

The default hermetic run executes these stages:

1. `database_guard`
2. `migrations`
3. `fixture_excel_import`
4. `admissions_fixture_enrichment`
5. `deterministic_vector_retrieval`
6. `course_feature_profiles`
7. `recommendation_service`
8. `api_schema_smoke`
9. `dashboard_playwright`

The fixture set is small and representative. It covers data or AI, business
analytics, application-material and risky or ineligible scenarios, with varied
intakes, fees and durations.

## Hermetic Behavior

The suite uses local fixture Excel data, local admissions fixture content,
deterministic local embeddings, temporary ChromaDB storage and a local
Streamlit dashboard. It does not call live USYD pages or external embedding
APIs by default.

Temporary fixture and vector state is cleaned after the run. Use
`--keep-artifacts` only when debugging.

## Artifacts

Run summaries, Streamlit logs and Playwright screenshots are written under:

```text
var/e2e_artifacts/<run-id>/
```

Every run writes `summary.json`. Dashboard failures also keep
`dashboard_failure.png` when Playwright can capture the page.

## Browser Mode

Playwright is headless by default:

```bash
E2E_DATABASE_URL='postgresql://localhost/usyd_pg_import_e2e' \
  .venv/bin/python -m src.cli e2e-regression
```

Use headed mode only for local debugging:

```bash
E2E_DATABASE_URL='postgresql://localhost/usyd_pg_import_e2e' \
  .venv/bin/python -m src.cli e2e-regression --headed --keep-artifacts
```

If browser dependencies are unavailable and you only need non-UI validation:

```bash
E2E_DATABASE_URL='postgresql://localhost/usyd_pg_import_e2e' \
  .venv/bin/python -m src.cli e2e-regression --skip-dashboard
```

## CI Usage

This suite is suitable for optional, nightly or manual CI. It is not the default
lightweight test gate for every small change. CI should create a disposable E2E
database, set `E2E_DATABASE_URL`, run the default command, and upload
`var/e2e_artifacts` on failure.

## Live Smoke

Live external smoke checks are separate and manual-only. They may call the real
USYD website or external embedding APIs only with an explicit operator opt-in
and must not be treated as the default regression gate.
