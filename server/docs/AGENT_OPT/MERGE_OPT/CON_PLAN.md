# MERGE_OPT — 编码级实现方案

> 输入: `server/docs/AGENT_OPT/MERGE_OPT/PLAN.md`
> 输出: `server/docs/AGENT_OPT/MERGE_OPT/CON_PLAN.md`

## F1: 去除查询改写 LLM 调用

### F1a: `router.py` — 删除 `_rewrite_query()` 及 `rewritten_query` 相关

**文件:** `server/app/agent/nodes/router.py`

#### Edit 1: 模块 docstring (lines 1-8)

```python
# Before
"""
Intent Router 节点 — 工作流第一个节点。

单次三分类 + 查询改写：
1. 意图分类: chat（闲聊）/ explicit（明确商品需求）/ scenario（场景化推荐）
2. 若为 explicit 或 scenario，利用 session_memory 中最近 N 轮历史改写当前查询，
   补充商品主体。完整查询不做改写（透传）。
"""

# After
"""
Intent Router 节点 — 工作流第一个节点。

单次三分类 + 欢迎语生成：
1. 意图分类: chat（闲聊）/ explicit（明确商品需求）/ scenario（场景化推荐）
2. 若为 explicit 或 scenario，生成欢迎语（基于 user_query + 对话历史）。
"""
```

#### Edit 2: line 14 — 删除 REWRITE_SYSTEM import

```python
# Before
from app.agent.prompts.rewrite_prompt import REWRITE_SYSTEM

# After
# (删除整行)
```

#### Edit 3: `_generate_welcome()` (lines 80-117) — 删除 `rewritten_query` 参数

```python
# Before
async def _generate_welcome(
    user_query: str,
    rewritten_query: str,
    recent_queries: list[dict],
    scenario_description: str,
    llm,
) -> str:
    """在 router 节点生成欢迎词。基于当前查询+改写结果+对话历史。

    参数:
        user_query: 原始用户查询。
        rewritten_query: 改写后的查询。
        recent_queries: 最近 N 轮历史原始查询。
        scenario_description: 场景描述（当前阶段始终为空，由下游 scenario_gen 产出）。
        llm: LLMService 实例。

    返回值:
        str: 欢迎词文本。LLM 不可用或失败时返回空字符串。
    """
    if not llm:
        return ""
    try:
        history_text = _format_recent_queries(recent_queries)
        prompt = WELCOME_SYSTEM.format(
            user_query=user_query,
            rewritten_query=rewritten_query,
            recent_queries=history_text,
            scenario_description=scenario_description or "无",
        )
        ...

# After
async def _generate_welcome(
    user_query: str,
    recent_queries: list[dict],
    scenario_description: str,
    llm,
) -> str:
    """在 router 节点生成欢迎词。基于当前查询+对话历史。

    参数:
        user_query: 用户查询。
        recent_queries: 最近 N 轮历史原始查询。
        scenario_description: 场景描述（当前阶段始终为空，由下游 scenario_gen 产出）。
        llm: LLMService 实例。

    返回值:
        str: 欢迎词文本。LLM 不可用或失败时返回空字符串。
    """
    if not llm:
        return ""
    try:
        history_text = _format_recent_queries(recent_queries)
        prompt = WELCOME_SYSTEM.format(
            user_query=user_query,
            recent_queries=history_text,
            scenario_description=scenario_description or "无",
        )
        ...
```

具体编辑:
- Line 82: 删除 `rewritten_query: str,` 参数
- Lines 90-91: 删除 docstring 中 `rewritten_query` 行
- Line 105: 删除 `.format()` 中的 `rewritten_query=rewritten_query,` 行

#### Edit 4: 删除 `_rewrite_query()` (lines 120-161)

删除整个函数（42 行）:
```python
async def _rewrite_query(
    user_query: str,
    recent_queries: list[dict],
    llm: LLMService,
) -> str:
    ...
```

#### Edit 5: `router_node()` (lines 164-223) — 删除 Step 2 + 改写 welcome 调用

