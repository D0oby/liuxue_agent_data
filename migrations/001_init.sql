create extension if not exists pgcrypto;

create table if not exists courses (
  id uuid primary key default gen_random_uuid(),
  course_name text not null,
  course_name_raw text not null,
  cricos text not null,
  duration_min_years numeric(4,2) not null,
  duration_max_years numeric(4,2) not null,
  duration_raw text not null,
  commencing_semester_raw text not null,
  tuition_fee_aud numeric(12,2) not null,
  source_file_name text,
  source_sheet_name text,
  source_row_number integer,
  source_row_hash text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (duration_min_years > 0),
  check (duration_max_years >= duration_min_years)
);

create table if not exists course_intakes (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references courses(id) on delete cascade,
  intake_month text not null check (intake_month in ('JAN','FEB','MAR','JUL','AUG','OCT')),
  sort_order smallint not null,
  created_at timestamptz not null default now(),
  unique (course_id, intake_month)
);

create table if not exists course_admission_requirements (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references courses(id) on delete cascade,
  requirement_version integer not null default 1,
  requirement_source text not null default 'excel_seed',
  source_url text,
  academic_requirement_text text,
  raw_english_requirement text,
  ielts_overall numeric(3,1),
  ielts_min_band numeric(3,1),
  english_req_details jsonb not null default '{}'::jsonb,
  notes text,
  is_current boolean not null default true,
  last_verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (ielts_overall is null or (ielts_overall >= 0 and ielts_overall <= 9)),
  check (ielts_min_band is null or (ielts_min_band >= 0 and ielts_min_band <= 9))
);

