# AI 导购多 Agent 架构设计

> 版本：v1.0  
> 目标：定义电商智能导购助手的 Agent 拆分、调用流程、会话状态和框架选型。

## 1. 设计目标

本系统要解决的不是简单“搜索商品”，而是模拟真实导购的决策过程：

- 用户刚开始可能只是聊天，系统要能识别潜在消费需求。
- 用户需求模糊时，系统要能主动追问，而不是立刻乱推荐。
- 用户需求明确时，系统要能基于商品库检索并给出可信推荐。
- 用户继续追问、对比、反选或加购时，系统要能利用历史上下文。
- 所有价格、库存、商品属性、优惠信息必须来自商品库或业务系统，不能由大模型编造。

因此，多 Agent 设计的核心是：

```text
先理解用户处于哪个阶段，再决定是探索、澄清、检索、推荐、对比还是执行购物车动作。
```

## 2. Agent 拆分

### 2.1 导购编排器

**导购编排器（GuideOrchestrator）** 不是具体 Agent，而是整个多 Agent 流程的控制中心。

职责：

- 读取和写入会话记忆。
- 调用各 Agent。
- 根据意图识别结果选择流程分支。
- 管理追问、检索、推荐、对比、购物车等状态流转。
- 将结果组织成后端 API 或 SSE 流式事件。

### 2.2 查询改写 Agent

**查询改写 Agent（QueryRewriteAgent）**

职责：

- 结合历史上下文，把用户当前输入补全为完整购物需求。
- 处理省略表达，例如“再便宜点”“不要这个”“第二个呢”。
- 纠正口语化、错别字、品牌别称。
- 提取初步实体，例如品类、预算、品牌、肤质、使用场景、否定约束。

示例：

```text
历史：我想买防晒
当前：不要太油，200 以内

改写后：
推荐 200 元以内、适合油皮、质地清爽不油腻的防晒产品。
```

输出示例：

```json
{
  "rewritten_query": "推荐200元以内、适合油皮、质地清爽不油腻的防晒产品",
  "entities": {
    "category": "防晒",
    "budget_max": 200,
    "skin_type": "油皮",
    "negative_constraints": ["油腻"]
  },
  "is_follow_up": true,
  "confidence": 0.92
}
```

### 2.3 意图识别 Agent

**意图识别 Agent（IntentRecognitionAgent）**

职责：

- 判断用户当前到底想做什么。
- 决定后续进入哪个业务流程。
- 区分明确购物需求、潜在购物需求、场景方案、商品对比、购物车操作和纯闲聊。

建议支持的意图：

| 意图 | 中文说明 | 示例 |
| --- | --- | --- |
| `clear_product_need` | 明确单品推荐 | “推荐一款 200 元以内的防晒” |
| `exploratory_need` | 潜在购物需求 | “最近皮肤状态好差” |
| `scenario_solution` | 场景方案 | “下周去三亚，帮我搭一套” |
| `compare_products` | 商品对比 | “第二个和第三个哪个好？” |
| `cart_action` | 购物车操作 | “把第二个加购物车” |
| `pure_chitchat` | 纯闲聊 | “你好呀” |
| `unknown` | 未知或越界 | 无法判断的输入 |

输出示例：

```json
{
  "intent": "clear_product_need",
  "confidence": 0.93,
  "primary_category": "美妆护肤",
  "reason": "用户明确要求推荐防晒产品"
}
```

### 2.4 需求探索 Agent

**需求探索 Agent（ExplorationAgent）**

职责：

- 处理用户还没明确说要买什么、但话里有潜在消费场景的情况。
- 从聊天中识别痛点、场景、人群和生活状态。
- 用自然追问把模糊表达逐步引导成可推荐需求。

示例：

```text
用户：最近皮肤状态好差

系统不直接推荐商品，而是追问：
是更偏干燥起皮、出油长痘，还是熬夜暗沉？我可以按你的状态帮你缩小护理方向。
```

下一轮：

```text
用户：主要是熬夜暗沉

系统继续追问：
你想先找一个精华单品，还是搭一套简单的晚间修护方案？
```

当用户说：

```text
先来个精华吧，别太贵
```

系统才切换到明确单品推荐流程。

### 2.5 需求澄清 Agent

**需求澄清 Agent（NeedClarifyAgent）**

职责：

- 用户已经大致知道要买什么时，判断信息是否足够进入检索。
- 如果信息不足，生成一个追问问题和 3-4 个可选项。
- 如果信息足够，进入商品检索。

需求探索 Agent 和需求澄清 Agent 的区别：

| Agent | 用户状态 | 目标 |
| --- | --- | --- |
| 需求探索 Agent | 用户还不知道自己要买什么 | 理解用户表达，必要时帮用户把痛点和场景说清楚 |
| 需求澄清 Agent | 用户知道大概要买什么 | 补齐预算、用途、偏好等检索条件 |

示例：

```text
用户：推荐个手机

需求澄清 Agent 判断：
信息不足，需要追问预算和偏好。
```

输出示例：

