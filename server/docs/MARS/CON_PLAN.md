# MARS 多智能体推荐系统 — 编码级系统骨架

> 基于 DEFINE.md + PLAN.md + `docs/agent_workflow_design.md` + 现有 `server/` 代码
> 目标：足够支撑开始编码，不展开实现细节

---

## 1. 细粒度模块拆分

| 文件 | 职责 | 行数估计 | 新增/复用/改造 |
|------|------|---------|--------------|
| `schemas/mars.py` | 所有 Pydantic 数据模型 (IntentResult, ProductPlan, ClarificationState, SessionMemory, RetrievalRequest/Response, ChatRequest/Response, EnrichedProduct, RAGChunk 等) | ~200 | **新增** |
| `services/session_manager.py` | Session CRUD (create/load/save/delete/exists) + history 追加 + TTL + 序列化; 支持 InMemory 和 Redis 双后端 | ~180 | **新增** |
| `agents/base.py` | Agent 基类: 统一的 LLM 调用封装、JSON 解析容错、超时控制、日志 | ~80 | **新增** |
| `agents/query_rewriter.py` | RW Agent: 口语标准化+实体提取+纠错补全 | ~120 | **新增** |
| `agents/intent_router.py` | INT Agent: 4 分支路由判断 | ~100 | **新增** |
| `agents/product_planner.py` | PLAN Agent: 场景库匹配 / 痛点推理猜测 | ~140 | **新增** |
| `agents/preference_clarifier.py` | CLARIFY Agent: 模式A/B/C 追问 + 约束累积 + READY 判断 | ~200 | **新增** |
| `agents/response_weaver.py` | WEAVE Agent: 推荐/组合/自由对话 三种格式生成 | ~150 | **新增** |
| `prompts/__init__.py` + 5 个 prompt 文件 | 5 套 Prompt 模板常量 (RW/INT/PLAN/CLARIFY/WEAVE 各一套, 含 system prompt + 输出格式示例) | ~300 total | **新增** |
| `services/orchestrator.py` | 核心编排器: 全链路调度 + 状态机 + CLARIFY 循环 + 快速路径 vs 完整路径 | ~250 | **新增** |
| `services/retrieval_module.py` | 检索适配层: 约束→SubQuery转换 + L3文本块提取 + EnrichedProduct组装 | ~200 | **新增** |
| `api/chat.py` | POST /api/chat 端点 + 参数校验 + 响应组装 | ~80 | **新增** |
| `data/scenarios.json` | 6 个预置场景模板数据 | ~80 | **新增** |
| `app/main.py` | **改造**: 注册 chat router | ~5 | **改造** (加2行) |
| `app/config.py` | **改造**: 新增 MarsSettings (Redis/TTL/轮数/场景库路径) | ~25 | **改造** (加1个class) |
| `config.yaml` | **改造**: 新增 `mars:` 配置段 | ~15 | **改造** |

**总计: ~15 个文件, 其中 12 个新增, 3 个改造, 0 个删除**

---

## 2. 目录结构

