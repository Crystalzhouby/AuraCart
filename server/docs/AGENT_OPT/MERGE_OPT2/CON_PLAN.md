# MERGE_OPT2 — 编码级实现方案

> 输入: `server/docs/AGENT_OPT/MERGE_OPT2/PLAN.md`
> 输出: `server/docs/AGENT_OPT/MERGE_OPT2/CON_PLAN.md`

## F1: 新建 unified_router_prompt.py

**文件:** `server/app/agent/prompts/unified_router_prompt.py` — **新建**

**操作:** 创建统一提示词 `UNIFIED_ROUTER_SYSTEM`，合并 ROUTER_SYSTEM + CHITCHAT_SYSTEM + WELCOME_SYSTEM。

```python
"""统一 Router 提示词模板 — 合并意图分类 + 闲聊 + 欢迎语。"""

UNIFIED_ROUTER_SYSTEM = """# 角色
你是一个专业的电商导购助手，需要同时完成两项任务：判断用户意图和生成自然回复。

# 任务 1: 意图分类
判断用户当前查询的意图类型（三选一）：
- chat: 非购物/商品/导购问题（聊天、问候、笑话、天气等）。
- explicit: 明确商品/品类/品牌/价格/功效/规格/对比/替代需求，可直接检索商品。
- scenario: 场景/任务/人群/行程需求，需要先拆多个商品品类。

分类示例：
- "怕晒黑怎么办""油皮用什么防晒""200元以下防晒""有没有好用的眼霜" → explicit
- "去三亚旅游要准备什么""开学宿舍要买什么""露营装备清单" → scenario
- "你好""讲个笑话""今天天气怎么样" → chat

# 任务 2: 回复生成
根据意图类型生成对应的 welcome_chat 内容：

**当意图为 chat 时（闲聊回复规则）：**
- 先回应用户情绪或语境，语气自然亲切。
- 50字内，不说教，不硬推销。
- 不编造信息，不推荐具体商品。
- 只有合适时，轻轻带到生活用品或选购建议。

**当意图为 explicit 或 scenario 时（欢迎语规则）：**
- 结合对话历史理解用户当前意图，欢迎语与上下文之间不要存在断裂感。
- 单品类时突出品类特点和用户需求，如"不含酒精的防晒对敏感肌超友好！帮你挑了几款口碑好、温和不刺激的。"
- 多品类时突出场景感，提及品类数量，如"海边度假装备得备齐！结合你的出游场景，帮你整理了几个超实用的品类～"
- 语气口语化、亲切，像朋友聊天。
- 一句话即可，不超过 60 字。
- 不要使用"亲爱的用户""欢迎光临"等客服腔。
- 不要编造商品名或具体品牌。

# 输出格式
只返回 JSON，不要输出解释。注意：welcome_chat 字段必须排在 intent 字段前面。

{"welcome_chat": "<回复内容（闲聊或欢迎语）>", "intent": "chat|explicit|scenario"}

# 对话历史
{recent_queries}

# 当前用户查询
{user_query}

请输出 JSON："""
```

**检查点:**
- [ ] `welcome_chat` 字段在 JSON 中排在 `intent` 前面
- [ ] 包含完整的分类示例（来自 ROUTER_SYSTEM）
- [ ] 包含闲聊风格规则（来自 CHITCHAT_SYSTEM）
- [ ] 包含欢迎语规则（来自 WELCOME_SYSTEM）
- [ ] 占位符 `{user_query}` 和 `{recent_queries}` 正确

---

## F2: 重写 router.py — 单次 LLM + SSE 发送

**文件:** `server/app/agent/nodes/router.py`

### Edit 1: 模块 docstring (lines 1-7)

```python
# Before
"""
Intent Router 节点 — 工作流第一个节点。

单次三分类 + 欢迎语生成：
1. 意图分类: chat（闲聊）/ explicit（明确商品需求）/ scenario（场景化推荐）
2. 若为 explicit 或 scenario，生成欢迎语（基于 user_query + 对话历史）。
"""

# After
"""
Intent Router 节点 — 工作流第一个节点，统一入口。

单次 LLM 完成意图分类 + 回复生成：
- chat: 生成闲聊回复 + SSE 推送 + done 事件
- explicit/scenario: 生成欢迎语 + SSE 推送
"""
```

