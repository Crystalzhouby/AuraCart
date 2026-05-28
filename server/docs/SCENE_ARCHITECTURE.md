# 六大场景分类 → 可执行系统架构

> **前置依赖：** [CON_PLAN.md](./CON_PLAN.md)（模块拆分、数据表、检索链路）、[CODE_PLAN.md](./CODE_PLAN.md)（实现细节）
> **定位：** 在现有混合检索架构之上，增加意图路由、多库动态调度、矛盾对冲、健壮性保障四个横切能力。

---

## 0. 架构总览：新组件与现有系统的关系

```
                        ┌──────────────────────────────────────────┐
                        │           INTENT ROUTER (NEW)             │
                        │   ScenarioClassifier → FlowDispatcher     │
                        │   "什么值得买" → 直接路由场景四             │
                        └──────────────┬───────────────────────────┘
                                       │ intent_label + flow_type
                                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    QUERY PARSER (已有, CON_PLAN §5.1)              │
│        LLM 拆解 → List[SubQuery]                                  │
│        增强：接收 intent_label，调整拆解策略权重                    │
└──────────────────────────────┬───────────────────────────────────┘
                               │ sub_queries + intent_label
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│              RETRIEVAL DISPATCHER (NEW)                           │
│        根据 intent → 选择性查询 FactStore / ContextStore /         │
│        FAQStore / FeedbackStore                                   │
│        ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│        │FactStore │ │ContextSt.│ │ FAQStore │ │FeedbackSt│       │
│        │(SQL精确) │ │(向量语义)│ │ (向量)   │ │(向量+情感)│       │
│        └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │
└─────────────┼────────────┼────────────┼────────────┼─────────────┘
              └────────────┴────────────┴────────────┘
                               │ merged_hits (per-source annotated)
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    MERGER (已有, CON_PLAN §4.6)                    │
│        source_weight + 聚合 + negation + 降级                      │
└──────────────────────────────┬───────────────────────────────────┘
                               │ ranked_products (with sources)
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│              CONFLICT DETECTOR (NEW)                              │
│        FAQ vs UserReview 矛盾检测                                  │
│        有矛盾 → 标记 conflict_flag + 注入对冲模板                   │
│        无矛盾 → 透传                                               │
└──────────────────────────────┬───────────────────────────────────┘
                               │ ranked_products + conflict_context
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    GENERATOR (已有, CON_PLAN §5.1)                 │
│        LLM 流式生成 → SSE                                          │
│        增强：conflict_flag=true 时使用矛盾对冲模板                   │
└──────────────────────────────────────────────────────────────────┘
```

**关键变更点：**
| 组件 | 状态 | 改动范围 |
|:---|:---|:---|
| IntentRouter | **新增** | 新文件 `services/intent_router.py` |
| RetrievalDispatcher | **新增** | 新文件 `services/retrieval_dispatcher.py` |
| ConflictDetector | **新增** | 新文件 `services/conflict_detector.py` |
| query_parser | **增强** | 接收 `intent_label` 参数，调整拆解 prompt |
| search.py (编排层) | **增强** | 注入 Dispatcher，传递 intent 上下文 |
| generator | **增强** | 支持 conflict_template 分支 |
| prompt.py | **增强** | 新增 intent_router / conflict 两套 prompt |

---

## 1. IntentRouter —— 意图路由层

### 1.1 设计目标

在查询拆解之前完成意图分类，输出两个关键信号：
- **`intent_label`**：六大场景标签（1-6）
- **`flow_type`**：`"exploration"`（需求探索流）或 `"decision_support"`（决策辅助流）

### 1.2 流定义

```
需求探索流 (exploration)
  ├── 场景一：商品发现与筛选    用户不知道买什么
  └── 场景四：选购建议与匹配    用户描述自身情况求推荐

决策辅助流 (decision_support)
  ├── 场景二：商品深度咨询      用户锁定商品，问细节
  ├── 场景三：对比与规格选择    用户在选项间犹豫
  ├── 场景五：使用指导与售后    用户问怎么用/怎么保养
  └── 场景六：口碑评价与反馈    用户想了解他人体验
```

### 1.3 分类策略：规则快路径 + LLM 慢路径

```
User Query
    │
    ▼
┌─────────────────────┐
│  Phase 1: 规则快路径  │  ← ~0ms，不消耗 token
│  关键词 + 模式匹配    │
│                      │
│  命中 → 直接返回      │
│  未命中 → Phase 2     │
└─────────┬───────────┘
          │ (miss)
          ▼
┌─────────────────────┐
│  Phase 2: LLM 分类   │  ← ~200ms，小模型即可
│  轻量 prompt +       │
│  结构化 JSON 输出     │
└─────────────────────┘
```

### 1.4 规则快路径关键词表

