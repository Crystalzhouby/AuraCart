# MARS 多智能体推荐系统 — 实现问题定义

> 基于 `docs/agent_workflow_design.md` (架构设计) + 现有 `server/` 代码库 (AuraCart RAG 搜索系统)

---

## 1. 最终交付物

| # | 交付物 | 形式 | 说明 |
|---|--------|------|------|
| 1 | **Agent 编排层** | `services/orchestrator.py` | 核心新增：调度 RW→INT→PLAN?→CLARIFY→检索→WEAVE 全链路，含4条链路分支和 CLARIFY 循环 |
| 2 | **5 个 Agent 实现** | `agents/` 目录下 5 个 .py | RW / INT / PLAN / CLARIFY / WEAVE，各自封装 LLM 调用+输出解析 |
| 3 | **Session Memory 层** | `services/session_manager.py` | Redis 读写、序列化、TTL、生命周期管理 |
| 4 | **检索适配层** | `services/retrieval_module.py` | 封装现有 Retriever+Merger+Generator 为统一 RetrievalRequest/Response 接口 |
| 5 | **多轮对话 API** | `api/chat.py` | `POST /api/chat` 端点，替代/并行于现有 `/api/search/stream` |
| 6 | **Pydantic 数据模型** | `schemas/mars.py` | IntentResult / ProductPlan / ClarificationState / SessionMemory / RetrievalRequest / Response 等 |
| 7 | **5 套 Agent Prompt 模板** | `prompts/` 目录或配置化存储 | 每个 Agent 一套，含 system prompt + 输出格式约束 + 正反例 |
| 8 | **场景库数据** | `data/scenarios.json` 或 DB 表 | 6 个预置场景模板 (sc_001~sc_006) |
| 9 | **单元/集成测试** | `tests/test_mars/` | 覆盖 4 条链路的端到端测试 + 各 Agent 的 mock 测试 |

---

## 2. 硬约束

| 约束项 | 具体要求 | 来源 |
|--------|---------|------|
| **后端框架** | FastAPI (已有) | 现有代码 |
| **大模型** | Doubao-Seed-2.0-lite, OpenAI 兼容 API | 现有 `llm.py` |
| **Embedding** | doubao-embedding, OpenAI 兼容 | 现有 `embedding.py` |
| **数据库** | PostgreSQL + pgvector (已有) | 现有 6 张表结构不变 |
| **会话存储** | Redis (新增依赖) | 架构设计 §2 |
| **Python** | ≥3.10, async/await 全链路 | 现有代码风格 |
| **兼容性** | 现有 `/api/search/stream` **不破坏**, 新增 `/api/chat` 并行存在 | 增量改造原则 |
| **反幻觉** | WEAVE Agent 不得编造价格/库存/功能 | 架构设计 §3.5 |
| **输出格式** | Tag 格式 (`<AIREPLY>`/`<OPTIONS>`/`<STATUS>`) | 架构设计 §5 |
| **最大追问轮数** | 3~5 轮 (可配置) | 架构设计 §1.5 |
| **商品返回数** | 5~10 个 | 架构设计 §1.5 |
| **Session TTL** | 30 分钟不活动过期 | 架构设计 §2 |

---

## 3. 隐含要求（从架构文档推导的实现层面需求）

### 3.1 Agent 编排层
- 需要一个**状态机驱动的编排器**，不是简单的线性函数调用
- 必须处理 **CLARIFY 的循环**（用户选择选项 → 更新 Memory → 再次调用 CLARIFY → 直到 READY）
- 必须处理 **模式切换**：模糊意图确认(模式C) → 用户选中品类 → 自动切到单品追问(模式A)
- **free_chat 短路**：跳过 PLAN + CLARIFY + 检索，直接调 WEAVE
- **多轮优化**：CLARIFY 追问期间，不需要重新走 RW+INT（仅需 RW 改写新输入 + CLARIFY）

### 3.2 Session Memory 工程化
- Memory 的 **读写时机**由 Orchestrator 控制，不由 Agent 自行写入
- **序列化**：Python dataclass/dict ↔ Redis Hash（JSON 序列化）
- **并发安全**：同一 session_id 的并发请求需要锁（Redis 分布式锁 or 应用层排队）
- **history 窗口管理**：最近 20 轮滑动裁剪，超长对话的优雅降级

### 3.3 Prompt 工程化管理
- 5 套 prompt 需要**版本化管理**（调优迭代时不能改坏其他 Agent）
- Prompt 中注入的动态变量（如 `{当前轮次}/{最大轮数}`）需要在运行时填充
- LLM 输出解析必须**容错**：JSON 解析失败、Tag 缺失、字段类型错误的降级策略
- 每个 Agent 可能需要不同的 temperature（RW/INT 低温度确定性输出，WEAVE 中等温度创意输出）