```python
# Before (lines 164-223)
async def router_node(state: dict, llm: LLMService) -> dict:
    """Intent Router + 查询改写节点函数。

    流程:
    1. LLM 三分类: chat / explicit / scenario
    2. 若为 explicit 或 scenario: 从 session_memory 取最近 N 轮 → LLM 改写查询

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。

    返回值:
        dict: {"intent", "rewritten_query"}，写入 AgentState。
    """
    user_query = state.get("user_query", "")
    session_memory = state.get("session_memory", [])

    # ---- Step 1: 三分类 ----
    ...

    # ---- Step 2: 查询改写（explicit / scenario 路径） ----
    if intent in ("explicit", "scenario"):
        n_rounds = settings.search.memory_recent_rounds
        recent_queries = get_recent_queries(session_memory, n_rounds)
        rewritten_query = await _rewrite_query(user_query, recent_queries, llm)
    else:
        rewritten_query = user_query
        recent_queries = []

    # ---- Step 3: 生成欢迎词（explicit / scenario 路径） ----
    welcome_text = ""
    if intent in ("explicit", "scenario"):
        scenario_desc = state.get("scenario_description") or ""
        welcome_text = await _generate_welcome(
            user_query=user_query,
            rewritten_query=rewritten_query,
            recent_queries=recent_queries,
            scenario_description=scenario_desc,
            llm=llm,
        )

    return {
        "intent": intent,
        "rewritten_query": rewritten_query,
        "welcome_text": welcome_text,
    }

# After
async def router_node(state: dict, llm: LLMService) -> dict:
    """Intent Router 节点函数。

    流程:
    1. LLM 三分类: chat / explicit / scenario
    2. 若为 explicit 或 scenario: 生成欢迎语

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。

    返回值:
        dict: {"intent", "welcome_text"}，写入 AgentState。
    """
    user_query = state.get("user_query", "")
    session_memory = state.get("session_memory", [])

    # ---- Step 1: 三分类 ----
    prompt = (ROUTER_SYSTEM
              .replace("{user_query}", user_query))
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        raw_response = await llm.chat(messages, temperature=0.1)
        parsed = _parse_router_response(raw_response)
    except Exception as e:
        logger.warning("Router LLM 调用失败，使用 fallback", error=str(e))
        parsed = {"intent": "explicit"}

    intent = parsed.get("intent", "explicit")

    # ---- Step 2: 生成欢迎词（explicit / scenario 路径） ----
    welcome_text = ""
    recent_queries = []
    if intent in ("explicit", "scenario"):
        n_rounds = settings.search.memory_recent_rounds
        recent_queries = get_recent_queries(session_memory, n_rounds)
        scenario_desc = state.get("scenario_description") or ""
        welcome_text = await _generate_welcome(
            user_query=user_query,
            recent_queries=recent_queries,
            scenario_description=scenario_desc,
            llm=llm,
        )

    return {
        "intent": intent,
        "welcome_text": welcome_text,
    }
```

### F1b: `state.py` — 删除 `rewritten_query` 字段

**文件:** `server/app/agent/state.py`

#### Edit 1: docstring (line 15)
删除 `rewritten_query: Router 改写后的用户查询。` 行。

#### Edit 2: TypedDict (line 31)
删除 `rewritten_query: str` 行。

### F1c: `search.py` — 删除初始 state 中的 `rewritten_query`

**文件:** `server/app/api/search.py`

#### Edit: line 213
```python
# Before
    "rewritten_query": "",

# After
# (删除整行)
```

### F1d: `extraction.py` — `rewritten_query` → `user_query`

**文件:** `server/app/agent/nodes/extraction.py`

#### Edit 1: `_build_context_with_memory()` (lines 63-102)

参数名和 docstring 全部 `rewritten_query` → `user_query`:

```python
# Before
def _build_context_with_memory(
    rewritten_query: str,
    categories: list[dict],
    session_memory: list[dict],
) -> str:
    """Step 2: ..."""
    ...
        lines.append(f"当前查询: {rewritten_query}")
    ...
    return "\n\n".join(parts) if parts else rewritten_query

# After
def _build_context_with_memory(
    user_query: str,
    categories: list[dict],
    session_memory: list[dict],
) -> str:
    """Step 2: 按品类从 session_memory 检索历史查询，与当前查询拼接。"""
    ...
        lines.append(f"当前查询: {user_query}")
    ...
    return "\n\n".join(parts) if parts else user_query
```

