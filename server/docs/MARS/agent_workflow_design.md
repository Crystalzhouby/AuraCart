# MARS — 多智能体推荐系统架构设计

> **MARS = Multi-Agent Recommendation System** | v2.0 | 2026-05-30

> *"Where Every Query Finds Its Perfect Match"*

---

## 1. MARS 架构总览

### 1.1 五大核心 Agent

| # | 中文名 (展示用) | 英文名 (代码) | 代号 | 核心职责 |
|---|----------------|--------------|------|---------|
| ① | **意图改写** | `QueryRewriter` | **RW** | 口语→标准化，纠错/补全/实体提取，不反推需求 |
| ② | **意图路由** | `IntentRouter` | **INT** | 4 分支智能分发：明确意图/场景方案/模糊意图/自由聊天 |
| ③ | **商品方案** | `ProductPlanner` | **PLAN** | 场景库匹配 or 痛点推理，输出商品方案框架 |
| ④ | **偏好澄清** | `PreferenceClarifier` | **CLARIFY** | 多轮交互式需求收敛与选项生成 |
| ⑤ | **回复编织** | `ResponseWeaver` | **WEAVE** | 将商品知识与真实评价编织成温暖推荐 |

### 1.2 四条链路对比

| 链路 | 触发条件 | 典型 Query | 是否经过③ | 问询重点 | 输出 |
|------|---------|-----------|----------|---------|------|
| **明确意图** | 有明确品类词/品牌/功能 | "防晒" "200块精华" | ❌ 跳过③ | 预算→参数→品牌→排除 | 单品列表 |
| **场景方案** | 多品类/多人/活动型描述 | "海边度假装备" | ✅ 经过③ | 预算→人群→槽位偏好 | 组合套装 |
| **模糊意图** ⭐ | 描述痛点/场景但无品类词 | "通勤太吵" "夏天出汗黏" | ✅ 经过③ | 确认猜测→转入明确/场景 | 取决于确认结果 |
| **自由聊天** ⭐ | 纯社交/无购物信号 | "你好" "谢谢" | ❌ 跳过③④ | 无追问 | 自由对话回复 |

### 1.3 总流程图

```
                        用户输入
                          │
                          ▼
                 ① 意图改写 RW
                   口语→标准化 / 纠错 / 实体提取（不反推需求）
                          │
                          ▼
              ② 意图路由 INT ─── 4 分支智能分发
                          │
     ┌────────────┬────────┴────────┬──────────────┐
     ▼            ▼                 ▼              ▼
 场景方案      模糊意图          明确意图       自由聊天
     │            │                 │              │
     └──────┬─────┘                 │              │
            ▼                       │              │
      ③ 商品方案 PLAN                │              │
       场景库匹配 / 痛点推理           │              │
            │                       │              │
            └───────────┬───────────┘              │
                        ▼                          │
               ④ 偏好澄清 CLARIFY                   │
                模式A/B/C 三种追问                  │
                 ├─ 追问中 → <OPTIONS>              │
                 └─ 信息足够 → READY                │
                        │                          │
                        ▼                          │
               【检索模块】(非Agent)                 │
                ├─ L1: RAG 检索                    │
                ├─ L2: SQL 补全                    │
                └─ L3: 文本块提取                   │
                        │                          │
                        └────────────┬─────────────┘
                                     ▼
                        ⑤ 回复编织 WEAVE
                             <AIREPLY> 推荐结果
```

**汇合规则：**
| 上游链路 | 经过的 Agent | 汇入点 |
|---------|-------------|--------|
| 场景方案 | ③PLAN → ④CLARIFY | 与模糊意图在③汇合，再与明确意图在④汇合 |
| 模糊意图 | ③PLAN → ④CLARIFY | 同上 |
| 明确意图 | 跳过③ → ④CLARIFY | 直接汇入④ |
| 自由聊天 | 跳过③④ → ⑤WEAVE | 直达⑤，与其他链路在⑤汇合 |

### 1.4 分场景走查

#### 走查 A：模糊意图 → 多轮收敛 → 推荐完成

```
第1轮 用户：通勤路上太吵了
 │
 ▼
① RW 改写："用户在通勤途中遇到环境噪音过大的问题..."
   entities: { problem_description: "通勤太吵", has_product_type: false }
 │
 ▼
② INT 路由：fuzzy_intent → 进入 ③
 │
 ▼
③ PLAN 痛点推理猜测：
   slots: [降噪耳机(0.9), 隔音耳塞(0.8), 骨传导(0.65)]
 │
 ▼
④ CLARIFY 模式C（确认猜测）：
 <AIREPLY> 听起来通勤路上的噪音确实很烦人！我猜您可能需要这类产品：
 <OPTIONS>
 [GUESS] 我猜您可能需要以下哪种？
 1) 降噪耳机 (主动降噪，效果最好)
 2) 隔音耳塞/入耳式耳机 (性价比高)
 3) 骨传导耳机 (开放双耳更安全)
 4) 都不是，我就是随便聊聊
 </OPTIONS>
 <STATUS>CLARIFYING</STATUS>

── 用户选择 1) 降噪耳机 ──────────────────────────

第2轮 用户：(系统自动代入) 降噪耳机
 │
 ▼
④ CLARIFY 模式A（转为明确意图追问）：
 <AIREPLY> 好的，降噪耳机是个不错的选择！那再了解一下您的偏好：
 <OPTIONS>
 [BUDGET] 预算大概多少？
 1) 300以内  2) 300-800  3) 800-1500  4) 1500以上

 [USAGE] 主要什么场景用？
 1) 地铁公交通勤  2) 办公室  3) 两者都有
 </OPTIONS>
 <STATUS>CLARIFYING</STATUS>

── 用户选择预算300-800 + 地铁通勤 ───────────────

第3轮 用户：(系统自动代入) 300-800，地铁通勤用
 │
 ▼
④ CLARIFY 判断：信息足够 → READY
 │
 ▼
检索模块 → ⑤ WEAVE 编织推荐回复
 <AIREPLY>
 📦 **索尼WH-1000XM5 主动降噪耳机** — ¥799
地铁通勤神器，30级降噪调节，地铁轰鸣声基本听不到。
💬 买家说："每天上班地铁一小时，戴上它世界瞬间安静了"

 📦 **SoundCore Q35i 无线降噪耳机** — ¥349
性价比之选，40dB深度降噪，续航超长。
✨ 温馨提示：降噪耳机建议每月充电一次保持电池健康～
</AIREPLY>
<STATUS>COMPLETE</STATUS>
```

#### 走查 B：明确意图 → 单轮直通

```
用户：想买个不太油的防晒，200以内
 │
 ▼
① RW 改写："寻找适合油性肌肤使用的防晒产品，要求质地清爽不油腻，预算200元以内"
   entities: { product_type: "防晒", price_max: 200, user_profile: {skin_type: "油性"}, negative: ["油腻"] }
 │
 ▼
② INT 路由：clear_intent → 跳过③，直接进入 ④
 │
 ▼
④ CLARIFY 模式A 判断：已有品类+预算+肤质+排除条件 → 信息足够 → READY
 │
 ▼
检索模块 → ⑤ WEAVE 编织推荐回复 → COMPLETE
（单轮完成，无需追问）
```

