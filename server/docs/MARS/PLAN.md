# MARS 多智能体推荐系统 — 实现方案

> 基于 DEFINE.md + `docs/agent_workflow_design.md` (架构设计) + 现有 `server/` 代码库

---

## 1. 各功能点概要实现链路

### 1.1 Agent 编排层 (Orchestrator) — 核心调度引擎

**文件**: `services/orchestrator.py`
**类**: `MarsOrchestrator`

```
用户请求 POST /api/chat {session_id, message}
        │
        ▼
┌─ Orchestrator.chat() ────────────────────────────────┐
│                                                        │
│  ① 加载/创建 SessionMemory (SessionManager)          │
│     ├─ 新 session → 创建空 Memory, UUID4              │
│     ├─ 已有 session → 从 Redis 加载                   │
│                                                        │
│  ② 追加用户消息到 conversation_history                 │
│                                                        │
│  ③ 判断是否处于 CLARIFY 循环中？                       │
│     ├─ 是(状态=CLARIFYING) → 走快速路径:               │
│     │   ├─ RW.rewrite(当前用户输入)                    │
│     │   └─ CLARIFY.clarify(memory) → 输出/继续循环      │
│     │                                                │
│     └─ 否(新请求或状态≠CLARIFYING) → 走完整链路:      │
│        ├─ RW.rewrite(user_input, history[-10:])       │
│        │   → 写入 memory.rewritten_query, entities    │
│        │                                                │
│        ├─ INT.route(entities)                          │
│        │   → 写入 memory.intent_result                │
│        │                                                │
│        ├─ [分支判断] ← intent_result.intent_type      │
│        │   ├─ free_chat → 跳到 ⑥                     │
│        │   ├─ clear_intent → 跳到 ④                  │
│        │   └─ scenario/fuzzy → ③ PLAN               │
│        │                                                │
│        ├─ ③ PLAN.plan(intent_result, entities)         │
│        │   source = intent_type (编排层映射)           │
│        │   → 写入 memory.product_plan                 │
│        │                                                │
│        ├─ ④ CLARIFY.clarify(memory)                   │
│        │   模式自动选择(规则B):                        │
│        │   clear→A / scenario→B / fuzzy→C            │
│        │   ├─ 输出 CLARIFYING → 返回给用户, 等待下一轮  │
│        │   └─ 输出 READY → 继续                      │
│        │                                                │
│        ├─ ⑤ RetrievalModule.search(constraints)        │
│        │   L1 RAG + L2 SQL补全 + L3 文本块提取         │
│        │   → 写入 memory.retrieval_cache, products    │
│        │                                                │
│        └─ ⑥ WEAVE.weave(products, chunks, intent)     │
│            → 写入 memory.final_response               │
│                                                        │
│  ⑦ 持久化 Memory 到 Redis                             │
│  ⑧ 返回 ChatResponse 给前端                           │
└────────────────────────────────────────────────────────┘
```

**关键设计决策**:
- **状态驱动**: 通过 `clarification_status` 判断走完整链路还是快速路径
- **单入口**: 所有请求统一进入 `chat()`，内部自动路由
- **原子性**: 每个 Agent 执行完立即持久化 Memory（防崩溃丢失）

### 1.2 ① QueryRewriter Agent (RW)

**文件**: `agents/query_rewriter.py`
**类**: `QueryRewriterAgent`

| 项目 | 说明 |
|------|------|
| **LLM 调用** | 1 次 non-stream (`llm.chat()`)，temperature=0.1 |
| **输入** | user_query(str) + history(list[ChatMessage], 最近10轮) |
| **输出** | RewriteResult(rewritten_query, extracted_entities dict, has_product_type bool, confidence float) |
| **Prompt** | 架构文档 §3.1 的完整 Prompt 模板（含8个提取维度+5条原则） |
| **输出解析** | JSON mode 解析；fallback: 正则提取 `<json>` 块 |
| **容错** | LLM 超时(3s) → 返回原始 query 作为 rewritten_query, entities 为空字典 |

**与现有代码关系**: 替换/增强现有 `query_parser.py` 的能力。RW 不做 SubQuery 拆解（那是旧流程），只做标准化+实体提取。

### 1.3 ② IntentRouter Agent (INT)

**文件**: `agents/intent_router.py`
**类**: `IntentRouterAgent`