```python
# 格式: (关键词模式, 匹配逻辑, intent_label, flow_type, priority)

FAST_RULES: list[tuple[Pattern, str, int, str, int]] = [
    # === 需求探索流 ===
    # 场景一：商品发现与筛选
    (r"有没有.*(推荐|好用的|合适的)",            "regex", 1, "exploration", 10),
    (r"(帮我找|搜一下|看看有什么).*",             "regex", 1, "exploration", 10),
    (r"(.*有哪些|.*什么牌子|.*什么品类)",         "regex", 1, "exploration", 5),
    
    # 场景四：选购建议与匹配（模糊提问优先命中此处）
    (r"什么值得买",                              "exact",  4, "exploration", 100),  # 最高优先级
    (r"(推荐|求推荐|安利|种草).*",                "regex",  4, "exploration", 20),
    (r"(油皮|干皮|敏感肌|混油|混干).*(用什么|推荐|适合)", "regex", 4, "exploration", 30),
    (r"(学生党|上班族|健身|孕妇|宝妈).*(推荐|买什么)",  "regex", 4, "exploration", 30),
    (r"(预算|价位).*(以内|左右|以下).*(推荐|买)",   "regex",  4, "exploration", 25),
    (r"(送|给).*(礼物|生日|节日|长辈|女朋友|男朋友)", "regex", 4, "exploration", 30),
    
    # === 决策辅助流 ===
    # 场景三：对比与规格选择
    (r".*(vs|对比|比较|和|还是|哪个好|哪个更|区别|差别).*", "regex", 3, "decision_support", 40),
    (r"(值得买吗|值不值|划算|性价比).*",          "regex",  3, "decision_support", 20),
    (r"(256|512|128).*还是.*(256|512|128)",     "regex",  3, "decision_support", 35),
    
    # 场景二：商品深度咨询（含具体商品名/品牌）
    (r"(成分|配方|含量|材质|面料|工艺|芯片|处理器)",  "regex",  2, "decision_support", 25),
    (r"(能用|适合|可以).*\?.*(敏感肌|孕妇|小孩|老人)", "regex", 2, "decision_support", 25),
    (r"(防水|防汗|续航|待机|快充).*",             "regex",  2, "decision_support", 20),
    
    # 场景五：使用指导
    (r"(怎么用|如何使用|用法|使用步骤|使用顺序|使用技巧)", "regex", 5, "decision_support", 30),
    (r"(怎么清洗|怎么保养|怎么维护|注意事项|禁忌)",  "regex",  5, "decision_support", 30),
    (r"(怎么.*泡|怎么.*涂|怎么.*敷|怎么.*喷).*",  "regex",  5, "decision_support", 25),
    (r"太油怎么办|太干怎么办|搓泥怎么办|卡粉怎么办",  "regex",  5, "decision_support", 40),
    
    # 场景六：口碑评价
    (r"(口碑|评价|测评|实测|体验|反馈|风评|翻车|踩雷|避雷)", "regex", 6, "decision_support", 30),
    (r"(好用吗|怎么样|行不行|靠谱吗|值得吗)",      "regex",  6, "decision_support", 20),
    (r"(大家觉得|用过的|买了的).*",               "regex",  6, "decision_support", 15),
]
```

### 1.5 规则冲突消解

当多条规则同时命中时，按以下顺序仲裁：
1. **Priority 值高者优先**（"什么值得买"=100，"vs/对比"=40）
2. **同 priority 取 specificity 高者**（匹配字符串更长/更具体的规则）
3. **仍冲突 → 降级到 LLM 分类**

### 1.6 LLM 分类 Prompt（Phase 2 慢路径）

```python
INTENT_ROUTER_SYSTEM = """
你是电商导购意图分类器。将用户输入映射到以下场景之一，仅返回 JSON。

## 六大场景定义

1. 商品发现与筛选 —— 用户描述需要的商品类型、功能、价格范围，没有指定具体品牌或型号
2. 商品深度咨询 —— 用户提到了具体商品/品牌，询问成分、技术、安全性、渠道等细节
3. 对比与规格选择 —— 用户在 2+ 个选项间比较，或询问不同规格（容量/颜色/配置）的区别
4. 选购建议与匹配 —— 用户描述自身情况（肤质/预算/身份/场景），请求个性化推荐
5. 使用指导与售后 —— 用户询问使用方法、步骤、保养、注意事项
6. 口碑评价与反馈 —— 用户询问其他用户的使用体验、好评、差评

## 判定边界

- "推荐一款面霜" → 场景1（泛品类搜索）
- "推荐一款适合油皮的面霜" → 场景4（描述了自身肤质）
- "雅诗兰黛小棕瓶怎么样" → 场景6（问口碑）或场景2（问细节），优先场景6
- "雅诗兰黛小棕瓶含酒精吗" → 场景2（具体成分咨询）
- "小棕瓶 vs 小黑瓶" → 场景3（明确对比）
- "小棕瓶怎么用" → 场景5（使用指导）
- "什么值得买" → 场景4（模糊推荐意图）

## 输出格式（严格 JSON）
{"intent_label": <1-6>, "flow_type": "<exploration|decision_support>", "confidence": <0.0-1.0>}
"""
```

### 1.7 集成方式