```
server/
├── app/
│   ├── __init__.py
│   ├── main.py                      # [改] +2行: register chat router
│   ├── config.py                    # [改] +MarsSettings class
│   ├── database.py                  # 不变
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── search.py               # 不变
│   │   ├── products.py             # 不变
│   │   ├── admin.py                # 不变
│   │   └── chat.py                 # [新] POST /api/chat
│   │
│   ├── models/                     # 不变 (6张表 ORM)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── product.py              # 不变
│   │   └── mars.py                 # [新] 所有 MARS Pydantic 模型
│   │
│   ├── services/
│   │   ├── __init__.py             # [改] 导出新模块
│   │   ├── llm.py                  # 不变 (复用)
│   │   ├── embedding.py            # 不变 (复用)
│   │   ├── query_parser.py         # 不变 (保留, 与 RW 并存)
│   │   ├── retriever.py            # 不变 (复用)
│   │   ├── sync.py                 # 不变
│   │   ├── import_data.py          # 不变
│   │   ├── orchestrator.py         # [新] 核心编排器
│   │   ├── session_manager.py      # [新] 会话 Memory 管理
│   │   └── retrieval_module.py     # [新] 检索适配层
│   │
│   ├── agents/                     # [新目录] 5 个 Agent
│   │   ├── __init__.py
│   │   ├── base.py                 # Agent 基类
│   │   ├── query_rewriter.py       # ① RW
│   │   ├── intent_router.py        # ② INT
│   │   ├── product_planner.py      # ③ PLAN
│   │   ├── preference_clarifier.py # ④ CLARIFY
│   │   └── response_weaver.py      # ⑤ WEAVE
│   │
│   ├── prompts/                    # [新目录] Prompt 模板
│   │   ├── __init__.py
│   │   ├── rewriter.py             # RW system prompt
│   │   ├── intent_router.py        # INT system prompt
│   │   ├── product_planner.py      # PLAN system prompt
│   │   ├── preference_clarifier.py # CLARIFY system prompt
│   │   └── response_weaver.py      # WEAVE system prompt
│   │
│   ├── rag/                        # 不变 (retriever/merger/generator/prompt)
│   ├── core/                       # 不变
│   └── models/                     # 不变
│
├── data/
│   ├── scenarios.json              # [新] 场景库 (6 个模板)
│   └── ecommerce_agent_dataset/    # 不变
│
├── config.yaml                     # [改] +mars: 段
├── tests/
│   ├── test_mars/                  # [新目录]
│   │   ├── __init__.py
│   │   ├── conftest.py            # fixtures: mock LLM, InMemorySession, test DB
│   │   ├── test_rewriter.py
│   │   ├── test_intent_router.py
│   │   ├── test_product_planner.py
│   │   ├── test_clarifier.py
│   │   ├── test_weaver.py
│   │   ├── test_orchestrator.py   # 4 条链路端到端
│   │   ├── test_session_manager.py
│   │   └── test_retrieval_module.py
│   └── ...                         # 现有测试不变
│
└── docs/
    └── MARS/
        ├── DEFINE.md              # ✅ 已完成
        ├── PLAN.md                # ✅ 已完成
        └── CON_PLAN.md             # 📝 本文件
```

---

## 3. 核心接口

### 3.1 Orchestrator — 主入口

```python
# services/orchestrator.py

class MarsOrchestrator:
    """MARS 多智能体编排器。所有 /api/chat 请求的唯一入口。"""
    
    def __init__(
        self,
        session_mgr: SessionManager,          # 会话管理
        rw: QueryRewriterAgent,                # ① 改写
        intent_router: IntentRouterAgent,     # ② 路由
        planner: ProductPlannerAgent,          # ③ 方案
        clarifier: PreferenceClarifierAgent,  # ④ 澄清
        weaver: ResponseWeaverAgent,          # ⑤ 编织
        retrieval: RetrievalModule,           # 检索适配
    ): ...

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """
        主入口：处理一轮用户对话。
        
        实现思路:
        1. loadOrCreate session → get/set session_id
        2. append user message to history
        3. if status == CLARIFYING:
               fast_path: only RW + CLARIFY (skip INT/PLAN)
           else:
               full_path: RW → INT → [PLAN?] → CLARIFY → retrieval → WEAVE
        4. persist memory
        5. return ChatResponse
        """

    async def _full_chain(self, memory: SessionMemory, user_input: str) -> None:
        """完整链路: RW → INT → PLAN? → CLARIFY → retrieval → WEAVE"""
        # 实现: 顺序调用各 agent，将结果写入 memory

    async def _clarify_loop(self, memory: SessionMemory, user_input: str) -> ClarifyResult:
        """CLARIFY 循环: 调用 CLARIFY → 如果 CLARIFYING 则返回; READY 则继续下游"""

    def _select_clarify_mode(self, memory: SessionMemory) -> str:
        """根据 intent_type + product_plan.source 选择模式 A/B/C (规则B)"""
```

### 3.2 Agent 基类

```python
# agents/base.py

class BaseAgent(ABC):
    """Agent 基类。提供统一的 LLM 调用和输出解析能力。"""
    
    def __init__(self, llm: LLMService, prompt_template: str, timeout: float = 10.0): ...

    async def _call_llm(
        self,
        messages: list[dict],
        temperature: float | None = None,
        parse_json: bool = True,
    ) -> dict | str:
        """
        统一 LLM 调用。
        
        实现思路:
        1. asyncio.wait_for(self.llm.chat(), timeout=self.timeout)
        2. if parse_json: 尝试 json.loads() → 失败则正则提取 ```json...``` → 再失败返回 {}
        3. else: 返回原始字符串
        4. 超时/异常: 记录日志, 返回默认空值 (由子类定义 default_response())
        """

    @abstractmethod
    def default_response(self) -> dict: ...

    def _build_messages(self, system_prompt: str, user_content: str, **kwargs) -> list[dict]:
        """将系统提示词模板与动态变量合并为 messages 列表"""
```