| 项目 | 说明 |
|------|------|
| **LLM 调用** | 1 次 non-stream, temperature=0.1 |
| **输入** | rewritten_query + extracted_entities + has_product_type |
| **输出** | IntentResult(intent_type enum, primary_category, confidence, routing_reason, suggested_pending_items) |
| **Prompt** | 架构文档 §3.2 的 Prompt（4分支定义+触发条件+示例） |
| **特殊逻辑** | 若 `has_product_type==false and problem_description 非空` → 强制 fuzzy_intent（不依赖 LLM 判断） |
| **容错** | LLM 失败 → 默认 fuzzy_intent（最安全兜底，宁可多问一句） |

### 1.4 ③ ProductPlanner Agent (PLAN)

**文件**: `agents/product_planner.py`
**类**: `ProductPlannerAgent`

| 项目 | 说明 |
|------|------|
| **LLM 调用** | 1 次 non-stream, temperature=0.3 |
| **输入** | intent_result + extracted_entities + source("scenario_plan"/"fuzzy_intent") |
| **输出** | ProductPlan(source, plan_name, slots[], guesses_confidence, ...) |
| **双策略** | source=scenario_plan → Prompt 注入场景库列表; source=fuzzy_intent → Prompt 引导痛点推理 |
| **场景库加载** | 启动时从 `data/scenarios.json` 加载到内存 (6 个模板) |
| **容错** | LLM 失败 → 返回空 slots + low confidence, CLARIFY 会降级为模式A追问 |

### 1.5 ④ PreferenceClarifier Agent (CLARIFY)

**文件**: `agents/preference_clarifier.py`
**类**: `PreferenceClarifierAgent` ⭐ 最复杂 Agent

| 项目 | 说明 |
|------|------|
| **LLM 调用** | 每次 1 次 non-stream, temperature=0.2 |
| **输入** | memory 全量 (intent + plan + constraints + state + history + current_input) |
| **输出** | ClarifyResult(AIREPLY str, OPTIONS list, STATUS enum) / ReadyResult(collected_constraints) |
| **模式自动选择** | 编排层根据 intent_type + product_plan.source 决定传入哪种模式指令 (见架构文档 2.5.2 规则B) |
| **状态更新** | 每次执行后更新 clarification_state.current_round += 1; 追加 collected_constraints |
| **READY 判断** | 任一: 约束可缩小到5~10商品 / 达到最大轮数 / 用户说"可以了" |
| **选项处理** | 用户点击选项 → 编排层将选项文本作为下一轮 user_input, 同时解析写入 collected_constraints |

**核心复杂度 — 模式C 流转**:
```
模糊意图 → PLAN 给出猜测 slots → CLARIFY 模式C 展示猜测选项
  → 用户选了某个猜测(如"降噪耳机")
  → 编排层将 selected_guess 补全到 collected_constraints.product_type
  → 下一轮: CLARIFY 自动切换为模式A(单品追问预算/场景)
  → 继续追问直到 READY
```

### 1.6 ⑤ ResponseWeaver Agent (WEAVE)

**文件**: `agents/response_weaver.py`
**类**: `ResponseWeaverAgent`

| 项目 | 说明 |
|------|------|
| **LLM 调用** | 1 次 stream (`llm.chat_stream()`) 用于最终推荐生成, temperature=0.5 |
| **输入** | enriched_products[] + rag_chunks[] + intent_result + product_plan(optional) |
| **输出** | WeaveResult(AIREPLY str, STATUS=COMPLETE, recommended_ids[]) |
| **三种格式** | 单品推荐 / 场景组合推荐 / 自由对话 (由 intent_type 决定使用哪个子 Prompt) |
| **与现有 Generator 关系** | 内部复用 `rag/generator.py` 的 `_build_context()` 逻辑来格式化商品信息；但 Prompt 完全不同（增加温暖语气、评价引用、Tag 输出） |
| **free_chat 特殊路径** | products=[], chunks=[] → 使用独立的"自由对话"子 Prompt |
| **容错** | LLM 失败 → 返回纯文本商品列表（无温度） |

### 1.7 Session Memory 层

**文件**: `services/session_manager.py`
**类**: `SessionManager`

| 项目 | 说明 |
|------|------|
| **存储** | Redis Hash, key=`mars:session:{session_id}` |
| **序列化** | orjson/json (Python dict ↔ JSON string) |
| **CRUD** | create() / load(session_id) / save(memory) / delete(session_id) / exists() |
| **TTL** | 每次save() 刷新 30min 过期 |
| **history 管理** | append_message() 自动裁剪超 20 轮的旧记录 |
| **Redis 降级** | ⚠️ Q1 待确认: 先实现 InMemorySessionManager (dict), 同一接口，后续无缝切换 Redis |

