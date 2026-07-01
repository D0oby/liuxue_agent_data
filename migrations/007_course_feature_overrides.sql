alter table courses
add column if not exists course_feature_overrides jsonb;

alter table courses
drop constraint if exists courses_course_feature_overrides_object_check;

alter table courses
add constraint courses_course_feature_overrides_object_check
check (course_feature_overrides is null or jsonb_typeof(course_feature_overrides) = 'object');
