# PRD: 留学知识 RAG V1

## 问题陈述

项目目前已有一个简单搜索路径和 USYD 专用推荐层，但还没有一个可复用的留学知识 RAG，用来检索更广泛的留学证据。

下一阶段语料会包括大学官网、政府政策页、留学帖子、学生经验内容、已验证内部案例，以及匿名内部摘要。这些资料和现有 USYD 招生推荐链路不同，需要独立的检索、排序、隐私、时效和引用规则。

如果直接把这些资料混进一个宽松搜索系统，官方要求、论坛帖子和匿名内部记录会缺少清晰边界。Agent 将很难解释为什么相信某条结果、是否允许返回原文、来源是否过期，以及该结果是否适合当前问题意图。

## 解决方案

新增独立的 Study Abroad Knowledge RAG V1，工程形态参考 Semble 的深模块结构。

模块只暴露窄 Python API：从 manifest-backed sources 构建索引、搜索、查找相关证据、格式化扁平可序列化结果。内部隐藏 source loading、chunking、sparse search、dense search、RRF fusion、Ranking Policy、privacy handling 和 cache metadata。

V1 返回 Study Abroad Search Results，不生成最终回答或推荐方案。Answer Generation Layer 由调用方负责，并且必须引用检索得到的 Evidence Snippets。

系统应当：

- 只索引 Source Manifest 中声明的 Study Abroad Sources。
- 索引前要求最低 source metadata。
- V1 只支持 Markdown、HTML、manifest-backed CSV 或 JSONL records。
- 新索引存储与现有 USYD admissions vector collection 独立。
- dense/sparse fusion 使用 RRF，再应用可配置 Ranking Policy。
- 每条结果返回 `rrf_score`、`final_score` 和 `ranking_reasons`。
- 遵守 Privacy Level，尤其是 Anonymous Internal Sources。
- 使用确定性 `unittest` 和 TDD tracer bullets 实现。
- V1 不做 MCP 工具层。
- V1 不接入现有 USYD recommendation runtime。

## 用户故事

