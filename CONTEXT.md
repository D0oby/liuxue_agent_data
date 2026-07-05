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