### Edit 2: imports (lines 8-16)

```python
# Before
import json
import re
import structlog
from app.config import settings
from app.agent.prompts.router_prompt import ROUTER_SYSTEM

from app.agent.prompts.show_prompt import WELCOME_SYSTEM
from app.agent.memory import get_recent_queries
from app.services.llm_service import LLMService

# After
import json
import re
import structlog
from app.config import settings
from app.agent.prompts.unified_router_prompt import UNIFIED_ROUTER_SYSTEM
from app.agent.prompts.show_prompt import WELCOME_SYSTEM  # 保留 — 非流式路径仍可能用到
from app.agent.memory import get_recent_queries
from app.services.llm_service import LLMService
```

> 注意: WELCOME_SYSTEM 保留仅因非流式 fallback 路径在 prompt 中仍有引用。实际上非流式路径也改用 UNIFIED_ROUTER_SYSTEM，所以最终不会用到 WELCOME_SYSTEM。为了保守起见，在 F2 中保留 import 不变，F6 删除 show_prompt.py 中的 WELCOME_SYSTEM 时再同步删除此 import。

**修正:** 非流式路径和流式路径使用同一个 `UNIFIED_ROUTER_SYSTEM`，因此 `WELCOME_SYSTEM` import 不再需要。

```python
# After (final)
import json
import re
import structlog
from app.config import settings
from app.agent.prompts.unified_router_prompt import UNIFIED_ROUTER_SYSTEM
from app.agent.memory import get_recent_queries
from app.services.llm_service import LLMService
```

### Edit 3: 删除 `_generate_welcome()` 函数 (lines 79-113)

删除整个函数（35 行）。

```python
# Before (lines 79-113)
async def _generate_welcome(
    user_query: str,
    recent_queries: list[dict],
    scenario_description: str,
    llm,
) -> str:
    """在 router 节点生成欢迎词。基于当前查询+对话历史。"""
    ...
```

### Edit 4: 重写 `router_node()` (lines 116-195)

完整重写，替换整个函数体。

**新函数签名不变:** `async def router_node(state: dict, llm: LLMService, _sse_queue=None) -> dict:`

```python
async def router_node(state: dict, llm: LLMService, _sse_queue=None) -> dict:
    """Intent Router 节点函数 — 统一入口。

    单次 LLM 调用完成分类 + 回复生成：
    1. 构建 UNIFIED_ROUTER_SYSTEM prompt
    2. 流式路径: stream_json_field 提取 welcome_chat 逐 token 推送
    3. 非流式路径: 同步 LLM → 解析 JSON → 发送对应事件

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。
        _sse_queue: 可选，asyncio.Queue，用于 SSE 推送。

    返回值:
        dict: {"intent", "welcome_text"}
    """
    user_query = state.get("user_query", "")
    session_memory = state.get("session_memory", [])
    stream = state.get("stream", True)
    queue = _sse_queue or state.get("_sse_queue")

    # ---- 构建 prompt ----
    n_rounds = settings.search.memory_recent_rounds
    recent_queries = get_recent_queries(session_memory, n_rounds)
    history_text = _format_recent_queries(recent_queries)
    prompt = (UNIFIED_ROUTER_SYSTEM
              .replace("{user_query}", user_query)
              .replace("{recent_queries}", history_text))
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    # ---- LLM 调用 + 流式推送 ----
    if stream and queue:
        # 流式路径: stream_json_field 提取 welcome_chat 逐 token 推送
        from app.agent.utils.stream_json import stream_json_field

        welcome_chat = ""
        intent = "explicit"

        try:
            await queue.put({"event": "welcome_chat_stream", "data": {"type": "start"}})

            async def _on_delta(ch: str):
                await queue.put({"event": "welcome_chat_stream", "data": {"type": "delta", "text": ch}})

            token_stream = llm.chat_stream(messages, temperature=0.1)
            _stream_events, parsed = await stream_json_field(token_stream, "welcome_chat", on_delta=_on_delta)

            await queue.put({"event": "welcome_chat_stream", "data": {"type": "end"}})

            if parsed:
                intent = parsed.get("intent", "explicit")
                welcome_chat = parsed.get("welcome_chat", "")
        except Exception as e:
            logger.warning("Unified Router 流式调用失败", error=str(e))
            welcome_chat = ""
            intent = "explicit"

        # chat 路径: 发送 done → 结束
        if intent == "chat":
            await queue.put({"event": "done", "data": {}})
            return {"intent": "chat", "welcome_text": ""}

        # explicit/scenario 路径: 继续后续链
        return {"intent": intent, "welcome_text": welcome_chat}

    else:
        # 非流式路径: 同步 LLM → 解析 JSON
        welcome_chat = ""
        intent = "explicit"

        try:
            raw = await llm.chat(messages, temperature=0.1)
            parsed = _parse_router_response(raw)
            intent = parsed.get("intent", "explicit")
            welcome_chat = parsed.get("welcome_chat", "")
        except Exception as e:
            logger.warning("Unified Router LLM 调用失败", error=str(e))
            welcome_chat = ""
            intent = "explicit"

        # chat 路径: chat_reply + done
        if intent == "chat":
            if queue:
                await queue.put({"event": "chat_reply", "data": welcome_chat or "我主要可以帮助您推荐和比较商品，有需要的话随时告诉我！"})
                await queue.put({"event": "done", "data": {}})
            return {"intent": "chat", "welcome_text": ""}

        # explicit/scenario 路径: welcome 事件
        if queue and welcome_chat:
            await queue.put({"event": "welcome", "data": welcome_chat})

        return {"intent": intent, "welcome_text": welcome_chat}
```