#### 走查 C：自由聊天 → 兜底直达

```
用户：你好呀
 │
 ▼
① RW 改写："用户发起问候"
 │
 ▼
② INT 路由：free_chat → 跳过③④，直达 ⑤
 │
 ▼
⑤ WEAVE 自由对话回复：
 <AIREPLY> 你好呀！😊 我是你的智能购物助手。有什么想买的、或者拿不准选哪款的，随时跟我说～
</AIREPLY>
<STATUS>COMPLETE</STATUS>
```

#### 走查 D：场景方案 → 槽位框架 → 逐槽位澄清

```
用户：夏天要去海边度假，帮我准备一下装备
 │
 ▼
① RW 改写："夏季海边度假场景，用户需要准备度假装备组合"
 │
 ▼
② INT 路由：scenario_plan → 进入 ③
 │
 ▼
③ PLAN 场景库匹配 (sc_001 夏日海边度假套装)：
   slots: [核心防晒(必), 晒后修护, 防水妆容]
 │
 ▼
④ CLARIFY 模式B（槽位追问）：
 <AIREPLY> 夏日海边度假！为您准备了「防晒+晒后修复+防水彩妆」的组合方案。
 <OPTIONS>
 [BUDGET] 整体预算大概多少？
 1) 200元以内(基础款)  2) 200-500元(品质款) 3) 500元以上(高端款)

 [USER_PROFILE] 谁使用？肤质如何？
 1) 女性油性肌肤  2) 女性干性肌肤  3) 男性通用
 </OPTIONS>
 <STATUS>CLARIFYING</STATUS>

── 用户选择后 → 继续按槽位澄清或直接 READY → 检索 → 推荐
```

### 1.5 关键参数

- 商品数量上限: **5~10 个**
- 最大追问轮数: **3~5 轮**
- 模糊意图引导轮数: **1~2 轮**
- 每次选项数: **3~4 个**
- 记忆粒度: **会话(Session)** 级别

---

## 1.6 会话状态流转

```
                    ┌──────────────┐
                    │   自由聊天    │  free_chat 直达⑤
                    └──────┬───────┘
                           │ 发现潜在购物痛点
                           ▼
                    ┌──────────────┐
                    │   模糊意图    │  进入③PLAN猜测 → ④CLARIFY确认
                    │  (探索中)     │  确认后转入 明确意图/场景方案
                    └──────┬───────┘
                           │ 用户明确品类或场景
              ┌────────────┼────────────┐
              ▼            ▼             │
       ┌──────────┐  ┌──────────────┤
       │  明确意图  │  │   场景方案    │
       │ (跳过③)   │  │ (经过③PLAN)  │
       └─────┬────┘  └──────┬───────┘
             │               │
             └───────┬───────┘
                     ▼
           ┌──────────────┐
           │  偏好澄清    │  模式A/B/C 追问
           │ (收集中)     │  信息足够 → READY
           └──────┬───────┘
                  ▼
           ┌──────────────┐
           │   可检索     │  ready_to_search
           └──────┬───────┘
                  ▼
           ┌──────────────┐
           │  推荐完成    │  COMPLETE
           └──────────────┘
```

| 状态 | 对应链路 | 说明 |
|------|---------|------|
| 自由聊天 | `free_chat` | 纯社交，无购物信号 |
| 探索中 | `fuzzy_intent` | 有痛点但无品类，正在猜测引导 |
| 收集中 | `clear_intent` / `scenario_plan` | 已有方向，正在补齐约束 |
| 可检索 | READY | 信息足够，进入检索+推荐 |
| 推荐完成 | COMPLETE | 最终输出已返回 |

**关键判断节点（两个核心问题）：**
1. 用户是否已经明确想买什么？ → 决定走哪条链路
2. 用户的信息是否足够进入商品检索？ → 决定追问还是推荐

---

## 2. 会话记忆 Session Memory

API 无状态，需要 Memory 维护跨请求上下文。

### 核心 Schema

```python
class SessionMemory:
    session_id: str
    conversation_history: list[ChatMessage]    # 对话历史
    
    # ① 意图改写 RW 写入
    rewritten_query: str                          # 改写后标准查询
    extracted_entities: dict                       # 提取的实体
    
    # ② 意图路由 INT 写入
    intent_result: IntentResult                    # clear_intent / scenario_plan / fuzzy_intent / free_chat
    
    # ③ 商品方案 PLAN 写入 (仅场景/模糊路径)
    product_plan: ProductPlan | None               # 商品方案框架 (统一结构)
    #   source: "scenario_plan" | "fuzzy_intent"
    #   slots: list[Slot]  (每个 Slot = { role, category_hint, required, reason })
    #   guesses_confidence: float  (仅 fuzzy_intent)
    
    # ④ 偏好澄清 CLARIFY 读写 ⭐核心状态机
    clarification_state: ClarificationState
    #   status: CLARIFYING / READY / COMPLETE
    #   current_round: int (当前第几轮, 最大5)
    #   pending_items: list[str] (待确认项)
    #   collected_constraints: dict (已收集的约束)
    
    # 检索模块写入
    retrieval_cache: dict                           # 检索结果缓存
    final_products: list[dict]                      # 最终商品列表
    
    # ⑤ 回复编织 WEAVE 写入
    final_response: str | None                      # 最终回复
```

### 读写规则

```
Agent                  Read                                       Write
─────────────────────  ──────────────────────────────────────────  ───────────────────────────────────
① 意图改写 RW           conversation_history[-10:]                      rewritten_query, extracted_entities
② 意图路由 INT          rewritten_query, extracted_entities              intent_result, suggested_pending_items
③ 商品方案 PLAN         intent_result, extracted_entities                 product_plan (slots/guesses)
④ 偏好澄清 CLARIFY      memory 全量 (含 plan + constraints + state)        clarification_state, collected_constraints
  检索模块               collected_constraints, product_plan                 retrieval_cache, final_products
⑤ 回复编织 WEAVE        memory 全量 (含 retrieval result)                  final_response
  编排层 (框架)          —                                              conversation_history (追加每轮对话)
```

### 存储与生命周期

| 项目 | 说明 |
|------|------|
| **存储介质** | Redis (Hash 结构, key = `session:{session_id}`) |
| **初始化** | 首次请求时由编排层创建空 SessionMemory, `session_id` 用 UUID4 生成 |
| **默认值** | `conversation_history=[]`, `clarification_status=None`, `collected_constraints={}`, `product_plan=None` |
| **写入时机** | 每个 Agent 执行完毕后**立即**由编排层持久化写入 Redis (非 Agent 自行写入) |
| **读取时机** | 每轮请求开始时, 编排层从 Redis 加载完整 Memory → 传给当前需执行的 Agent |
| **TTL** | 30 分钟不活动自动过期 (可配置) |
| **历史窗口** | `conversation_history` 保留最近 **20 轮** (10组问答), 超出后滑动裁剪最旧记录 |

### 多轮对话中的 Memory 演变

以「模糊意图 → 多轮收敛」为例:

```
初始状态 (新会话):
  conversation_history = []
  intent_result = null
  product_plan = null
  clarification_state = null
  collected_constraints = {}

-- 第1轮: 用户"通勤太吵" --
  RW 写入:   rewritten_query, entities(has_product_type=false)
  INT 写入:  intent_result = { type: "fuzzy_intent", ... }
  PLAN 写入: product_plan = { source:"fuzzy_intent", slots:[降噪耳机, 隔音耳塞, 骨传导] }
  CLARIFY写: status=CLARIFYING, 展示猜测选项
  编排层追加: history += [{role:"user", msg:"通勤太吵"}, {role:"assistant", msg:CLARIFY输出}]

-- 第2轮: 用户选"1)降噪耳机" --
  RW 写入:   改写用户选择 -> entities补全 product_type="降噪耳机"
  INT:       跳过! (多轮追问期间不走完整链路, 仅 RW+CLARIFY)
  CLARIFY写: collected_constraints = { product_type: "降噪耳机" }
             status=CLARIFYING (继续追问预算/场景)
  编排层追加: history += [{role:"user", msg:"1)降噪耳机"}, {role:"assistant", msg:CLARIFY输出}]

-- 第3轮: 用户选预算"300-800,地铁通勤" --
  CLARIFY写: collected_constraints += { price_min:300, price_max:800, usage_scene:["地铁通勤"] }
             status=READY (信息足够!)
  --> 进入检索模块 --> 得到 products + chunks
  --> WEAVE 写入: final_response
  --> COMPLETE
```

### conversation_history 写入责任

| 操作 | 责任方 | 说明 |
|------|--------|------|
| 追加用户消息 | **编排层** | 每轮开始时, 将 user_message 追加到 history |
| 追加 AI 回复 | **编排层** | 每个 Agent 输出后, 将回复追加到 history |
| 选项选择处理 | **编排层** | 用户点击选项后, 将选项文本作为下一轮 user_message 代入; 同时记录到 collected_constraints |
| **注意** | Agent **不直接操作** history | Agent 只通过输入参数读取 history, 不负责写入 |
---

---

## 2.5 Agent 间数据流与接口契约

> 本节定义各 Agent 之间的精确数据传递规则，消除衔接歧义。

### 2.5.1 全局数据流拓扑

```
用户输入
   |
   v
+----------+     rewritten_query          +----------+
| ① RW     | -------------------------> | ② INT    |
|          |     extracted_entities       |          |
|          |     has_product_type         |          |
+----------+                              +-----+
                                               |
                                  intent_result | (intent_type -> source)
                                  primary_category
                                  suggested_pending_items
                                               v
   +-------------------------------------------------------+
   |                       分发决策                         |
   |                                                       |
   |  intent_type == free_chat ---------------> 跳到 ⑤WEAVE |
   |  intent_type == clear_intent -----------> 跳到 ④CLARIFY|
   |  intent_type in [scenario_plan, fuzzy_intent] -> ③PLAN |
   +----------------------v--------------------------------+
                          |
                          v
                   +----------+
                   | ③ PLAN   |
                   |          |
                   | product_plan (slots/source/confidence)
                   +-----+
                        |
                        v  (plan + clear_intent 汇合)
                   +----------+
                   | ④ CLARIFY|
                   |          |
                   | collected_constraints (READY时)
                   +-----+
                        |
                        v
                   +--------------+
                   |  检索模块      |
                   |              |
                   | enriched_products
                   | rag_chunks
                   +------+-------+
                          |
                          v
                   +----------+
                   | ⑤ WEAVE  |
                   +----------+
```

### 2.5.2 关键映射规则

#### 规则 A: INT → PLAN 的 source 映射

| INT 输出的 intent_type | 传入 PLAN 的 source | PLAN 使用的策略 |
|----------------------|-------------------|---------------|
| `scenario_plan` | `"scenario_plan"` | 策略A: 场景库匹配 |
| `fuzzy_intent` | `"fuzzy_intent"` | 策略B: 痛点推理猜测 |
| 其他 | — | **不调用** PLAN |

> **实现**: 编排层根据 `intent_result.intent_type` 决定是否调用 PLAN，调用时将 `intent_type` 值作为 `source` 参数传入。

#### 规则 B: CLARIFY 模式自动选择

CLARIFY 不需要显式指定模式，**编排层根据以下规则自动选择**：

| 条件 | CLARIFY 模式 | 说明 |
|------|------------|------|
| `intent_type == clear_intent` 且 **无** `product_plan` | **模式A** | 单品追问 |
| `intent_type in [scenario_plan, fuzzy_intent]` 且 **有** `product_plan` | **模式B 或 C** | 若 `product_plan.source == "fuzzy_intent"` → 先走 **模式C**(确认猜测)，用户选中后转模式A/B；若 `source == "scenario_plan"` → **模式B**(槽位追问) |
| `intent_type == free_chat` | **不经过 CLARIFY** | 直达 WEAVE |

#### 规则 C: 检索模块输入 Schema (RetrievalRequest)

当 CLARIFY 输出 `READY` 时，编排层将以下结构传给检索模块：

```python
class RetrievalRequest:
    # === 必需参数 ===
    intent_type: str                           # 来自 INT 输出
    collected_constraints: dict                # 来自 CLARIFY 收集:
    # {
    #   "product_type": str | None,            # 品类 (RW提取 or PLAN猜测后用户确认)
    #   "price_min": int | None,               # 预算下限
    #   "price_max": int | None,               # 预算上限
    #   "brand_preference": list[str] | None,  # 品牌
    #   "user_profile": dict | None,           # {skin_type, age_group, gender}
    #   "key_requirements": list[str],         # 核心需求
    #   "negative_constraints": list[str],     # 排除条件
    #   "usage_scene": list[str],              # 使用场景
    # }

    # === 可选参数 ===
    product_plan: ProductPlan | None           # 来自 PLAN (场景方案时的槽位框架)
    primary_category: str | None               # 来自 INT (品类大类)
```

#### 规则 D: 检索模块输出 Schema (RetrievalResponse)

```python
class RetrievalResponse:
    enriched_products: list[EnrichedProduct]    # 最终商品列表 (5~10个)
    # EnrichedProduct:
    # {
    #   "product_id": str,
    #   "name": str,
    #   "brand": str,
    #   "price": float,
    #   "category": str,
    #   "marketing_description": str,          # L3提取
    #   "official_faq": list[str],             # L3提取
    #   "user_reviews": list[str],             # L3提取
    #   "score": float,                        # 相关性评分
    #   "matched_slot": str | None             # 匹配的槽位名 (仅场景方案时有值)
    # }

    rag_chunks: list[RAGChunk]                 # RAG 文本块
    # RAGChunk:
    # {
    #   "content": str,
    #   "source_type": "marketing" | "faq" | "review" | "general",
    #   "product_id": str | None,
    #   "relevance_score": float
    # }

    retrieval_meta: dict                       # 检索元信息
    # { "total_candidates": int, "l1_rag_count": int,
    #   "l2_sql_count": int, "query_used": str }
```

#### 规则 E: free_chat 链路 → WEAVE 的特殊处理

当 `intent_type == free_chat` 时：
- **不调用** 检索模块
- **传入 WEAVE**: `enriched_products=[]`, `rag_chunks=[]`, `intent_result`(正常), `product_plan=None`
- WEAVE 根据空商品列表 + `free_chat` intent 自动使用"自由对话格式"