```json
{
  "status": "clarify",
  "missing_slots": ["budget", "priority"],
  "question": "你更看重哪方面？",
  "options": [
    {"value": "我更看重拍照", "constraints": {"priority": "camera"}},
    {"value": "我更看重续航", "constraints": {"priority": "battery"}},
    {"value": "我更看重性价比", "constraints": {"priority": "value"}},
    {"value": "我更看重游戏性能", "constraints": {"priority": "gaming"}}
  ]
}
```

### 2.6 场景方案 Agent

**场景方案 Agent（ScenarioPlanAgent）**

职责：

- 处理“给我配一套”“某个场景需要什么”的需求。
- 将一个场景拆成多个商品槽位。
- 为每个槽位生成独立检索需求。

示例：

```text
用户：下周去三亚度假，帮我搭一套
```

输出示例：

```json
{
  "scenario": "beach_vacation",
  "overall_constraints": {
    "location": "三亚",
    "weather": "高温强日晒",
    "budget_max": null
  },
  "slots": [
    {
      "slot": "sun_protection",
      "role": "防晒防护",
      "query": "高倍防晒 防水 清爽"
    },
    {
      "slot": "outfit",
      "role": "清凉穿搭",
      "query": "夏季 透气 轻薄 出游"
    },
    {
      "slot": "hydration",
      "role": "补水解渴",
      "query": "低糖 清爽 饮料 户外"
    }
  ]
}
```

### 2.7 商品检索 Agent

**商品检索 Agent（ProductSearchAgent）**

职责：

- 将用户需求转成检索计划。
- 决定走关键词检索、向量检索、结构化过滤或混合检索。
- 调用商品知识库和检索工具。
- 对候选商品重排并标记推荐依据。

商品检索 Agent 内部依赖工具，不直接凭空推荐：

```text
商品检索 Agent
  ├─ 关键词检索工具
  ├─ 向量检索工具
  ├─ 结构化过滤工具
  └─ 重排工具
```

输出示例：

```json
{
  "search_plan": {
    "keyword_queries": ["防晒", "清爽"],
    "semantic_queries": ["适合油皮不油腻的日常防晒"],
    "filters": {
      "price_lte": 200,
      "exclude_brands": ["资生堂", "SK-II"],
      "stock_gt": 0
    }
  },
  "products": []
}
```

### 2.8 商品对比 Agent

**商品对比 Agent（ComparisonAgent）**

职责：

- 处理用户对多个商品的比较需求。
- 识别比较对象和比较维度。
- 拉取商品属性、评价、FAQ、价格等证据。
- 输出结构化对比和购买建议。

示例：

```text
用户：第二个和第三个哪个更适合敏感肌？
```

输出示例：

```json
{
  "compare_dimension": ["敏感肌适配", "价格", "使用场景"],
  "items": [],
  "winner": "product_id_xxx",
  "reason": "该商品在敏感肌说明和用户评价中证据更充分"
}
```

### 2.9 购物车动作 Agent

**购物车动作 Agent（CartActionAgent）**

职责：

- 识别自然语言中的加购、删除、改数量、查看购物车、下单确认等动作。
- 解析“这个”“第二个”“刚才那个”等指代。
- 生成结构化动作，由购物车工具执行。

输出示例：

```json
{
  "action": "add",
  "target": {
    "product_ref": "second_recommended_item",
    "sku_id": "sku_xxx"
  },
  "quantity": 1,
  "need_confirm": false
}
```

注意：购物车动作 Agent 只负责理解意图，真正加删改查由购物车工具执行。

### 2.10 推荐生成 Agent

**推荐生成 Agent（RecommendAgent）**

职责：

- 将检索结果、对比结果或场景方案组织成用户能理解的导购回复。
- 说明推荐理由，并关联用户需求。
- 明确哪些条件已满足，哪些条件无法确认。
- 不编造价格、库存、优惠券、功能和功效。
- 同时输出自然语言和结构化商品卡片数据。

推荐输出建议采用结构化格式：

```xml
<AIREPLY>
我更推荐第一款，因为它满足你提到的油皮、清爽、200 元以内三个条件。
</AIREPLY>

<PRODUCTS>
...
</PRODUCTS>

<STATUS>
complete
</STATUS>
```

### 2.11 快捷回复 Agent

**快捷回复 Agent（NextStepGuideAgent）**

职责：

- 根据当前会话阶段，预测用户下一步可能想回复的内容。
- 生成最多 3 个可点击选项，降低用户输入成本，提升对话顺滑度。
- 保证选项和当前上下文强相关，不能生成无关引导。
- 保证选项之间尽量互斥，方便用户快速选择。
- 保留用户自由输入能力，不强迫用户只能点选项。
- 不以强行转化为目标，不把纯闲聊硬引到购物。

快捷回复 Agent 不是理解当前用户意图，也不是强制引导用户购物，而是给用户提供“少打字也能继续聊”的快捷回复。

```text
意图识别 Agent：判断用户当前想干什么
快捷回复 Agent：预测用户下一步可能怎么回复
```

不同阶段的选项含义不同：

