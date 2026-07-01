# AGENTS.md

`migrations/` 保存 PostgreSQL schema 迁移。

## 目录职责

- 创建和升级 `courses`、`course_intakes`、`course_admission_requirements`、`course_admission_dlq`、`course_admission_chunks` 等表结构。
- 维护索引、扩展和兼容性 SQL。

## 边界

- 推荐层默认只读现有表；不要为推荐功能破坏或重建 ingestion 表。
- 不修改 `source_row_hash` 的含义或唯一性契约。
- 不把 `CRICOS` 改成课程唯一键。
- 如需为推荐查询增加索引或只读视图，必须保持向后兼容。
- 不写会清空、重排或重新生成生产数据的迁移，除非用户明确要求。

## 验证

新增迁移时，确认可按文件名顺序重复应用到干净库；涉及 pgvector 时说明扩展不可用时的行为。
