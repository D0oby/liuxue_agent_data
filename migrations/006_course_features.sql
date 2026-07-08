alter table courses
add column if not exists course_features jsonb;

alter table courses
drop constraint if exists courses_course_features_object_check;

alter table courses
add constraint courses_course_features_object_check
check (course_features is null or jsonb_typeof(course_features) = 'object');

create index if not exists idx_courses_course_features_gin
on courses using gin (course_features);
