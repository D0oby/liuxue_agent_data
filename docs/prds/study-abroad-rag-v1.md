# PRD: Study Abroad Knowledge RAG V1

## Problem Statement

The project has a simple search path and a USYD-specific recommendation layer, but it does not yet have a reusable Study Abroad Knowledge RAG for broader study-abroad evidence.

The next corpus will include official university and government sources, study-abroad posts, student experience content, verified internal cases, and anonymous internal summaries. These sources need different retrieval, ranking, privacy, freshness, and attribution rules from the existing USYD admissions recommendation workflow.

The current risk is that a broader RAG system could become a loose search utility that mixes official requirements, public forum posts, and anonymous internal records without clear source boundaries. That would make it hard for an agent to explain why a result was trusted, whether raw evidence can be returned, whether the source is current, and whether a result is appropriate for a given query intent.

## Solution

Build Study Abroad Knowledge RAG V1 as an independent retrieval-only module inspired by Semble's deep-module shape.

The module should expose a narrow Python API for building an index from manifest-backed sources, searching, finding related evidence, and formatting flat serializable results. Internally it should hide source loading, chunking, sparse search, dense search, RRF fusion, Ranking Policy, privacy handling, and cache metadata.

V1 should return Study Abroad Search Results, not final answers or recommendation plans. The Answer Generation Layer remains caller-owned and must cite retrieved Evidence Snippets.

The system should:

- Index only Study Abroad Sources declared in a Source Manifest.
- Require minimum source metadata before indexing.
- Support Markdown, HTML, and manifest-backed CSV or JSONL records in V1.
- Keep the new index storage separate from the existing USYD admissions vector collection.
- Use RRF for dense/sparse fusion, then apply a configurable Ranking Policy.
- Return `rrf_score`, `final_score`, and `ranking_reasons` for every returned result.
- Respect Privacy Level rules, especially for Anonymous Internal Sources.
- Use deterministic unittest coverage and TDD tracer bullets for implementation.
- Avoid MCP tooling in V1.
- Avoid integration with the existing USYD recommendation runtime in V1.

## User Stories

