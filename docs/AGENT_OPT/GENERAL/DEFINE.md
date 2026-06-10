# 问题定义

## 1. 功能需求

- **FR1 意图路由与查询分类**：根据用户输入和对话历史，同时完成两级分类：(a) 意图分流——"商品推荐"或"闲聊"；(b) 查询类型判断——"明确商品需求"（`is_scenario=false`）或"场景化需求"（`is_scenario=true`）。输出 `intent` + `is_scenario` 驱动条件边。
- **FR2 意图提取**：仅处理明确商品需求（`is_scenario=false`）路径。从用户提问中提取结构化 SubQuery 列表，复用现有 QueryParser 的分解能力；结合对话历史做同品类需求合并。**需具备品类标记能力**——为 SubQuery 标注 `category`/`sub_category` 字段（可选，能确定时填写），与 Scenario Gen 保持数据契约一致。不再输出 `topic_shift`——话题切换的判断完全交由 Product Retrieval 的 LLM 筛选处理。
- **FR3 场景需求生成与整合**（合并原 FR3+FR4）：当 `is_scenario=true` 时，**单次 LLM 调用 + 一次性端到端提示词**完成。品类列表从 **category_lookup 表**动态注入提示词（替换硬编码），LLM 直接按品类分组输出带 `category`（大类）+ `sub_category`（细类）标签的 SubQuery 列表（取值精确匹配查找表）。写入 Memory。保留 `scenario_description` 供 Option Gen 使用。
- **FR4 商品检索与推荐理由**：从 Memory 读取 SubQuery 列表，执行四步操作：(a) **LLM 需求筛选**——轻量级提示词，2000 token 窗口（与截断阈值一致）；(b) **按 sub_category 分组**（三级回退：sub_category → category → default）；(c) **并行检索**——各组并行执行，**每个并行任务通过 `async_session()` 创建独立 AsyncSession**（避免共享 session 的 `InvalidRequestError`），最大并发数 5（`config.yaml` 可配，启动时加载，不支持运行时动态调整），超出分批，连接池 `pool_size` ≥ `max_category_concurrency` + 3（额外预留 buffer），`max_overflow` = 5；(d) **渐进式返回**——每完成一个品类即 SSE 发送 `[{product_id, sku_id, category, sub_category}]`；前端通过新的 **batch API**（`/api/products/batch`、`/api/products/image/batch`、`/api/sku/batch`）批量获取商品详情。**(e) 提取 products_summary**——每品类检索完成后提取轻量摘要（标题/价格/品类），聚合写入 `AgentState.products_summary` 供 Option Gen 使用。
- **FR5 推荐选项生成**：在 Product Retrieval **所有品类返回后执行一次**。从 `AgentState.products_summary` 读取全部商品的轻量摘要作为生成上下文，**无需访问数据库**。输出 2-4 条下一步推荐选项，可灵活针对不同推荐品类的商品。
- **FR6 闲聊处理**：对非导购提问做简短友好回复，声明服务边界。
- **FR7 多轮对话记忆**：集中式会话记忆，append-only 策略。每个元素仅存储 `{sub_queries}`，按 token 数截断（阈值 **2000 token**，与 LLM 筛选窗口一致）。截断在**每次 append 后立即执行**（写时截断），允许截断不完整的需求组，**仅在日志中记录截断信息**。不依赖 `topic_shift` 等规则式标志。
- **FR8 LangGraph 工作流编排**：基于条件边的 Agent 路由——Router 两级分流（chat/recommend + scenario/explicit），形成两条推荐路径（explicit: Router → Intent Extraction → Memory → Product Retrieval → Option Gen；scenario: Router → Scenario Gen → Memory → Product Retrieval → Option Gen）。Product Retrieval 内部并行任务通过 `async_session()` 创建独立 session；Option Gen 无需 DB session，从 AgentState 读取 products_summary。
- **FR9 Category 查找表**：新增 `category_lookup` 表（category, sub_category, UNIQUE），从现有 product 表 DISTINCT 填充。通过 **`/server/scripts/` 下手动脚本**构建表结构和填充数据，在 `operation.md` 中说明执行步骤。Scenario Gen 动态读取可用品类注入提示词；Product Retrieval 分组时校验 sub_category 有效性。