**关键逻辑说明:**

| 路径 | 流式 | 事件 | 行为 |
|---|---|---|---|
| chat | stream | `welcome_chat_stream` (start/delta/end) → `done` | router 直接结束 graph |
| chat | non-stream | `chat_reply` → `done` | router 直接结束 graph |
| explicit/scenario | stream | `welcome_chat_stream` (start/delta/end) | 继续 extraction/scenario_gen |
| explicit/scenario | non-stream | `welcome` | 继续 extraction/scenario_gen |

**`_parse_router_response` 兼容性:** 无需改动。该函数解析完整 JSON 对象，当新 prompt 输出 `{"welcome_chat": "...", "intent": "..."}` 时，解析结果自然包含两个字段。默认值 `{"intent": "explicit"}` 保持不变作为 fallback。

**非流式 chat fallback:** 当 `welcome_chat` 为空时，使用 `FALLBACK_REPLY`（从 chitchat.py 迁移）作为兜底回复。

**检查点:**
- [ ] `WELCOME_SYSTEM` import 已删除
- [ ] `_generate_welcome()` 已删除
- [ ] 新增 `stream_json_field` import
- [ ] `UNIFIED_ROUTER_SYSTEM` import 正确
- [ ] `_parse_router_response()` 保留不动
- [ ] `_format_recent_queries()` 保留不动

---

## F3: 删除旧文件

### F3a: 删除 `chitchat.py`

**文件:** `server/app/agent/nodes/chitchat.py` → **删除**

**迁移内容:**
- `FALLBACK_REPLY` 常量 inline 到 `router_node` 非流式 fallback 路径

### F3b: 删除 `chitchat_prompt.py`

**文件:** `server/app/agent/prompts/chitchat_prompt.py` → **删除**

### F3c: 删除 `router_prompt.py`

**文件:** `server/app/agent/prompts/router_prompt.py` → **删除**

---

## F4: 更新 graph.py

**文件:** `server/app/agent/graph.py`

### Edit 1: 模块 docstring (lines 1-5)

```python
# Before
"""
StateGraph 构建模块 — 将 6 个 Agent 节点组装为 LangGraph 工作流。

条件边路由：Intent Router → ChitChat / Extraction / Scenario Gen，
两条推荐路径在 retrieval 处汇合。
"""

# After
"""
StateGraph 构建模块 — 将 5 个 Agent 节点组装为 LangGraph 工作流。

条件边路由：Unified Router 直接输出 chat（→ END）/ explicit（→ Extraction）/ scenario（→ Scenario Gen），
两条推荐路径在 retrieval 处汇合。
"""
```

### Edit 2: imports (lines 9-16)