```python
# services/intent_router.py

@dataclass
class IntentResult:
    intent_label: int          # 1-6
    flow_type: str             # "exploration" | "decision_support"
    confidence: float          # 0.0-1.0
    matched_rule: str | None   # 命中的快路径规则，None=LLM分类

class IntentRouter:
    def __init__(self, llm_service: LLMService):
        self.llm = llm_service
        self._compile_rules(FAST_RULES)
    
    async def classify(self, query: str) -> IntentResult:
        # Phase 1: 快路径
        result = self._match_fast_rules(query)
        if result and result.confidence >= 0.85:
            return result
        # Phase 2: LLM 慢路径
        return await self._llm_classify(query)
    
    # 特殊规则："什么值得买"类模糊提问
    # 如果快路径未命中且 LLM confidence < 0.6，默认路由到场景4
    async def classify_with_fallback(self, query: str) -> IntentResult:
        result = await self.classify(query)
        if result.confidence < 0.6:
            result.intent_label = 4
            result.flow_type = "exploration"
            result.matched_rule = "low_confidence_fallback"
        return result
```

### 1.8 对下游的影响

IntentRouter 的输出传递给：
1. **query_parser**：根据 `flow_type` 微调研解 prompt
   - `exploration` → 增加语义检索权重，优先查 ContextStore
   - `decision_support` → 优先结构化过滤，精准匹配已知商品
2. **RetrievalDispatcher**：根据 `intent_label` 选择 source filter（见 §2）

---

## 2. Multi-Store RAG —— 数据分层检索架构

### 2.1 设计目标

将现有 `product_review` 表的单一向量检索，拆分为按 `source` 分区的逻辑检索库，由 Dispatcher 按意图选择性查询，避免跨来源噪音。

### 2.2 四库定义（映射到现有 product_review.source）

```
┌──────────────────────────────────────────────────────────────┐
│                   product_review (pgvector)                    │
│                                                               │
│  ┌─────────────────┐  ┌─────────────────┐                     │
│  │   ContextStore   │  │    FAQStore     │                     │
│  │ source=marketing │  │   source=faq    │                     │
│  │                  │  │                 │                     │
│  │ ~100 条向量      │  │ ~400 条向量     │                     │
│  │ 语义检索为主     │  │ 语义检索为主    │                     │
│  │ search_weight:0.9│  │ search_weight:  │                     │
│  │                  │  │   1.0           │                     │
│  └─────────────────┘  └─────────────────┘                     │
│                                                               │
│  ┌─────────────────┐  ┌─────────────────┐                     │
│  │   FactStore      │  │  FeedbackStore  │                     │
│  │ (非向量)         │  │source=user_rev. │                     │
│  │ product + sku表  │  │                 │                     │
│  │                  │  │ ~400 条向量     │                     │
│  │ SQL 精确查询     │  │ 语义+情感检索   │                     │
│  │ 品牌/价格/规格   │  │ search_weight:  │                     │
│  │                  │  │   0.6           │                     │
│  └─────────────────┘  └─────────────────┘                     │
└──────────────────────────────────────────────────────────────┘
```

### 2.3 各库索引策略

| Store | 物理表 | 检索方式 | 索引 | 适用查询 |
|:---|:---|:---|:---|:---|
| **FactStore** | `product` + `sku` | SQL `WHERE` / `ILIKE` / `IN` | B-tree (product_id, brand, category, price) | "500以内" "256GB" "Nike" |
| **ContextStore** | `product_review` WHERE source='marketing' | pgvector cosine + tsquery | HNSW + GIN | "适合油皮的清爽面霜" "通勤背包" |
| **FAQStore** | `product_review` WHERE source='faq' | pgvector cosine + tsquery | HNSW + GIN | "PITERA是什么" "敏感肌能用吗" |
| **FeedbackStore** | `product_review` WHERE source='user_review' | pgvector cosine + tsquery | HNSW + GIN + rating 字段过滤 | "这款发热严重吗" "实际续航" |

### 2.4 动态检索分配矩阵

Dispatcher 根据 `intent_label` 决定查询哪些库、各库权重分配：

```
Intent  →  Store Activation & Weight
──────────────────────────────────────
场景1 商品发现
  FactStore:     ✓ (filter: category/price range)     weight: 0.3
  ContextStore:  ✓ (main semantic search)              weight: 0.7
  FAQStore:      ✗
  FeedbackStore: ✗

场景2 深度咨询
  FactStore:     ✓ (target product lookup)             weight: 0.2
  ContextStore:  ✓ (support context)                   weight: 0.2
  FAQStore:      ✓ (main — answer specific Qs)         weight: 0.6
  FeedbackStore: ✗

场景3 对比选择
  FactStore:     ✓ (main — spec comparison)            weight: 0.5
  ContextStore:  ✓ (product positioning)               weight: 0.2
  FAQStore:      ✗
  FeedbackStore: ✓ (real-world experience)             weight: 0.3

场景4 选购建议
  FactStore:     ✗
  ContextStore:  ✓ (main — matching user profile)      weight: 0.7
  FAQStore:      ✗
  FeedbackStore: ✓ (social proof)                      weight: 0.3

场景5 使用指导
  FactStore:     ✓ (specific product lookup)            weight: 0.1
  ContextStore:  ✓ (usage tips in description)          weight: 0.3
  FAQStore:      ✓ (main — how-to answers)              weight: 0.6
  FeedbackStore: ✗

场景6 口碑反馈
  FactStore:     ✗
  ContextStore:  ✗
  FAQStore:      ✗
  FeedbackStore: ✓ (main — reviews only)                weight: 1.0
```

