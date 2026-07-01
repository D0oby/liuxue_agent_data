# AGENTS.md

`src/models/` 保存共享 DTO 和数据对象。

## 目录职责

- 定义导入、爬虫、向量或推荐层共享的数据结构。
- 保持字段语义清晰、类型稳定。
- 为跨模块契约提供单一来源。

## 边界

- 不放数据库访问、外部 API 调用或业务流程编排。
- 不在模型里实现评分、RAG 查询、爬虫抓取或导入写入。
- 已被 API、Dashboard、测试或下游模块使用的字段不要随意重命名。

## 推荐层契约

新增推荐模型时，保持这些对象语义稳定：

- `UserProfile`
- `RecommendationRequest`
- `CourseCandidate`
- `NormalizedRequirement`
- `ScoreResult`
- `ScoredCourseCandidate`
- `RecommendationResponse`

新增字段应优先保持向后兼容。

## 验证

模型字段变更需要同步更新受影响测试和文档示例，尤其是响应 schema。