具体:
- Line 64: 参数 `rewritten_query` → `user_query`
- Line 74: docstring `rewritten_query` → `user_query`
- Line 99: `{rewritten_query}` → `{user_query}`
- Line 102: `rewritten_query` → `user_query`

#### Edit 2: `_extract_categories_and_brands()` (lines 105-181)

```python
# Before
async def _extract_categories_and_brands(
    rewritten_query: str,
    ...
) -> list[dict]:
    """Step 1: ...
    参数:
        rewritten_query: Router 改写后的查询。
    """
    ...
        {"role": "user", "content": rewritten_query},

# After
async def _extract_categories_and_brands(
    user_query: str,
    ...
) -> list[dict]:
    """Step 1: LLM 提取品类/品牌 + Tool 校验合法性。
    参数:
        user_query: 用户查询。
    """
    ...
        {"role": "user", "content": user_query},
```

具体:
- Line 106: 参数 `rewritten_query` → `user_query`
- Line 113: docstring `rewritten_query` → `user_query`
- Line 133: `rewritten_query` → `user_query`

#### Edit 3: `extraction_node()` (lines 230-301)

```python
# Before (line 245)
rewritten_query = state.get("rewritten_query", state.get("user_query", ""))
...
categories = await _extract_categories_and_brands(
    rewritten_query, llm, db_session_factory
)
...
context = _build_context_with_memory(rewritten_query, categories, session_memory)
...
        "text": rewritten_query,

# After
user_query = state.get("user_query", "")
...
categories = await _extract_categories_and_brands(
    user_query, llm, db_session_factory
)
...
context = _build_context_with_memory(user_query, categories, session_memory)
...
        "text": user_query,
```

具体:
- Line 245: `rewritten_query = state.get(...)` → `user_query = state.get("user_query", "")`
- Line 250: `rewritten_query, llm, ...` → `user_query, llm, ...`
- Line 259: `rewritten_query, categories, ...` → `user_query, categories, ...`
- Line 291: `"text": rewritten_query` → `"text": user_query`

### F1e: `scenario_gen.py` — `rewritten_query` → `user_query`

**文件:** `server/app/agent/nodes/scenario_gen.py`

#### Edit 1: 模块 docstring (line 4)

```python
# Before
从 rewritten_query 出发，结合可用品类列表和历史查询，

# After
从 user_query 出发，结合可用品类列表和历史查询，
```

#### Edit 2: `_build_scenario_history_context()` (lines 64-97)

```python
# Before
def _build_scenario_history_context(
    rewritten_query: str,
    ...
) -> str:
    """...
    参数:
        rewritten_query: Router 改写后的查询。
    """

# After
def _build_scenario_history_context(
    user_query: str,
    ...
) -> str:
    """为 Scenario Gen 构建历史查询上下文。
    参数:
        user_query: 用户查询。
    """
```

具体:
- Line 65: 参数 `rewritten_query` → `user_query`
- Line 74: docstring `rewritten_query` → `user_query`

#### Edit 3: `scenario_gen_node()` (lines 126-227)

```python
# Before (line 143)
rewritten_query = state.get("rewritten_query", state.get("user_query", ""))
...
history_context = _build_scenario_history_context(
    rewritten_query, category_list, session_memory
)
...
              .replace("{user_query}", rewritten_query))
...
    scenario_description = data.get("scenario_description", rewritten_query)
...
        "scenario_description": rewritten_query,

# After
user_query = state.get("user_query", "")
...
history_context = _build_scenario_history_context(
    user_query, category_list, session_memory
)
...
              .replace("{user_query}", user_query))
...
    scenario_description = data.get("scenario_description", user_query)
...
        "scenario_description": user_query,
```

具体:
- Line 143: `rewritten_query = state.get(...)` → `user_query = state.get("user_query", "")`
- Line 148: `rewritten_query, category_list, ...` → `user_query, category_list, ...`
- Line 182: `.replace("{user_query}", rewritten_query)` → `.replace("{user_query}", user_query)`
- Line 195: `rewritten_query` → `user_query`
- Line 201: `rewritten_query` → `user_query`

### F1f: `show_prompt.py` — `WELCOME_SYSTEM` 移除 `{rewritten_query}`

**文件:** `server/app/agent/prompts/show_prompt.py`

#### Edit: line 19

```python
# Before
{rewritten_query}

# After
{user_query}
```