```python
# Before
from app.agent.nodes.router import router_node
from app.agent.nodes.extraction import extraction_node
from app.agent.nodes.scenario_gen import scenario_gen_node
from app.agent.nodes.retriever import retrieval_node
from app.agent.nodes.option_gen import option_gen_node
from app.agent.nodes.chitchat import chitchat_node

# After
from app.agent.nodes.router import router_node
from app.agent.nodes.extraction import extraction_node
from app.agent.nodes.scenario_gen import scenario_gen_node
from app.agent.nodes.retriever import retrieval_node
from app.agent.nodes.option_gen import option_gen_node
# chitchat_node 已删除 — 功能合并到 router_node
```

### Edit 3: `route_intent()` — 路由目标 (lines 47-65)

```python
# Before
def route_intent(state: AgentState) -> str:
    intent = state.get("intent", "explicit")
    if intent == "chat":
        target = "chitchat"
    elif intent == "scenario":
        target = "scenario_gen"
    else:
        target = "extraction"
    logger.debug("route_intent 路由决策", intent=intent, target=target)
    return target

# After
def route_intent(state: AgentState) -> str:
    intent = state.get("intent", "explicit")
    if intent == "chat":
        target = "chat"
    elif intent == "scenario":
        target = "scenario_gen"
    else:
        target = "extraction"
    logger.debug("route_intent 路由决策", intent=intent, target=target)
    return target
```

### Edit 4: 删除 `_chitchat` wrapper (lines 90-94)

```python
# Before
    async def _chitchat(state: AgentState) -> dict:
        logger.debug("chitchat 输入", state=_preview(state))
        result = await chitchat_node(state, llm=llm)
        logger.debug("chitchat 输出", result=_preview(result))
        return result

# After
# (删除整个 wrapper)
```

### Edit 5: 删除 chitchat 节点注册 (line 133)

```python
# Before
    graph.add_node("chitchat", _chitchat)

# After
# (删除整行)
```

### Edit 6: 更新条件边 (lines 142-150)

```python
# Before
    graph.add_conditional_edges(
        "router",
        route_intent,
        {
            "chitchat": "chitchat",
            "extraction": "extraction",
            "scenario_gen": "scenario_gen",
        },
    )

# After
    graph.add_conditional_edges(
        "router",
        route_intent,
        {
            "chat": END,
            "extraction": "extraction",
            "scenario_gen": "scenario_gen",
        },
    )
```

### Edit 7: 删除 chitchat → END 边 (line 152)

```python
# Before
    graph.add_edge("chitchat", END)

# After
# (删除整行)
```

**检查点:**
- [ ] `from app.agent.nodes.chitchat import chitchat_node` 已删除
- [ ] `_chitchat` wrapper 已删除
- [ ] `graph.add_node("chitchat", ...)` 已删除
- [ ] `graph.add_edge("chitchat", END)` 已删除
- [ ] 条件边 `"chat": END` 正确
- [ ] `route_intent` 测试期望值更新

---

## F5: 更新 retriever.py — 删除 welcome 发送

**文件:** `server/app/agent/nodes/retriever.py`

### Edit 1: 模块 docstring (lines 1-12)

```python
# Before
"""
Product Retrieval 节点。

流水线：
1. 欢迎语（由 router 节点生成，从 state 读取）
2. 按品类分组检索（requirements 已按品类分组）
...
"""

# After
"""
Product Retrieval 节点。

流水线：
1. 按品类分组检索（requirements 已按品类分组）
...
"""
```

### Edit 2: 删除 welcome 发送代码块 (lines 344-348)

```python
# Before
    # 1. 欢迎语（仅非流式模式: Router 已写入 state，此处读取并发送）
    if not stream:
        welcome_text = state.get("welcome_text", "")
        if queue and welcome_text:
            await queue.put({"event": "welcome", "data": welcome_text})

    # 2. 并行检索

# After
    # 1. 并行检索
```

### Edit 3: 更新后续注释编号

line 350 `# 2. 并行检索` → `# 1. 并行检索`
line 375 `# 3. SSE 逐品类` → `# 2. SSE 逐品类`
line 450 `# 4. Memory 更新` → `# 3. Memory 更新`

---

## F6: 更新 show_prompt.py — 删除 WELCOME_SYSTEM

**文件:** `server/app/agent/prompts/show_prompt.py`

### Edit 1: 模块 docstring (line 1)