**空库兜底：** 任何场景下，如果主库检索返回 < 3 条结果，按以下顺序启用备用库：
- 场景6 无结果 → 启用 ContextStore（FAQ 和 review 都没有时用营销描述兜底）
- 场景4 无结果 → 启用 FactStore（放宽到全品类浏览）
- 场景5 无结果 → 启用 ContextStore（用营销描述中的使用 tips 补充）

### 2.5 Dispatcher 实现

```python
# services/retrieval_dispatcher.py

@dataclass
class StoreConfig:
    """单个检索库的激活配置"""
    name: str                      # "fact" | "context" | "faq" | "feedback"
    source_filter: str | None      # product_review.source 过滤值，FactStore 为 None
    active: bool                   # 是否参与本次检索
    weight: float                  # 在 merger 中的权重系数
    strategy: str                  # "sql" | "semantic" | "keyword" | "hybrid"

# 分配矩阵
DISPATCH_MATRIX: dict[int, list[StoreConfig]] = {
    1: [  # 场景一：商品发现与筛选
        StoreConfig("fact",     None,           True, 0.3, "sql"),
        StoreConfig("context",  "marketing",    True, 0.7, "semantic"),
        StoreConfig("faq",      "faq",          False, 0.0, "semantic"),
        StoreConfig("feedback", "user_review",  False, 0.0, "semantic"),
    ],
    # ... (其余场景按 §2.4 矩阵配置)
}

class RetrievalDispatcher:
    """根据意图标签，生成本次检索的库激活方案"""
    
    def __init__(self, dispatch_matrix: dict = DISPATCH_MATRIX):
        self.matrix = dispatch_matrix
    
    def get_store_plan(self, intent_label: int) -> list[StoreConfig]:
        """返回本次检索需要激活的库列表（按权重降序）"""
        active = [s for s in self.matrix[intent_label] if s.active]
        return sorted(active, key=lambda s: s.weight, reverse=True)
    
    def get_fallback_plan(self, intent_label: int, failed_stores: list[str]) -> list[StoreConfig]:
        """主库无结果时，返回备用库激活方案"""
        # 场景6 无结果 → 启用 ContextStore 兜底
        if intent_label == 6 and "feedback" in failed_stores:
            return [StoreConfig("context", "marketing", True, 1.0, "semantic")]
        # 场景4 无结果 → 启用 FactStore 兜底
        if intent_label == 4 and "context" in failed_stores:
            return [StoreConfig("fact", None, True, 1.0, "sql")]
        # 场景5 无结果 → 启用 ContextStore 兜底
        if intent_label == 5 and "faq" in failed_stores:
            return [StoreConfig("context", "marketing", True, 1.0, "semantic")]
        return []
```

### 2.6 检索执行

Dispatcher 输出 `StoreConfig[]` → `search.py` 编排层遍历执行：

```python
# services/search.py (增强后的编排逻辑)

async def execute_search(
    query: str,
    intent: IntentResult,
    dispatcher: RetrievalDispatcher,
    retriever: Retriever,
    merger: Merger,
) -> list[RankedProduct]:
    
    store_plan = dispatcher.get_store_plan(intent.intent_label)
    all_hits = []
    
    for store in store_plan:
        try:
            hits = await retriever.search(
                query=query,
                source_filter=store.source_filter,
                strategy=store.strategy,
                top_k=20,
            )
            # 标注来源库和权重
            for h in hits:
                h.store_name = store.name
                h.store_weight = store.weight
            all_hits.extend(hits)
        except Exception:
            continue  # 单库失败不阻断整体
    
    # 主库结果不足 → 触发兜底
    if len(all_hits) < 3:
        failed = [s.name for s in store_plan if not any(h.store_name == s.name for h in all_hits)]
        fallback_plan = dispatcher.get_fallback_plan(intent.intent_label, failed)
        for store in fallback_plan:
            hits = await retriever.search(
                query=query,
                source_filter=store.source_filter,
                strategy=store.strategy,
            )
            for h in hits:
                h.store_name = store.name
                h.store_weight = store.weight
            all_hits.extend(hits)
    
    return merger.merge(all_hits, intent=intent)
```

### 2.7 与现有 source_weight 的关系

现有 `config.yaml` 中的 `search.source_weights`（faq=1.0, marketing=0.9, user_review=0.6）是 **merger 层面的静态得分系数**，表示"FAQ 天然比评价可信"。

Dispatcher 的 store weight 是 **检索层面的动态激活系数**，表示"在当前意图下，这个来源有多重要"。

两者叠加关系：`final_score = cosine_similarity × source_weight × store_weight`

- `source_weight`：来自 `config.yaml`，静态，反映信息源可信度
- `store_weight`：来自 Dispatcher，动态，反映当前意图对该源的需求强度

---

## 3. Conflict Resolution —— "矛盾对冲"输出模板

### 3.1 设计目标

当检索结果中同一商品的 FAQ（官方宣称）与 user_review（用户评价）存在显著矛盾时，强制 Agent 同时呈现双方观点，禁止只输出官方说辞。

### 3.2 矛盾检测机制

