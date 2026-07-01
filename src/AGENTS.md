# AGENTS.md

`src/` 是运行时代码根目录。这里的 agent 重点是保持模块边界清楚。

## 1. 现有职责

- `cli.py`：命令入口，只做参数解析和流程调用。
- `config.py`：环境变量和运行配置读取。
- `db.py`：PostgreSQL 连接和 migration 执行。
- `dashboard.py`：Streamlit 查询后台。
- `extract/`、`transform/`、`load/`：Excel 导入链路。
- `crawl/`：官网招生爬虫链路。
- `vector_store/`：招生文本 chunk、embedding、ChromaDB 存储与搜索。
- `models/`：共享 DTO 和数据对象。

## 2. 新增推荐层时的放置原则

如果用户要求实现 USYD RAG + Agent MVP 推荐层：

- 新建独立推荐模块，避免把推荐业务塞进导入、爬虫、向量或 Dashboard 文件。
- API/CLI/Agent 只调用 service/tool，不直接写 SQL 或评分逻辑。
- Repository 只做只读 SQL 和数据映射。
- RAG、Requirement、Scoring、PlanAssembler 分别保持单一职责。
- 新增配置优先接入现有 `Settings` 读取方式，测试中应能覆盖不同配置。

## 3. 禁止事项

- 不在 `dashboard.py` 或 API handler 里实现评分、分档、RAG 合并或 SQL 细节。
- 不在 Agent 文件里放 SQL、ChromaDB 查询或数学评分公式。
- 不为了推荐层改写已有 ingestion、crawler、embedding 管道。
- 不按 `CRICOS` 做唯一性判断。

## 4. 验证

修改 `src/` 后，优先运行相关单测；跨模块改动运行全量测试：

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```
