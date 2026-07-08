# Limit V1 Study Abroad Loaders

The first Study Abroad Knowledge RAG implementation will support Markdown, HTML, and manifest-backed CSV or JSONL records only. PDF, Excel, dynamic web crawling, and direct database loaders are deferred so V1 can stabilize source metadata, chunk boundaries, locators, privacy handling, and deterministic tests while keeping the public `StudyAbroadRAGIndex` interface open for later loader plugins.