1. As a planning agent caller, I want to search study-abroad evidence through one stable Python interface, so that I do not need to know how the index loads, chunks, embeds, ranks, or formats sources.
2. As a planning agent caller, I want search results to include traceable Evidence Snippets, so that generated answers can cite where each fact came from.
3. As a planning agent caller, I want search results to include source metadata, so that I can distinguish official policy evidence from student experience evidence.
4. As a planning agent caller, I want search results to include `ranking_reasons`, so that I can debug why a source was boosted or penalized.
5. As a planning agent caller, I want final answers to remain outside the RAG index, so that retrieval can be tested without LLM behavior.
6. As a developer, I want Study Abroad Knowledge RAG to be independent from the USYD Recommendation Layer, so that broader corpus work does not change admissions scoring behavior.
7. As a developer, I want the new RAG module to use a narrow public API, so that internal ranking and storage choices can evolve without breaking callers.
8. As a developer, I want the new RAG module to use an independent index namespace, so that source schemas and privacy rules do not mix with USYD admissions chunks.
9. As a developer, I want source loading to be manifest-backed, so that every indexed source has explicit identity, type, locator, freshness, trust, privacy, and language metadata.
10. As a developer, I want invalid manifest entries to be rejected before indexing, so that low-quality source metadata cannot silently produce untraceable evidence.
11. As a developer, I want Markdown sources to produce stable locators, so that Evidence Snippets can point back to headings or sections.
12. As a developer, I want HTML sources to produce stable locators, so that official pages and captured web content remain inspectable.
13. As a developer, I want CSV and JSONL records to produce stable locators, so that curated posts and internal summaries can be indexed as records without direct database coupling.
14. As a developer, I want V1 to avoid PDF, Excel, dynamic crawling, and direct database loaders, so that the first implementation can stabilize core retrieval behavior.
15. As a search user, I want exact names, schools, programs, visa terms, scores, costs, and dates to match well, so that precise factual queries are not lost in semantic search.
16. As a search user, I want semantic intent queries to retrieve relevant broader evidence, so that planning questions can find useful content without exact wording.
17. As a search user, I want Chinese, English, mixed-language, numeric, and phrase tokens to work in sparse search, so that common study-abroad queries behave predictably.
18. As a search user, I want dense-only and sparse-only matches to survive hybrid fusion, so that useful evidence is not discarded too early.
19. As a reviewer, I want RRF fusion to stay separate from Ranking Policy, so that retrieval mechanics and domain trust rules can be tested separately.
20. As a reviewer, I want each candidate to receive `rrf_score` before Ranking Policy is applied, so that score provenance is inspectable.
21. As a reviewer, I want Ranking Policy to compute `final_score`, so that study-abroad trust, freshness, intent, privacy, and saturation rules are explicit.
22. As a reviewer, I want Ranking Policy rules to be configuration-driven, so that boosts and penalties are not hardcoded in search logic.
23. As a reviewer, I want requirement, deadline, fee, and policy queries to strongly prefer official university, government, and handbook evidence, so that high-risk facts use authoritative sources.
24. As a reviewer, I want applicant-fit and chance-estimation queries to use internal case evidence only as supplemental context, so that internal cases do not override official requirements.
25. As a reviewer, I want program recommendation queries to consider curriculum, career, and background fit evidence, so that ranking does not collapse into "which program is easiest to enter."
26. As a reviewer, I want student experience queries to allow student experience posts and anonymous summaries to rank higher, so that lived-experience questions are answered with appropriate evidence.
27. As a reviewer, I want public forum posts to be lower ranked by default, so that unofficial evidence does not dominate factual or policy queries.
28. As a reviewer, I want stale sources to be penalized, so that old requirements, fees, deadlines, and policy pages do not outrank current evidence.
29. As a reviewer, I want missing metadata to reduce score or block indexing where required, so that poor source quality is visible instead of hidden.
30. As a reviewer, I want same-source saturation, so that the top results are not filled by one domain, one source type, or one document.
31. As a privacy reviewer, I want raw anonymous internal records to be blocked from display by default, so that anonymity is not treated as permission to quote sensitive data.
32. As a privacy reviewer, I want anonymous summaries to be returnable only when Privacy Level allows it, so that internal evidence can be useful without exposing raw records.
33. As a privacy reviewer, I want evidence containing personal identifiers to be blocked from raw return, so that privacy-sensitive material cannot leak through search.
34. As an operator, I want cache metadata to describe source hashes, schema version, chunker version, tokenizer version, model name, and creation time, so that stale indexes can be detected.
35. As an operator, I want persistent cache to be optional in V1, so that the first implementation can focus on correctness before storage optimization.
36. As a developer, I want embedding and vector storage behind narrow protocols, so that tests can use deterministic embedders and production can use configured backends.
37. As a developer, I want no external embedding API calls in unit tests, so that the test suite is deterministic and fast.
38. As a developer, I want no MCP layer in V1, so that the Python API and result schema can stabilize before tool contracts are introduced.
39. As a maintainer, I want no integration with RecommendationService or PlanningAgent in V1, so that existing USYD recommendation behavior remains unchanged.
40. As a maintainer, I want the implementation broken into TDD tracer bullets, so that each issue produces a verifiable vertical slice.

## Implementation Decisions

- Build Study Abroad Knowledge RAG as a separate retrieval module, not as an expansion of the existing USYD Recommendation Layer.
- Treat the module as retrieval-only. It returns Study Abroad Search Results and does not generate final answers, admissions advice, or conflict-resolved conclusions.
- Use Source Manifests as the only V1 source inventory. The module does not scan future business database tables directly.
- Require each indexable source to provide source identity, source type, title, source locator, content locator, freshness metadata, Trust Tier, language, and privacy metadata where needed.
- Allow optional filtering metadata such as country, institution, program, degree level, intake, and tags.
- Support only Markdown, HTML, and manifest-backed CSV or JSONL records in V1.
- Defer PDF, Excel, dynamic web crawling, and direct database loaders.
- Keep new index storage independent from the existing USYD admissions vector collection.
- Define narrow protocols for embedding, dense search, sparse search, and index storage.
- Default runtime implementations may use the existing stack where appropriate, but core retrieval and ranking should not depend directly on external services.
- Keep the public Python API narrow: construct an index from sources or a path, search it, find related evidence, and format results.
- Do not expose fusion weights directly in the public API. Query intent and configuration control ranking behavior.
- Use RRF for hybrid fusion and keep domain-specific boosts and penalties out of the fusion layer.
- Apply Ranking Policy after fusion. Each candidate gets an `rrf_score`; Ranking Policy computes `final_score`.
- Ranking Policy owns trust-tier boosts, source-type boosts, source-type penalties, staleness penalties, filter-match boosts, mismatch penalties, privacy penalties, same-source saturation, and query-intent boosts.
- Every result must include `ranking_reasons` that explain meaningful boosts and penalties.
- Official university, official government, and course handbook sources define factual boundaries for requirements, English requirements, fees, deadlines, visa, and policy queries.
- Verified internal case and anonymous internal summary evidence can support applicant fit, chance estimation, background similarity, and student experience, but cannot override official requirements.
- Public forum and social experience sources default to lower trust and should be boosted only for student experience or lived-experience query intent.
- Anonymous Internal Sources cannot return raw evidence by default.
- Privacy Level controls whether raw text, redacted text, summary-only evidence, or no displayable content can be returned.
- Evidence with personal identifiers is not returnable as raw evidence.
- Same-source saturation prevents one source, source type, or domain from occupying too many top-ranked results.
- Cache metadata must model schema version, chunker version, tokenizer version, model name, source manifest hash, source content hashes, and creation time.
- Full persistent cache optimization is not required for the first slice, but cache invalidation decisions must be testable.
- Do not build an MCP layer in V1.
- Do not wire V1 into the existing recommendation runtime, dashboard recommendation flow, or USYD scoring and eligibility logic.