1. 作为 planning agent 调用方，我希望通过一个稳定 Python 接口搜索留学证据，以便不用了解索引如何加载、切块、embedding、排序或格式化。
2. 作为 planning agent 调用方，我希望搜索结果包含可追溯 Evidence Snippets，以便生成回答时能引用事实来源。
3. 作为 planning agent 调用方，我希望搜索结果包含来源 metadata，以便区分官方政策证据和学生经验。
4. 作为 planning agent 调用方，我希望搜索结果包含 `ranking_reasons`，以便调试为什么某个来源被加权或降权。
5. 作为 planning agent 调用方，我希望最终回答生成留在 RAG index 外部，以便检索可以脱离 LLM 行为进行测试。
6. 作为开发者，我希望 Study Abroad Knowledge RAG 独立于 USYD Recommendation Layer，以便更广泛语料不会改变招生评分行为。
7. 作为开发者，我希望新 RAG 模块只有窄公开 API，以便内部 ranking 和 storage 选择可以演进而不破坏调用方。
8. 作为开发者，我希望新 RAG 使用独立 index namespace，以便 source schema 和 privacy rules 不与 USYD admissions chunks 混在一起。
9. 作为开发者，我希望 source loading 基于 manifest，以便每个 indexed source 都有明确身份、类型、定位、时效、可信度、隐私和语言 metadata。
10. 作为开发者，我希望无效 manifest entry 在索引前被拒绝，以便低质量 metadata 不会生成不可追溯证据。
11. 作为开发者，我希望 Markdown source 生成稳定 locator，以便 Evidence Snippets 能回到标题或章节。
12. 作为开发者，我希望 HTML source 生成稳定 locator，以便官方页面和网页快照可检查。
13. 作为开发者，我希望 CSV 和 JSONL records 生成稳定 locator，以便整理后的帖子和内部摘要无需直连数据库也能索引。
14. 作为开发者，我希望 V1 不做 PDF、Excel、动态抓取或数据库直连 loader，以便第一版先稳定核心检索行为。
15. 作为搜索用户，我希望学校名、项目名、签证术语、成绩、费用和日期能精确命中，以便事实查询不会被纯语义搜索漏掉。
16. 作为搜索用户，我希望宽泛意图查询能召回相关证据，以便规划问题不依赖完全相同措辞。
17. 作为搜索用户，我希望中文、英文、中英混合、数字和短语 token 都可用于 sparse search，以便常见留学问题行为稳定。
18. 作为搜索用户，我希望 dense-only 和 sparse-only 命中都能经过 hybrid fusion 保留下来，以便有用证据不会太早丢失。
19. 作为 reviewer，我希望 RRF fusion 与 Ranking Policy 分离，以便检索机制和领域信任规则能分别测试。
20. 作为 reviewer，我希望每个 candidate 先得到 `rrf_score`，再应用 Ranking Policy，以便分数来源可检查。
21. 作为 reviewer，我希望 Ranking Policy 计算 `final_score`，以便留学领域的可信度、时效、问题意图、隐私和饱和规则是显式的。
22. 作为 reviewer，我希望 Ranking Policy 配置化，以便加权和降权不硬编码在 search logic 中。
23. 作为 reviewer，我希望 requirement、deadline、fee、policy query 强烈偏向大学官网、政府官网和 course handbook，以便高风险事实使用权威来源。
24. 作为 reviewer，我希望 applicant-fit 和 chance-estimation query 只把内部案例作为补充上下文，以便内部案例不覆盖官方要求。
25. 作为 reviewer，我希望 program recommendation query 考虑课程、职业和背景匹配证据，以便排序不退化成“哪个项目最容易进”。
26. 作为 reviewer，我希望 student experience query 可适当提高学生经验帖和匿名摘要权重，以便生活体验问题使用合适证据。
27. 作为 reviewer，我希望 public forum posts 默认低权重，以便非官方证据不会主导事实或政策问题。
28. 作为 reviewer，我希望过期来源被降权，以便旧要求、旧费用、旧截止日期和旧政策不压过当前证据。
29. 作为 reviewer，我希望缺失 metadata 会降权或在必填字段缺失时阻止索引，以便 source quality 不被隐藏。
30. 作为 reviewer，我希望有 same-source saturation，以便前排结果不会被单一 domain、source type 或 document 占满。
31. 作为 privacy reviewer，我希望 raw anonymous internal records 默认禁止展示，以便匿名不等于允许引用敏感数据。
32. 作为 privacy reviewer，我希望匿名摘要只有在 Privacy Level 允许时才可返回，以便内部证据有用但不暴露原始记录。
33. 作为 privacy reviewer，我希望包含 personal identifiers 的证据禁止原文返回，以便隐私敏感材料不会通过搜索泄漏。
34. 作为 operator，我希望 cache metadata 描述 source hashes、schema version、chunker version、tokenizer version、model name 和 created time，以便判断索引是否过期。
35. 作为 operator，我希望 V1 的 persistent cache 可以暂缓，以便第一版先保证正确性再优化存储。
36. 作为开发者，我希望 embedding 和 vector storage 位于窄协议后面，以便测试使用 deterministic embedder，生产使用配置后端。
37. 作为开发者，我希望 unit tests 不调用外部 embedding API，以便测试稳定且快速。
38. 作为开发者，我希望 V1 不做 MCP 层，以便 Python API 和 result schema 稳定后再设计工具契约。
39. 作为维护者，我希望 V1 不接入 RecommendationService 或 PlanningAgent，以便现有 USYD 推荐行为不变。
40. 作为维护者，我希望实现被拆成 TDD tracer bullets，以便每个 issue 都能独立验证。

## 实现决策

- Study Abroad Knowledge RAG 是独立检索模块，不扩展现有 USYD Recommendation Layer。
- 模块只做检索，不生成最终回答、录取建议或冲突归并结论。
- V1 只使用 Source Manifest 作为 source inventory，不直接扫描未来业务数据库表。
- 每个可索引 source 必须提供 source identity、source type、title、source locator、content locator、freshness metadata、Trust Tier、language，以及需要时的 privacy metadata。
- country、institution、program、degree level、intake、tags 等 filtering metadata 可选。
- V1 只支持 Markdown、HTML、manifest-backed CSV 或 JSONL records。
- PDF、Excel、动态网页抓取和数据库直连 loader 延后。
- 新 index storage 与现有 USYD admissions vector collection 独立。
- embedding、dense search、sparse search 和 index storage 使用窄协议。
- 默认 runtime 可以复用现有技术栈，但核心 retrieval 和 ranking 不直接依赖外部服务。
- 公共 Python API 保持窄接口：从 sources 或 path 构建 index、search、find related evidence、format results。
- 不在公开 API 暴露 fusion weights；query intent 和 config 控制 ranking 行为。
- hybrid fusion 使用 RRF，领域加权和降权不进入 fusion 层。
- Ranking Policy 在 fusion 后应用。每个 candidate 先有 `rrf_score`，再计算 `final_score`。
- Ranking Policy 负责 trust-tier boosts、source-type boosts、source-type penalties、staleness penalties、filter-match boosts、mismatch penalties、privacy penalties、same-source saturation 和 query-intent boosts。
- 每条结果必须包含解释关键加权和降权的 `ranking_reasons`。
- 官方大学、官方政府和 course handbook source 负责 requirement、English requirement、fee、deadline、visa 和 policy query 的事实边界。
- verified internal case 和 anonymous internal summary 可支持 applicant fit、chance estimation、background similarity 和 student experience，但不能覆盖官方要求。
- public forum 和 social experience sources 默认低信任，只在 student experience 或 lived-experience query intent 下适当提升。
- Anonymous Internal Sources 默认不能返回 raw evidence。
- Privacy Level 控制 raw text、redacted text、summary-only evidence 或 no displayable content。
- 包含 personal identifiers 的证据不能作为 raw evidence 返回。
- same-source saturation 防止单一来源、source type 或 domain 占据过多前排结果。
- cache metadata 必须表达 schema version、chunker version、tokenizer version、model name、source manifest hash、source content hashes 和 creation time。
- V1 不要求完整 persistent cache 优化，但 cache invalidation decision 必须可测试。
- V1 不做 MCP 层。
- V1 不接入现有 recommendation runtime、dashboard recommendation flow 或 USYD scoring / eligibility logic。