### 1.8 检索适配层 (RetrievalModule)

**文件**: `services/retrieval_module.py`
**类**: `RetrievalModule`

**职责**: 将 MARS 的 `collected_constraints` + `product_plan` 转换为现有检索系统能理解的格式，并增强输出。

```
RetrievalRequest (MARS 格式)
        │
        ▼
┌─ RetrievalModule.search() ──────────────────────┐
│                                                    │
│  Step 1: 约束转换                                  │
│    collected_constraints → List[SubQuery]          │
│    - product_type → semantic SubQuery             │
│    - price_min/max → structured_filter SubQuery   │
│    - brand → structured_filter (expanded_values)  │
│    - negative_constraints → negation SubQuery     │
│                                                    │
│  Step 2: 调用现有检索                              │
│    Retriever.retrieve(sub_queries) → SKUHit[]     │
│    Merger.merge(keyword, semantic) → ranked[]     │
│                                                    │
│  Step 3: SKUHit → EnrichedProduct 升级             │
│    - 按 product_id 聚合 SKUHit → 商品粒度          │
│    - JOIN product 表取 title/brand/category        │
│    - JOIN sku 表取实时 price/stock                 │
│                                                    │
│  Step 4: L3 文本块提取 (新增!)                     │
│    - 对每个 product_id:                            │
│      ├─ SELECT content FROM product_review        │
│      │   WHERE source='marketing' LIMIT 1         │
│      ├─ SELECT question, answer FROM product_faq  │
│      │   WHERE product_id=? LIMIT 3               │
│      └─ SELECT content FROM user_review           │
│          WHERE product_id=? ORDER BY rating DESC   │
│          LIMIT 3                                   │
│    - 组装 RAGChunk[]                               │
│                                                    │
│  Step 5: 场景方案 slot 匹配 (可选)                  │
│    - 若 product_plan 存在:                         │
│      将每个 EnrichedProduct.matched_slot 设为       │
│      最佳匹配的 slot.role                          │
│                                                    │
└────────────────────────────────────────────────────┘
        │
        ▼
RetrievalResponse (enriched_products[] + rag_chunks[])
```

### 1.9 API 层

**文件**: `api/chat.py`
**端点**: `POST /api/chat`

```python
# Request
class ChatRequest:
    session_id: str | None = None   # null=新建会话
    message: str                    # 用户消息

# Response (交互期: CLARIFYING)
class ChatResponse:
    reply: str                      # <AIREPLY> 内容
    options: list[Option] | None    # <OPTIONS> 解析后的结构化数据
    status: "CLARIFYING" | "READY" | "COMPLETE"
    session_id: str

# Response (完成期: COMPLETE)
class ChatResponse:
    reply: str                      # <AIREPLY> 推荐内容
    options: None
    status: "COMPLETE"
    session_id: str
    recommended_products: list[ProductSummary] | None  # 仅 COMPLETE 时有值
```

**协议选择 (Q3 决策)**: 采用 **JSON request-response** 模式（非 SSE）。原因：
- 多轮对话每次交互都是完整的 请求-响应
- SSE 的价值仅在最终推荐的流式生成阶段
- v0.1 先用 JSON 保证简单可靠，v1.0 可考虑 WEAVE 阶段用 SSE 流式输出推荐语

---

## 2. 主要优点

1. **增量改造，零破坏**
   - 现有 `/api/search/stream` 完全不动
   - 新增独立模块 (`agents/`, `services/session_manager.py`, `api/chat.py`)
   - 检索层通过适配器封装，不修改现有 retriever/merger/generator 内部逻辑

2. **编排层解耦 Agent 逻辑**
   - 每个 Agent 是纯函数式（输入→调用LLM→解析输出），不持有状态
   - 所有状态在 SessionMemory 中，由 Orchestrator 统一管理
   - Agent 可独立测试（mock LLM 即可）

3. **渐进式降级保证可用性**
   - 任一 Agent 失败不影响整体崩溃：RW失败→原文送INT；INT失败→默认fuzzy；PLAN失败→空plan走模式A；CLARIFY失败→强制READY；WEAVE失败→返回商品列表
   - Redis 降级为内存 dict，保证即使没有 Redis 也能跑通主流程

4. **Prompt 工程化基础扎实**
   - 架构文档已提供每个 Agent 的完整 Prompt 初版（含正反例）
   - 输出格式约束严格（Tag + JSON Schema），降低解析复杂度
   - temperature 分级设置（确定性 vs 创意性分离）