## 2. 性能需求

- **NFR1 延迟**：单轮推荐场景的端到端延迟不超过当前 `/api/search` 管线延迟 + 新增 Agent 调用开销（预估每个 LLM Agent 节点增加 1-3s）。场景路径下并行检索 + 独立 session + 渐进式返回确保首个品类结果快速展示；SSE products 仅传 ID + 前端 batch API 聚合查询减少传输延迟和请求数。
- **NFR2 并发**：与现有 FastAPI 服务共用异步运行时，不引入阻塞调用。品类分组检索使用 `asyncio` 并发 + 独立 `AsyncSession`（每个任务从连接池获取独立连接）。LLM API 调用通过 `max_category_concurrency` 信号量控制峰值。
- **NFR3 可降级**：新增 Agent 节点超时或失败时不应阻断主流程（推荐检索链路），详见下方 fallback 策略表。

### Fallback 策略

| Agent | 失败/超时行为 | 理由 |
|---|---|---|
| **Intent Router** | 默认 `intent="recommend"`, `is_scenario=false` | 宁可多做推荐也不错失导购机会 |
| **Intent Extraction** | 回退为单一语义检索：`[SubQuery(text=user_query, strategy="semantic")]` | 复用现有 `/api/search` 的 fallback |
| **Scenario Gen** | 视为误判，回退到 Intent Extraction 做 explicit 分解 | 场景分析失败 ≠ 用户没有商品需求 |
| **Product Retrieval** | LLM 筛选失败 → 使用 Memory 全部 2000 token 历史；单品类检索失败 → 跳过该品类（记录到 `failed_categories`），其他品类继续；全部失败 → 用原始 `user_query` 做语义检索兜底 | 检索不能无输出；单品类失败隔离 |
| **Option Gen** | 跳过，回复末尾不追加选项 | 非必需功能 |
| **Chit-Chat** | 返回硬编码兜底消息 | 最轻量 fallback |

## 3. 最终交付物

1. LangGraph 工作流定义（StateGraph + 条件边 + 节点函数，6 个 Agent 节点）。
2. 各 Agent 节点的 LLM 提示词实现（6 个提示词模板，Scenario Gen 提示词含动态品类注入，Intent Extraction 提示词含品类标记能力）。
3. Memory 机制实现（`AgentState` 设计 + 2000 token 写时截断 + 日志记录截断信息 + Product Retrieval 侧 LLM 需求筛选）。
4. 与现有 QueryParser / Retriever / Merger / Generator 的集成适配层（含按 sub_category 分组并行检索 + 渐进式 SSE + SSE 精简 + products_summary 提取）。
5. Category 查找表（`category_lookup` 数据模型 + `/server/scripts/` 下手动构建脚本 + `operation.md` 操作说明 + Scenario Gen 品类注入适配）。
6. 独立 session 管理（Product Retrieval 内部 `async_session()` 创建逻辑 + 连接池 `pool_size` 与 `max_overflow` 配置）。Option Gen 无需 session。
7. 可配置并发控制（`config.yaml`：`search.max_category_concurrency`，默认 5；`database.pool_size` ≥ max_concurrency + 3；`database.max_overflow` = 5）。
8. SubQuery 数据类扩展（新增 `category` + `sub_category` 可选字段）。
9. Fallback 降级策略实现（超时控制 + 单品类失败隔离 + 兜底逻辑）。
10. 前端 batch API（`/api/products/batch`、`/api/products/image/batch`、`/api/sku/batch`）——支持一次性批量查询，减少前端请求数。
11. 单元测试 & 集成测试（覆盖单轮/多轮/场景化三条路径 + 并行检索 + 独立 session + 单品类失败隔离 + 写时截断 + fallback 路径 + batch API）。

