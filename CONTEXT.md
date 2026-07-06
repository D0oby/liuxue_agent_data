# Context

## Glossary

### UI Language

The language used by the dashboard shell and product-authored interface copy.
Changing the UI Language affects labels, buttons, tabs, table headers, helper
text, warnings, and validation messages.

The selected UI Language is session-scoped in the dashboard. It is not persisted
to the database, is not account-specific, and is not encoded in URL query
parameters for the initial version.

English is the default UI Language.

The UI Language switch belongs in the dashboard header area, aligned to the top
right of the main title. It is a global dashboard control, not a sidebar filter.

Dashboard-authored UI copy should be translated for both English and Chinese,
while domain abbreviations and standard admissions terms such as GPA, WAM,
IELTS, CRICOS, REACH, MATCH, SAFETY, AI, Data, and RAG remain unchanged.

The initial UI Language coverage includes the dashboard shell and product
copy in the recommendation and course-query workspaces: titles, captions,
workspace selectors, form labels, buttons, helper text, warnings, validation
messages, major table headers, and error messages.

It does not translate official course content, admissions requirement source
text, RAG evidence snippets, course names, CRICOS values, stored course feature
tags, or other source-of-truth data.

Recommendation service responses, repository objects, response schemas, logs,
exceptions, and test fixtures are not bilingualized by UI Language. The
dashboard may localize user-facing summaries around those values, but the
underlying service contracts and diagnostic details remain in their existing
language and shape.

End-to-end validation for UI Language behavior should use Playwright. The core
smoke path is: load the dashboard, verify English is the default UI, switch to
Chinese, verify dashboard-authored labels change, navigate the main dashboard
areas, and verify the selected language remains active within the session.

### Bilingual Project Documentation

Project-authored documentation should be available in both Chinese and English
when it describes product behavior, operator workflows, rollout steps, or
agent-ready implementation work.

English is the default documentation entry language. Chinese and English
documentation should be kept as paired files, not as mixed language sections in
one file. The UI may switch between the paired documents when documentation is
linked from the dashboard or operator workflows.

When project documentation is linked from the dashboard, the target should
follow the active UI Language: English UI links to the default English document,
Chinese UI links to the paired `.zh.md` document when it exists, and missing
Chinese pairs fall back to the English default.

The initial bilingual documentation scope covers project-authored entry and
operator guidance that users are expected to read while using or validating the
dashboard. Historical specifications, database dictionaries, and older handoff
documents are outside the initial bilingual documentation scope unless they
become active user-facing guidance.

Official source data and generated evidence are not treated as documentation
that must be translated.

### E2E Regression Suite

The E2E Regression Suite protects the full USYD data-to-dashboard workflow, not
only the visible dashboard UI. Its scope includes Excel import, database
migrations, official admissions crawl behavior, admissions chunking and vector
storage, recommendation retrieval and scoring, Course Feature Profile behavior,
and the Streamlit dashboard user flows.

The suite verifies the integrated workflow as an operator/user would experience
it. It is broader than a Dashboard smoke test and broader than isolated unit or
module integration tests.

The default E2E Regression Suite is hermetic: it uses local fixtures, a local
test database, deterministic embedding behavior, temporary vector storage, and
Playwright against a local Streamlit dashboard. It should be repeatable without
external network access.

The hermetic E2E Regression Suite must use an isolated database. It must not
reuse the developer or production `DATABASE_URL`. The suite should read an
explicit E2E database configuration, run migrations and fixture ingestion there,
and clean up its own state without writing to normal project data.

The default hermetic fixture set should be small and representative rather than
a full production Excel import. It should cover a few courses across distinct
domains, admissions outcomes, application-detail cases, intakes, fees, and
durations so regressions are easy to understand and the suite remains fast.

The default browser mode for the E2E Regression Suite is headless. Headed
browser execution is only a local debugging option and is not the default
regression gate.

The E2E Regression Suite should have a single operator-facing command. That
entry point orchestrates migrations, fixture import, admissions enrichment,
chunk/vector preparation, Course Feature Profile generation, recommendation
checks, and Streamlit/Playwright dashboard checks in order.

In the hermetic E2E Regression Suite, admissions crawl coverage means fixture
admissions content is parsed and stored through the project ingestion path so
later recommendation and dashboard checks consume realistic admissions data. It
does not mean the default suite visits the live USYD website.

In the hermetic E2E Regression Suite, embedding behavior should be deterministic
and local. The suite should still exercise real admissions chunking, vector
storage, ChromaDB search, hybrid retrieval, and vector-unavailable fallback
behavior without calling external embedding APIs by default.

The primary E2E Regression Suite entry points are the Python recommendation
service path and the Streamlit dashboard path. FastAPI endpoint coverage is a
thin schema smoke layer, not the central orchestration path for the full suite.

The E2E Regression Suite should produce failure artifacts under an E2E artifacts
directory. Useful artifacts include Playwright screenshots, optional traces or
videos, server logs, and a run summary with failed stage, course identifiers,
queries, and diagnostic messages. Temporary vector storage and database state
are cleaned by default unless an explicit keep-artifacts option is enabled.

The hermetic E2E Regression Suite is suitable for optional, nightly, or manual
CI workflows and local operator validation. It is not the default lightweight
test gate for every small change. Live external smoke checks are manual only.

Live external smoke checks are separate and manual. They may call the real USYD
website or external embedding APIs, must require an explicit opt-in flag, and
are not part of the default regression gate.