```
merger 输出 ranked_products
        │
        ▼
┌──────────────────────────────────┐
│  Step 1: 来源标记检查             │
│  同一 product_id 是否同时存在     │
│  source=faq 和 source=user_review │
│  的检索命中？                     │
│  否 → 跳过，无矛盾风险             │
│  是 → Step 2                      │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  Step 2: 语义矛盾检测 (LLM轻量)   │
│  将 FAQ answer + review content  │
│  输入小 prompt，判断是否存在       │
│  正面/负面在同一维度上的冲突       │
│                                   │
│  返回: {conflict: bool,           │
│         dimension: str,           │
│         official_claim: str,      │
│         user_counterclaim: str}   │
└──────────────┬───────────────────┘
               │
        ┌──────┴──────┐
        │ conflict?    │
        │ 是 → 注入模板 │
        │ 否 → 正常生成 │
        └─────────────┘
```

### 3.3 矛盾检测 Prompt

```python
CONFLICT_DETECT_PROMPT = """
分析以下同一商品的官方FAQ回答与用户评价，判断是否存在显著矛盾。

## 官方FAQ
问题：{faq_question}
回答：{faq_answer}

## 用户评价
{user_reviews}

## 判定标准
- "显著矛盾"：官方宣称的某个积极功能/特性，在≥2条用户评价中被明确质疑或反驳
- 非矛盾：官方未提及的维度、个别用户的主观偏好差异、评分正常波动
- 典型矛盾示例：官方说"续航强，可连续使用12小时" vs 用户评价"用了3小时就没电了""发热严重，掉电快"

## 输出格式（严格JSON）
{
  "has_conflict": true/false,
  "conflict_dimension": "矛盾维度（如：续航、肤感、舒适度）",
  "official_claim": "官方具体宣称了什么",
  "user_counterclaim": "用户实际反馈了什么（摘录关键句）",
  "severity": "high|medium|low"
}
"""
```

### 3.4 结构化对比输出模板

当 `has_conflict=true` 时，generator 使用此模板替代默认 prompt：

```python
CONFLICT_AWARE_GENERATOR_PROMPT = """
你是电商导购专家。你需要回答用户关于以下商品的问题。

⚠️ 系统检测到该商品在「{conflict_dimension}」维度上，官方描述与部分用户实际体验存在差异。

你必须使用以下"双视角结构"输出，不得隐瞒任一方信息，不得偏袒：

---
## 商品推荐分析

（正常推荐内容，200字内）

## ⚠️ 多维视角参考

### 官方说明
{官方FAQ对该维度的描述}

### 用户实际反馈
- ✅ 正向反馈（评分≥4星的相关评价摘录）
- ⚠️ 争议反馈（评分≤3星的相关评价摘录）

### 差异分析
（1-2句话客观总结官方与用户反馈的差异，说明可能的适用条件：
"官方续航数据是在实验室标准条件下测得，日常重度使用（游戏+5G+高亮度）下续航会显著缩短。
如果您主要是轻度办公场景，官方数据可参考；如果重度使用，建议参考用户实际反馈。")
---

## 约束
1. 如用户反馈明显具备统计意义（≥3条同向反馈），明确指出
2. 如用户反馈仅为个别情况（1-2条），客观说明样本有限
3. 不得使用"官方夸大宣传""虚假广告"等主观定性词汇
4. 不得使用"不过""但是""虽然"等暗示官方信息不可信的转折词
5. 使用"官方数据是在X条件下测得，实际使用场景下可能Y"的客观表述
"""
```

### 3.5 矛盾检测触发范围

仅以下场景启用矛盾检测（因为只有这些场景会同时检索 FAQ 和 Feedback）：

| 场景 | FAQStore | FeedbackStore | 是否检测矛盾 |
|:---|:---|:---|:---|
| 场景一（商品发现） | ✗ | ✗ | 不触发 |
| 场景二（深度咨询） | ✓ | ✗ | 不触发 |
| 场景三（对比选择） | ✗ | ✓ | 不触发 |
| 场景四（选购建议） | ✗ | ✓ | 不触发 |
| 场景五（使用指导） | ✓ | ✗ | 不触发 |
| 场景六（口碑反馈） | 兜底启用 | ✓ | **触发** |

> 场景六触发的原因：FeedbackStore 主库无结果时，兜底启用 ContextStore（含 FAQ），此时可能出现 FAQ 与 review 矛盾。

**实际触发场景：场景六为主，场景二的兜底路径为辅。**

### 3.6 实现

```python
# services/conflict_detector.py

@dataclass
class ConflictReport:
    has_conflict: bool
    conflict_dimension: str | None
    official_claim: str | None
    user_counterclaim: str | None
    severity: str | None   # "high" | "medium" | "low"
    faq_excerpts: list[str]
    review_excerpts: list[str]

class ConflictDetector:
    def __init__(self, llm_service: LLMService):
        self.llm = llm_service
    
    async def detect(
        self,
        product_id: str,
        faq_hits: list[Hit],
        review_hits: list[Hit],
    ) -> ConflictReport:
        """检测同一商品的 FAQ 与 user_review 是否在关键维度上矛盾"""
        
        # 无 FAQ 或无 review → 无法矛盾
        if not faq_hits or not review_hits:
            return ConflictReport(has_conflict=False)
        
        # 构造检测 prompt
        faq_text = "\n".join(
            f"Q: {h.metadata.get('question', '')}\nA: {h.content}"
            for h in faq_hits
        )
        review_text = "\n".join(
            f"[{h.metadata.get('nickname', '匿名')} 评分{h.metadata.get('rating', '?')}星]: {h.content}"
            for h in review_hits
        )
        
        prompt = CONFLICT_DETECT_PROMPT.format(
            faq_question=", ".join(h.metadata.get("question", "") for h in faq_hits),
            faq_answer=faq_text,
            user_reviews=review_text,
        )
        
        result = await self.llm.chat_json(prompt)
        return ConflictReport(**result)
```

