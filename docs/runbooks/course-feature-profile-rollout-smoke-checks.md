# Course Feature Profile Rollout Smoke Checks

Use this runbook when validating Course Feature Profile runtime compatibility.
The recommendation layer must stay usable during partial rollout, including
databases that have not yet applied the feature-profile migrations.

## Default Test Suite

Run the full unittest suite first:

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
.venv/bin/python -m unittest discover -s tests -v
```

Expected result:

- All tests pass.
- Missing feature-profile storage tests pass.
- Existing migrated-profile tests still pass.

Run the headed Playwright bilingual dashboard smoke test when validating the
local UI:

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
RUN_DASHBOARD_E2E=1 .venv/bin/python -m unittest tests.test_dashboard_bilingual_e2e -v
```

Expected result:

- A visible Chromium window opens.
- English is the default dashboard UI.
- Switching to Chinese updates dashboard-authored labels.
- The language remains active while moving between recommendation and course
  search workspaces.
- Documentation links point to the active language pair when available.

## Unmigrated Database Smoke Check

Use this state when the local `courses` table does not yet have
`course_features` or `course_feature_overrides`.

1. Start the dashboard:

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
.venv/bin/python -m streamlit run src/dashboard.py --server.port 8502 --server.headless true
```

2. Open:

```text
http://localhost:8502
```

3. In `推荐方案`, click `运行申请资格筛选` with the default form values.

Expected result:

- The recommendation request completes.
- The page shows candidate counts and recommendation bands.
- The page does not show only `Recommendation request failed.`
- Course feature profile data is treated as absent/defaulted.

4. Switch to `课程查询`.

Expected result:

- The course table loads.
- A warning explains that Course Feature Profile storage is unavailable until
  the `course_features` migration has been applied.
- Existing course/admissions search still works.
- Feature tag columns may be empty.

## Migrated Database Smoke Check

Use this state after applying:

- `migrations/006_course_features.sql`
- `migrations/007_course_feature_overrides.sql`

Then generate profiles for local development data:

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
.venv/bin/python -m src.cli generate-course-features --dry-run
.venv/bin/python -m src.cli generate-course-features
```

Start or refresh the dashboard and check:

- `课程查询` loads without degraded-mode warning.
- `画像标签` is visible for generated profiles.
- Searching by a feature tag, for example `data science`, returns matching
  programs such as data-focused courses when local data contains them.
- Course detail `画像特征` shows tags and 0-5 profile scores.
- `推荐方案` still returns hard-filtered recommendations.

## Semantic Search Smoke Check

In `课程查询`, use `录取要求语义搜索`.

Expected result:

- Empty semantic-search results show a normal no-results message.
- Successful results show match score, matched snippet, source kind, source
  field metadata when present, and source URL.
- Query terms are highlighted in snippets.
- OpenAI or vector-store configuration failures are shown separately from
  no-results states.

## Boundaries

These smoke checks must not:

- Modify ingestion tables.
- Change `source_row_hash`.
- Deduplicate by CRICOS.
- Automatically run migrations from dashboard or recommendation requests.
- Rebuild crawling, embedding, or vectorization pipelines unless explicitly
  invoked by the operator.
