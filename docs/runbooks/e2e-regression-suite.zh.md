# Hermetic E2E 回归测试套件

英文是默认入口文档。英文文件：
[e2e-regression-suite.md](e2e-regression-suite.md)。

## 默认命令

```bash
cd /Users/admin/Documents/liuxue_agent\ real/usyd_pg_import
E2E_DATABASE_URL='postgresql://localhost/usyd_pg_import_e2e' \
  .venv/bin/python -m src.cli e2e-regression
```

`E2E_DATABASE_URL` 必须指向隔离的 E2E 数据库。套件不会 fallback 到普通
`DATABASE_URL`；如果没有显式 E2E 数据库配置，会在 `database_guard` 阶段失败。

## 套件执行内容

默认 hermetic run 会按顺序执行：

1. `database_guard`
2. `migrations`
3. `fixture_excel_import`
4. `admissions_fixture_enrichment`
5. `deterministic_vector_retrieval`
6. `course_feature_profiles`
7. `recommendation_service`
8. `api_schema_smoke`
9. `dashboard_playwright`

fixture 数据集很小但有代表性，覆盖 data/AI、business analytics、申请材料、
高风险或不满足条件场景，并包含不同开学季、费用和学制。

## Hermetic 行为

套件使用本地 fixture Excel、本地 admissions fixture、确定性本地 embedding、
临时 ChromaDB 存储和本地 Streamlit Dashboard。默认不会访问 live USYD 页面，
也不会调用外部 embedding API。

临时 fixture 和 vector 状态会在运行后清理。只有调试时才使用
`--keep-artifacts`。

## Artifacts

运行摘要、Streamlit 日志和 Playwright 截图写入：

```text
var/e2e_artifacts/<run-id>/
```

每次运行都会写入 `summary.json`。Dashboard 失败时，如果 Playwright 能捕获页面，
还会保留 `dashboard_failure.png`。

## 浏览器模式

Playwright 默认 headless：

```bash
E2E_DATABASE_URL='postgresql://localhost/usyd_pg_import_e2e' \
  .venv/bin/python -m src.cli e2e-regression
```

本地调试时才使用 headed：

```bash
E2E_DATABASE_URL='postgresql://localhost/usyd_pg_import_e2e' \
  .venv/bin/python -m src.cli e2e-regression --headed --keep-artifacts
```

如果浏览器依赖不可用，只需要验证非 UI 链路：

```bash
E2E_DATABASE_URL='postgresql://localhost/usyd_pg_import_e2e' \
  .venv/bin/python -m src.cli e2e-regression --skip-dashboard
```

## CI 用法

该套件适合作为 optional、nightly 或 manual CI，不是每个小改动默认必跑的轻量
测试门禁。CI 应创建一次性 E2E 数据库，设置 `E2E_DATABASE_URL`，运行默认命令，
并在失败时上传 `var/e2e_artifacts`。

## Live Smoke

Live external smoke 是独立的人工流程。只有在操作者显式 opt-in 时，才可以访问真实
USYD 网站或外部 embedding API；它不能作为默认 regression gate。