```python
# Before
"""SSE 展示流提示词模板 — 欢迎语 / 品类介绍 / 单商品推荐 / 结束语。"""

# After
"""SSE 展示流提示词模板 — 品类介绍 / 单商品推荐。"""
```

### Edit 2: 删除 WELCOME_SYSTEM (lines 3-24)

删除从 line 3 (`WELCOME_SYSTEM = """...`) 到 line 24 (`请生成欢迎语："""`) 的完整块（22 行）。

```python
# Before (lines 3-24)
WELCOME_SYSTEM = """你是一个电商导购助手。根据用户当前查询和对话历史，生成一句自然的欢迎语。
...
请生成欢迎语："""

# After
# (删除整个 WELCOME_SYSTEM 块)
#
# CATEGORY_INTRO_SYSTEM 紧随其后
```

---

## 7. 测试更新

### `tests/test_chitchat.py` — **删除**

### `tests/test_router.py` — 扩展

#### Edit 1: import (line 8)

```python
# Before
from app.agent.nodes.router import router_node, _parse_router_response

# After
from app.agent.nodes.router import router_node, _parse_router_response, _format_recent_queries
```

#### Edit 2: 新增测试 — 验证统一 prompt 输出解析

```python
@pytest.mark.asyncio
async def test_router_unified_prompt_explicit():
    """Router 应正确解析统一 prompt 的 JSON 输出（explicit）。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": "帮你找了几款防晒霜，都是清爽不油腻的类型～",
        "intent": "explicit",
    })

    state = {"user_query": "推荐一款防晒霜"}
    result = await router_node(state, llm=mock_llm)

    assert result["intent"] == "explicit"
    assert "防晒霜" in result["welcome_text"]


@pytest.mark.asyncio
async def test_router_unified_prompt_chat():
    """Router 应正确解析统一 prompt 的 JSON 输出（chat + welcome_chat 为闲聊）。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": "你好呀！有什么想买的吗，我帮你挑挑～",
        "intent": "chat",
    })

    state = {"user_query": "你好"}
    result = await router_node(state, llm=mock_llm)

    assert result["intent"] == "chat"
    assert result["welcome_text"] == ""


@pytest.mark.asyncio
async def test_router_unified_prompt_scenario():
    """Router 应正确解析统一 prompt 的 JSON 输出（scenario）。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": "海边度假装备得备齐！帮你整理了几个超实用的品类～",
        "intent": "scenario",
    })

    state = {"user_query": "去三亚需要带什么"}
    result = await router_node(state, llm=mock_llm)

    assert result["intent"] == "scenario"
    assert "海边" in result["welcome_text"]
```

#### Edit 3: 更新现有测试

原有测试 `test_router_explicit`, `test_router_scenario`, `test_router_chat` 的 mock LLM 返回格式改为新的 JSON 结构（添加 `welcome_chat` 字段）：

```python
# test_router_explicit — mock LLM 返回更新
mock_llm.chat.return_value = json.dumps({"welcome_chat": "帮你找到了相关商品～", "intent": "explicit"})

# test_router_scenario — mock LLM 返回更新
mock_llm.chat.return_value = json.dumps({"welcome_chat": "整理了相关品类～", "intent": "scenario"})

# test_router_chat — mock LLM 返回更新
mock_llm.chat.return_value = json.dumps({"welcome_chat": "你好！有需要随时找我～", "intent": "chat"})
```

#### Edit 4: 新增流式路径测试