---

## 4. Robustness Testing —— 健壮性测试

### 4.1 漏斗测试：面霜太油怎么办

**测试用例：** 用户输入 `"面霜太油怎么办"`

**测试目标：** 验证系统能否正确区分"使用指导"与"口碑反馈"的边界，该走场景五而非场景六。

#### 路由决策推演

```
用户输入: "面霜太油怎么办"

Phase 1: 规则快路径
  ├── 匹配规则: r"太油怎么办|太干怎么办|搓泥怎么办|卡粉怎么办" → intent=5, flow=decision_support
  ├── 同时命中: r"(好用吗|怎么样|行不行|靠谱吗|值得吗)" ? 
  │   检查: "怎么办" ≠ "怎么样"，不命中场景六规则
  └── 唯一命中: 场景五(使用指导), priority=40, confidence=0.9 ✓

Phase 2: Dispatcher 分配
  ├── intent_label=5 → 激活 FAQStore(0.6) + ContextStore(0.3) + FactStore(0.1)
  └── FeedbackStore 不激活 ← 关键：不会检索用户评价

检索结果:
  ├── FAQStore: "面霜太油可能是因为用量过多，建议减少到黄豆大小...""油皮建议选择无油配方..."
  ├── ContextStore: marketing 中的使用 tips（清爽型面霜推荐、使用方法）
  └── FactStore: product 表中的清爽型面霜列表

Generator 输出: 使用指导 + 可选的产品推荐（清爽型替代品）
```

#### 判定关键

| 维度 | 场景五（使用指导） | 场景六（口碑反馈） | 裁决 |
|:---|:---|:---|:---|
| 关键词 | "怎么办"（求解法） | "怎么样"（求评价） | "怎么办" → 场景五 |
| 用户意图 | 我在用面霜但太油了，怎么办？ | 这款面霜口碑怎么样？ | 前者更合理（未指定产品） |
| 未指定品牌 | 说明用户可能没用具体产品 | 如果指定了产品，更可能是场景六 | 无产品名 → 偏向场景五 |
| 规则 confidence | priority=40, 精确匹配 | 无匹配 | 场景五 confidence 更高 |

#### 处理结论

系统正确路由到 **场景五（使用指导）**，激活 FAQStore 获取使用方法建议，同时通过 FactStore 提供替代产品信息。用户得到双重价值：使用方法优化 + 替代产品推荐。

---

### 4.2 空集测试：查询不存在的商品

**测试用例：** 用户输入 `"特斯拉CyberPhone怎么样"`

**测试目标：** 验证系统在检索结果为空时的回退链路。

#### 路由与检索推演

```
用户输入: "特斯拉CyberPhone怎么样"

Phase 1: 规则快路径
  ├── "怎么样" → 未命中场景六规则（规则要求"好用吗|怎么样"，
  │   但"特斯拉CyberPhone"作为前缀改变了上下文）
  └── 未命中 → 进入 Phase 2 LLM 分类

Phase 2: LLM 分类
  ├── 识别: "特斯拉CyberPhone"是具体品牌+产品名 + "怎么样"求评价
  └── 输出: intent=6(口碑反馈), flow=decision_support

Phase 3: Dispatcher 分配
  ├── intent_label=6 → 只激活 FeedbackStore
  └── FeedbackStore 检索: "特斯拉 CyberPhone" → cosine similarity < threshold
  
Phase 4: 空结果处理
  ├── 主库 hits=0 < 3 → 触发兜底
  ├── dispatcher.get_fallback_plan(intent=6, failed=["feedback"])
  │   → 返回 [StoreConfig("context", "marketing", True, 1.0, "semantic")]
  └── ContextStore 检索: "特斯拉 CyberPhone" → 仍然 < threshold

Phase 5: 全局兜底（在 search.py 编排层）
  ├── 所有库 hits=0 → 提取查询中的类别/品牌关键词
  ├── 关键词提取: brand="特斯拉" (无匹配, 不在知识库)
  │                category_hint=null
  └── 触发跨场景回退: 场景六 → 场景一（商品发现）

Phase 6: 回退执行
  ├── 以"手机 数码"为初始查询，按场景一重新检索
  ├── FactStore: WHERE category='数码电子' AND sub_category='智能手机'
  ├── ContextStore: semantic search "手机"
  └── 返回: 知识库中的手机类商品（iPhone, 华为, 小米等）
  
Phase 7: Generator 输出 (SSE)
  event: products
  data: [{iPhone 17 Pro}, {华为 Pura 90 Pro}, {小米 MIX Fold 5}, ...]
  
  event: reasoning
  data: "抱歉，我目前没有找到关于「特斯拉CyberPhone」的信息。
        特斯拉目前暂未发布手机产品。以下是为您找到的热门手机推荐："
```

