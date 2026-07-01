# AGENTS.md

`src/crawl/` 是官网招生信息抓取、解析、校验和落库模块。

## 目录职责

- 从数据库读取课程种子。
- 抓取 USYD 官网课程页。
- 解析 academic requirements、language requirements、application details。
- 通过 Pydantic 模型校验爬虫结果。
- 成功时更新 `course_admission_requirements`，失败时写入 DLQ。

## 边界

- 不做推荐排序、评分或分档。
- 不生成 embedding，不写 `course_admission_chunks`。
- 不让爬虫失败静默丢失；失败记录必须可追踪。
- 不改变导入层的 `courses` 唯一性规则。
- 推荐层只能读取爬虫产物，不能把推荐判断塞回爬虫。

## 验证

修改 parser、storage 或 runner 时，优先覆盖结构化解析、Pydantic 校验、source fingerprint 和 DLQ 行为。
