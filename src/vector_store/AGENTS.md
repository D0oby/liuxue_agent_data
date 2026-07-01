# AGENTS.md

`src/vector_store/` 负责招生文本 chunk、embedding 生成、ChromaDB 存储和语义搜索能力。

## 目录职责

- 从当前招生要求读取 academic、English、application 文本。
- 切分文本 chunk。
- 调用 embedding client。
- 写入或重建 ChromaDB `course_admission_chunks` collection。
- 提供语义搜索能力给 Dashboard 或后续 RAG 服务读取。

## 边界

- 不做课程推荐、评分或 REACH/MATCH/SAFETY 分档。
- 不在这里合并关键词召回结果；推荐层的 `CandidateMerger` 应在独立推荐模块中。
- 不吞掉 embedding 或 ChromaDB 失败；调用方需要能判断是否降级。
- 不修改 `courses`、`course_intakes`、`source_row_hash` 或导入幂等规则。

## 验证

修改 chunking、embedding 或 storage 时，覆盖 chunk 边界、metadata 保留、重复写入和向量不可用降级相关测试。