| 当前阶段 | 选项作用 | 示例 |
| --- | --- | --- |
| 纯闲聊 | 轻量延续对话 | 继续聊聊 / 换个话题 / 说说你的需求 |
| 需求探索 | 帮用户表达痛点 | 熬夜暗沉 / 出油长痘 / 干燥起皮 |
| 需求澄清 | 补齐检索条件 | 拍照 / 续航 / 性价比 |
| 推荐完成 | 降低继续操作成本 | 看更便宜的 / 对比前两款 / 加购第一款 |
| 场景方案 | 调整方案方向 | 控预算 / 更轻便 / 更高端 |
| 商品对比 | 继续细化比较 | 看价格 / 看评价 / 看适合人群 |

纯闲聊也可以有 ABC 选项，但选项必须是自然聊天方向，不能假装用户已经要购物。

示例 0：纯闲聊阶段

```text
用户：你好呀

回复：
你好，我在呢。你可以随便聊，也可以告诉我最近想解决的小需求。

A. 随便聊聊
B. 我想看看有什么推荐
C. 先介绍你能做什么
```

示例 1：需求探索阶段

```text
用户：最近皮肤状态好差

回复：
听起来可能和作息、肤质或季节有关。你更像哪种情况？

A. 熬夜暗沉
B. 出油长痘
C. 干燥起皮
```

示例 2：需求澄清阶段

```text
用户：推荐个手机

回复：
可以，我先帮你缩小方向。你更看重哪方面？

A. 拍照
B. 续航
C. 性价比
```

示例 3：推荐完成阶段

```text
回复：
我更推荐第一款，适合油皮、预算也合适。

A. 看更便宜的
B. 对比前两款
C. 加第一款到购物车
```

输出示例：

```json
{
  "next_options": [
    {
      "key": "A",
      "value": "我更看重拍照",
      "payload": {
        "priority": "camera"
      }
    },
    {
      "key": "B",
      "value": "我更看重续航",
      "payload": {
        "priority": "battery"
      }
    },
    {
      "key": "C",
      "value": "我更看重性价比",
      "payload": {
        "priority": "value"
      }
    }
  ],
  "allow_free_input": true
}
```

前端点击选项时，建议同时传自然语言和结构化 payload：

```json
{
  "message": "我更看重拍照",
  "selected_option": {
    "key": "A",
    "payload": {
      "priority": "camera"
    }
  }
}
```

这样后端既能按自然语言理解，也能直接读取结构化约束，稳定性更高。

### 2.12 兜底 Agent

**兜底 Agent（FallbackAgent）**

职责：

- 处理无法理解、商品库无结果、纯闲聊或越界请求。
- 给用户一个可继续对话的出口。

示例：

```text
这个问题我暂时没法直接推荐商品。你可以告诉我想买的品类、预算或使用场景，我再帮你筛。
```

## 3. Agent Prompt 设计

本节定义各 Agent 的基础 Prompt。后续实现时建议统一放在：

```text
server/app/agents/prompts.py
```

所有 Agent 输出都应优先使用严格 JSON，便于后端解析和测试。

### 3.1 项目数据上下文

Prompt 必须显式告诉模型，本项目商品库字段来自 `data/ecommerce_agent_dataset`，不能脱离数据编造。

当前商品 JSON 的核心字段包括：

```text
product_id                  商品 ID
title                       商品标题
brand                       品牌
category                    一级类目，例如 美妆护肤 / 数码电子 / 服饰运动 / 食品饮料
sub_category                二级类目，例如 防晒 / 精华 / 蓝牙耳机 / 跑鞋 / 咖啡
base_price                  商品基础价格
image_path                  商品图片路径
skus                        SKU 列表
  - sku_id                  SKU ID
  - properties              规格、颜色、容量等变体属性
  - price                   SKU 价格
rag_knowledge               RAG 知识
  - marketing_description   营销介绍和使用建议
  - official_faq            官方问答
  - user_reviews            用户评价，含 rating 和 content
```

Agent 通用约束：

```text
1. 不得编造商品库不存在的商品、价格、库存、优惠券、功效和成分。
2. 涉及商品事实时，只能基于 product、sku、rag_knowledge 中的信息。
3. 用户表达模糊时，优先追问或生成下一步选项，不要强行推荐。
4. 用户有否定条件时，必须保留，例如“不含酒精”“不要日系”“不要太贵”。
5. 输出必须是可解析 JSON，不要包 Markdown 代码块。
```

### 3.2 查询改写 Agent Prompt

用途：把用户当前输入结合会话记忆补全成完整购物需求。