> 注: 对应规则行 "额外关注当前查询" 保持不变；占位名从 `rewritten_query` 改为 `user_query` 以匹配 `_generate_welcome()` 中 `.format()` 调用。

### F1g: 删除 `rewrite_prompt.py`

**文件:** `server/app/agent/prompts/rewrite_prompt.py` → **删除**

---

## F2: 合并结束语生成与选项生成

### F2a: `option_gen_prompt.py` — 新增合并 prompt

**文件:** `server/app/agent/prompts/option_gen_prompt.py`

#### 操作: 用 `ENDING_OPTION_SYSTEM` 替换 `OPTION_GEN_SYSTEM`

```python
# Before (整个文件内容)
OPTION_GEN_SYSTEM = """..."""

# After
ENDING_OPTION_SYSTEM = """# 人设
你是电商导购助手，需要同时完成两项任务：生成结束语和生成下一步推荐选项。

# 任务 1: 结束语
- 主要回应当前用户查询
- 简要总结推荐内容（提及品类数量和商品总数）
- 引导用户进一步互动（如询问预算、偏好、尺码等）
- 1到3句话，不超过60字
- 不使用"感谢您的耐心""期待为您服务"等客服腔
- 不使用"以上是""综上所述"等书面语
- 语气轻松自然，像朋友聊天收尾

# 任务 2: 推荐选项
- 站在用户视角写，像用户自己会输入的话，不要用导购提问口吻
- 每个选项尽量短，适合手机按钮展示，最多16个中文字符
- 选项用于继续明确需求方向，可包含属性细化、预算调整、场景补充、偏好切换或合理搭配
- 不重复用户已明确表达的需求，不凭空扩展新品类，不生成检索失败品类
- 最多3个选项

# 输出格式
只返回 JSON，不要输出解释:
{
  "ending": "<结束语>",
  "next_options": ["选项1", "选项2", "选项3"]
}

# 输入信息
## 当前用户查询
{user_query}

## 推荐概况
品类: {categories_summary}
共 {product_count} 件商品

## 场景描述
{scenario_description}

## 对话历史
{recent_queries}

## 当前用户需求
{requirements}

## 已推荐商品信息（含商品基础信息 + 检索到的 FAQ/评价）
{retrieval_results}

## 检索失败的品类（避免生成这些品类的选项）
{failed_categories}
"""
```

### F2b: `option_gen.py` — 扩展为合并节点

**文件:** `server/app/agent/nodes/option_gen.py`

#### Edit 1: import (line 10)

```python
# Before
from app.agent.prompts.option_gen_prompt import OPTION_GEN_SYSTEM

# After
from app.agent.prompts.option_gen_prompt import ENDING_OPTION_SYSTEM
```

#### Edit 2: 新增 `_build_ending_context()` 函数 (插入在 `_build_retrieval_summary` 之后)

```python
def _build_ending_context(state: dict) -> dict:
    """从 state 构建结束语所需的上下文字段。"""
    retrieval_results = state.get("retrieval_results", [])
    categories = set()
    for p in retrieval_results:
        cat = p.get("category", "")
        sub = p.get("sub_category", "")
        if cat and sub:
            categories.add(f"{cat}/{sub}")
    return {
        "categories_summary": "、".join(sorted(categories)) if categories else "无",
        "product_count": len(retrieval_results),
    }
```

#### Edit 3: 新增 `_build_recent_queries_text()` 函数

```python
def _build_recent_queries_text(state: dict) -> str:
    """从 session_memory 构建最近查询文本。"""
    from app.agent.memory import get_recent_queries
    from app.config import settings
    memory = state.get("session_memory", [])
    if not memory:
        return "(无历史记录)"
    recent = get_recent_queries(memory, settings.search.memory_recent_rounds)
    if not recent:
        return "(无历史记录)"
    sorted_q = sorted(recent, key=lambda x: x["timestamp"])
    return "\n".join(f"- {q['query']}" for q in sorted_q)
```

#### Edit 4: `option_gen_node()` — 核心逻辑替换