### 3.3 各 Agent 接口

```python
# agents/query_rewriter.py
class QueryRewriterAgent(BaseAgent):
    async def rewrite(
        self, user_query: str, history: list[ChatMessage] | None = None
    ) -> RewriteResult:
        """
        实现: 组装 messages (system=REWRITER_PROMPT, user=user_query+history摘要)
              → _call_llm() → 解析 JSON → 返回 RewriteResult
        """

# agents/intent_router.py
class IntentRouterAgent(BaseAgent):
    async def route(
        self, rewritten_query: str, entities: dict, has_product_type: bool
    ) -> IntentResult:
        """
        实现: 若 !has_product_type and entities.problem_description → 直接返回 fuzzy_intent
              否则 → _call_llm() → 解析 intent_type enum
        """

# agents/product_planner.py
class ProductPlannerAgent(BaseAgent):
    def __init__(self, llm, scenarios: list[ScenarioTemplate], ...): ...
    
    async def plan(
        self, intent_result: IntentResult, entities: dict, source: str
    ) -> ProductPlan:
        """
        实现: source=='scenario_plan' → 注入场景库列表到 Prompt
              source=='fuzzy_intent' → 引导痛点推理 Prompt
              → _call_llm() → 解析 ProductPlan JSON
        """

# agents/preference_clarifier.py
class PreferenceClarifierAgent(BaseAgent):
    async def clarify(
        self, memory: SessionMemory, current_input: str
    ) -> ClarifyResult | ReadyResult:
        """
        实现: 根据 memory 选择模式(A/B/C)子 Prompt
              注入: 已收集约束 + 当前轮次 + 方案slots + 对话历史 + 用户输入
              → _call_llm()
              → 解析 <STATUS>: 若 CLARIFYING → 更新 state.round++, 返回 ClarifyResult
                          若 READY → 合并约束到 collected_constraints, 返回 ReadyResult
        """

# agents/response_weaver.py
class ResponseWeaverAgent(BaseAgent):
    async def weave(
        self,
        products: list[EnrichedProduct],
        chunks: list[RAGChunk],
        intent: IntentResult,
        plan: ProductPlan | None = None,
    ) -> WeaveResult:
        """
        实现: 根据 intent.intent_type 选择子 Prompt
              (clear/scenario→单品/组合格式, free_chat→自由对话格式)
              注入: 商品信息 + RAG chunks (必须引用!)
              → _call_llm(stream=True) → 逐 token 收集 → 返回 WeaveResult
        """
```

### 3.4 Session Manager

```python
# services/session_manager.py

class SessionManager:
    """会话 Memory 的 CRUD 管理。支持 InMemory 和 Redis 双后端。"""
    
    def __init__(self, backend: str = "memory", **redis_kwargs): ...
    
    async def create(self) -> SessionMemory:
        """创建新会话: 空 history/空 constraints/UUID4 session_id"""

    async def load(self, session_id: str) -> SessionMemory | None:
        """从后端加载完整 SessionMemory; 不存在返回 None"""

    async def save(self, memory: SessionMemory) -> None:
        """序列化并写入后端; 刷新 TTL"""

    async def delete(self, session_id: str) -> None:
        """删除会话"""

    async def exists(self, session_id: str) -> bool:
        """检查会话是否存在"""

    async def append_message(
        self, session_id: str, role: str, content: str
    ) -> None:
        """追加一条消息到 history; 自动裁剪超 20 轮的旧记录"""

    class InMemoryBackend:
        """内存实现 (dict[str, SessionMemory]), 用于无 Redis 环境"""

    class RedisBackend:
        """Redis 实现 (Hash + TTL), 用于生产环境"""
```

### 3.5 Retrieval Module