```text
你是电商导购系统中的“查询改写 Agent”。

你的任务：
1. 结合用户当前输入和历史会话，把用户的话改写成完整、明确、可检索的购物需求。
2. 保留所有约束，包括预算、品牌、类目、肤质、人群、场景、否定条件。
3. 处理省略表达，例如“再便宜点”“不要这个”“第二个呢”“换个清爽的”。
4. 不要生成推荐结果，不要编造商品，只输出改写和实体。

可用商品类目包括：
- 美妆护肤：防晒、精华、洁面、面霜、化妆水等
- 数码电子：蓝牙耳机、手机、键盘、充电器等
- 服饰运动：跑鞋、T恤、外套、运动装备等
- 食品饮料：咖啡、饮料、零食、冲调等

输入：
{
  "user_message": "用户当前输入",
  "session_memory": {
    "conversation_history": [],
    "collected_constraints": {},
    "last_products": [],
    "pending_question": null
  }
}

输出 JSON：
{
  "rewritten_query": "完整购物需求",
  "entities": {
    "category": null,
    "sub_category": null,
    "brand_preference": [],
    "budget_min": null,
    "budget_max": null,
    "user_profile": {},
    "usage_scene": [],
    "key_requirements": [],
    "negative_constraints": []
  },
  "is_follow_up": false,
  "confidence": 0.0,
  "rewrite_notes": []
}
```

### 3.3 意图识别 Agent Prompt

用途：判断用户当前进入哪个导购流程。

```text
你是电商导购系统中的“意图识别 Agent”。

你的任务：
判断用户当前输入属于哪一种意图，并给出路由建议。

意图类型：
1. clear_product_need：用户明确想买某类商品
2. exploratory_need：用户只是聊天或表达痛点，但存在潜在购物需求
3. scenario_solution：用户需要一个场景化组合方案
4. compare_products：用户想比较多个商品
5. cart_action：用户想加购、删除、改数量、查看购物车或下单
6. pure_chitchat：纯闲聊，和购物无明显关系
7. unknown：无法判断

判断规则：
- “推荐/买/想要/有没有/适合我的”通常是 clear_product_need。
- “最近皮肤差/通勤太吵/夏天太热/下周去旅行”可能是 exploratory_need。
- “帮我搭一套/去某地需要什么/一整套方案”是 scenario_solution。
- “哪个更好/对比/区别/第二个和第三个”是 compare_products。
- “加购物车/删掉/买这个/下单”是 cart_action。

输出 JSON：
{
  "intent": "clear_product_need | exploratory_need | scenario_solution | compare_products | cart_action | pure_chitchat | unknown",
  "confidence": 0.0,
  "primary_category": null,
  "primary_sub_category": null,
  "route": "explore | clarify | scenario | compare | cart | chat | fallback",
  "reason": "判断原因"
}
```

### 3.4 需求探索 Agent Prompt

用途：用户还没明确买什么时，把聊天中的痛点转成购物方向。

```text
你是电商导购系统中的“需求探索 Agent”。

用户现在还没有明确说要买什么。你的任务不是推荐商品，而是：
1. 识别用户话里的潜在痛点、生活场景或消费动机。
2. 推测可能相关的商品方向，但不要直接推荐具体商品。
3. 提出一个自然、轻量的问题，引导用户继续说清楚。
4. 可以给下一步引导 Agent 提供候选选项。

结合本项目商品库，常见探索方向：
- 皮肤状态差 → 防晒、精华、洁面、面霜、护肤套装
- 通勤太吵 → 蓝牙耳机、降噪耳机
- 夏天太热/户外 → 防晒、饮料、轻薄服饰
- 跑步/健身 → 跑鞋、运动服、咖啡或功能饮料
- 熬夜困 → 咖啡、护肤修护类商品

输出 JSON：
{
  "latent_needs": {
    "pain_points": [],
    "scenario": null,
    "category_candidates": [],
    "user_profile": {}
  },
  "reply": "自然追问",
  "candidate_next_options": [
    {"value": "用户点击后发送的话", "payload": {}}
  ],
  "should_search_now": false
}
```

### 3.5 需求澄清 Agent Prompt

用途：用户已有购物方向，但信息可能不足，需要判断追问还是检索。

```text
你是电商导购系统中的“需求澄清 Agent”。

你的任务：
1. 判断当前需求是否足够进入商品检索。
2. 如果不足，生成一个追问问题和 3 个候选选项。
3. 如果足够，输出 ready，并整理检索约束。

不同类目的关键槽位：
- 美妆护肤：品类、肤质、预算、功效、敏感肌、使用场景、成分排除
- 数码电子：品类、预算、核心偏好、品牌、使用场景
- 服饰运动：品类、预算、尺码/脚型/运动强度、风格、季节
- 食品饮料：品类、预算、口味、糖分/咖啡因、饮用场景

判断原则：
- “推荐手机”信息不足，应追问预算或偏好。
- “推荐200元以内蓝牙耳机”信息基本足够。
- “推荐适合油皮的防晒”信息基本足够，可检索。
- 如果候选范围会很大，优先追问一个最关键问题。
- 每次只问一个问题，避免用户压力过大。

输出 JSON：
{
  "status": "clarify | ready",
  "missing_slots": [],
  "collected_constraints": {},
  "question": null,
  "candidate_next_options": [],
  "reason": "判断原因"
}
```

### 3.6 场景方案 Agent Prompt

用途：把场景需求拆成多个商品槽位。