5. **场景库可扩展**
   - JSON 文件存储，新增场景无需改代码
   - 匹配算法基于关键词+类别，简单有效

---

## 3. 主要风险与缓解

| # | 风险 | 缓解措施 |
|---|------|---------|
| R-1 | Redis 不可用 | InMemorySessionManager 同接口实现，启动时通过配置切换 |
| R-2 | LLM 输出格式不稳定 | 三级策略: JSON mode → 正则 fallback → 重试(1次) → 降级默认值 |
| R-3 | CLARIFY 死循环 | 最大轮数硬限制(5轮, configurable); 超限强制 READY |
| R-4 | 并发 session 混淆 | v0.1 不处理(串行假设); 接口预留 session_lock 机制 |
| R-5 | INT 路由错误 | has_product_type+problem_description 双重硬规则覆盖; free_chat 可在下一轮转入 fuzzy |
| R-6 | 检索转换信息损失 | RW 已做结构化实体提取; 转换层加日志记录映射过程便于调试 |
| R-7 | WEAVE 推荐质量 | 复用现有 Generator 的上下文构建经验; Prompt 含真实评价引用要求 |
| R-8 | 端到端延迟 | 单轮完整链路约 3~8s (5次LLM调用串行); 后续可并行化 RW+INT 或缓存 PLAN 结果 |

---

## 4. 实现复杂度评估

### 总体评级：中高（比现有搜索系统高一个等级，核心在编排和状态管理）

| 维度 | 评估 | 说明 |
|------|------|------|
| **新概念学习** | 低 | FastAPI/Redis/Pydantic/asyncio 均为团队已有技术栈 |
| **模块数量** | 中高 | 新增 ~12 个 .py 文件 (5 agents + orchestrator + session + retrieval_module + chat api + schemas + prompts + scenarios) |
| **外部依赖** | 中 | 新增 Redis (但可降级); 其余复用现有 |
| **算法复杂度** | 中 | 无自研算法; 核心是条件分支编排和状态机，均为确定性的 if-else 逻辑 |
| **状态管理** | **中高** | SessionMemory 的并发读写、序列化、TTL、窗口滑动 —— 这是比现有系统最大的复杂度增量 |
| **边界情况** | 中高 | 4 条链路 × 3 种 CLARIF 模式 × N 轮循环 × Agent 降级路径 = 大量组合需测试覆盖 |

### 按模块复杂度

| 模块 | 复杂度 | 关键难点 |
|------|--------|---------|
| `orchestrator.py` | **中高** | 状态机驱动调度; CLARIFY 循环; 模式切换; 快速路径 vs 完整路径 |
| `agents/clarifier.py` | **中高** | 3 种模式的 Prompt 和输出解析; 约束累积逻辑; READY 判断 |
| `retrieval_module.py` | **中** | 约束→SubQuery 转换; L3 文本块提取 SQL; SKU→EnrichedProduct 升级 |
| `session_manager.py` | **中** | 序列化/反序列化; TTL; history 窗口; Redis 操作 |
| `agents/weaver.py` | **中** | 3 种输出格式; 与现有 Generator 的关系; Tag 输出封装 |
| `agents/rewriter.py` | **低中** | 标准 LLM 调用+JSON 解析; 容错简单 |
| `agents/intent_router.py` | **低中** | 4 分类 + 1 条硬规则; 容错默认 fuzzy |
| `agents/product_planner.py` | **低中** | 双策略(Prompt 分支); 场景库匹配 |
| `api/chat.py` | **低** | 标准 FastAPI 端点; 参数校验; 响应组装 |

**关键路径风险**: Orchestrator + CLARIFIER 的状态管理质量决定系统可靠性。

---

## 5. 可测试性

### 测试分层

| 层级 | 范围 | 工具 | 覆盖目标 |
|------|------|------|---------|
| **Agent 单元测试** | 每个 Agent 独立 | pytest + pytest-asyncio + mock LLM | 每个 Agent 的正常输出/格式错误/超时/降级路径 |
| **Orchestrator 集成测试** | 4 条链路的完整调度 | pytest + mock 所有 Agent + InMemorySession | 链路路由正确性; 状态流转正确性; CLARIFY 循环终止 |
| **Session Manager 测试** | CRUD + TTL + 序列化 | pytest + fakeredis (或 InMemory) | 读写一致性; TTL 过期; history 裁剪 |
| **Retrieval Module 测试** | 约束转换 + L3 提取 | pytest + test DB | 约束→SubQuery 映射正确; EnrichedProduct 字段完整 |
| **API 端到端测试** | POST /api/chat 全流程 | httpx + test DB + mock LLM (预设回复 fixture) | 4 条链路各一个完整 happy path + 错误路径 |
| **Prompt 质量验证** | LLM 输出格式验证 | 预设 20+ 组典型输入 → 验证输出符合 JSON Schema / Tag 格式 | 格式遵循率目标 > 95% |