### 2.5.3 各 Agent 接口汇总表

| Agent | 输入 (必/可选) | 输出 | 下游消费者 |
|-------|---------------|------|-----------|
| **① RW** | `user_query`(必) / `history[-10:]`(可选) | rewritten_query, entities, has_product_type | ② INT |
| **② INT** | `rewritten_query`(必) / `entities`(必) / `has_product_type`(必) | IntentResult(type, category, reason, suggested_pending) | 编排层 + ③/④/⑤ |
| **③ PLAN** | `intent_result`(必) / `entities`(必) / `source`=intent_type(必) | ProductPlan(slots, source, confidence) | ④ CLARIFY |
| **④ CLARIFY** | memory全量(必) / `user_input`(必) | `<AIREPLY>+<OPTIONS>+<STATUS>` / constraints(READY时) | 用户 / 检索模块 |
| **检索模块** | RetrievalRequest(必) | RetrievalResponse(products+chunks+meta) | ⑤ WEAVE |
| **⑤ WEAVE** | `products`(必) / `chunks`(必) / `intent_result`(必) / `plan`(可选) | `<AIREPLY>+COMPLETE` | 前端 |

## 3. 各 Agent 详细设计 (Prompt / 输入输出 / 正反例)

---

### 3.1 ① 意图改写 QueryRewriter (RW)

**职责**: 从口语化表述中提取所有关键信息，纠错/补全/同义替换，确保信息无损传达。**不做需求推测和品类猜测。**

**输入**: `user_query` + `conversation_history`
**输出**: `rewritten_query`(改写后标准文本) + `extracted_entities`(结构化实体) + `confidence`

#### 参数明细

| 参数 | 方向 | 类型 | 必需 | 来源 | 说明 |
|------|------|------|------|------|------|
| `user_query` | IN | string | **必需** | 用户本轮输入 | 原始用户消息 |
| `conversation_history` | IN | list[ChatMessage] | 可选 | Memory读取 | 最近10轮对话, 用于指代消解和上下文补全 |
| `rewritten_query` | OUT | string | **必需** | RW生成 | 标准化后的查询文本 |
| `extracted_entities` | OUT | dict | **必需** | RW生成 | 结构化实体 (见Prompt中定义的维度) |
| `has_product_type` | OUT | bool | **必需** | RW生成 | 是否检测到明确品类词, 影响INT路由决策 |
| `confidence` | OUT | float (0~1) | 可选 | RW生成 | 改写置信度, 低置信度时可触发兜底策略 |
| `corrections_made` | OUT | list[str] | 可选 | RW生成 | 所做的纠错/补全列表, 用于调试和日志 |

#### Prompt 模板

```markdown
你是一个电商查询预处理专家。将用户的口语化购物表述转化为标准、信息完整的查询文本。

## 核心原则
1. 信息不损耗：不能丢失用户提到的任何关键信息
2. 纠错：修正明显的错误（品牌名、拼写）
3. 补全：补充合理隐含信息（仅限从上下文可合理推断的信息）
4. 同义替换：口语 → 标准术语
5. ⚠️ 不反推需求：如果用户没有提到具体品类，不要猜测他想要什么产品

## 提取维度
- product_type: 产品类型/品类 (仅当用户明确提及)
- brand_preference: 品牌偏好
- price_info: 预算 (min/max)
- user_profile: 用户特征 (肤质/年龄/性别/场景)
- key_requirements: 核心需求/功效
- negative_constraints: 排除条件
- usage_scene: 使用场景
- problem_description: 用户描述的问题/痛点 (原样保留，不翻译为品类!)

## 输出格式 (严格 JSON)
{
  "rewritten_query": "标准查询语句",
  "extracted_entities": { ... },
  "confidence": 0.0~1.0,
  "corrections_made": ["做了什么修正"],
  "has_product_type": true/false  // 是否检测到明确品类词
}
```

#### ✅ 正例

输入: `"俺想买个防晒，不要太油的"`

```json
{
  "rewritten_query": "寻找适合油性肌肤使用的防晒产品，要求质地清爽不油腻，主要用途为日常防晒防护",
  "extracted_entities": {
    "product_type": "防晒产品/防晒霜",
    "brand_preference": null,
    "price_info": null,
    "user_profile": {"skin_type": "油性肌肤", "concern": "怕油腻/质地清爽"},
    "key_requirements": ["防晒", "清爽不油腻"],
    "negative_constraints": ["油腻"],
    "usage_scene": ["日常使用"],
    "problem_description": null
  },
  "confidence": 0.9,
  "corrections_made": [
    "补全了'防晒产品'的标准品类名称",
    "将'不要太油'转化为'油性肌肤/清爽质地'"
  ],
  "has_product_type": true
}
```

输入: `"通勤路上太吵了"` (模糊意图示例)

```json
{
  "rewritten_query": "用户在通勤途中遇到环境噪音过大的问题，影响日常出行体验",
  "extracted_entities": {
    "product_type": null,
    "brand_preference": null,
    "price_info": null,
    "user_profile": null,
    "key_requirements": ["降低/隔绝环境噪音"],
    "negative_constraints": null,
    "usage_scene": ["通勤途中"],
    "problem_description": "通勤路上太吵了"
  },
  "confidence": 0.85,
  "corrections_made": [
    "将'太吵了'扩展为'环境噪音过大'的标准化描述"
  ],
  "has_product_type": false
}
```

#### ❌ 反例 (禁止这样输出)

| 输入 | 错误输出 | 问题 |
|------|---------|------|
| "想买个防晒" | `{"rewritten_query":"防晒"}` | 太简略，没补全隐含信息 |
| "推荐个兰蔻小小瓶" | `{"rewritten_query":"推荐一款高端精华"}` | 丢失品牌信息且未纠错 |
| "不要含酒精的" | `{"rewritten_query":"不含酒精的产品"}` | 缺少 product_type |
| "通勤路上太吵了" | `product_type: "降噪耳机"` | ⚠️ **反推了需求！违反原则5** |
| "夏天出汗黏糊糊" | `product_type: "止汗露"` | ⚠️ **反推了需求！应保留为 problem_description** |

---

### 3.2 ② 意图路由 IntentRouter (INT)

**职责**: 4 分支智能分发 —— 判断 query 属于明确意图/场景方案/模糊意图/自由聊天，写入会话记忆

**输入**: `rewritten_query` + `extracted_entities` + `has_product_type`
**输出**: `IntentResult`(intent_type, primary_category, confidence, routing_reason)

#### 参数明细

| 参数 | 方向 | 类型 | 必需 | 来源 | 说明 |
|------|------|------|------|------|------|
| `rewritten_query` | IN | string | **必需** | ① RW 输出 | 标准化查询文本 |
| `extracted_entities` | IN | dict | **必需** | ① RW 输出 | 含 product_type, problem_description 等 |
| `has_product_type` | IN | bool | **必需** | ① RW 输出 | 路由关键判断依据 |
| `intent_type` | OUT | enum | **必需** | INT生成 | 4选1: clear_intent / scenario_plan / fuzzy_intent / free_chat |
| `primary_category` | OUT | string or null | 可选 | INT生成 | 品类大类, 供PLAN和检索使用 |
| `confidence` | OUT | float (0~1) | 可选 | INT生成 | 路由置信度 |
| `routing_reason` | OUT | string | **必需** | INT生成 | 选择该分支的理由 (用于日志/调试) |
| `suggested_pending_items` | OUT | list[str] | 可选 | INT生成 | 建议后续确认项, 供CLARIFY参考 |