```text
你是电商导购系统中的“场景方案 Agent”。

你的任务：
1. 理解用户的场景，例如旅行、通勤、跑步、护肤、办公、露营。
2. 拆成 2-4 个商品槽位，每个槽位对应一个可检索的商品方向。
3. 每个槽位必须能映射到本项目商品库中的类目或子类目。
4. 不直接编造商品，只生成检索需求。

可用大类：
美妆护肤、数码电子、服饰运动、食品饮料。

输出 JSON：
{
  "scenario": "场景名称",
  "overall_constraints": {},
  "slots": [
    {
      "slot": "槽位英文标识",
      "role": "槽位中文作用",
      "category": "一级类目",
      "sub_category": "二级类目或null",
      "query": "用于检索的需求文本",
      "constraints": {}
    }
  ],
  "need_clarify": false,
  "clarify_question": null
}
```

### 3.7 商品检索 Agent Prompt

用途：生成检索计划，实际检索由工具执行。

```text
你是电商导购系统中的“商品检索 Agent”。

你的任务：
1. 根据用户需求生成检索计划。
2. 明确关键词检索、语义检索和结构化过滤条件。
3. 保留否定条件，例如不要某品牌、不含某成分、不要太贵。
4. 不输出推荐文案，不编造商品。

可检索字段：
- product: product_id, title, brand, category, sub_category, base_price
- sku: sku_id, properties, price
- rag_knowledge: marketing_description, official_faq, user_reviews

输出 JSON：
{
  "keyword_queries": [],
  "semantic_queries": [],
  "filters": {
    "category": null,
    "sub_category": null,
    "brand_in": [],
    "brand_not_in": [],
    "price_lte": null,
    "price_gte": null,
    "stock_gt": null
  },
  "knowledge_queries": [],
  "rerank_focus": [],
  "negative_constraints": []
}
```

### 3.8 商品对比 Agent Prompt

用途：处理多个商品的对比决策。

```text
你是电商导购系统中的“商品对比 Agent”。

你的任务：
1. 从会话记忆中定位用户要比较的商品。
2. 识别用户关心的对比维度。
3. 基于商品字段、SKU、FAQ、评价和营销描述进行对比。
4. 不能编造商品事实；没有证据时要说“不足以判断”。

输出 JSON：
{
  "target_products": [],
  "compare_dimensions": [],
  "comparison_table": [],
  "recommendation": {
    "winner_product_id": null,
    "reason": ""
  },
  "need_more_info": false
}
```

### 3.9 购物车动作 Agent Prompt

用途：把用户自然语言转成购物车动作。

```text
你是电商导购系统中的“购物车动作 Agent”。

你的任务：
1. 识别用户要执行的购物车动作。
2. 解析“这个”“第二个”“刚才那个”等指代。
3. 输出结构化动作，交给购物车工具执行。
4. 不直接修改购物车，不编造商品 ID。

动作类型：
add, remove, update_quantity, view_cart, checkout_confirm, unknown

输出 JSON：
{
  "action": "add | remove | update_quantity | view_cart | checkout_confirm | unknown",
  "target": {
    "product_ref": null,
    "product_id": null,
    "sku_id": null
  },
  "quantity": 1,
  "need_confirm": false,
  "clarify_question": null
}
```

### 3.10 推荐生成 Agent Prompt

用途：基于真实商品结果生成导购回复。

```text
你是电商导购系统中的“推荐生成 Agent”。

你的任务：
1. 基于提供的商品、SKU、FAQ、评价、营销描述生成导购回复。
2. 必须引用真实商品信息作为推荐理由。
3. 不得编造价格、库存、优惠券、功效、成分。
4. 如果商品不能完全满足用户条件，要明确说明。
5. 回复要自然，不要说“根据检索结果”这类技术表述。

输入商品字段：
product_id, title, brand, category, sub_category, base_price, image_path,
skus, rag_knowledge.marketing_description, rag_knowledge.official_faq,
rag_knowledge.user_reviews

输出 JSON：
{
  "reply": "面向用户的自然语言回复",
  "recommended_products": [
    {
      "product_id": "商品ID",
      "sku_id": "SKU ID或null",
      "reason": "推荐理由",
      "matched_constraints": [],
      "risk_notes": []
    }
  ],
  "status": "complete | partial | no_result"
}
```

### 3.11 快捷回复 Agent Prompt

用途：每轮回复后生成 ABC 选项。

```text
你是电商导购系统中的“快捷回复 Agent”。

你的任务：
1. 根据当前会话阶段、用户输入、系统回复和商品结果，生成最多 3 个快捷回复选项。
2. 选项的目标是降低用户输入成本，而不是强行引导购物。
3. 选项必须和当前上下文强相关，不能泛泛而谈。
4. 每个选项的 value 既作为前端展示文案，也作为点击后发送的话。
5. 用户必须仍然可以自由输入。
6. 如果当前是纯闲聊，选项必须保持闲聊或温和帮助，不要默认用户要购买。

输出 JSON：
{
  "next_options": [
    {
      "key": "A",
      "value": "点击后作为用户输入的句子",
      "type": "chat | explore | clarify | filter | compare | action",
      "payload": {}
    }
  ],
  "allow_free_input": true
}
```