## 测试决策

- 使用 TDD tracer bullets：一个失败行为测试，一个最小实现，然后重复。
- 主测试 seam 是 Study Abroad Knowledge RAG 的公开 Python API。
- 次级测试 seam 是 result formatter。
- 测试应通过公开接口验证行为，不测试私有 loader、chunker、ranking 或 fusion 实现细节。
- 只 mock 系统边界：embedding generation、time，以及必要的 filesystem setup。
- 不 mock Study Abroad Knowledge RAG 自己拥有的内部模块。
- V1 使用项目现有 `unittest` 风格，不引入 pytest fixtures。
- 使用小型确定性 fixture corpus，覆盖 official sources、forum posts、anonymous internal summaries、stale sources 和 metadata edge cases。
- 使用 deterministic mock embedder，保证 dense retrieval 稳定且不调用外部 API。
- 覆盖 manifest validation：缺必填 metadata 阻止索引。
- 覆盖 Markdown、HTML、CSV、JSONL 的 source loading 和 chunk locators。
- 覆盖中文、英文、中英混合、数字短语、学校名、费用和日期的 sparse tokenization。
- 覆盖 hybrid retrieval，确保 dense-only 和 sparse-only matches 能经过 RRF fusion 返回。
- 覆盖 requirement、deadline、fee、policy、applicant-fit、program-recommendation、student-experience query intent 下的 Ranking Policy。
- 覆盖 privacy handling，确保 raw anonymous internal evidence 默认不返回。
- 覆盖 same-source saturation，确保单一 source 的重复 chunks 不主导 top results。
- 覆盖 formatter output，确保调用方得到 flat JSON-compatible results 且不泄漏内部 index objects。
- 覆盖 cache metadata invalidation：schema version、chunker version、tokenizer version、model name、manifest hash 和 source content hash 变化。
- 每个 tracer bullet 后运行相关 Study Abroad Knowledge RAG tests。
- 完成实现前运行全量现有 unittest suite。

## 非目标

- MCP server 或 MCP tools。
- 最终回答生成。
- 录取决策生成。
- 接入 RecommendationService、PlanningAgent 或现有 USYD scoring。
- 写入 ingestion tables。
- 重建现有 Excel import、crawler、admissions chunking 或 `course_admission_chunks` vectorization path。
- PDF loader。
- Excel loader。
- 动态网页抓取。
- 直接扫描业务数据库作为 source loader。
- 多 Agent 编排。
- 多学校推荐评分。
- ML admission probability。
- 默认返回 raw anonymous internal records。
- 在 search logic 中硬编码 ranking weights。
- 向调用方暴露 dense/sparse fusion internals。

## 进一步说明

已确认设计记录在 ADR 0001 到 ADR 0015。

推荐实现顺序：

1. 定义公共 DTO、Source Manifest validation 和 flat formatting。
2. 实现 Markdown、HTML、CSV、JSONL loading，并生成稳定 locator。
3. 实现 multilingual sparse tokenization 和 sparse search。
4. 实现 embedder protocol 和 deterministic dense search path。
5. 实现 RRF fusion 和公开 search behavior。
6. 实现 Ranking Policy，覆盖 query intent、trust、source type、freshness、privacy、mismatch、filter 和 saturation rules。
7. 实现 Privacy Level returned evidence enforcement。
8. 实现 cache metadata 和 invalidation checks。
9. 通过公开 API 增加 `find_related` 行为。
10. 运行完整验证。

第一个 TDD tracer bullet 应证明：一个 manifest-backed official source 能通过公开 Python API 被索引和搜索，返回包含 source identity、locator、score fields 和 ranking reasons 的 flat Evidence Snippet。