### 关键测试场景 (必须覆盖)

| # | 场景 | 验证点 |
|---|------|--------|
| T-1 | "通勤太吵" → fuzzy → PLAN猜测 → CLARIFY确认 → 模式A追问 → READY → 推荐 | 完整模糊意图收敛链路 |
| T-2 | "200块防晒，不要太油" → clear_intent → CLARIFY 直接 READY | 明确意图单轮直通 |
| T-3 | "你好呀" → free_chat → WEAVE 自由对话 | 自由聊天短路 |
| T-4 | "海边度假装备" → scenario → PLAN 匹配 sc_001 → CLARIFY 模式B 槽位追问 | 场景方案槽位澄清 |
| T-5 | CLARIFY 达到 5 轮仍未 READY → 强制 READY 用已有信息检索 | 轮数上限保护 |
| T-6 | RW LLM 超时 → 原文透传 → INT 正常工作 | RW 降级 |
| T-7 | INT LLM 超时 → 默认 fuzzy_intent → 进入 PLAN | INT 降级 |
| T-8 | WEAVE LLM 超时 → 返回商品列表无推荐语 | WEAVE 降级 |
| T-9 | Redis 断开 → InMemory 兜底 → 多轮正常工作 | 存储降级 |
| T-10 | 同一 session 连续 3 轮对话 → history 正确累积 → 第 3 轮能引用第 1 轮信息 | 多轮上下文保持 |

---

## 6. 可交付性

### 交付物清单

| # | 交付物 | 形式 | 验收标准 |
|---|--------|------|---------|
| 1 | Agent 编排器 | `services/orchestrator.py` | 4 条链路可正确调度; CLARIFY 循环可正常终止 |
| 2 | 5 个 Agent | `agents/*.py` (5 files) | 各自通过单元测试(mock LLM); 输出格式符合 Schema |
| 3 | Session Manager | `services/session_manager.py` | CRUD 正常; TTL 生效; history 窗口裁剪 |
| 4 | 检索适配层 | `services/retrieval_module.py` | 约束转换正确; L3 文本块可提取; 输出含 EnrichedProduct+RAGChunk |
| 5 | Chat API | `api/chat.py` | POST /api/chat 可调用; 3 种 status 均可返回 |
| 6 | Pydantic Schemas | `schemas/mars.py` | 所有数据模型可通过类型检查 |
| 7 | Prompt 模板 | `prompts/*.py` (5 files) 或内嵌 | 5 套 Prompt 完整可用 |
| 8 | 场景库 | `data/scenarios.json` | 6 个场景模板可被 PLAN 加载和匹配 |
| 9 | config 扩展 | `config.yaml` 新增 mars 段 | Redis/TTL/轮数等参数可配置 |
| 10 | 测试 | `tests/test_mars/` | ≥10 个关键测试场景通过 |

### 不交付

- Deerflow2 接入
- 前端 UI
- 用户认证
- 性能压测
- Docker/K8s 配置
- 现有 `/api/search/stream` 的任何修改

### 交付节奏建议

| 阶段 | 内容 | 预计人天 |
|------|------|---------|
| **Phase 1: 基础骨架** | schemas/mars.py + SessionManager(InMemory) + config扩展 + 场景库JSON | 1-2 天 |
| **Phase 2: Agent 实现** | 5 个 Agent (RW/INT/PLAN/CLARIFY/WEAVE) + Prompt 模板 + 输出解析 | 2-3 天 |
| **Phase 3: 编排层** | Orchestrator (全链路调度 + 状态机 + 4 条链路 + CLARIFY 循环) | 2-3 天 |
| **Phase 4: 检索适配 + API** | RetrievalModule + api/chat.py + 端到端联调 | 1-2 天 |
| **Phase 5: 测试 + 降级** | 10 个关键测试场景 + Agent 降级路径 + 边界情况 | 1-2 天 |
| **总计** | | **7-12 人天** |

> 工期范围取决于 LLM 输出格式稳定性验证的迭代轮数。