```python
# Before (lines 63-119)
async def option_gen_node(state: dict, llm: LLMService) -> dict:
    """Option Gen 节点函数。"""
    options: list[str] = []

    try:
        requirements = json.dumps(state.get("requirements", {}), ensure_ascii=False)
        retrieval_results = _build_retrieval_summary(state.get("retrieval_results", []))
        scenario_description = state.get("scenario_description") or "无"
        failed_categories = state.get("failed_categories", [])
        failed_categories_str = (
            json.dumps(failed_categories, ensure_ascii=False) if failed_categories else "无"
        )

        prompt = (
            OPTION_GEN_SYSTEM
            .replace("{requirements}", requirements)
            .replace("{retrieval_results}", retrieval_results)
            .replace("{scenario_description}", scenario_description)
            .replace("{failed_categories}", failed_categories_str)
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请生成下一步推荐选项"},
        ]
        ...

        raw_response = await llm.chat(messages, temperature=0.3)

        start = raw_response.find("{")
        end = raw_response.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw_response[start:end])
            options = data.get("next_options", [])
        ...

    # 截断到最多 3 条
    if len(options) > 3:
        options = options[:3]

    return {"next_options": options}

# After
async def option_gen_node(state: dict, llm: LLMService) -> dict:
    """Option Gen 节点函数 — 合并生成结束语 + 下一步推荐选项。

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。

    返回值:
        dict: {"next_options": [...], "ending": "..."}
    """
    options: list[str] = []
    ending: str = ""
    queue = state.get("_sse_queue")

    try:
        # 1. 构建结束语上下文
        ending_ctx = _build_ending_context(state)
        categories_summary = ending_ctx["categories_summary"]
        product_count = ending_ctx["product_count"]

        # 2. 构建最近查询
        recent_queries = _build_recent_queries_text(state)

        # 3. 构建选项上下文
        user_query = state.get("user_query", "")
        requirements = json.dumps(state.get("requirements", {}), ensure_ascii=False)
        retrieval_results = _build_retrieval_summary(
            state.get("retrieval_results", [])
        )
        scenario_description = state.get("scenario_description") or "无"
        failed_categories = state.get("failed_categories", [])
        failed_categories_str = (
            json.dumps(failed_categories, ensure_ascii=False) if failed_categories else "无"
        )

        # 4. LLM 调用合并 prompt
        prompt = (
            ENDING_OPTION_SYSTEM
            .replace("{user_query}", user_query)
            .replace("{categories_summary}", categories_summary)
            .replace("{product_count}", str(product_count))
            .replace("{scenario_description}", scenario_description)
            .replace("{recent_queries}", recent_queries)
            .replace("{requirements}", requirements)
            .replace("{retrieval_results}", retrieval_results)
            .replace("{failed_categories}", failed_categories_str)
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请生成结束语和推荐选项"},
        ]

        logger.debug("option_gen prompt", prompt_len=len(prompt),
                     product_count=product_count)

        raw_response = await llm.chat(messages, temperature=0.3)

        start = raw_response.find("{")
        end = raw_response.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw_response[start:end])
            ending = data.get("ending", "")
            options = data.get("next_options", [])
        else:
            logger.warning("Option Gen 响应不含 JSON", raw=raw_response[:200])

        # 5. 通过 queue 发送 ending 事件
        if queue and ending:
            await queue.put({"event": "ending", "data": ending})

    except Exception as e:
        logger.warning("Option Gen 调用失败", error=str(e))

    # 截断到最多 3 条
    if len(options) > 3:
        options = options[:3]

    return {"next_options": options}
```

### F2c: `retriever.py` — 删除 `_generate_ending()`

**文件:** `server/app/agent/nodes/retriever.py`

#### Edit 1: 模块 docstring (line 11)
```
# Before
7. 结束语（LLM）+ ending 事件
8. Memory 更新（原始查询按品类追加到 session_memory）

# After
7. Memory 更新（原始查询按品类追加到 session_memory）
```

#### Edit 2: line 25 — 删除 ENDING_SYSTEM import
```python
# Before
    CATEGORY_INTRO_SYSTEM,
    PRODUCT_REASON_SYSTEM, ENDING_SYSTEM,

# After
    CATEGORY_INTRO_SYSTEM,
    PRODUCT_REASON_SYSTEM,
```

#### Edit 3: 删除 `_generate_ending()` (lines 320-373)

删除整个函数（54 行）。

#### Edit 4: `retrieval_node()` — 删除结束语调用 (lines 483-486)