## 4. 硬约束

- **HC1 语言**：Python 3.10+，与现有 FastAPI 服务栈一致。
- **HC2 框架**：必须使用 LangGraph（`langgraph` 包）实现 Agent 工作流。
- **HC3 LLM 调用**：复用现有 `LLMService`（`server/app/services/llm.py`），不引入新的 LLM 客户端。
- **HC4 数据库**：复用现有 SQLAlchemy 异步会话（`AsyncSession`），不修改现有数据模型。新增 `category_lookup` 表为独立新增表，不影响现有 schema。Option Gen 不从数据库查询商品详情（改用 AgentState.products_summary）。
- **HC5 RAG 管线**：QueryParser / Retriever / Merger / Generator 的核心逻辑不重构，以适配层方式接入 Agent 工作流。
- **HC6 持久化**：暂不引入 LangGraph checkpoint 持久化（SqliteSaver 等），Memory 为进程内会话级。
- **HC7 SubQuery 兼容**：新增 `category: str|None` 和 `sub_category: str|None` 字段，默认 None，现有构造代码无需修改。
- **HC8 连接池**：`pool_size` ≥ `max_category_concurrency` + 3（默认 ≥ 8），`max_overflow` = 5，需在 `create_async_engine` 中显式配置。

## 5. 隐含要求

1. 新增 Agent 节点必须支持超时控制，规格与现有 `settings.timeout` 一致。
2. 流式输出（SSE）能力保持：Product Retrieval 的推荐理由部分继续支持 token 级流式传输；渐进式返回按品类分组 SSE 事件，`products` 仅含 `[{product_id, sku_id, category, sub_category}]`。前端通过 batch API 批量获取商品详情。
3. SubQuery 结构作为 Agent 间唯一数据契约，新增 `category` + `sub_category` 均为可选字段。Intent Extraction 在能确定品类时也应填写这两个字段。
4. 提示词模板应集中管理（参考现有 `server/app/rag/prompt.py` 的组织方式）。Scenario Gen 提示词支持 `{category_list}` 动态注入；Intent Extraction 提示词需包含品类标记指引。
5. Option Gen 的选项文案最终需追加到 SSE 事件流中返回给前端；选项可跨品类灵活生成；**从 AgentState.products_summary 读取商品摘要，无需数据库访问**。
6. Memory 截断阈值 **2000 token**，LLM 筛选输入窗口同为 2000 token。截断在每次 append 后执行（写时截断），允许不完整需求组，**仅在日志中记录截断信息**（不向前端推送提示）。
7. Memory 采用 append-only 策略，所有历史需求保留，不做主动删除；由 Product Retrieval 负责 LLM 相关性筛选。
8. 不引入 `topic_shift` 等规则式标志——话题切换检测完全由 Product Retrieval 的 LLM 筛选步骤动态处理。
9. `search.max_category_concurrency`（默认 5）通过 config.yaml 配置，启动时加载，**不支持运行时动态调整**。
10. Scenario Gen 采用一次性端到端提示词——不输出中间推理，LLM 直接按品类分组输出 SubQuery。
11. 并行检索的每个任务通过 `async_session()` 创建独立 `AsyncSession`，不得共享 FastAPI DI 注入的 session。
12. Category 查找表（`category_lookup`）通过 `/server/scripts/` 下手动脚本构建和填充，执行步骤在 `operation.md` 中说明。**不采用应用启动自动同步**。
13. 前端通过新的 batch API（`/api/products/batch`、`/api/products/image/batch`、`/api/sku/batch`）批量获取商品卡片详情，替代逐 ID 调用单个 API 的方式。
14. Product Retrieval 在每品类检索完成后提取轻量商品摘要（product_id/sku_id/title/price/category/sub_category），聚合写入 `AgentState.products_summary`，供 Option Gen 使用。

