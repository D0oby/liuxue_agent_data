# PRD: Recommendation Runtime Compatibility And Search Diagnostics

## Problem Statement

After adding Course Feature Profile support, the dashboard and recommendation runtime can fail in environments where the database has not yet applied the new feature-profile migrations.

The observed user-facing failure is too generic:

```text
推荐失败：Recommendation request failed.
```

The underlying runtime failure is that read paths query `courses.course_features` before the local database has the column:

```text
column c.course_features does not exist
```

This creates three user problems:

1. Operators cannot use the recommendation dashboard while the Course Feature Profile rollout is partially applied.
2. The UI does not clearly explain whether the failure is caused by database migration state, vector search state, missing environment variables, or user input.
3. Search results are harder to inspect because keyword search does not consistently explain whether a course matched by official text, course metadata, or feature-profile tags.

The recommendation layer must remain usable during a staged rollout. Missing feature-profile storage should degrade to an absent profile, not crash existing recommendation flows.

## Solution

Make the recommendation dashboard and recommendation runtime tolerant of missing Course Feature Profile storage, while surfacing actionable diagnostics.

The system should:

- Continue loading course search and recommendation results when `course_features` or `course_feature_overrides` columns are missing.
- Represent missing feature profiles as `None` or an empty/default profile, following the existing model contract.
- Keep recommendation behavior read-only; the runtime must not auto-run migrations or write to ingestion tables.
- Preserve the ability to use feature profiles when the columns do exist.
- Show actionable UI messaging when the system is running in degraded feature-profile mode.
- Improve course search inspectability by including feature tags in keyword search and making search-hit explanations easier to read.
- Keep all changes testable through public interfaces and high-level repository/dashboard seams.

## User Stories

1. As a dashboard user, I want the recommendation form to still run when feature-profile migrations have not been applied, so that I can continue using the existing recommendation workflow.
2. As a dashboard user, I want a clear message when feature-profile data is unavailable, so that I understand why profile-specific tags or scores are missing.
3. As an operator, I want missing `course_features` storage to degrade safely, so that partial rollout does not block admissions matching.
4. As an operator, I want the recommendation dashboard to distinguish migration problems from vector search or OpenAI configuration problems, so that I know what to fix next.
5. As an operator, I want the system to keep reading old course records without feature profiles, so that existing production data remains valid.
6. As an operator, I want the recommendation runtime to avoid automatic database writes, so that read-only recommendation requests do not mutate ingestion data.
7. As an operator, I want a predictable migration readiness signal, so that I can verify whether Course Feature Profile storage is available.
8. As a developer, I want repository reads to use a safe fallback when feature-profile columns are absent, so that recommendation retrieval does not crash before scoring.
9. As a developer, I want failed SELECT statements to rollback before retrying fallback SQL, so that PostgreSQL transaction state does not poison the rest of the request.
10. As a developer, I want fallback behavior covered by tests, so that future schema additions do not reintroduce rollout crashes.
11. As a developer, I want tests to verify observable recommendation behavior, so that the system can be refactored without fragile implementation-coupled tests.
12. As a developer, I want course query fallback tested separately from recommendation fallback, so that failures identify the affected runtime path.
13. As a developer, I want the feature-profile model contract to remain unchanged, so that downstream matching code can treat missing profiles consistently.
14. As a recommender user, I want a course recommendation result instead of a generic failure when feature profiles are unavailable, so that I can still compare eligible programs.
15. As a recommender user, I want high-risk and excluded courses to still be shown correctly, so that feature-profile fallback does not hide admissions risk.
16. As a recommender user, I want existing GPA and IELTS hard-filter behavior to stay unchanged, so that the rollout does not alter admissions thresholds.
17. As a search user, I want keyword search to match course name, CRICOS, admissions text, application flags, language-test text, and feature tags, so that search behaves like a unified course search.
18. As a search user, I want query results to show why a course matched, so that I can trust the search output.
19. As a search user, I want feature tags visible near the course name when available, so that profile-based matches are easy to inspect.
20. As a search user, I want old databases without feature tags to still show normal search results, so that missing optional data does not create blank pages.
21. As a dashboard user, I want semantic search results to show match score, matched text, source field, and source URL, so that I can inspect admissions evidence quickly.
22. As a dashboard user, I want highlighted query terms in semantic search snippets, so that I can scan why a result was returned.
23. As an operator, I want empty semantic search results to be shown as a normal state, so that an empty vector result is not confused with a system failure.
24. As an operator, I want OpenAI/vector-store configuration failures to remain clearly reported, so that semantic search setup can be fixed independently.
25. As a maintainer, I want the fallback behavior documented in the PRD and issues, so that future agents know not to require immediate backfill.
26. As a maintainer, I want the issue slices to be small enough for TDD tracer bullets, so that each fix can be reviewed independently.
27. As a reviewer, I want acceptance criteria to include backward compatibility, so that the feature-profile rollout does not regress old data.
28. As a reviewer, I want tests for both migrated and unmigrated database shapes, so that the rollout path is explicit.
29. As a reviewer, I want no changes to source-row hashing or CRICOS deduplication, so that ingestion invariants remain intact.
30. As a reviewer, I want recommendation scoring and banding to remain configuration-driven, so that this work does not hardcode new matching rules in the dashboard.