```python
# services/retrieval_module.py

class RetrievalModule:
    """检索适配层: 将 MARS 约束转换为现有检索系统能理解的格式。"""
    
    def __init__(
        self,
        db: AsyncSession,
        emb: EmbeddingService,
        retriever: Retriever,          # 现有 services/retriever.py
        merger: Merger,               # 现有 rag/merger.py
    ): ...

    async def search(self, request: RetrievalRequest) -> RetrievalResponse:
        """
        实现:
        Step 1: _constraints_to_subqueries(request.collected_constraints) → List[SubQuery]
        Step 2: retriever.retrieve(sub_queries) → {keyword:[], semantic:[]}
        Step 3: merger.merge(keyword, semantic) → ranked SKUHit[]
        Step 4: _enrich_products(ranked_skuhits) → EnrichedProduct[] (JOIN product+sku)
        Step 5: _extract_text_blocks(product_ids) → RAGChunk[] (L3 提取)
        Step 6: _match_slots_if_needed(products, request.product_slot) → 设置 matched_slot
        Step 7: 组装 RetrievalResponse 返回
        """

    def _constraints_to_subqueries(self, constraints: dict) -> list[SubQuery]:
        """将 collected_constraints 字典映射为 SubQuery 列表"""

    async def _extract_text_blocks(self, product_ids: list[str]) -> list[RAGChunk]:
        """L3 提取: 从 product_review/product_faq/user_review 取文本块"""
```

### 3.6 API 层

```python
# api/chat.py

router = APIRouter(prefix="/api", tags=["chat"])

@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    orch: MarsOrchestrator = Depends(get_orchestrator),
) -> ChatResponse:
    """
    实现: 参数校验 → orch.chat(req) → 组装 ChatResponse 返回
    
    错误处理:
    - 400: message 为空
    - 500: 内部错误 (含具体 agent 阶段信息)
    - 默认: 返回 status=ERROR + error message
    """

def get_orchestrator() -> MarsOrchestrator:
    """依赖注入工厂: 组装所有 Agent + SessionManager + RetrievalModule"""
```

---

## 4. 关键数据结构

### 4.1 SessionMemory (完整 Schema)

```python
@dataclass
class SessionMemory:
    session_id: str                                    # UUID4
    conversation_history: list[ChatMessage]             # 最近20轮, [{role, content}]
    
    # ① RW 写入
    rewritten_query: str | None = None
    extracted_entities: dict | None = None             # {product_type, brand, price_info, ...}
    
    # ② INT 写入
    intent_result: IntentResult | None = None         # {intent_type, primary_category, confidence, ...}
    
    # ③ PLAN 写入 (仅 scenario/fuzzy 路径)
    product_plan: ProductPlan | None = None            # {source, slots[], guesses_confidence, ...}
    
    # ④ CLARIFY 读写 ⭐
    clarification_state: ClarificationState | None = None
    #   status: "IDLE" | "CLARIFYING" | "READY" | "COMPLETE"
    #   current_round: int = 0
    #   pending_items: list[str] = []
    #   collected_constraints: dict = {}              # {product_type, price_min, price_max, brand, ...}
    
    # 检索模块写入
    retrieval_cache: dict | None = None
    final_products: list[EnrichedProduct] | None = None
    
    # ⑤ WEAVE 写入
    final_response: str | None = None


@dataclass
class ChatMessage:
    role: str        # "user" | "assistant"
    content: str
```

### 4.2 Agent 输出模型