### 3.4 与现有代码的集成边界
- **复用**：`llm.py`(LLMService)、`embedding.py`(EmbeddingService)、`config.py`(Settings)、`models/`(ORM)、`database.py`
- **封装**：现有 `retriever.py` + `merger.py` + `generator.py` → 统一为 `RetrievalModule`
- **替换关系**：MARS 的 WEAVE Agent 内部调用现有 Generator 的能力，但增加 Tag 输出格式和场景组合逻辑
- **并行共存**：`/api/search/stream`(旧, 单轮 RAG) 和 `/api/chat`(新, 多轮 Agent) 同时存在

### 3.5 检索模块适配
- 现有检索基于 `SubQuery`(语义/关键词/结构化过滤)，MARS 基于 `collected_constraints`(字典)
- 需要**转换层**：`collected_constraints` → `List[SubQuery]`
- 现有检索返回 `SKUHit`(sku粒度)，MARS 需要 `EnrichedProduct`(商品粒度 + 文本块)
- 需要新增 **L3 文本块提取**：从 product_review 取 marketing_description / official_faq / user_reviews

### 3.6 错误传播与降级
- 任一 Agent LLM 调用失败 → 该 Agent 有明确的降级策略
- 整条链路超时 → 返回已有部分结果 + 错误提示
- Redis 不可用 → 退化为无状态模式（每轮独立，不支持多轮上下文）

---

## 4. 任务完成边界

### ✅ 在范围内

| 功能 | 说明 |
|------|------|
| 5 个 Agent 的完整实现 | 含 Prompt 模板、LLM 调用、输出解析、容错 |
| Agent 编排器 (Orchestrator) | 4 条链路调度 + CLARIFY 循环 + 模式切换 |
| Session Memory (Redis) | CRUD + 序列化 + TTL + history 管理 |
| 检索适配层 | 约束→SubQuery 转换 + EnrichedProduct 组装 + L3 文本块提取 |
| POST /api/chat 多轮对话端点 | 请求/响应协议 + SSE 或非流式 |
| 场景库 | 6 个预置场景 (sc_001~sc_006) |
| Pydantic Schema 全集 | 所有接口契约的数据模型 |
| 单元/集成测试 | 4 条链路端到端 + Agent mock 测试 |
| config.yaml 扩展 | 新增 MARS 相关配置项 (Redis/轮数/TTL/场景库) |

### ❌ 明确不在范围内

| 功能 | 原因 |
|------|------|
| Deerflow2 接入 | 架构设计标注"可行"但本次不实现，留后续扩展点 |
| 前端 UI | 不涉及 |
| 用户认证/权限 | 不涉及 |
| Docker/K8s 部署 | 本地运行即可 |
| 性能压测 | 后续优化 |
| 现有 `/api/search/stream` 的修改 | 保持不变，并行共存 |
| 向量数据库迁移/Schema 变更 | 复用现有 6 张表，不改结构 |
| Embedding 模型切换/对比 | 使用现有 doubao-embedding |

---

## 5. 实现风险点

### 5.1 🔴 阻塞级风险（必须实现前解决）

| # | 风险 | 影响 | 缓解方向 |
|---|------|------|---------|
| R-1 | **Redis 是否可用？** | Session Memory 的基础依赖。如果环境没有 Redis，整个多轮能力无法工作 | ⚠️ **待确认**：是否允许先用内存 dict 伪实现，后续再接 Redis？或者 Redis 是硬性前提？ |
| R-2 | **LLM 输出格式稳定性** | 5 个 Agent 都依赖 LLM 返回严格 JSON / Tag 格式。Doubao-Seed-2.0-lite 对 JSON mode 和格式指令的遵循度未知 | 先做原型验证；准备正则 fallback 解析；定义"解析失败→重试→降级"三级策略 |
| R-3 | **CLARIFY 循环的终止条件** | 用户可能无限循环选选项（每次都给新信息但不满足 READY）。如何防止死循环？ | 最大轮数硬限制(5轮)；达到上限后强制 READY 用已有信息检索；Prompt 中引导用户说"可以了" |
| R-4 | **并发 session 的 Memory 隔离** | 同一用户多标签页/多设备同时对话，session 混淆 | ⚠️ **待确认**：是否需要支持并发 session？还是简单假设单会话串行？ |

### 5.2 🟡 重要级风险（影响质量，可迭代优化）