```python
@pytest.mark.asyncio
async def test_router_stream_chat():
    """流式路径: chat 意图应推送 welcome_chat_stream + done。"""
    mock_llm = AsyncMock()
    async def _mock_stream():
        for ch in '{"welcome_chat": "你好', '呀！', '", "intent": "chat"', "}":
            yield ch
    mock_llm.chat_stream.return_value = _mock_stream()

    queue = asyncio.Queue()
    state = {
        "user_query": "你好",
        "stream": True,
        "_sse_queue": queue,
    }
    result = await router_node(state, llm=mock_llm)

    assert result["intent"] == "chat"
    assert result["welcome_text"] == ""

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert events[0] == {"event": "welcome_chat_stream", "data": {"type": "start"}}
    assert events[-2] == {"event": "welcome_chat_stream", "data": {"type": "end"}}
    assert events[-1] == {"event": "done", "data": {}}


@pytest.mark.asyncio
async def test_router_stream_explicit():
    """流式路径: explicit 意图应推送 welcome_chat_stream 但不发送 done。"""
    mock_llm = AsyncMock()
    async def _mock_stream():
        for ch in '{"welcome_chat": "帮你找到了！', '", "intent": "explicit"', "}":
            yield ch
    mock_llm.chat_stream.return_value = _mock_stream()

    queue = asyncio.Queue()
    state = {
        "user_query": "推荐一款防晒霜",
        "stream": True,
        "_sse_queue": queue,
    }
    result = await router_node(state, llm=mock_llm)

    assert result["intent"] == "explicit"
    assert "帮你找到了" in result["welcome_text"]

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert events[0] == {"event": "welcome_chat_stream", "data": {"type": "start"}}
    assert events[-1] == {"event": "welcome_chat_stream", "data": {"type": "end"}}
    # 推荐路径不应有 done 事件
    assert not any(e["event"] == "done" for e in events)
```

### `tests/test_graph.py` — 更新

#### Edit 1: `test_route_intent_chat()` (lines 15-19)

```python
# Before
def test_route_intent_chat():
    """route_intent 应将 intent=chat 路由到 chitchat。"""
    from app.agent.graph import route_intent
    state = {"intent": "chat"}
    assert route_intent(state) == "chitchat"

# After
def test_route_intent_chat():
    """route_intent 应将 intent=chat 路由到 'chat' (→ END)。"""
    from app.agent.graph import route_intent
    state = {"intent": "chat"}
    assert route_intent(state) == "chat"
```

#### Edit 2: `test_build_graph_registers_six_nodes()` (lines 43-56)

```python
# Before
async def test_build_graph_registers_six_nodes():
    """build_graph 应向 StateGraph 注册 6 个节点。"""

# After
async def test_build_graph_registers_five_nodes():
    """build_graph 应向 StateGraph 注册 5 个节点（post-chitchat 删除）。"""
```

---

## 8. 验证检查清单

完成后逐项确认：

- [ ] `grep -rn "chitchat_node" server/app/` 返回空
- [ ] `grep -rn "ROUTER_SYSTEM" server/app/` 仅存在于 `unified_router_prompt.py`
- [ ] `grep -rn "CHITCHAT_SYSTEM" server/app/` 仅存在于 `unified_router_prompt.py`
- [ ] `grep -rn "WELCOME_SYSTEM" server/app/` 返回空（已迁移到 unified_router_prompt.py）
- [ ] `grep -rn "from app.agent.nodes.chitchat" server/app/` 返回空
- [ ] `grep -rn "from app.agent.prompts.router_prompt" server/app/` 返回空
- [ ] `grep -rn "from app.agent.prompts.chitchat_prompt" server/app/` 返回空
- [ ] `chitchat.py` 文件已删除
- [ ] `chitchat_prompt.py` 文件已删除
- [ ] `router_prompt.py` 文件已删除
- [ ] `python -m pytest tests/test_router.py tests/test_graph.py -v` 全部通过
- [ ] `python -m pytest tests/ -v --ignore=tests/test_e2e.py` 全部通过（离线测试，183+ 个）

---

## 9. 实现顺序

```
F1 (新建 unified_router_prompt.py)
  → F2 (重写 router.py: import + 删除 _generate_welcome + 重写 router_node)
    → F3a (删除 chitchat.py)
    → F3b (删除 chitchat_prompt.py)
    → F3c (删除 router_prompt.py)
      → F4 (graph.py: 5 处编辑)
        → F5 (retriever.py: 删除 welcome 发送块 + 注释编号更新)
          → F6 (show_prompt.py: 删除 WELCOME_SYSTEM)
            → 测试更新 (test_router.py 扩展 + test_chitchat.py 删除 + test_graph.py 更新)
              → 全量测试验证
```

**顺序理由:** F1 创建新提示词（无依赖），F2 切换 router 到新提示词（依赖 F1），F3 删除旧文件（依赖 F2 确保无引用），F4 更新 graph（依赖 F3 无 import 错误），F5-F6 清理残留（依赖 F2 确保功能正确）。
