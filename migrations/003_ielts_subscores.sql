alter table course_admission_requirements
add column if not exists ielts_listening numeric(3,1),
add column if not exists ielts_reading numeric(3,1),
add column if not exists ielts_speaking numeric(3,1),
add column if not exists ielts_writing numeric(3,1);

alter table course_admission_requirements
drop constraint if exists course_admission_requirements_ielts_listening_check,
drop constraint if exists course_admission_requirements_ielts_reading_check,
drop constraint if exists course_admission_requirements_ielts_speaking_check,
drop constraint if exists course_admission_requirements_ielts_writing_check;

alter table course_admission_requirements
add constraint course_admission_requirements_ielts_listening_check
check (ielts_listening is null or (ielts_listening >= 0 and ielts_listening <= 9)),
add constraint course_admission_requirements_ielts_reading_check
check (ielts_reading is null or (ielts_reading >= 0 and ielts_reading <= 9)),
add constraint course_admission_requirements_ielts_speaking_check
check (ielts_speaking is null or (ielts_speaking >= 0 and ielts_speaking <= 9)),
add constraint course_admission_requirements_ielts_writing_check
check (ielts_writing is null or (ielts_writing >= 0 and ielts_writing <= 9));

update course_admission_requirements
set
  ielts_listening = coalesce((english_req_details->'ielts_subscores'->>'listening')::numeric, ielts_min_band),
  ielts_reading = coalesce((english_req_details->'ielts_subscores'->>'reading')::numeric, ielts_min_band),
  ielts_speaking = coalesce((english_req_details->'ielts_subscores'->>'speaking')::numeric, ielts_min_band),
  ielts_writing = coalesce((english_req_details->'ielts_subscores'->>'writing')::numeric, ielts_min_band)
where ielts_min_band is not null or english_req_details ? 'ielts_subscores';