#### 关键处理节点

```
                    ┌──────────┐
                    │ 主库检索  │
                    └────┬─────┘
                         │ hits=0
                         ▼
                    ┌──────────┐
                    │ 库级兜底  │  ← Dispatcher.fallback_plan
                    └────┬─────┘
                         │ 所有库 hits=0
                         ▼
                    ┌──────────┐
                    │ 关键词提取 │  ← 提取 brand/category/属性
                    └────┬─────┘
                         │
                    ┌────┴─────┐
                    │ brand存在 │  brand不存在
                    │ 于知识库？ │
                    └────┬─────┘
                    否    │    是
                    │    │    │
                    ▼    │    ▼
              ┌─────────┐│ ┌──────────────┐
              │ 回退到   ││ │ 同品牌其他    │
              │ 场景一   ││ │ 品类推荐      │
              │ 同类目   ││ └──────────────┘
              │ 浏览     ││
              └─────────┘│
                         ▼
                    ┌──────────┐
                    │ Generator│
                    │ 友好降级  │
                    │ 输出      │
                    └──────────┘
```

### 4.3 空集处理实现

```python
# services/search.py 中的全局兜底逻辑

async def search_with_fallback(
    query: str,
    intent: IntentResult,
    dispatcher: RetrievalDispatcher,
    retriever: Retriever,
    merger: Merger,
    llm: LLMService,
) -> SearchResult:
    
    hits = await execute_search(query, intent, dispatcher, retriever, merger)
    
    if hits.total > 0:
        return SearchResult(hits=hits, fallback_used=False)
    
    # === 全局兜底 ===
    # Step 1: 提取查询中的可检索实体
    entities = await _extract_searchable_entities(query, llm)
    # entities = {"brand": "特斯拉", "category": null, "attributes": []}
    
    # Step 2: 尝试品牌匹配（如果 brand 存在于知识库）
    if entities.get("brand"):
        brand_products = await retriever.fact_search(
            filters={"brand__ilike": f"%{entities['brand']}%"}
        )
        if brand_products:
            return SearchResult(
                hits=brand_products,
                fallback_used=True,
                fallback_reason=f"未找到'{query}'，展示{entities['brand']}品牌其他商品"
            )
    
    # Step 3: 回退到场景一 —— 同类目浏览
    category = entities.get("category") or _infer_category_from_query(query, intent)
    fallback_intent = IntentResult(intent_label=1, flow_type="exploration", confidence=1.0)
    fallback_hits = await execute_search(
        query=category or "热门推荐",
        intent=fallback_intent,
        dispatcher=dispatcher,
        retriever=retriever,
        merger=merger,
    )
    
    return SearchResult(
        hits=fallback_hits,
        fallback_used=True,
        fallback_reason=f"未找到'{query}'的匹配结果，为您展示{category or '热门'}商品"
    )
```

### 4.4 测试用例矩阵

| # | 测试输入 | 预期路由 | 预期兜底路径 | 验证点 |
|:---|:---|:---|:---|:---|
| T1 | "面霜太油怎么办" | 场景五 | 不触发兜底 | 规则快路径优先命中，不走场景六 |
| T2 | "特斯拉CyberPhone怎么样" | 场景六→空集→场景一 | 品牌不存在→类目浏览 | 全局兜底触发，友好降级输出 |
| T3 | "什么值得买" | 场景四 | 不触发兜底 | 最高 priority=100 的快路径 |
| T4 | "iPhone 17 Pro发热严重是真的吗" | 场景六 | 矛盾检测触发 | FeedbackStore → FAQStore 兜底 → 矛盾检测 |
| T5 | "推荐一款不存在的XX品类" | 场景四→空集 | ContextStore 为空→FactStore兜底 | 场景四内兜底 → 全局兜底 |
| T6 | "小棕瓶和小黑瓶对比" | 场景三 | 不触发兜底 | vs 关键词 → 优先场景三 |
| T7 | "SK-II神仙水含酒精吗" | 场景二 | 不触发兜底 | 品牌+成分关键词 → 场景二 |
| T8 | "雅诗兰黛小棕瓶怎么用" | 场景五 | 不触发兜底 | "怎么用" > "小棕瓶"品牌匹配 |

---

## 5. 文件变更清单

### 新增文件

| 文件 | 说明 |
|:---|:---|
| `server/app/services/intent_router.py` | 意图路由（规则快路径 + LLM 慢路径） |
| `server/app/services/retrieval_dispatcher.py` | 多库动态调度器 |
| `server/app/services/conflict_detector.py` | 矛盾检测器 |
| `server/app/prompts/intent_router.py` | 意图路由 LLM prompt |
| `server/app/prompts/conflict.py` | 矛盾检测 + 对冲输出 prompt |
| `server/tests/test_intent_router.py` | 意图路由单元测试 |
| `server/tests/test_retrieval_dispatcher.py` | 调度器单元测试 |
| `server/tests/test_conflict_detector.py` | 矛盾检测单元测试 |
| `server/tests/test_robustness.py` | 健壮性集成测试（§4 场景） |

