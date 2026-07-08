# Use Independent Study Abroad Index Storage

Study Abroad Knowledge RAG will use its own index and cache namespace, separate from the existing `course_admission_chunks` Chroma collection used by the USYD recommendation layer. The broader study-abroad corpus has different source schemas, privacy metadata, ranking policy, and invalidation rules, so mixing it with admissions chunks would make filtering, disclosure control, cache freshness, and debugging harder to reason about.