## Implementation Decisions

- Treat Course Feature Profile storage as optional at runtime until migrations are applied.
- Preserve `CourseFeatureProfile` as the canonical schema when data exists.
- Preserve `course_features = None` as a valid state for old records and unmigrated databases.
- Do not automatically run migrations from dashboard, API, repository, or recommendation service code.
- Do not backfill feature profiles as part of a recommendation request.
- Keep repository code responsible for SQL and row mapping only.
- Keep scoring, eligibility, and plan assembly behavior outside the dashboard.
- Add a repository-level fallback for read paths that select feature-profile columns:
  - Try the normal query with real feature-profile columns.
  - If the database reports a missing feature-profile column, rollback the failed transaction.
  - Retry the same read with `null` feature-profile fields.
  - Re-raise unrelated database errors.
- Add a dashboard course-list fallback for unmigrated databases using the same behavior:
  - Try loading real feature-profile columns.
  - Retry with `null` feature-profile fields only when the missing-column error is specifically about feature-profile storage.
- Avoid broad exception swallowing. Generic database failures should still surface as failures.
- Add a user-facing degraded-mode signal when feature-profile storage is unavailable.
- Improve recommendation error messages so the UI can show actionable root causes where safe.
- Keep logs detailed enough to preserve the underlying exception chain.
- Include feature-profile tag text in course keyword search when feature-profile data exists.
- Keep course keyword search working when feature-profile data is absent.
- Show feature tags in the search results table near the course name.
- Render semantic search results as inspectable results with score, source kind, matched snippet, source URL, and query-term highlighting.
- Keep semantic search empty results separate from errors.
- Keep vector search failure behavior independent from feature-profile fallback.
- Do not change existing GPA, IELTS, intake, duration, or hard-filter formulas.
- Do not change source-row hash idempotency.
- Do not deduplicate by CRICOS.

## Testing Decisions

- Use TDD tracer bullets: one behavior, one failing test, one minimal implementation, then repeat.
- Prefer public interfaces and high-level seams over private implementation details.
- Good tests for this PRD should verify user-visible behavior:
  - A recommendation request succeeds when feature-profile storage is missing.
  - Course query data loads when feature-profile storage is missing.
  - Existing migrated databases still return stored course features.
  - Keyword search can match feature-profile tags when present.
  - Keyword search still works when feature profiles are absent.
  - Semantic search result rendering highlights query terms and escapes unsafe text.
  - Missing migration state is reported as degraded feature-profile mode, not as a generic failure.
- The primary testing seams should be:
  - Recommendation service or recommendation repository behavior for course retrieval.
  - Dashboard data-loading helpers for course query compatibility.
  - Dashboard search helper behavior for keyword matching and highlighting.
  - Existing unittest-based recommendation tests for end-to-end recommendation behavior.
- Avoid tests that assert exact SQL formatting unless they are narrowly checking the public behavior of fallback query selection.
- Use fake connections/cursors for missing-column behavior where database setup would make the test slow or brittle.
- Use real model parsing for `CourseFeatureProfile` where profile data exists.
- Keep Playwright/Streamlit interaction as smoke verification, not the main regression suite, unless the project later adds stable e2e test infrastructure.
- Run the full existing test suite after each vertical slice:

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
.venv/bin/python -m unittest discover -s tests -v
```

## Out of Scope

- Creating new course feature dimensions.
- Changing the Course Feature Profile schema.
- Changing matching weights or scoring formulas.
- Backfilling all production course profiles.
- Automatically running migrations from application runtime.
- Rebuilding Excel import, crawling, ChromaDB vectorization, or embedding pipelines.
- Adding multi-school abstractions.
- Adding ML-based admission probability.
- Reworking the whole dashboard layout.
- Closing or editing existing GitHub issues automatically.

## Further Notes

This PRD is intended to be fed into `$to-issues` and then implemented with `$tdd`.

Recommended issue slicing:

1. Add repository fallback for missing Course Feature Profile columns.
2. Add dashboard data-loading fallback and degraded-mode messaging.
3. Improve recommendation error diagnostics in the dashboard.
4. Expand course keyword search to include feature-profile tags and visible match context.
5. Improve semantic search result rendering with source metadata and highlighted snippets.
6. Add rollout smoke checks for migrated and unmigrated local databases.

Recommended first TDD tracer bullet:

```text
An existing recommendation request succeeds when the database does not yet have `courses.course_features`; the returned candidates have absent/default feature profiles instead of crashing.
```

Recommended second TDD tracer bullet:

```text
The course query dashboard data loader succeeds when feature-profile columns are missing and marks feature-profile data as unavailable/degraded.
```

Recommended third TDD tracer bullet:

```text
Course keyword search matches a stored feature-profile knowledge tag, while old courses without feature profiles still search normally.
```