### 3.12 兜底 Agent Prompt

用途：处理未知、越界或无法推荐的情况。

```text
你是电商导购系统中的“兜底 Agent”。

你的任务：
1. 当系统无法理解用户输入、商品库无结果或请求超出导购范围时，给出友好回复。
2. 不编造商品。
3. 引导用户提供品类、预算、使用场景或偏好。

输出 JSON：
{
  "reply": "友好兜底回复",
  "reason": "兜底原因",
  "candidate_next_options": []
}
```

## 4. 现有代码改造需求

当前 `ymf_backend` 已有 RAG 基础链路，但要支持上述多 Agent 方案，需要改造以下点。

### 4.1 Prompt 文件需要扩展

当前只有：

```text
server/app/rag/prompt.py
  - QUERY_PARSE_SYSTEM
  - GENERATOR_SYSTEM
```

需要新增：

```text
server/app/agents/prompts.py
  - QUERY_REWRITE_PROMPT
  - INTENT_RECOGNITION_PROMPT
  - EXPLORATION_PROMPT
  - NEED_CLARIFY_PROMPT
  - SCENARIO_PLAN_PROMPT
  - PRODUCT_SEARCH_PLAN_PROMPT
  - COMPARISON_PROMPT
  - CART_ACTION_PROMPT
  - RECOMMEND_PROMPT
  - NEXT_STEP_GUIDE_PROMPT
  - FALLBACK_PROMPT
```

### 4.2 现有 QueryParser 不能替代查询改写 Agent

当前 `QueryParser` 的职责是把用户查询拆成：

```text
semantic / keyword / structured_filter
```

它适合作为商品检索前的查询拆解工具，但不适合处理：

- 多轮上下文补全
- 用户省略表达
- 需求探索
- 是否需要追问
- 下一步 ABC 选项

因此需要新增独立的查询改写 Agent 和需求澄清 Agent。

### 4.3 推荐生成需要接入 RAG 知识块

当前推荐生成主要使用商品和 SKU 信息。后续要把以下内容也传给推荐生成 Agent：

```text
rag_knowledge.marketing_description
rag_knowledge.official_faq
rag_knowledge.user_reviews
```

否则推荐理由无法充分利用官方问答和用户评价。

### 4.4 API 需要支持多轮和选项

当前搜索接口偏单轮检索。后续需要新增或改造对话接口：

```text
POST /api/chat
POST /api/chat/stream
```

请求体建议支持：

```json
{
  "session_id": "xxx",
  "message": "我更看重拍照",
  "selected_option": {
    "key": "A",
    "payload": {
      "priority": "camera"
    }
  }
}
```

响应体或 SSE 事件需要支持：

```text
reply
products
cart_update
next_options
status
```

### 4.5 需要增加会话记忆

当前链路缺少稳定的跨轮状态。需要新增：

```text
SessionMemory
ClarificationState
LastProducts
LatentNeeds
SelectedOption
```

MVP 可以先用内存字典，后续落 PostgreSQL 或 Redis。

## 5. 非 Agent 工具层

以下模块不建议做成 Agent，因为它们属于确定性业务逻辑。

### 5.1 会话记忆

**会话记忆（SessionMemory）**

记录多轮对话状态：

```json
{
  "session_id": "xxx",
  "conversation_stage": "exploring",
  "conversation_history": [],
  "latent_needs": {
    "pain_points": ["熬夜暗沉"],
    "scenario": null,
    "category_candidates": ["精华", "面霜", "护肤套装"]
  },
  "collected_constraints": {
    "budget_max": 200,
    "negative_constraints": ["油腻"]
  },
  "last_intent": "exploratory_need",
  "last_products": [],
  "pending_question": "你想找单品还是搭配方案？",
  "cart_state": {}
}
```

### 5.2 商品知识库

**商品知识库（ProductKnowledgeBase）**

包含：

- 商品主表
- SKU
- 商品详情
- 营销描述
- 官方 FAQ
- 用户评价
- 图片信息
- 向量索引
- 结构化属性索引

### 5.3 业务工具

**业务工具（BusinessTools）**

包含：

- 商品检索工具
- 商品详情工具
- 购物车工具
- 订单模拟工具
- 库存和价格查询工具

Agent 负责判断和生成结构化调用，工具负责稳定执行。

## 6. 完整多 Agent 流程

### 6.1 总流程

```text
用户输入
  │
  ▼
导购编排器
  │
  ├─ 读取会话记忆
  │
  ▼
查询改写 Agent
  │
  ▼
意图识别 Agent
  │
  ├─ 纯闲聊
  │     └─ 兜底 Agent → 快捷回复 Agent
  │
  ├─ 聊天中有潜在购物需求
  │     └─ 需求探索 Agent → 快捷回复 Agent
  │
  ├─ 明确单品推荐
  │     └─ 需求澄清 Agent
  │           ├─ 信息不足 → 快捷回复 Agent → 返回追问和 ABC 选项
  │           └─ 信息足够 → 商品检索 Agent → 推荐生成 Agent → 快捷回复 Agent
  │
  ├─ 场景方案
  │     └─ 场景方案 Agent → 商品检索 Agent → 推荐生成 Agent → 快捷回复 Agent
  │
  ├─ 商品对比
  │     └─ 商品对比 Agent → 推荐生成 Agent → 快捷回复 Agent
  │
  └─ 购物车操作
        └─ 购物车动作 Agent → 购物车工具 → 快捷回复 Agent
```

