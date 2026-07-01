# AGENTS.md

`tests/` 保存项目测试。

## 目录职责

- 覆盖解析、导入幂等、爬虫 parser、向量切块和后续推荐层核心规则。
- 尽量使用小而确定的输入样例。
- 数据库相关测试应显式隔离配置，不依赖生产库凭据。

## 推荐层最低覆盖

实现推荐层时至少覆盖：

- `QueryBuilder` 中英文方向映射。
- `CandidateMerger` 按 `course_id` 合并并保留 evidence。
- `RequirementNormalizer` GPA 和 IELTS 规则。
- `ScoreCalculator` 配置权重和公式。
- `BandClassifier` 在 `0.95`、`1.1` 边界的分档。
- `PlanAssembler` 每档数量、解释、source URL、excluded reasons。
- `RecommendationService` 完整用户画像的端到端 happy path。
- 向量检索失败时关键词降级和 `metadata.degraded_retrieval = true`。

## 验证入口

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

不能运行测试时，在交付说明里写清原因。
