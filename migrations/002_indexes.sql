create index if not exists idx_courses_cricos on courses (cricos);
create index if not exists idx_course_intakes_month on course_intakes (intake_month);
create index if not exists idx_course_adm_course_id on course_admission_requirements (course_id);
create index if not exists idx_course_adm_details_gin on course_admission_requirements using gin (english_req_details);