### 修改文件

| 文件 | 变更内容 |
|:---|:---|
| `server/app/services/search.py` | 注入 IntentRouter → Dispatcher → ConflictDetector 编排链路 |
| `server/app/services/query_parser.py` | 接收 `flow_type` 参数，按流类型调整拆解策略 |
| `server/app/rag/merger.py` | 接收 `store_weight` 系数，叠加到 `source_weight` |
| `server/app/rag/generator.py` | 接收 `ConflictReport`，有矛盾时使用对冲模板 |
| `server/app/rag/prompt.py` | 新增 `INTENT_ROUTER_SYSTEM`、`CONFLICT_DETECT`、`CONFLICT_AWARE_GENERATOR` |
| `server/config.yaml` | 新增 intent_router 配置段（规则表/LLM 模型/超时） |

### config.yaml 新增配置段

```yaml
# ---- 意图路由 ----
intent_router:
  fast_path_enabled: true         # 是否启用规则快路径
  fast_path_min_confidence: 0.85  # 快路径最低置信度，低于此值走 LLM
  llm_fallback_confidence: 0.6    # LLM 分类置信度低于此值 → 默认路由场景4
  llm_model: "doubao-seed-2.0-lite"
  llm_temperature: 0.1
  timeout: 2.0                    # 意图路由总超时（超时 → 默认路由场景4）

# ---- 矛盾检测 ----
conflict:
  enabled: true
  min_review_count: 2            # 至少N条同向review才算"显著矛盾"
  severity_threshold: "medium"   # 低于此级别不打标记
  llm_temperature: 0.0
  timeout: 2.0
```

---

## 6. 编排层伪代码（search.py 完整链路）

```python
# services/search.py

async def search_stream(query: str, session_id: str, history: list):
    """
    SSE 流式搜索 —— 集成全部新组件的编排层
    """
    # 1. 意图路由
    intent = await intent_router.classify_with_fallback(query)
    # SSE: 可选发送 intent 调试信息
    yield SSEMessage(event="intent", data={"label": intent.intent_label, "flow": intent.flow_type})
    
    # 2. 查询拆解（传递 flow_type）
    sub_queries = await query_parser.parse(query, flow_type=intent.flow_type)
    
    # 3. 动态库调度 + 检索
    store_plan = dispatcher.get_store_plan(intent.intent_label)
    all_hits = []
    for store in store_plan:
        for sq in sub_queries:
            hits = await retriever.search(sq, source_filter=store.source_filter, strategy=store.strategy)
            for h in hits:
                h.store_name = store.name
                h.store_weight = store.weight
            all_hits.extend(hits)
    
    # 4. 主库不足 → 兜底
    if _count_unique_products(all_hits) < 3:
        fallback = dispatcher.get_fallback_plan(intent.intent_label, _failed_stores(all_hits, store_plan))
        all_hits.extend(await _search_stores(fallback, sub_queries, retriever))
    
    # 5. 全局兜底 → 回退到场景一
    if _count_unique_products(all_hits) == 0:
        intent = IntentResult(intent_label=1, flow_type="exploration", confidence=1.0)
        store_plan = dispatcher.get_store_plan(1)
        all_hits = await _search_stores(store_plan, sub_queries, retriever)
    
    # 6. 合并排序
    ranked = merger.merge(all_hits, intent=intent)
    
    # 7. 发送商品卡片
    yield SSEMessage(event="products", data=[p.to_dict() for p in ranked])
    
    # 8. 矛盾检测（仅场景六触发）
    conflict_report = None
    if intent.intent_label == 6:
        for product in ranked:
            faq_hits = [h for h in all_hits if h.product_id == product.id and h.source == "faq"]
            review_hits = [h for h in all_hits if h.product_id == product.id and h.source == "user_review"]
            if faq_hits and review_hits:
                conflict_report = await conflict_detector.detect(product.id, faq_hits, review_hits)
                if conflict_report.has_conflict:
                    break  # 只报告第一个显著矛盾
    
    # 9. 流式生成（有矛盾时使用对冲模板）
    async for token in generator.generate_stream(
        query=query,
        products=ranked,
        conflict=conflict_report,
        history=history,
    ):
        yield SSEMessage(event="delta", data={"text": token})
    
    yield SSEMessage(event="done", data={"session_id": session_id})
```

---

## 7. 复杂度增量评估

| 维度 | 原架构 | 增量 | 说明 |
|:---|:---|:---|:---|
| 新文件 | — | 9 个文件 | 4 服务 + 2 prompt + 3 测试 |
| LLM 调用次数 | 2 次/请求 | +0-2 次/请求 | 快路径 → 0 增量；慢路径 → +1（意图分类）；场景六 → +1（矛盾检测） |
| 检索次数 | N 次（= 子查询数） | 同左 | 不增加检索次数，仅增加 source 过滤条件 |
| 延迟增量 | — | 快路径 0ms / 慢路径 +200ms | 90%+ 查询命中快路径 |
| 配置项 | 26 项 | +9 项 | intent_router(5) + conflict(4) |