```python
class IntentType(str, Enum):
    CLEAR_INTENT = "clear_intent"
    SCENARIO_PLAN = "scenario_plan"
    FUZZY_INTENT = "fuzzy_intent"
    FREE_CHAT = "free_chat"

@dataclass
class IntentResult:
    intent_type: IntentType
    primary_category: str | None = None       # "美妆护肤"|"数码电子"|...
    confidence: float = 0.0
    routing_reason: str = ""
    suggested_pending_items: list[str] = field(default_factory=list)

@dataclass
class Slot:
    role: str                                   # "核心防晒"|"降噪设备"
    category_hint: str | None = None           # "美妆护肤"|"数码电子"
    sub_category_hint: list[str] = field(default_factory=list)
    required: bool = False
    reason: str = ""
    confidence: float = 0.0                     # 仅 fuzzy_intent 有意义

@dataclass
class ProductPlan:
    source: str                                 # "scenario_plan" | "fuzzy_intent"
    plan_name: str = ""
    slots: list[Slot] = field(default_factory=list)
    guesses_confidence: float = 0.0             # 仅 fuzzy
    fallback_to_chat: bool = False              # 仅 fuzzy
    matched_scenario_id: str | None = None      # 仅 scenario
    total_price_range_hint: dict | None = None # 仅 scenario {min, max}

@dataclass
class ClarificationState:
    status: str = "IDLE"                        # IDLE | CLARIFYING | READY | COMPLETE
    current_round: int = 0
    max_rounds: int = 5                           # 可配置
    pending_items: list[str] = field(default_factory=list)
    collected_constraints: dict = field(default_factory=dict)

@dataclass
class Option:
    option_id: str                               # "BUDGET" | "SKIN_TYPE" | "GUESS"
    question: str
    choices: list[str]

@dataclass
class ClarifyResult:                             # STATUS=CLARIFYING 时返回
    reply: str                                    # <AIREPLY> 内容
    options: list[Option]                         # <OPTIONS> 结构化
    status: Literal["CLARIFYING"] = "CLARIFYING"

@dataclass
class ReadyResult:                               # STATUS=READY 时返回
    status: Literal["READY"] = "READY"
    collected_constraints: dict                   # 最终约束字典

@dataclass
class WeaveResult:                                # STATUS=COMPLETE 时返回
    reply: str                                    # <AIREPLY> 推荐内容
    status: Literal["COMPLETE"] = "COMPLETE"
    recommended_ids: list[str] = field(default_factory=list)
```

### 4.3 检索契约

```python
@dataclass
class RetrievalRequest:
    intent_type: IntentType
    collected_constraints: dict                    # {product_type, price_min, price_max, ...}
    product_plan: ProductPlan | None = None
    primary_category: str | None = None

@dataclass
class RAGChunk:
    content: str
    source_type: str                              # "marketing" | "faq" | "review" | "general"
    product_id: str | None = None
    relevance_score: float = 0.0

@dataclass
class EnrichedProduct:
    product_id: str
    name: str
    brand: str | None = None
    category: str | None = None
    price: float | None = None
    stock: int | None = None
    image_url: str | None = None
    marketing_description: str | None = None      # L3
    official_faq: list[str] = field(default_factory=list)  # L3
    user_reviews: list[str] = field(default_factory=list)   # L3
    score: float = 0.0
    matched_slot: str | None = None               # 场景方案时的槽位名

@dataclass
class RetrievalResponse:
    enriched_products: list[EnrichedProduct]
    rag_chunks: list[RAGChunk]
    retrieval_meta: dict = field(default_factory=dict)
    # {total_candidates, l1_rag_count, l2_sql_count, query_used}
```

### 4.4 API 层

```python
class ChatRequest(BaseModel):
    session_id: str | None = None                 # null=新建
    message: str                                  # 用户消息 (必填, >0字符)

class OptionOut(BaseModel):
    option_id: str
    question: str
    choices: list[str]

class ChatResponse(BaseModel):
    reply: str                                     # AI 回复
    options: list[OptionOut] | None = None         #追问选项 (仅 CLARIFYING)
    status: Literal["CLARIFYING", "READY", "COMPLETE", "ERROR"]
    session_id: str
    recommended_products: list[dict] | None = None # 仅 COMPLETE
```

---

## 5. 主功能链路时序

### 5.1 clear_intent 链路 (明确意图单轮直通)

```
Client                    Orchestrator          RW              INT           CLARIFY        RetrievalModule    WEAVE           SessionMgr    Redis/Mem
  |                           |                   |               |             |                |                 |               |            |
  | POST /api/chat           |                   |               |             |                |                 |               |            |
  | {msg:"防晒200以内"}      |                   |               |             |                |                 |               |            |
  |------------------------->|                   |               |             |                |                 |               |            |
  |                           | load(null)→create  |               |             |                |                 |               |            |
  |                           |------------------>|               |             |                |                 |               |            |
  |                           |                   | rewrite("防晒..")|             |                |                 |               |            |
  |                           |<------------------|               |             |                |                 |               |            |
  |                           | route(entities)   |--------------->|             |                |                 |               |            |
  |                           |<------------------|---------------|             |                |                 |               |            |
  |                           | [clear→跳过PLAN]   |               |             |                |                 |               |            |
  |                           | clarify(memory)  |               |------------->|                |                 |               |            |
  |                           |<------------------|               |<------------|                |                 |               |            |
  |                           | [READY! 信息足够]  |               |             |                |                 |               |            |
  |                           | search(constraints)|               |             |---------------->|                 |               |            |
  |                           |<------------------|               |             |<----------------|                 |               |            |
  |                           | weave(products)   |               |             |                |---------------->|               |            |
  |                           |<------------------|               |             |                |<----------------|               |            |
  |                           | save(memory)     |               |             |                |                 |-------------->|            |
  |                           |------------------>|               |             |                |                 |               |           |
  |<--------------------------|                   |               |             |                |                 |               |            |
  | {reply, COMPLETE}       |                   |               |             |                |                 |               |            |
```

