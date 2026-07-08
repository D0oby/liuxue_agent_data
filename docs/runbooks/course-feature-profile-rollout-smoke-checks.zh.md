# Course Feature Profile Rollout 烟测检查

当需要验证 Course Feature Profile 的运行时兼容性时使用本 runbook。推荐层必须在部分上线期间保持可用，包括数据库尚未应用画像字段 migration 的情况。

## 默认测试套件

先运行完整 unittest：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
.venv/bin/python -m unittest discover -s tests -v
```

预期结果：

- 所有测试通过。
- 缺失 feature-profile 存储字段的兼容测试通过。
- 已迁移画像数据的既有测试仍然通过。

验证本地 UI 时运行 headed Playwright 双语 Dashboard 烟测：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
RUN_DASHBOARD_E2E=1 .venv/bin/python -m unittest tests.test_dashboard_bilingual_e2e -v
```

预期结果：

- 可见 Chromium 窗口会打开。
- Dashboard 默认显示英文 UI。
- 切换到中文后，Dashboard 自有文案会更新。
- 在推荐方案和课程查询工作区之间切换时，语言状态保持在当前 session 内。
- 文档链接在存在配对文件时指向当前语言版本。

## 未迁移数据库烟测

适用于本地 `courses` 表还没有 `course_features` 或 `course_feature_overrides` 的状态。

1. 启动 Dashboard：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
.venv/bin/python -m streamlit run src/dashboard.py --server.port 8502 --server.headless true
```

2. 打开：

```text
http://localhost:8502
```

3. 在 `Recommendation Plan` / `推荐方案` 中，使用默认表单值点击运行资格筛选。

预期结果：

- 推荐请求可以完成。
- 页面显示候选数和推荐分档。
- 页面不会只显示 `Recommendation request failed.`。
- Course Feature Profile 数据会按缺失或默认画像处理。

4. 切换到 `Course Search` / `课程查询`。

预期结果：

- 课程表可以加载。
- 页面提示 Course Feature Profile storage 需要 migration 后才完整可用。
- 既有课程查询和 admissions 搜索仍可用。
- Feature tag 列可以为空。

## 已迁移数据库烟测

适用于已经应用以下 migration 的状态：

- `migrations/006_course_features.sql`
- `migrations/007_course_feature_overrides.sql`

为本地开发数据生成画像：

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
.venv/bin/python -m src.cli generate-course-features --dry-run
.venv/bin/python -m src.cli generate-course-features
```

启动或刷新 Dashboard 后检查：

- `Course Search` / `课程查询` 加载时没有 degraded-mode warning。
- 已生成画像的课程显示 feature tags。
- 使用 feature tag，例如 `data science` 搜索，可以返回本地数据中的相关课程。
- 课程详情中的 `Feature Profile` / `画像特征` 显示标签和 0-5 分画像。
- `Recommendation Plan` / `推荐方案` 仍能返回 hard-filtered recommendations。

## 语义搜索烟测

在 `Course Search` / `课程查询` 中使用 admissions semantic search。

预期结果：

- 空结果显示正常的 no-results 状态。
- 成功结果显示匹配分数、命中片段、source kind、字段 metadata 和 source URL。
- 查询词会在片段中高亮。
- OpenAI 或 vector-store 配置错误与 no-results 状态区分显示。

## 边界

这些烟测不得：

- 修改 ingestion 表。
- 修改 `source_row_hash`。
- 按 CRICOS 去重。
- 从 Dashboard 或推荐请求自动执行 migration。
- 自动重建爬虫、embedding 或向量化链路，除非 operator 明确执行。