## 6. 任务完成边界

| 范围 | 包含 | 不包含 |
|---|---|---|
| **Agent 实现** | 6 个 Agent 节点 + Memory + LangGraph 工作流 + fallback + 并行检索 + 独立 session 管理 + products_summary 提取 | Agent 性能调优、A/B 测试框架 |
| **集成** | 与现有 RAG 管线和 API 层适配（含按 sub_category 分组并行检索 + 渐进式 SSE + SSE 精简 + batch API） | 修改 `/api/search` 之外的 API |
| **Memory** | 会话级内存 + 2000 token 写时截断 + 仅存 sub_queries + 日志记录截断信息 | 跨进程持久化 / Redis / 数据库存储；按轮次边界对齐截断（标记为后续优化）；前端截断提示 |
| **话题切换** | Product Retrieval 侧 LLM 需求筛选（2000 token 窗口） | Memory 层需求重置或归档；不引入 topic_shift |
| **Scenario Gen** | 一次性端到端 LLM 调用 + category_lookup 表动态品类注入 | 场景知识库构建、外部场景 API |
| **Category 查找表** | 数据模型 + `/server/scripts/` 手动构建脚本 + `operation.md` 操作说明 + Scenario Gen 注入适配 | 管理后台 CRUD、品类层级树、数据库触发器同步、应用启动自动同步 |
| **配置** | `max_category_concurrency`（默认 5）+ `pool_size`（≥ 8）+ `max_overflow`（5）| 运行时动态调整、自适应限流 |
| **SubQuery** | 新增 `category` + `sub_category` 可选字段；Intent Extraction 品类标记 | 品类体系标准化 |
| **DB session** | Product Retrieval 并行任务独立 `async_session()` + 连接池配置（pool_size + max_overflow）；Option Gen 无需 session | 跨请求 session 共享、分布式事务 |
| **前端** | 新增 batch API（`/api/products/batch`、`/api/products/image/batch`、`/api/sku/batch`）| 前端 SSE 消费逻辑、UI 渲染 |
| **测试** | 核心路径单测 + 集成测试 + 并行检索测试 + 独立 session 测试 + 单品类失败隔离 + 写时截断 + fallback + batch API 测试 | 压力测试、端到端 UI 测试 |

## 7. 可能的风险点

