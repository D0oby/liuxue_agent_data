do $$
begin
  create extension if not exists vector;
exception
  when undefined_file or feature_not_supported then
    raise notice 'pgvector extension is not available; skipping course_admission_chunks migration.';
end $$;

do $$
begin
  if exists (select 1 from pg_extension where extname = 'vector') then
    execute $sql$
      create table if not exists course_admission_chunks (
        id uuid primary key default gen_random_uuid(),
        course_id uuid not null references courses(id) on delete cascade,
        requirement_id uuid not null references course_admission_requirements(id) on delete cascade,
        chunk_kind text not null check (chunk_kind in ('academic', 'english', 'application')),
        chunk_index integer not null check (chunk_index >= 0),
        content text not null,
        content_hash text not null,
        source_url text,
        metadata_json jsonb not null default '{}'::jsonb,
        embedding_model text,
        embedding vector,
        embedded_at timestamptz,
        created_at timestamptz not null default now(),
        updated_at timestamptz not null default now(),
        unique (requirement_id, chunk_kind, chunk_index)
      )
    $sql$;

    create index if not exists idx_course_adm_chunks_course_id on course_admission_chunks (course_id);
    create index if not exists idx_course_adm_chunks_requirement_id on course_admission_chunks (requirement_id);
    create index if not exists idx_course_adm_chunks_content_hash on course_admission_chunks (content_hash);
    create index if not exists idx_course_adm_chunks_metadata_gin on course_admission_chunks using gin (metadata_json);

    begin
      create index if not exists idx_course_adm_chunks_embedding_hnsw
      on course_admission_chunks
      using hnsw (embedding vector_cosine_ops)
      where embedding is not null;
    exception
      when others then
        raise notice 'Skipping course_admission_chunks HNSW index. Check that pgvector supports HNSW in this PostgreSQL installation.';
    end;
  else
    raise notice 'Install pgvector and rerun migrations to create course_admission_chunks.';
  end if;
end $$;