## Testing Decisions

- Use TDD tracer bullets: one failing behavior test, one minimal implementation, then repeat.
- Use the public Study Abroad Knowledge RAG Python API as the primary test seam.
- Use result formatting as the secondary public seam.
- Tests should verify behavior through public interfaces rather than private loader, chunker, ranking, or fusion implementation details.
- Mock only system boundaries: embedding generation, time, and filesystem setup where necessary.
- Do not mock internal modules owned by the Study Abroad Knowledge RAG package.
- Use the project's existing `unittest` style rather than introducing pytest fixtures for V1.
- Use a small deterministic fixture corpus with official sources, forum posts, anonymous internal summaries, stale sources, and metadata edge cases.
- Use a deterministic mock embedder so dense retrieval behavior is stable and does not call external APIs.
- Cover manifest validation: missing required metadata prevents indexing.
- Cover source loading and chunk locators for Markdown, HTML, CSV, and JSONL.
- Cover sparse tokenization for Chinese, English, mixed-language queries, numeric phrases, institution names, fees, and dates.
- Cover hybrid retrieval so dense-only and sparse-only matches can appear after RRF fusion.
- Cover Ranking Policy for requirement, deadline, fee, policy, applicant-fit, program-recommendation, and student-experience query intent.
- Cover privacy handling so raw anonymous internal evidence is not returned by default.
- Cover same-source saturation so repeated chunks from one source cannot dominate the top results.
- Cover formatter output so callers receive flat JSON-compatible results without internal index objects.
- Cover cache metadata invalidation decisions for schema version, chunker version, tokenizer version, model name, manifest hash, and source content hash changes.
- Run the relevant Study Abroad Knowledge RAG tests after each tracer bullet.
- Run the full existing unittest suite before the implementation is considered complete.

## Out of Scope

- MCP server or MCP tools.
- Final answer generation.
- Admission decision generation.
- Integration with RecommendationService, PlanningAgent, or existing USYD scoring.
- Writing to ingestion tables.
- Rebuilding the existing Excel import, crawler, admissions chunking, or `course_admission_chunks` vectorization path.
- PDF loaders.
- Excel loaders.
- Dynamic website crawling.
- Direct business database scanning as a source loader.
- Multi-agent orchestration.
- Multi-school recommendation scoring.
- ML-based admission probability.
- Returning raw anonymous internal records by default.
- Hardcoding ranking weights inside search logic.
- Exposing dense/sparse fusion internals to callers.

## Further Notes

The confirmed design is recorded across ADR 0001 through ADR 0015.

Recommended implementation order:

1. Define public DTOs, Source Manifest validation, and flat formatting.
2. Implement Markdown, HTML, CSV, and JSONL loading with stable locators.
3. Implement multilingual sparse tokenization and sparse search.
4. Implement embedder protocol and deterministic dense search path.
5. Implement RRF fusion and public search behavior.
6. Implement Ranking Policy with query intent, trust, source type, freshness, privacy, mismatch, filter, and saturation rules.
7. Implement Privacy Level enforcement for returned evidence.
8. Implement cache metadata and invalidation checks.
9. Add `find_related` behavior through the public API.
10. Run full verification.

The first TDD tracer bullet should prove that a manifest-backed official source can be indexed and searched through the public Python API, returning a flat Evidence Snippet with source identity, locator, score fields, and ranking reasons.