#### Prompt 模板

```markdown
你是电商购物意图路由专家。将用户查询分发到正确的处理链路。

## 四大分支

### clear_intent (明确意图)
触发条件: 用户提及了明确的品类词 / 品牌 / 具体功能需求
示例: "防晒" "200块精华" "兰蔻小黑瓶" "降噪耳机推荐"
后续路径: → ④偏好澄清 (模式A) → 检索 → ⑤回复编织

### scenario_plan (场景方案)
触发条件: 描述了一个完整场景，涉及多品类 / 多人 / 多用途 / 活动型需求
示例: "海边度假装备" "学生开学必备" "给男朋友准备生日礼物"
后续路径: → ③商品方案(场景库匹配) → ④偏好澄清(模式B) → 检索 → ⑤回复编织

### fuzzy_intent (模糊意图) ⭐
触发条件: 描述了痛点/问题/感受，但没有出现品类词，但有潜在购物转化价值
关键判断: has_product_type=false 且 problem_description 非空
示例: "通勤太吵" "夏天出汗黏糊糊" "熬夜脸黄" "最近总失眠"
后续路径: → ③商品方案(痛点推理) → ④偏好澄清(模式C:确认猜测) → 检索 → ⑤回复编织

### free_chat (自由聊天)
触发条件: 纯社交 / 问候 / 感谢 / 无任何购物信号
示例: "你好" "谢谢" "今天天气不错" "哈哈"
后续路径: → ⑤回复编织 (直达，跳过③④)

## 输出格式 (严格 JSON)
{
  "intent_type": "clear_intent" | "scenario_plan" | "fuzzy_intent" | "free_chat",
  "primary_category": "美妆护肤"|"数码电子"|"服饰运动"|"食品生活"|null,
  "confidence": 0.0~1.0,
  "routing_reason": "选择该分支的理由",
  "suggested_pending_items": ["待确认项"]
}

## 品类映射
美妆护肤: 防晒/精华/面霜/洁面/彩妆
数码电子: 手机/耳机/平板
服饰运动: T恤/运动鞋
食品生活: 咖啡/零食
```

#### ✅ 正例

| 输入 | intent_type | routing_reason |
|------|------------|----------------|
| "寻找适合油性肌肤使用的防晒产品..." | `clear_intent` | 明确提及品类词"防晒产品" |
| "夏天要去海边度假，帮我准备一下装备" | `scenario_plan` | 多品类活动型描述(海边+度假+装备) |
| "用户在通勤途中遇到环境噪音过大..." | `fuzzy_intent` | 有痛点描述(noise_problem)但无品类词(has_product_type=false) |
| "你好呀今天天气真不错" | `free_chat` | 纯社交问候，无购物信号 |

#### ❌ 反例

| 错误 | 说明 |
|------|------|
| "夏天去海边" → clear_intent | 有场景关键词，应为 scenario_plan |
| "推荐一款防晒" → scenario_plan | 有明确品类词，应为 clear_intent |
| "通勤太吵" → free_chat | ⚠️ 有潜在购物价值，不应归入闲聊！应为 fuzzy_intent |
| "买个东西" → 强行判断类型 | 信息过少但非闲聊，可为 fuzzy_intent 或要求澄清 |

---

### 3.3 ③ 商品方案 ProductPlanner (PLAN) ⭐ 合并 Agent

**职责**: 统一处理两种来源的商品方案生成：
- **scenario_plan 来源**: 从预置场景库匹配 → 输出槽位框架
- **fuzzy_intent 来源**: 从痛点/场景推理猜测 → 输出猜测品类框架

**两种来源输出统一结构，后续均由偏好澄清 Agent 处理。**

**输入**: `intent_result` + `extracted_entities` + `source`(scenario or fuzzy_intent)
**输出**: `ProductPlan`(统一 slots 结构)

#### 参数明细

| 参数 | 方向 | 类型 | 必需 | 来源 | 说明 |
|------|------|------|------|------|------|
| `intent_result` | IN | IntentResult | **必需** | ② INT 输出 | 含 intent_type, primary_category |
| `extracted_entities` | IN | dict | **必需** | ① RW 输出 (经INT透传) | 场景关键词/痛点描述等 |
| `source` | IN | string | **必需** | **编排层根据 intent_type 映射** (见2.5.2规则A) | `"scenario_plan"` 或 `"fuzzy_intent"` |
| `product_plan` | OUT | ProductPlan | **必需** | PLAN生成 | 统一 slots 结构 (见Prompt输出JSON Schema) |
| `product_plan.source` | OUT | string | **必需** | PLAN生成 | 标识来源, 决定CLARIFY使用哪种模式 |
| `product_plan.slots[]` | OUT | list[Slot] | **必需** | PLAN生成 | 每个槽位含 role/category_hint/required/reason/confidence |
| `guesses_confidence` | OUT | float | 可选 (仅fuzzy) | PLAN生成 | 整体猜测置信度 |
| `fallback_to_chat` | OUT | bool | 可选 (仅fuzzy) | PLAN生成 | 是否建议转入闲聊 |

#### Prompt 模板

```markdown
你是电商商品方案规划师。根据输入来源不同，采用不同策略生成商品推荐方案框架。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 策略 A: 场景库匹配 (source = scenario_plan)

从预设场景库中匹配最合适的商品组合方案。

### 工作流程
1. 分析场景关键词和已收集的约束
2. 从场景库匹配合适的模板
3. 无精确匹配则找最接近的并说明调整
4. 返回组合框架

## 策略 B: 痛点推理猜测 (source = fuzzy_intent) ⭐

用户描述了一个问题/痛点但没有说想要什么产品。你需要：
1. 分析 problem_description 和 usage_scene
2. 推理出可能解决该问题的 2~4 个品类候选
3. 给出每个猜测的理由和置信度
4. 注意：只是猜测，需要后续由用户确认

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 统一输出格式 (严格 JSON)
{
  "source": "scenario_plan" | "fuzzy_intent",
  
  // ===== 通用字段 =====
  "plan_name": "方案名称",
  "slots": [
    {
      "role": "角色标签(如:核心防晒/降噪设备)",
      "category_hint": "推测品类(如:美妆护肤/数码电子)",
      "sub_category_hint": ["子品类候选"],
      "required": true | false,
      "reason": "为什么需要这个",
      "confidence": 0.0~1.0   // 仅 fuzzy_intent 时有意义
    }
  ],
  
  // ===== fuzzy_intent 特有 =====
  "guesses_confidence": float,       // 整体猜测置信度
  "fallback_to_chat": false,          // 是否建议转入闲聊
  "alternative_guesses": [...]        // 备选猜测(如果主猜测被拒)
  
  // ===== scenario_plan 特有 =====
  "matched_scenario_id": "sc_xxx" | null,
  "total_price_range_hint": {"min": 数值, "max": 数值},
  "adaptation_notes": "调整说明"
}
```