### 6.2 用户只是聊天时的流程

```text
用户：最近皮肤状态好差
  │
  ▼
意图识别 Agent 判断：
这不是明确购买请求，但有潜在护肤需求
  │
  ▼
需求探索 Agent
  │
  ├─ 不直接推荐商品
  ├─ 记录潜在痛点：皮肤状态差
  └─ 快捷回复 Agent 生成选项：
       A. 熬夜暗沉
       B. 出油长痘
       C. 干燥起皮
```

下一轮：

```text
用户：主要是熬夜暗沉
  │
  ▼
需求探索 Agent 继续收集信息
  │
  ├─ 记录痛点：熬夜暗沉
  └─ 快捷回复 Agent 生成选项：
       A. 找一个精华单品
       B. 搭一套晚间修护
       C. 先看看平价方案
```

再下一轮：

```text
用户：先来个精华吧，别太贵
  │
  ▼
意图识别 Agent 判断：
用户已经明确要买精华
  │
  ▼
需求澄清 Agent 判断：
信息基本够了
  │
  ▼
商品检索 Agent
  │
  ▼
推荐生成 Agent
```

### 6.3 用户需求明确时的流程

```text
用户：推荐一款 200 元以内适合油皮的防晒
  │
  ▼
查询改写 Agent
  │
  └─ 标准化为：推荐 200 元以内、适合油皮、质地清爽的防晒产品
  │
  ▼
意图识别 Agent
  │
  └─ 判断为：明确单品推荐
  │
  ▼
需求澄清 Agent
  │
  └─ 判断信息足够，不用追问
  │
  ▼
商品检索 Agent
  │
  ▼
推荐生成 Agent
  │
  ▼
快捷回复 Agent
  │
  └─ 生成：看更便宜的 / 对比前两款 / 加第一款到购物车
```

### 6.4 用户需求不够明确时的流程

```text
用户：推荐个手机
  │
  ▼
查询改写 Agent
  │
  └─ 标准化为：推荐手机
  │
  ▼
意图识别 Agent
  │
  └─ 判断为：明确单品推荐
  │
  ▼
需求澄清 Agent
  │
  └─ 判断信息不足
  │
  ▼
返回追问：
你更看重哪方面？
1. 拍照
2. 续航
3. 性价比
4. 游戏性能

快捷回复 Agent 可输出：
A. 拍照
B. 续航
C. 性价比
```

## 7. 快捷回复选项机制

快捷回复选项用于提升用户体验，让用户在不想打字时也能继续对话。它的目标是降低输入成本和提升幸福感，而不是强行引导用户购物。

### 7.1 基本原则

- 每次最多输出 3 个主选项，避免选择过载。
- 选项必须来自当前上下文，不能为了凑数生成无关内容。
- 选项之间应尽量互斥。
- 用户可以点击选项，也可以自由输入。
- 选项既可以是需求补充，也可以是下一步动作。
- 纯闲聊时也可以输出选项，但选项必须服务于继续聊天或了解能力，不应默认用户有购买意图。
- 推荐结果中的价格、库存、商品属性仍必须来自商品库。

### 7.2 选项类型

| 类型 | 作用 | 示例 |
| --- | --- | --- |
| 闲聊型选项 | 轻量延续对话 | 随便聊聊 / 换个话题 / 你能做什么 |
| 探索型选项 | 帮用户表达潜在需求 | 熬夜暗沉 / 出油长痘 / 干燥起皮 |
| 澄清型选项 | 补齐检索槽位 | 拍照 / 续航 / 性价比 |
| 筛选型选项 | 继续缩小商品范围 | 200 元以内 / 不要日系 / 敏感肌可用 |
| 对比型选项 | 降低比较成本 | 对比前两款 / 看评价 / 看参数 |
| 行动型选项 | 执行业务动作 | 加购物车 / 换一批 / 查看详情 |

### 7.3 后端响应结构

建议在每次对话响应中附带：

```json
{
  "reply": "可以，我先帮你缩小一下手机方向。你更看重哪方面？",
  "next_options": [
    {
      "key": "A",
      "value": "我更看重拍照",
      "type": "clarify",
      "payload": {
        "priority": "camera"
      }
    },
    {
      "key": "B",
      "value": "我更看重续航",
      "type": "clarify",
      "payload": {
        "priority": "battery"
      }
    },
    {
      "key": "C",
      "value": "我更看重性价比",
      "type": "clarify",
      "payload": {
        "priority": "value"
      }
    }
  ],
  "allow_free_input": true
}
```

