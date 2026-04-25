alter table course_admission_requirements
add column if not exists academic_requirements_json jsonb not null default '{}'::jsonb,
add column if not exists application_details_json jsonb not null default '{}'::jsonb,
add column if not exists supplementary_metadata_json jsonb not null default '{}'::jsonb,
add column if not exists source_map_json jsonb not null default '{}'::jsonb,
add column if not exists source_fingerprint text;

create index if not exists idx_course_adm_fingerprint on course_admission_requirements (source_fingerprint);
create index if not exists idx_course_adm_academic_gin on course_admission_requirements using gin (academic_requirements_json);
create index if not exists idx_course_adm_application_gin on course_admission_requirements using gin (application_details_json);

create table if not exists course_admission_dlq (
  dlq_id uuid primary key default gen_random_uuid(),
  cricos text,
  course_name text,
  source_url text,
  stage text not null,
  error_code text not null,
  error_message text not null,
  raw_payload_json jsonb not null default '{}'::jsonb,
  raw_html_excerpt text,
  source_context_json jsonb not null default '{}'::jsonb,
  retryable boolean not null default true,
  created_at timestamptz not null default now(),
  review_status text not null default 'NEW',
  review_notes text
);

create index if not exists idx_course_adm_dlq_cricos on course_admission_dlq (cricos);
create index if not exists idx_course_adm_dlq_stage on course_admission_dlq (stage);
create index if not exists idx_course_adm_dlq_error on course_admission_dlq (error_code);