#### ✅ 正例: 场景来源

输入: source=scenario, keywords=["海边","度假","夏天"], season=夏季

```json
{
  "source": "scenario_plan",
  "plan_name": "夏日海边度假套装",
  "slots": [
    { "role": "核心防晒", "category_hint": "美妆护肤", "sub_category_hint": ["防晒霜"], "required": true, "reason": "海边紫外线强，防晒是刚需", "confidence": 0.95 },
    { "role": "晒后修护", "category_hint": "美妆护肤", "sub_category_hint": ["芦荟胶","修复精华"], "required": false, "reason": "暴晒后舒缓修护", "confidence": 0.85 },
    { "role": "防水妆容", "category_hint": "美妆护肤", "sub_category_hint": ["防水眼线","防水睫毛膏"], "required": false, "reason": "海边玩水不脱妆", "confidence": 0.8 }
  ],
  "matched_scenario_id": "sc_001",
  "total_price_range_hint": { "min": 200, "max": 800 }
}
```

#### ✅ 正例: 模糊意图来源

输入: source=fuzzy_intent, problem="通勤路上环境噪音过大", scene="通勤途中"

```json
{
  "source": "fuzzy_intent",
  "plan_name": "通勤降噪方案",
  "guesses_confidence": 0.82,
  "fallback_to_chat": false,
  "slots": [
    { "role": "主动降噪", "category_hint": "数码电子", "sub_category_hint": ["降噪耳机"], "required": false, "reason": "主动降噪技术可有效消除通勤环境噪音", "confidence": 0.9 },
    { "role": "被动隔音", "category_hint": "数码电子", "sub_category_hint": ["隔音耳塞","入耳式耳机"], "required": false, "reason": "被动隔音方案，性价比更高", "confidence": 0.8 },
    { "role": "骨传导备选", "category_hint": "数码电子", "sub_category_hint": ["骨传导耳机"], "required": false, "reason": "开放双耳同时听环境音，安全通勤", "confidence": 0.65 }
  ],
  "alternative_guesses": [
    "如果用户表示不需要电子产品，可猜测: 舒缓音乐/白噪音App(虚拟服务)"
  ]
}
```

#### ❌ 反例

| 错误 | 说明 |
|------|------|
| 场景来源但 slots 含"羽绒服"(海边) | 季节矛盾 |
| 所有 slots 都标记 required | 应区分必选/可选 |
| 模糊意图只给1个猜测 | 应给 2~4 个供选择 |
| 模糊意图猜测置信度都标 1.0 | 猜测就是不确定的，应 < 0.95 |
| 无匹配时不给 fallback | 应说明下一步建议 |

---

### 3.4 ④ 偏好澄清 PreferenceClarifier (CLARIFY) ⭐ 核心 Agent

**职责**: 唯一与用户直接交互的 Agent。评估信息充分性，生成 `<OPTIONS>` 或转 `READY`。
**支持三种模式：单品追问 / 方案槽位追问 / 模糊意图确认**

**输入**: memory 全量 (意图+方案+约束+状态+对话历史+当前用户输入)
**输出**: 固定 Tag 格式 (`<AIREPLY>` / `<OPTIONS>` / `<STATUS>`)

#### 参数明细

| 参数 | 方向 | 类型 | 必需 | 来源 | 说明 |
|------|------|------|------|------|------|
| `intent_result` | IN | IntentResult | **必需** | Memory (②INT写入) | 决定追问模式的基础依据 |
| `product_plan` | IN | ProductPlan or None | 可选 | Memory (③PLAN写入) | 场景方案/模糊意图时有值, 明确意图时为null |
| `clarification_state` | IN | ClarificationState | **必需** | Memory (自身上次写入) | 当前状态/轮数/已收集项 |
| `collected_constraints` | IN | dict | **必需** | Memory (自身累积写入) | 已收集的用户偏好约束 |
| `conversation_history` | IN | list[ChatMessage] | **必需** | Memory (编排层维护) | 对话上下文, 避免重复问已回答的问题 |
| `current_user_input` | IN | string | **必需** | 用户本轮输入 | 用户最新回复/选择 |
| `<AIREPLY>` | OUT | string (Tag) | **必需** | CLARIFY生成 | AI 自然语言回复 |
| `<OPTIONS>` | OUT | Option[] (Tag) | 条件必需 | CLARIFY生成 | 仅 CLARIFYING 状态时输出 |
| `<STATUS>` | OUT | enum (Tag) | **必需** | CLARIFY生成 | CLARIFYING / READY / COMPLETE |

#### Prompt 模板

```markdown
你是专业电商导购助手，通过多轮对话精确了解购物需求。

## 核心任务
判断当前已收集的信息是否足够精准推荐商品。如果不够，生成追问选项让用户选择。

## 信息充分的判断标准 (满足任一即 READY)
1. 已收集的约束可以将候选商品范围缩小到 5~10 个以内
2. 已达到最大追问轮数 (当前第 {round}/{max_rounds} 轮)
3. 用户主动表示"可以了""直接推荐吧"

## 三种追问模式

### 模式 A: 明确意图追问 (来自 clear_intent)
优先级:
1. BUDGET (预算) — 最关键的过滤条件
2. 核心参数 — 因品类而异 (护肤品看肤质/功效，数码看性能/容量)
3. BRAND_PREFERENCE (品牌偏好)
4. NEGATIVE_CONSTRAINTS (排除条件)

### 模式 B: 方案槽位追问 (来自 scenario_plan → ProductPlanner)
按每个 slot 的 role 依次确认:
1. BUDGET (整体预算)
2. USER_PROFILE (人群特征)
3. SLOT_PREFERENCES (各槽位的具体偏好)
4. REQUIRED_VS_OPTIONAL (必选vs可选确认)

### 模式 C: 模糊意图确认 (来自 fuzzy_intent → ProductPlanner) ⭐
轻量引导，1~2轮:
第1轮: 展示猜测的品类选项让用户确认/选择/拒绝
- 用户选中某个猜测 → 自动补全品类信息 → 转入模式A或B
- 用户选"都不是"/拒绝 → 再给一轮 alternative_guesses 或转入自由对话

## 输出格式 — 必须严格遵守！

### 状态: CLARIFYING (还需要追问)
<AIREPLY>
{一句自然的过渡语，总结目前了解到的信息}
</AIREPLY>

<OPTIONS>
[{OPTION_ID}] {问题文本}
1) {选项A}  2) {选项B}  3) {选项C} 4) {选项D}

[{OPTION_ID2}] {问题文本2}
1) {选项X}  2) {选项Y}
</OPTIONS>

<STATUS>CLARIFYING</STATUS>

### 状态: READY (信息足够)
<AIREPLY>
好的，我已经了解了您的需求：{总结关键约束}。让我为您查找...
</AIREPLY>

<STATUS>READY</STATUS>

## 已知信息
{已有约束}

## 商品方案 (如果有)
{product_plan slots}

## 对话历史
{最近对话}

## 当前用户输入
{用户本轮说的话}

请严格遵循上述格式输出：
```

#### ✅ 正例: 模式 A — 单品追问