如果走 SSE，可以新增事件：

```text
event: next_options
data: {"options":[...],"allow_free_input":true}
```

### 7.4 生成位置

快捷回复 Agent 建议放在每个业务分支的末尾，包括纯闲聊和需求探索分支。

```text
业务 Agent 先完成本轮理解、追问、检索或推荐
  ↓
快捷回复 Agent 根据当前状态生成 ABC 选项
  ↓
后端返回自然语言回复 + 商品卡片 + 下一步选项
```

原因：

- 需求探索 Agent 知道用户痛点，但不一定负责统一选项格式。
- 需求澄清 Agent 知道缺哪些槽位，但不一定负责体验排序。
- 推荐生成 Agent 知道推荐结果，但不一定负责统一快捷回复结构。
- 兜底 Agent 知道当前不能推荐，但也可以提供“继续聊、换话题、了解能力”等低压力选项。
- 快捷回复 Agent 统一处理选项数量、文案、互斥性和结构化 payload。

## 8. 会话状态机

多轮导购需要维护用户当前处于哪个阶段。

建议状态：

```text
纯闲聊
  ↓ 发现潜在购物痛点
需求探索
  ↓ 用户明确品类或场景
需求澄清
  ↓ 关键槽位足够
可检索
  ↓ 检索完成
推荐中
  ↓ 用户继续追问
对比 / 加购 / 继续筛选
```

状态字段示例：

| 状态 | 说明 |
| --- | --- |
| `pure_chitchat` | 纯闲聊，无购物意图 |
| `exploring` | 正在探索潜在需求 |
| `clarifying` | 已有购物方向，正在补齐条件 |
| `ready_to_search` | 信息足够，可以检索 |
| `recommending` | 正在推荐 |
| `comparing` | 正在对比 |
| `cart_action` | 正在处理购物车动作 |
| `complete` | 当前任务完成 |

## 9. 框架选型建议

### 9.1 推荐方案

推荐使用：

```text
多 Agent 编排：LangGraph
模型调用和工具封装：LangChain 或现有 LLMService
结构化输出：Pydantic
检索：自研商品检索工具
会话记忆：PostgreSQL / Redis，MVP 可先用内存
后端接口：FastAPI
流式返回：SSE
```

### 9.2 为什么推荐 LangGraph

本项目的核心流程不是单条链路，而是有状态、有分支、有循环的导购状态机。

LangGraph 适合表达：

- 查询改写 → 意图识别 → 条件分支。
- 信息不足 → 追问 → 等待下一轮 → 再判断。
- 单品推荐、场景方案、商品对比、购物车操作等不同流程。
- 多轮会话状态的持续传递。

因此，LangGraph 更适合作为导购 Agent 的编排框架。

### 9.3 LangChain 的定位

LangChain 更适合作为辅助工具库：

- Prompt 模板
- 模型调用
- 工具封装
- 结构化输出
- RAG 检索组件

不建议只用 LangChain 承担完整多 Agent 状态机，否则容易退化成大量手写 `if/else`。

### 9.4 DeerFlow 2.0 的定位

DeerFlow 2.0 可以作为后续扩展方向，但不建议当前阶段直接接入。

原因：

- DeerFlow 是完整的 SuperAgent 平台，包含沙箱、技能、长期记忆、Gateway、子 Agent 等能力。
- 它更适合长任务，例如调研、代码生成、报告生成、文件处理。
- 电商导购更强调低延迟、多轮对话、结构化检索和业务闭环。
- 当前阶段直接引入 DeerFlow 会增加部署和调试复杂度。

建议写法：

```text
项目后续可接入 DeerFlow 2.0 作为多 Agent 编排和长期任务执行框架。
当前阶段优先使用 LangGraph 实现轻量导购状态机。
```

## 10. MVP 实现范围

第一阶段建议实现：

```text
导购编排器
查询改写 Agent
意图识别 Agent
需求探索 Agent
需求澄清 Agent
商品检索 Agent
推荐生成 Agent
会话记忆
```

第二阶段增强：

```text
场景方案 Agent
商品对比 Agent
购物车动作 Agent
更完整的商品知识库和向量检索
```

第三阶段扩展：

```text
LangGraph 可视化和调试
长期用户偏好记忆
多模态输入
DeerFlow 2.0 兼容或迁移
```

## 11. 最终结论

本项目的多 Agent 架构应以 **导购编排器 + 会话记忆 + 多个业务 Agent + 确定性工具层** 为核心。

推荐主流程：

```text
查询改写 Agent
  → 意图识别 Agent
  → 需求探索 Agent / 需求澄清 Agent / 场景方案 Agent / 商品对比 Agent / 购物车动作 Agent
  → 商品检索 Agent
  → 推荐生成 Agent
  → 快捷回复 Agent
```

其中最关键的两个判断是：

```text
用户是否已经明确想买什么？
用户的信息是否足够进入商品检索？
```

这样设计后，系统既能处理明确搜索，也能处理“聊着聊着才知道用户想买什么”的真实导购场景。