### 5.2 fuzzy_intent 链路 (模糊意图多轮收敛)

```
=== 第1轮 ===
Client          Orchestrator    RW        INT        PLAN      CLARIFY(R)    SessMgr
  |                  |             |          |          |          |            |
  | "通勤太吵"      |             |          |          |          |            |
  |---------------->|             |          |          |          |            |
  |                  | rewrite ---->|          |          |          |            |
  |                  |<-------------|          |          |          |            |
  |                  | route ------->|          |          |          |            |
  |                  |<-------------|---------->|          |          |            |
  |                  | [fuzzy→PLAN]  |          |----->|   |            |
  |                  |              |          |    |<---|   |            |
  |                  | clarify ---->|          |    |    |--->| (模式C)    |
  |                  |<-------------|          |    |    |<---|            |
  |                  | [CLARIFYING]  |          |    |    |    |            |
  |                  | save         |          |    |    |    |------->|
  |<----------------|              |          |    |    |    |       |
  | {reply+options}  |              |          |    |    |    |       |
  |  (展示猜测选项)  |              |          |    |    |    |       |

=== 第2轮 (用户选了"降噪耳机") ===
Client          Orchestrator    RW        CLARIFY(R)  SessMgr
  |                  |             |          |          |
  | (自动代入)"降噪耳机"|          |          |          |
  |---------------->|             |          |          |
  |                  | [状态=CLARIFYING]        |          |
  |                  | quick path: 只做 RW+CLARIFY |   |
  |                  | rewrite ---->|          |          |
  |                  |<-------------|          |          |
  |                  | clarify ---->| (模式A:单品追问)|
  |                  |<-------------|<---------|          |
  |                  | [CLARIFYING]  |          |          |
  |                  | save         |------->|          |
  |<----------------|              |          |          |
  | {reply+预算选项}  |          |          |          |

=== 第3轮 (用户选预算300-800) ===
Client          Orchestrator    CLARIFY(R)  Retrieval  WEAVE    SessMgr
  |                  |             |          |         |        |
  | "300-800,地铁通勤" |          |         |        |
  |---------------->|             |          |         |        |
  |                  | clarify -->|          |         |        |
  |                  |<-----------| [READY!]  |         |        |
  |                  | search ----|--------->|         |        |
  |                  |<-----------|<---------|         |        |
  |                  | weave ---->|--------->|-------->|
  |                  |<-----------|<---------|<--------|------>|
  |                  | save       |          |         |        |
  |<----------------|           |          |         |        |
  | {reply+商品推荐} |          |         |        |        |
```

### 5.3 free_chat 链路 (短路直达)

```
Client          Orchestrator    RW        INT        WEAVE      SessMgr
  |                  |             |          |          |        |
  | "你好呀"         |             |          |          |        |
  |---------------->|             |          |          |        |
  |                  | rewrite ---->|          |          |        |
  |                  |<-------------|          |          |        |
  |                  | route ------->|          |          |        |
  |                  |<-------------|---------->|          |        |
  |                  | [free_chat]  |          |          |        |
  |                  | [跳过PLAN+CLARIFY+检索]      |          |        |
  |                  | weave(free) ---------------->|        |
  |                  |<--------------------------------|        |
  |                  | save       |----------------------->|
  |<----------------|           |                        |
  | {你好呀回复}     |           |                        |
```

### 5.4 scenario_plan 链路 (场景方案槽位澄清)

```
(与 fuzzy 类似，区别在 PLAN 匹配场景库 + CLARIFY 用模式B槽位追问)
第1轮: "海边度假装备" → INT(scenario) → PLAN(匹配sc_001) → CLARIFY(模式B: 预算+人群)
第2轮: 用户选预算/人群 → CLARIFY(继续模式B或转A) → ... → READY → 检索 → 推荐
```

---

## 6. 权限、隔离和边界