```
<AIREPLY>
好的，您需要一款适合油性肌肤的清爽防晒。为了给您更精准的推荐：
</AIREPLY>

<OPTIONS>
[BUDGET] 您的预算大概是多少？
1) 100元以下  2) 100-200元  3) 200-500元  4) 500元以上

[SKIN_TYPE] 对防晒倍数有要求吗？
1) 日常通勤SPF30即可  2) 户外需要SPF50  3) 没特别要求
</OPTIONS>
<STATUS>CLARIFYING</STATUS>
```

#### ✅ 正例: 模式 C — 模糊意图确认

```
<AIREPLY>
听起来通勤路上的噪音确实很烦人！我猜您可能是在找这类产品：
</AIREPLY>

<OPTIONS>
[GUESS] 我猜您可能需要以下哪种？
1) 降噪耳机 (主动降噪，效果最好)  2) 隔音耳塞/入耳式耳机 (性价比高)  3) 骨传导耳机 (开放双耳更安全)  4) 都不是，我就是随便聊聊
</OPTIONS>
<STATUS>CLARIFYING</STATUS>
```

用户选了 "1) 降噪耳机" 后，下一轮自动转为模式 A (单品追问):
```
<AIREPLY>
好的，降噪耳机是个不错的选择！那再了解一下您的偏好：
</AIREPLY>

<OPTIONS>
[BUDGET] 预算大概多少？
1) 300以内  2) 300-800  3) 800-1500  4) 1500以上

[USAGE] 主要什么场景用？
1) 地铁公交通勤  2) 办公室  3) 两者都有
</OPTIONS>
<STATUS>CLARIFYING</STATUS>
```

#### ✅ 正例: 模式 B — 方案槽位追问

```
<AIREPLY>
夏日海边度假！为您准备了「防晒+晒后修复+防水彩妆」的组合方案。先确认几个关键信息：
</AIREPLY>

<OPTIONS>
[BUDGET] 这套海边装备整体预算大概多少？
1) 200元以内(基础款)  2) 200-500元(品质款) 3) 500元以上(高端款)

[USER_PROFILE] 谁使用？肤质如何？
1) 女性油性肌肤  2) 女性干性肌肤  3) 男性通用  4) 敏感肌专用
</OPTIONS>
<STATUS>CLARIFYING</STATUS>
```

#### ❌ 反例

| 错误 | 说明 |
|------|------|
| 一次问 5 个问题 | 超过 2 组 OPTIONS |
| 选项超过 4 个 | 每组最多 4 个 choice |
| 忘记写 `<STATUS>` | 格式不完整 |
| CLARIFYING 时直接给了推荐结果 | 状态矛盾 |
| 模式 C 只给了1个猜测选项 | 应给多个猜测+都不选 |
| 模式 C 用户拒绝后继续硬推 | 应转入自由对话或给备选 |

---

### 3.5 ⑤ 回复编织 ResponseWeaver (WEAVE)

**职责**: 将检索到的商品信息和 RAG 文本块编织为温暖、个性化的推荐回复。**必须引用真实文本块作为依据，不能编造信息。**

**输入**: `enriched_products` + `rag_chunks`(marketing_description + FAQ + reviews) + `intent_result` + `product_plan`(可选)
**输出**: `<AIREPLY>` 最终回复 + 推荐商品ID列表

#### 参数明细

| 参数 | 方向 | 类型 | 必需 | 来源 | 说明 |
|------|------|------|------|------|------|
| `enriched_products` | IN | list[EnrichedProduct] | **必需** | 检索模块输出 | 商品列表 (**free_chat 时为空列表 []**) |
| `rag_chunks` | IN | list[RAGChunk] | **必需** | 检索模块输出 | 文本块 (**free_chat 时为空列表 []**) |
| `intent_result` | IN | IntentResult | **必需** | Memory (②INT写入) | 决定输出格式 (单品/组合/自由对话) |
| `product_plan` | IN | ProductPlan or None | 可选 | Memory (③PLAN写入) | 场景方案时用于组合推荐格式 |
| `final_response` | OUT | string (Tag `<AIREPLY>`) | **必需** | WEAVE生成 | 最终推荐回复 |
| `recommended_ids` | OUT | list[str] | 可选 | WEAVE生成 | 推荐的商品ID列表, 供前端渲染卡片 |

#### Prompt 模板

```markdown
你是一位温暖专业的购物顾问。基于真实商品信息和用户评价，为用户编织一份贴心的推荐回复。

## 核心规则
1. 只能使用提供的商品信息，不得编造价格/库存/功能
2. 推荐理由必须来自提供的 RAG 文本块 (营销描述/FAQ/评价)
3. 信息不足时诚实告知
4. 语气温暖自然，像一位懂行的朋友在分享好物
5. 禁止说"根据检索结果""根据商品信息""系统推荐"
6. 每个推荐都要有真实的"人味"——引用真实用户评价

## 输出格式
<AIREPLY>
{推荐内容}
</AIREPLY>
<STATUS>COMPLETE</STATUS>

## 单品推荐格式
<AIREPLY>
根据您的需求，为您精心挑选了以下几款：

📦 **{标题}** — ¥{价格}
{用自然的语言引用营销描述中的亮点，像在介绍自己用过的好物}
💬 有买家这样说："{一条真实好评}"

📦 **{商品2}** — ¥{价格}
...

✨ 温馨提示：{基于 FAQ 的实用建议，像朋友的叮嘱}
</AIREPLY>

## 场景组合推荐格式
<AIREPLY>
🎯 为您搭配的「{方案名}」：

📦 **{槽位角色}: {商品名}** — ¥{价格}
{自然推荐语}

📦 **{槽位角色2}: {商品名}** — ¥{价格}
...

💰 这套搭配总计约：¥{总价}
✨ 使用小贴士：{搭配建议}
</AIREPLY>

## 自由对话格式 (free_chat 链路)
<AIREPLY>
{自然友好的对话回复，可以适当结合电商知识但不强行推销}
</AIREPLY>
<STATUS>COMPLETE</STATUS>

## 可用商品信息
{商品列表}

## RAG 参考文本 (推荐依据 — 必须引用!)
{文本块内容}
```

#### ✅ 正例 (单品)

输入: 商品=[安热沙金瓶¥298, 科颜氏淡斑精华¥520], chunks=[安热沙:"高浓度二裂酵母...", 用户评价:"熬夜党救星!..."]

输出:
```
<AIREPLY>
根据您的需求，为您精心挑选了以下两款：

📦 **安热沙金瓶防晒 SPF50+ PA++++** — ¥298
这款防晒真的很有料——它用了高浓度二裂酵母发酵产物来修护肌底，不是简单防晒而是边防护边养肤的感觉。户外长时间暴晒也扛得住。
💬 有买家这样说："熬夜党救星！每晚3滴吸收超快不黏腻，第二天皮肤完全不暗沉"

📦 **科颜氏新集焕白淡斑精华** — ¥520
主打乙基维生素C抑制黑色素，加上玻色因修护屏障。质地是我很喜欢的那种清爽型，上脸不闷。
✨ 温馨提示：这款含VC成分，白天用的话记得叠加足量防晒哦～
</AIREPLY>
<STATUS>COMPLETE</STATUS>
```

#### ✅ 正例 (场景组合)