| 风险 | 说明 |
|---|---|
| **R1 LangGraph 学习曲线** | 团队对 LangGraph 的 StateGraph / 条件边 / checkpoint 机制需要熟悉，可能会影响进度。 |
| **R2 多 Agent LLM 调用成本** | 单次请求最多 5 个 LLM 调用节点（Router → Extraction/ScenarioGen → LLM 筛选 → Generator × N 品类 → Option Gen）。通过 `max_category_concurrency` 控制 Generator 峰值并发。 |
| **R3 Memory 截断与历史丢失** | 2000 token 写时截断允许不完整需求组，可能导致跨会话关联需求丢失。通过 LLM 筛选在窗口内最大化召回，截断仅在日志体现。后续可优化为按轮次边界对齐截断。 |
| **R4 现有管线适配风险** | 新增按 sub_category 分组并行检索 + 独立 session + 渐进式 SSE + SSE 精简 + products_summary 提取 + batch API。Generator 接口不变（`Generator(llm)`），`_get_skus()` 作为独立函数在品类任务中调用；Option Gen 改为纯 State 读取。 |
| **R5 SSE 流式兼容** | LangGraph 节点执行模型与渐进式 token 流式输出需协调；跨品类并行返回的多组 SSE 事件需前端适配；前端通过 batch API（3 次请求）替代逐 ID 调用（最多 45 次），大幅降低请求数和渲染复杂度。 |
| **R6 Product Retrieval 需求筛选** | LLM 筛选替代 topic_shift，更智能但增加一次 LLM 调用。2000 token 窗口在频繁话题切换的长对话中可能不足。 |
| **R7 Scenario Gen 品类依赖** | 依赖 category_lookup 表的准确性和完整性。若品类数据过期（新品类上架但未手动刷新脚本），Scenario Gen 可能遗漏合法品类。需在 operation.md 中明确刷新时机。 |
| **R8 SubQuery 字段扩展兼容性** | 新增 `category` + `sub_category` 可选字段，dataclass 默认 None，现有代码无需改动。若未来 JSON 序列化/反序列化需确保新字段正确处理。 |
| **R9 并行 Generator 的 LLM API 限流** | 5 个品类并行 → 最多 5 个 Generator + 1 个筛选 + 1 个 Option Gen = 7 个 LLM 调用可能同时进行（跨请求合并），可能触发 LLM API 限流。通过 `max_category_concurrency` 限制 Generator 并发数。 |
| **R10 单品类失败隔离** | 并行检索中单品类失败不应阻断其他品类，需在 `done` 事件中携带 `failed_categories` 列表。独立 session 确保失败的 session 可安全关闭而不影响其他任务。 |
| **R11 连接池耗尽** | 5 个并行任务各占 1 个连接 + 主请求 DI session 1 个 + 其他并发请求。配置 `pool_size ≥ max_category_concurrency + 3`（默认 8）+ `max_overflow = 5` 提供缓冲。若连接池耗尽，新任务将阻塞等待。 |
| **R12 Category 查找表同步时机** | 改为手动脚本维护，避免启动时全表扫描拖慢启动速度。但需确保品类变更后及时执行脚本，否则 Scenario Gen 品类列表过期。operation.md 需说明执行时机。 |
| **R13 products_summary 数据一致性** | Product Retrieval 各品类任务独立提取摘要并聚合写入 AgentState。若某品类失败，其摘要缺失——Option Gen 基于不完整信息生成选项，可能遗漏跨品类搭配推荐。需在 Option Gen 提示词中标注 failed_categories。 |

## 8. 待明确问题（第八轮）

> **迭代说明**：第七轮的 5 个问题中，Q3（Intent Extraction 品类标记）部分解决——已确认扩展现有 `QUERY_PARSE_SYSTEM`，Intent Extraction 与现有 `/api/search` 的 QueryParser 共用同一份扩展提示词。但是否注入 `{category_list}` 仍待确定。新增 Q6。

1. **batch API 的批量大小是否需要上限？**：当前设计前端收到所有 SSE products 事件后，可一次性通过 3 个 batch API 获取全部商品详情。如果场景路径下 5 品类各 3 SKU = 15 个 product_id + 15 个 sku_id，单次 batch 请求传 15 个 ID。但在极端场景（如品类数 > 5 或每品类 SKU > 3）下，ID 数量可能更大——是否需要在前端/后端限制单次 batch 请求的 ID 数量上限（如 50 或 100）？还是不做限制？

2. **products_summary 摘要字段的精确范围？**：当前计划包含 product_id、sku_id、title、price、category、sub_category。是否还需要 brand（品牌维度选项）、stock（库存状态选项）？字段越多 Option Gen 生成的选项越精准，但 AgentState 中存储的数据量也越大。需要确定最小必要字段集。

3. **Intent Extraction 品类标记的实现深度？**（部分已解决）：
   - ✅ **已确定**：扩展现有 `QUERY_PARSE_SYSTEM`（`app/rag/prompt.py`），Intent Extraction 节点与现有 `/api/search` 的 QueryParser **共用同一份提示词**。新增 `category`/`sub_category` 输出字段 + 品类标记指引 + 需求合并逻辑。
   - ❓ **待确定**：explicit 路径下是否也需要给 Intent Extraction 的提示词注入 `{category_list}`（与 Scenario Gen 共享品类查找逻辑）？还是让 LLM 基于商品知识自由判断品类名称（可能产生不在查找表中的品类值，Product Retrieval 分组时会回退到 default）？