### 6.1 新增 vs 复用 vs 改造 清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `schemas/mars.py` | **新增** | 所有 MARS Pydantic 模型，不影响现有 schemas/product.py |
| `services/orchestrator.py` | **新增** | 编排层，纯新增逻辑 |
| `services/session_manager.py` | **新增** | 会话管理，纯新增逻辑 |
| `services/retrieval_module.py` | **新增** | 适配层，内部调用现有 retriever/merger 但不修改它们 |
| `agents/*.py` (5 files) | **新增** | 5 个 Agent，纯新增目录 |
| `prompts/*.py` (5 files) | **新增** | Prompt 模板常量 |
| `api/chat.py` | **新增** | 新端点，现有 search/products/admin 不动 |
| `data/scenarios.json` | **新增** | 场景库数据 |
| `app/main.py` | **改造** | 加 2 行: `include_router(chat.router)` |
| `app/config.py` | **改造** | 加 1 个 MarsSettings class + settings.mars 属性 |
| `config.yaml` | **改造** | 加 `mars:` 段 (~10行) |
| `services/__init__.py` | **微调** | 可选: 导出新模块方便引用 |

**总结: 12 个新增文件, 3 个微改造, 0 个删除, 0 个修改现有业务逻辑**

### 6.2 Agent 间调用约定

| 约定 | 规则 |
|------|------|
| **调用方式** | 全部同步 await（串行调用），无并行需求 (v0.1) |
| **错误传播** | Agent 抛出 AgentError(含 stage_name/message/should_retry)，Orchestrator 捕获后决定降级还是重试 |
| **LLM 调用并发限制** | 同一时刻最多 1 个 LLM 调用在飞 (通过 asyncio 串行自然保证) |
| **超时策略** | RW:3s, INT:3s, PLAN:5s, CLARIFY:5s, WEAVE:15(stream), 总请求:30s |
| **Memory 写入时机** | 每个 Agent 返回后立即由 Orchestrator 调用 session_mgr.save() |
| **Memory 读取时机** | Orchestrator.chat() 开始时加载一次，后续 Agent 共享同一对象引用 |

### 6.3 Redis 连接管理

```python
# 方案: 使用 aioredis (async redis), 连接池化
# ⚠️ Q1 决策: v0.1 先用 InMemorySessionManager (同接口)
#     Redis 后续切换只需改 SessionManager.__init__ 的 backend 参数

class RedisConfig:
    url: str = "redis://localhost:6379/0"
    pool_size: int = 10
    key_prefix: str = "mars:session:"
    ttl_seconds: int = 1800          # 30 min
```

### 6.4 LLM 调用的降级策略矩阵

| Agent | LLM 超时/失败 | 降级行为 | 对下游影响 |
|------|---------------|---------|-----------|
| **RW** | 3s 超时 | 返回 original_query 作为 rewritten_query, entities={} | INT 收到空实体 → 可能路由到 fuzzy (安全) |
| **INT** | 3s 超时 | 返回 fuzzy_intent (最安全兜底) | 进入 PLAN → PLAN 收到模糊输入 → 给宽泛猜测 |
| **PLAN** | 5s 超时 | 返回空 Plan (slots=[], low confidence) | CLARIFY 收到空 plan → 退化为模式 A (单品追问) |
| **CLARIFY** | 5s 超时 | 强制 READY (用已有约束) | 可能约束不足但不会死循环 |
| **WEAVE** | 15s 超时 | 返回商品列表文本 (无温度) | 用户仍能看到商品, 只是缺少推荐语 |

### 6.5 ⚠️ 待确认边界条件

| # | 边界 | 当前决策 | 备注 |
|---|------|---------|------|
| B-1 | 同一用户多设备并发 | v0.1 不处理 (最后写入胜) | 后续加 distributed lock |
| B-2 | Session 数量上限 | 无硬限 (Redis 内存控制) | 生产需加 LRU 淘汰 |
| B-3 | 单次请求最大 Memory 大小 | < 50KB (20轮 × ~2KB/轮) | 超大截断历史 |
| B-4 | 场景库热更新 | 不支持 (启动时加载) | 重启生效 |
| B-5 | Prompt 版本管理 | 硬编码在 .py 常量中 | 后续可迁至 DB/配置中心 |
| B-6 | WEAVE 流式输出 | v0.1 用 non-stream (简单可靠) | v1.0 可改为 stream+SSE |