输入: 方案="夏日海边度假套装", slots={核心防晒:安热沙, 晒后修复:科颜氏芦荟胶, 防水妆容: KISS ME}, chunks=[...]

输出:
```
<AIREPLY>
🎯 为您搭配的「夏日海边三件套」：

📦 **核心防晒: 安热沙金瓶防晒 SPF50+ PA++++** — ¥298
海边必备！防水防汗配方，下水游泳也不怕。紫外线猛的时候这款安全感拉满。

📦 **晒后修护: 科颜氏芦荟胶** — ¥99
暴晒回来敷一层，冰冰凉凉很舒服。敏感肌也能放心用。

📦 **防水持妆: KISS ME 防水眼线笔** — ¥78
出汗碰水眼线纹丝不动，海边玩一天也不用补妆。

💰 这套搭配总计约：¥475
✨ 使用小贴士：防晒建议出门前20分钟涂好，芦荟胶可以放冰箱冷藏后用更舒爽～
</AIREPLY>
<STATUS>COMPLETE</STATUS>
```

#### ✅ 正例 (自由对话/free_chat链路)

输入: intent=free_chat, message="你好呀"

输出:
```
<AIREPLY>
你好呀！😊 我是你的智能购物助手。有什么想买的、或者拿不准选哪款的，随时跟我说～
</AIREPLY>
<STATUS>COMPLETE</STATUS>
```

#### ❌ 反例

| 错误 | 说明 |
|------|------|
| 编造价格或功能 | 违反规则1 |
| 说"根据检索结果""系统推荐" | 违反规则5，暴露机器感 |
| 没有引用任何文本块 | 违反规则2，无依据 |
| 只返回商品名没有温度 | 不像朋友分享 |
| free_chat 链路却强行推荐商品 | 违反自由对话定位 |

---

## 4. 检索模块 (非 Agent)

**不是 Agent** — 不调 LLM，纯数据访问层。内部分 3 层：

```
Layer 1: RAG 检索     复用现有 Retriever (semantic + keyword + filter) + Merger(RRF)
Layer 2: SQL 补全      复用现有 _get_skus() JOIN product+sku
Layer 3: 文本块提取   🆕 新增! 取 marketing_description + official_faq + user_reviews
```

**为什么不拆成两个 Agent**: 两者都不调 LLM，SQL 输入天然依赖 RAG 输出，同一 DB session 内完成性能更好。

**商品方案路径特殊处理**: 按 ProductPlanner 输出的每个 slot 分别检索 → 合并结果。

---

## 5. 输出格式规范

所有对外输出统一 Tag 格式：

```markdown
<AIREPLY>
{AI 的自然语言回复}
</AIREPLY>

<OPTIONS>
[{OPTION_ID}] {问题}
1) {选项A}  2) {选项B}  3) {选项C}

[{OPTION_ID2}] {问题2}
1) {选项X}  2) {选项Y}
</OPTIONS>

<STATUS>{CLARIFYING | READY | COMPLETE}</STATUS>
```

| 后端输出 | 前端渲染 |
|---------|---------|
| `<AIREPLY>` | AI 气泡 (Markdown) |
| `<OPTIONS>` | 可点击的选项按钮 |
| `CLARIFYING` | 显示选项等待点击 |
| `READY` | "正在查找..." 加载动画 |
| `COMPLETE` | 最终推荐 + 商品卡片 |

---

## 6. 场景库

基于 data 文件夹 4 个品类 (美妆护肤/数码电子/服饰运动/食品生活) 设计：

| ID | 名称 | 触发关键词 | 槽位 |
|----|------|-----------|------|
| sc_001 | 夏日海边度假套装 | 海边/度假/游泳/防晒/夏天 | 核心防晒(必) + 晒后修护 + 防水妆容 |
| sc_002 | 学生党开学必备 | 学生/开学/宿舍/平价/性价比 | 护肤(必) + 穿搭(必) + 数码 + 零食 |
| sc_003 | 职场精致通勤套装 | 上班/通勤/办公室/商务 | 抗老护肤(必) + 正装 + 办公数码 |
| sc_004 | 健身运动装备 | 健身/运动/跑步/减肥 | 运动服饰(必) + 运动补给 + 运动数码 |
| sc_005 | 送礼精选套装 | 送礼/礼物/生日/纪念日 | 主礼物(必) + 搭配食品 + 实用配件 |
| sc_006 | 换季护肤升级 | 换季/春秋/入冬/干燥/过敏 | 季节精华(必) + 强化保湿(必) + 清洁 |

**流程**: 意图路由(scenario_plan) → 商品方案PLAN匹配场景库 → 槽位转为 pending_items → 偏好澄清CLARIFY按槽位追问

---

## 7. Deerflow2 可行性: ✅

MARS 架构天然适合接入 Deerflow2：
- 工作流基本线性 (RW→INT→PLAN?→CLARIFY→检索→WEAVE)，4 条条件分支清晰
- 每个 Agent 有明确的 Input/Output Pydantic Schema
- 检索模块可包装为 Task Node
- 偏好澄清 CLARIFY 的循环结构(含模式C的模糊意图确认) Deerflow2 支持 loop/condition
- 后续只需将 Python 编排转为 YAML DAG 配置

---

## 8. API 接口

### 新增: POST /api/chat

多轮对话主接口 (现有 `/api/search/stream` 保持不变):

```json
// Request
{ "session_id": "null或已有", "message": "想买个不太油的防晒" }

// Response (追问中)
{
  "reply": "好的，您需要一款适合油性肌肤的清爽防晒...",
  "options": [
    {"option_id": "BUDGET", "question": "预算?", "choices": ["100以下","100-200","200-500"]},
    {"option_id": "SKIN", "question": "肤质?", "choices": ["油性","干性","敏感"]}
  ],
  "status": "CLARIFYING",
  "session_id": "sess_xxx"
}

// Response (完成)
{
  "reply": "为您推荐...\n📦 **安热沙金瓶**...",
  "options": null,
  "status": "COMPLETE",
  "recommended_products": [{ "product_id": "...", ... }]
}
```

### 其他
- `GET /api/chat/{session_id}/history` — 获取会话历史
- `DELETE /api/chat/{session_id}` — 清除会话

---

## 9. 与现有代码的复用关系

```
新组件                      ← 对应 →              现有代码
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① 意图改写 RW               ← 升级 →       QueryParser (部分能力，新增不反推原则)
② 意图路由 INT               ← 新增 →       (QueryParser 中隐式的 strategy 判断，扩展为4分支)
③ 商品方案 PLAN (合并)      ← 新增+合并 →   (原场景Agent + 新增模糊意图推理能力)
④ 偏好澄清 CLARIFY          ← 新增 →       (完全缺失)
  检索模块                   ← 增强 →       Retriever + Merger + _get_skus
   ├ L1 RAG                  ← 复用 →       Retriever.retrieve()
   ├ L2 SQL补全               ← 复用 →       _get_skus()
   └ L3 文本块提取             ← 新增 →       (Generator 拿不到文本块)
⑤ 回复编织 WEAVE             ← 升级 →       Generator (增加文本块引用+温暖语气+chat链路)
Session Memory               ← 新增 →       (API 完全无状态)
```

**全部 Agent 共用**: `app/services/llm.py` 的 `LLMService`
