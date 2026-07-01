# AGENTS.md

`src/load/` 是 Excel 导入链路的数据库写入层。

## 目录职责

- 将 `CourseRecord` 写入 `courses`。
- 将 intake 写入 `course_intakes`。
- 将 Excel 中已有语言要求写入 `course_admission_requirements`。
- 保持导入事务性和幂等性。

## 边界

- 只处理导入链路写入，不承载推荐层逻辑。
- 不修改 `source_row_hash` 规则，除非用户明确要求重定义导入幂等契约。
- 不按 `CRICOS` 去重；`CRICOS` 可重复。
- 不写 `course_admission_chunks`，向量数据属于 `vector_store/`。
- 不在这里实现招生要求推荐标准化、评分或 Agent 工具。

## 验证

修改写入逻辑时，必须覆盖幂等导入、重复 `CRICOS`、事务失败回滚或字段映射测试。