| # | 风险 | 影响 | 缓解方向 |
|---|------|------|---------|
| R-5 | **INT 路由准确率** | "通勤太吵"被误判为 free_chat 而非 fuzzy_intent → 丢失潜在转化机会 | has_product_type + problem_description 双重判断；路由错误时可在下一轮通过自由聊天发现痛点后转入 fuzzy_intent（状态流转图已覆盖此路径） |
| R-6 | **PLAN 场景匹配精度** | "海边度假"可能匹配到 sc_001 但用户实际想要的是"海边拍照"（偏数码） | 场景库匹配加 confidence 阈值；低置信度时走模糊意图路径而非强行套场景 |
| R-7 | **WEAVE 推荐质量** | 温暖人味的推荐语 vs 机械模板化的差异，高度依赖 Prompt 和 RAG 文本块质量 | Prompt 已在架构文档中详细设计（含正反例）；文本块质量依赖 L3 提取策略 |
| R-8 | **检索适配层的约束转换损失** | `collected_constraints`(自然语言) → `SubQuery`(结构化) 的信息丢失 | RW 已提取结构化实体，约束大部分已是结构化的；仅 problem_description 需特殊处理（不走检索） |
| R-9 | **L3 文本块提取策略** | marketing_description / FAQ / reviews 从哪张表取？取多少条？如何排序？ | 架构设计已定义 source 和 schema；需确定具体 SQL 查询和数量限制 |
| R-10 | **SSE vs 非 SSE 选择** | 多轮对话场景下，SSE(单向推送)还是普通 JSON(请求-响应)更适合？ | ⚠️ **待确认**：多轮场景每次交互都是一次完整的请求-响应，SSE 仅在最终推荐生成阶段有价值 |

### 5.3 🟢 建议级风险（实现时可自然决策）

| # | 风险 | 默认决策 |
|---|------|---------|
| R-11 | Prompt 存储方式 | 先硬编码在各 Agent .py 文件的类常量中，后续再抽出到配置文件/DB |
| R-12 | 各 Agent 的 temperature | RW=0.1, INT=0.1, PLAN=0.3, CLARIFY=0.2, WEAVE=0.5 |
| R-13 | 场景库存储格式 | 先用 Python JSON 文件 (`data/scenarios.json`)，后续可迁入 DB |
| R-14 | 日志/可观测性 | 复用现有 structlog，新增 MARS 专用 logger（记录 agent_name/route/round/session_id） |
| R-15 | 测试 Mock 策略 | LLM 调用统一通过依赖注入替换为预设回复文件 (fixtures/) |

---

## 6. 已明确 & 仍待确认

### 6.1 已明确

- [x] 技术栈：FastAPI + PostgreSQL/pgvector + Redis + Doubao LLM + Doubao Embedding
- [x] 增量改造：不破坏现有 `/api/search/stream`，新增 `/api/chat` 并行
- [x] 复用清单：llm.py, embedding.py, config.py, models/, database.py — 直接复用不改动
- [x] 封装清单：retriever.py, merger.py, generator.py — 封装为 RetrievalModule
- [x] 5 个 Agent 的职责、Prompt 大纲、输入输出 Schema — 见架构文档 §3
- [x] 4 条链路的路由规则、跳过/经过关系 — 见架构文档 §1.2-1.4
- [x] Session Memory Schema 和读写规则 — 见架构文档 §2
- [x] 数据流契约 (RetrievalRequest/Response) — 见架构文档 §2.5
- [x] 场景库 6 个模板 — 见架构文档 §6
- [x] 输出格式 Tag 规范 — 见架构文档 §5

### 6.2 仍待确认

#### 阻塞级：

| # | 问题 | 候选 | 建议 |
|---|------|------|------|
| Q1 | **Redis 是否可用？** | A: 硬性前提 | B: 先用内存 dict 伪实现 | 推荐 B 先行，预留 Redis 接口 |
| Q2 | **并发 session 支持？** | A: 需要支持 | B: 单会话串行即可(v0.1) | 推荐 B，加分布式锁预留 |
| Q3 | **API 协议：SSE 还是 JSON？** | A: 全程 SSE | B: 交互期 JSON + 最终推荐 SSE | 推荐 B，多轮交互是 request-response，仅最终生成用 SSE |

#### 重要级：

| # | 问题 | 说明 |
|---|------|------|
| Q4 | **L3 文本块提取的具体 SQL** | 每个 product 取多少条 marketing/faq/review？按什么排序？ |
| Q5 | **WEAVE 的场景组合推荐格式** | 当 product_plan 有多个 slots 时，如何将多个 slot 的检索结果组装为"套装"推荐？ |
| Q6 | **free_chat 链路的 LLM 回复来源** | 是否复用 WEAVE 的 Prompt（简化版）？还是完全独立的闲聊 Prompt？ |
| Q7 | **错误码体系** | Agent 失败时的错误分类（LLM超时/格式错误/Redis断开/...）及对应 HTTP status code |