```python
# Before
    # 4. 结束语
    ending_text = await _generate_ending(safe_results, requirements, llm, session_memory=state.get("session_memory"), user_query=state.get("rewritten_query") or state.get("user_query", ""))
    if queue and ending_text:
        await queue.put({"event": "ending", "data": ending_text})

    # 5. Memory 更新

# After
    # 4. Memory 更新
```

同时更新后续注释编号: `# 5.` → `# 4.`

### F2d: `show_prompt.py` — 删除 `ENDING_SYSTEM`

**文件:** `server/app/agent/prompts/show_prompt.py`

#### Edit: 删除 lines 69-91

```python
# Before (lines 69-91)
ENDING_SYSTEM = """你是一个电商导购助手。根据已完成的推荐，生成自然的结束语。
...
请生成结束语："""

# After
# (删除整个 ENDING_SYSTEM 块)
```

---

## 3. 测试更新

### `tests/test_agent_state.py`

所有 mock state 删除 `rewritten_query` 字段:

| 行号 | 改动 |
|---|---|
| 16, 42, 61, 81 | 删除 `rewritten_query="",` |
| 27 | 删除 `assert state["rewritten_query"] == ""` |

### `tests/test_router.py`

| 行号 | 改动 |
|---|---|
| 24, 40 | `assert "rewritten_query" in result` → `assert "welcome_text" in result` |
| 56-57 | 删除 `rewritten_query` 断言（chat 路径不再设置此字段） |

### `tests/test_extraction.py`

| 行号 | 改动 |
|---|---|
| 125, 156, 197 | mock state 中 `"rewritten_query"` → `"user_query"` |
| 173-174 | 测试名 `test_extraction_uses_rewritten_query` → `test_extraction_uses_user_query`；docstring 更新 |

### `tests/test_scenario_gen.py`

| 行号 | 改动 |
|---|---|
| 48, 69, 131 | mock state 中 `"rewritten_query"` → `"user_query"` |

### `tests/test_option_gen.py`

新增测试用例验证:
- `ending` 字段在 LLM 响应中被正确解析
- `ending` 事件通过 `_sse_queue` 发送
- `next_options` 仍然正确返回

### `tests/test_retriever.py`

- 删除 `_generate_ending` 相关测试
- 验证 `retrieval_node` 不再发送 `ending` 事件

---

## 4. 文档同步

### `server/docs/AGENT_OPT/GENERAL/SPEC.md`

- AgentState 表: 删除 `rewritten_query` 行
- Router 节点描述: 删除"查询改写"步骤
- Retriever 节点 I/O: 删除 `ending` 输出
- OptionGen 节点 I/O: 新增 `ending` 输出

### `delivery/API.md`

- AgentState 字段表: 删除 `rewritten_query`
- SSE 事件流: 标注 `ending` 由 option_gen_node 发送

---

## 5. 实现顺序

```
F1a (router.py: 删除 _rewrite_query, 清理 welcome 调用)
  → F1b (state.py: 删除字段)
    → F1c (search.py: 删除初始值)
      → F1d (extraction.py: 变量重命名)
        → F1e (scenario_gen.py: 变量重命名)
          → F1f (show_prompt.py: WELCOME_SYSTEM {rewritten_query}→{user_query})
            → F1g (删除 rewrite_prompt.py)
              → F2a (option_gen_prompt.py: 合并 prompt)
                → F2b (option_gen.py: 扩展节点)
                  → F2c (retriever.py: 删除 _generate_ending)
                    → F2d (show_prompt.py: 删除 ENDING_SYSTEM)
                      → 测试更新
                        → 文档同步
```

## 6. 验证检查清单

- [ ] `grep -rn "rewritten_query" server/app/` 返回空（零残留引用）
- [ ] `grep -rn "REWRITE_SYSTEM" server/app/` 返回空
- [ ] `grep -rn "_generate_ending" server/app/` 返回空
- [ ] `grep -rn "ENDING_SYSTEM" server/app/` 仅存在于 option_gen_prompt.py（新 `ENDING_OPTION_SYSTEM`）
- [ ] `rewrite_prompt.py` 文件已删除
- [ ] `python -m pytest tests/ -v` 全部通过, 无回归
- [ ] curl 手动验证: ending 事件由 option_gen_node 发送，出现在所有 product_reason 之后
- [ ] curl 手动验证: next_options 正常发送，done 事件收尾