4. **category_lookup 手动脚本的执行时机？**：脚本放在 `/server/scripts/` 下，但执行时机未定——是 (a) 部署时一次性执行，(b) 每次商品品类变更后手动执行，(c) 定期（如每周）手动执行？这取决于品类变更频率和 Scenario Gen 对品类过期数据的容忍度。需要在 operation.md 中给出明确的执行时机指引。

5. **前端 batch API 的调用策略？**：前端是 (a) 每收到一个 SSE `products` 事件就立即调用 batch API 获取该品类详情（渐进式渲染，每个品类 3 次 batch 请求，5 品类 = 15 次），还是 (b) 等 `done` 事件后收集全部 ID 再统一调用（一次性渲染，共 3 次 batch 请求）？策略 (a) 首屏更快但总请求数多，策略 (b) 总请求数极少但需等所有品类完成。

6. **SSE reasoning token 的流式渲染模式？**：5 个品类并行检索 + LLM 生成时，不同品类的 reasoning token 通过 `asyncio.Queue` 汇合可能交替到达前端。前端期望的是：
   - (a) **交错渐进式**：各品类 token 按 LLM 产出速度实时交替到达，每个 token 附带 `category`/`sub_category` 路由键，前端维护多品类文本缓冲区分别追加渲染。首屏最快，但前端需处理多品类并发渲染。
   - (b) **品类顺序式**：品类 A 的全部 reasoning token → 品类 B 的全部 reasoning token → ...。后端需在品类任务内部缓冲全部 token 后一次性 `queue.put`（或按完成顺序串行发送）。前端实现更简单，但首批品类完成前无任何文本输出。
   
   两种策略影响前后端实现方式。当前后端设计支持方案 (a)。

## 9. 实现设计边界条件（新增）

> 以下问题属于**实现设计层面**的边界条件。8 个主要边界问题（B1-B8）已在 PLAN.md 中确认，
> 3 个编码层面细化设计（B9-B11）亦已标记。此处列出 PLAN.md 终稿后新识别的设计边界问题。

1. **QUERY_PARSE_SYSTEM 扩展后对现有 `/api/search` 非 Agent 路径的影响范围？**：B3 确定扩展现有 `QUERY_PARSE_SYSTEM`，新增 `category`/`sub_category` 输出字段。这意味着现有 `/api/search`（非 Agent 路径，不经 LangGraph）的 `QueryParser` 返回的 `SubQuery` 也将包含这两个新字段。需确认：
   - 现有 `/api/search` 的 SSE `sub_queries` 事件中新增字段是否影响前端解析？
   - `SearchResponse` 模型的 `sub_queries` 序列化是否需要同步更新以包含新字段？

2. **graph.ainvoke() 异常时 SSE 消费者如何退出？**：当前设计 `event_stream()` 通过 `while True: event = await queue.get()` 消费事件，以 `event["event"] == "done"` 为退出条件。如果 `graph.ainvoke()` 因未捕获异常而崩溃（节点未 put "done" 事件），`queue.get()` 将永久阻塞，导致连接泄漏。需在消费者端增加超时保护（如 `asyncio.wait_for(queue.get(), timeout=...)`）或通过 try/finally 确保 "done" 事件一定被推送。

3. **并行品类数超过 max_category_concurrency 时的分批策略？**：`asyncio.Semaphore(5)` 限流下，当品类数 > 5（如 8 品类），信号量自动排队——但排队的任务以什么顺序启动（先到先得 vs 按完成顺序填补）？信号量的默认行为是 FIFO 等待队列，品类完成顺序不影响启动顺序。需确认此行为是否符合预期（可能导致 LLM 调用峰值分布不均匀）。

