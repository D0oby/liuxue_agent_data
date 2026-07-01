# AGENTS.md

本文件是 `usyd_pg_import/` 主工程的框架 agent 说明。子目录里的 `AGENTS.md` 会进一步约束本目录下的具体文件。

## 1. 工程定位

`usyd_pg_import/` 当前已经实现 USYD 研究生课程数据资产链路：

- Excel -> PostgreSQL 导入。
- 官网 admissions 爬虫补全招生要求。
- 招生文本切块、embedding 和 ChromaDB 存储。
- Streamlit 本地查询后台。

下一阶段要新增的是只读 USYD RAG + Agent MVP 推荐决策层，不是重写上述数据管道。

## 2. 默认技术栈和风格

- Python 3.11+。
- 现有依赖以 `pyproject.toml` 为准：`psycopg`、`pandas`、`pydantic`、`streamlit`、`Scrapy`、`Playwright`。
- 数据库连接沿用 `src/config.py` 和 `src/db.py` 的方式。
- 测试沿用 `unittest` 风格，入口为 `PYTHONPATH=. python3 -m unittest discover -s tests -v`。
- 新代码优先复用现有 DTO、配置读取、数据库连接和测试布局。

如果用户要求实现推荐层且仓库仍没有对应目录，优先在 `src/` 下新增清晰的推荐层模块，而不是把推荐逻辑塞进已有导入、爬虫、向量或 Dashboard 文件。

## 3. V1.0 推荐链路

推荐层目标流程：

1. `UserProfileParser` 解析完整用户画像。
2. `AdmissionsRAGService` 通过关键词检索 + 向量检索召回候选课程。
3. `RequirementService` 批量读取并标准化招生要求。
4. `ScoringService` 使用配置驱动的 GPA/IELTS 模型计算分数。
5. `PlanAssembler` 生成 `reach_programs`、`match_programs`、`safety_programs`、`excluded_programs`。
6. 单体 `PlanningAgent` 固定编排工具调用。
7. 输出稳定 `RecommendationResponse` JSON 和可解释文本。

## 4. 数据读取范围

推荐层只读：

- `courses`
- `course_intakes`
- `course_admission_requirements`，默认 `is_current = true`
- ChromaDB `course_admission_chunks` collection

`course_admission_dlq` 不进入 V1.0 推荐主链路。

Repository 层只负责 SQL 和数据映射，不包含推荐、评分、分档或 Agent 编排逻辑。

## 5. 不可破坏的边界

- 不重建 Excel 导入、官网爬虫或 embedding 生成链路。
- 不修改 ingestion 表的写入规则。
- 不按 `CRICOS` 去重；一行 Excel 是一条课程记录，推荐层合并使用 `course_id`。
- 不修改 `source_row_hash`。
- Agent 不直接写 SQL、不直接检索 ChromaDB、不直接计算评分。
- V1.0 不引入多 Agent、录取概率 ML、多学校推荐或缺失画像自动追问。
- 权重、阈值、Top-K、候选数量、IELTS 小分硬门槛开关必须来自配置。

## 6. 核心对象契约

保持这些语义稳定，新增字段只能是向后兼容的：

- `UserProfile`：`target_major_keyword`、`gpa_user`、`ielts_overall_user`、`ielts_min_band_user`、`academic_background`、`preferred_intake`、`budget_range`、`duration_preference`。
- `CourseCandidate`：必须保留 `course_id`、`course_name`、`cricos`、学制、学费、intakes、招生要求、retrieval 分数、retrieval reason、evidence snippets、source URL。
- `NormalizedRequirement`：`gpa_min`、`ielts_overall_min`、`ielts_min_band_min`、`requirement_summary`、`requirement_source_url`。
- `ScoreResult`：GPA component、IELTS component、`final_score`、`match_band`、`reason_tags`。
- `RecommendationResponse`：`user_profile`、`query_summary`、`reach_programs`、`match_programs`、`safety_programs`、`excluded_programs`、`metadata`。

## 7. 默认评分和分档

默认评分公式：

```text
S = 0.7 * (GPA_user / GPA_min) + 0.3 * (IELTS_user / IELTS_min)
```

默认分档：

- `S < 0.95` -> `REACH`
- `0.95 <= S <= 1.1` -> `MATCH`
- `S > 1.1` -> `SAFETY`

这些数值只能作为配置默认值，不要散落在业务函数、Agent 或 API handler 中。

## 8. 错误处理和日志

推荐请求需要生成并贯穿 `request_id`。预期行为：

- 缺招生要求：加入 `excluded_programs`，reason 为 `missing_requirement`，记录 `WARN`。
- 缺 IELTS 结构化字段：先尝试确定性规则解析，失败则排除并记录 `WARN`。
- 向量检索不可用：降级关键词检索，`metadata.degraded_retrieval = true`，记录 `ERROR`。
- 单课程评分失败：跳过或排除该课程，不中断整批请求，记录 `WARN`。
- 数据库连接失败：返回服务级错误，记录 `ERROR`。

## 9. Definition of Done

完成一项工程任务前确认：

- 改动符合只读推荐层边界。
- 领域对象和响应 schema 稳定。
- 评分、分档、检索和输出数量配置化。
- RAG evidence 没有在链路中丢失。
- Agent 文件没有 SQL、ChromaDB 查询或评分公式。
- 测试或验证命令已运行；若不能运行，说明原因。

## Agent skills

### Issue tracker

Issues and PRDs are tracked as GitHub issues in `D0oby/liuxue_agent_data`; external PRs are not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

The canonical triage labels map directly to GitHub label strings. See `docs/agents/triage-labels.md`.

### Domain docs

This repo uses a single-context domain-doc layout. See `docs/agents/domain.md`.
