"""MCL-A3: Router 节点测试。

验证 Unified Router 节点的输入输出，使用 mock LLM。
"""
import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agent.nodes.intent_route_agent import intent_route_node, _parse_route_response


@pytest.mark.asyncio
async def test_router_explicit():
    """Router 应将明确的商品需求路由为 explicit，并解析 welcome_chat。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": "帮你找到了几款蓝牙耳机～",
        "intent": "explicit",
    })

    state = {"user_query": "200元以下的蓝牙耳机"}
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "explicit"
    assert "welcome_text" in result
    assert "蓝牙耳机" in result["welcome_text"]


@pytest.mark.asyncio
async def test_router_scenario():
    """Router 应将场景化需求路由为 scenario，并解析 welcome_chat。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": "度假装备得备齐！帮你整理了几个品类～",
        "intent": "scenario",
    })

    state = {"user_query": "去三亚度假需要准备什么"}
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "scenario"
    assert "welcome_text" in result
    assert "度假" in result["welcome_text"]


@pytest.mark.asyncio
async def test_router_chat():
    """Router 应将非导购提问路由为 chat，chat 路径 welcome_text 为空。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": "你好呀！有什么想买的吗？",
        "intent": "chat",
    })

    state = {"user_query": "讲个笑话"}
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "chat"
    assert result["welcome_text"] == ""
    assert "chat_reply" in result
    assert len(result["chat_reply"]) >= 1


@pytest.mark.asyncio
async def test_router_fallback_on_llm_error():
    """LLM 调用失败时 fallback 为 explicit。"""
    mock_llm = AsyncMock()
    mock_llm.chat.side_effect = Exception("LLM connection error")

    state = {"user_query": "蓝牙耳机"}
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "explicit"


@pytest.mark.asyncio
async def test_router_fallback_on_bad_json():
    """LLM 返回无效 JSON 时 fallback 为 explicit。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = "这不是有效的 JSON"

    state = {"user_query": "蓝牙耳机"}
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "explicit"


# ---------------------------------------------------------------------------
# Router completion: enhanced JSON parsing robustness
# ---------------------------------------------------------------------------


def test_parse_route_response_markdown_fence():
    """_parse_route_response 应能处理 markdown 代码围栏包裹的 JSON。"""
    raw = '```json\n{"intent": "scenario"}\n```'
    result = _parse_route_response(raw)
    assert result["intent"] == "scenario"


def test_parse_route_response_trailing_comma():
    """_parse_route_response 应能处理 JSON 中的尾随逗号（常见 LLM 错误）。"""
    raw = '{"intent": "chat",}'
    result = _parse_route_response(raw)
    assert result["intent"] == "chat"


def test_parse_route_response_text_before_json():
    """_parse_route_response 应能从非 JSON 文本中提取 JSON 对象。"""
    raw = '分析结果如下：用户想要推荐商品。\n{"intent": "explicit"}'
    result = _parse_route_response(raw)
    assert result["intent"] == "explicit"


def test_parse_route_response_empty_returns_fallback():
    """_parse_route_response 在空字符串时应返回 fallback。"""
    result = _parse_route_response("")
    assert result == {"intent": "explicit"}


def test_parse_route_response_pure_text_returns_fallback():
    """_parse_route_response 在纯文本无 JSON 时应返回 fallback。"""
    result = _parse_route_response("这是纯文本回复，不包含任何 JSON 对象")
    assert result == {"intent": "explicit"}


def test_parse_route_response_unified_format():
    """_parse_route_response 应正确解析统一 prompt 的完整 JSON 输出。"""
    raw = '{"welcome_chat": "帮你找到了防晒霜～", "intent": "explicit"}'
    result = _parse_route_response(raw)
    assert result["intent"] == "explicit"
    assert result["welcome_chat"] == "帮你找到了防晒霜～"


@pytest.mark.asyncio
async def test_router_handles_markdown_fence_response():
    """Router 节点应处理 LLM 返回 markdown 代码围栏包裹的 JSON。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = '```json\n{"welcome_chat": "你好！", "intent": "chat"}\n```'

    state = {"user_query": "你好"}
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "chat"


# ---------------------------------------------------------------------------
# Streaming path tests
# ---------------------------------------------------------------------------


async def _async_gen(*items):
    """将多个字符串转为异步生成器。"""
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_router_stream_chat():
    """流式: chat 意图应推送 welcome_chat_stream (start/delta/end) + done。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.return_value = _async_gen(
        '{"welcome_chat": "你好', '呀！', '", "intent": "chat"', "}",
    )

    queue = asyncio.Queue()
    state = {
        "user_query": "你好",
        "stream": True,
        "_sse_queue": queue,
    }
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "chat"
    assert result["welcome_text"] == ""
    assert "chat_reply" in result
    assert len(result["chat_reply"]) >= 1

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert events[0] == {"event": "welcome_chat_stream", "data": {"type": "start"}}
    assert events[-2] == {"event": "welcome_chat_stream", "data": {"type": "end"}}
    assert events[-1] == {"event": "done", "data": {}}


@pytest.mark.asyncio
async def test_router_stream_explicit():
    """流式: explicit 意图应推送 welcome_chat_stream 但不发送 done。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.return_value = _async_gen(
        '{"welcome_chat": "帮你找到了！', '", "intent": "explicit"', "}",
    )

    queue = asyncio.Queue()
    state = {
        "user_query": "推荐一款防晒霜",
        "stream": True,
        "_sse_queue": queue,
    }
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "explicit"
    assert "帮你找到了" in result["welcome_text"]

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert events[0] == {"event": "welcome_chat_stream", "data": {"type": "start"}}
    assert events[-1] == {"event": "welcome_chat_stream", "data": {"type": "end"}}
    assert not any(e["event"] == "done" for e in events)


@pytest.mark.asyncio
async def test_router_stream_scenario():
    """流式: scenario 意图应推送 welcome_chat_stream 但不发送 done。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.return_value = _async_gen(
        '{"welcome_chat": "度假装备要备齐～', '", "intent": "scenario"', "}",
    )

    queue = asyncio.Queue()
    state = {
        "user_query": "去三亚需要带什么",
        "stream": True,
        "_sse_queue": queue,
    }
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "scenario"
    assert "度假" in result["welcome_text"]

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert not any(e["event"] == "done" for e in events)


# ---------------------------------------------------------------------------
# Non-streaming path tests (with queue)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_nonstream_chat_sends_chat_reply_and_done():
    """非流式 chat: 应发送 chat_reply + done SSE 事件。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": "你好！有需要随时找我～",
        "intent": "chat",
    })

    queue = asyncio.Queue()
    state = {
        "user_query": "你好",
        "stream": False,
        "_sse_queue": queue,
    }
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "chat"
    assert result["welcome_text"] == ""
    assert "chat_reply" in result
    assert len(result["chat_reply"]) >= 1

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert events[0] == {"event": "chat_reply", "data": "你好！有需要随时找我～"}
    assert events[1] == {"event": "done", "data": {}}


@pytest.mark.asyncio
async def test_router_blocks_unsupported_order_action_before_llm():
    """订单/支付类能力边界请求应确定性拦截，不调用 LLM，不进入检索链路。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": "你还没告诉我想买什么商品哦～",
        "intent": "explicit",
    })

    queue = asyncio.Queue()
    state = {
        "user_query": "帮我直接下单",
        "stream": False,
        "_sse_queue": queue,
    }
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "chat"
    assert result["welcome_text"] == ""
    assert "没法直接帮你下单" in result["chat_reply"]
    mock_llm.chat.assert_not_called()

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert events[0]["event"] == "chat_reply"
    assert "下单" in events[0]["data"]
    assert events[1] == {"event": "done", "data": {}}


@pytest.mark.asyncio
async def test_router_blocks_unsupported_after_sales_action_before_llm():
    """客服/退货类能力边界请求应确定性拦截，不调用 LLM。"""
    mock_llm = AsyncMock()

    queue = asyncio.Queue()
    state = {
        "user_query": "你能替我联系客服退货吗",
        "stream": False,
        "_sse_queue": queue,
    }
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "chat"
    assert "售后" in result["chat_reply"]
    mock_llm.chat.assert_not_called()


@pytest.mark.asyncio
async def test_router_handles_ambiguous_pregnancy_caffeine_question_as_chat():
    """无上下文的孕期咖啡因安全咨询由 Router 判为 chat 并先澄清具体商品。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": (
            "需要先确认你说的是哪款具体商品。孕期咖啡因通常建议每日总量不超过200mg，"
            "特殊情况请遵医嘱。"
        ),
        "intent": "chat",
    })

    queue = asyncio.Queue()
    state = {
        "user_query": "孕妇可以喝这款咖啡吗",
        "stream": False,
        "_sse_queue": queue,
        "session_memory": [],
    }
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "chat"
    assert result["welcome_text"] == ""
    mock_llm.chat.assert_called_once()

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert events[0]["event"] == "chat_reply"
    assert "具体商品" in events[0]["data"]
    assert "不超过200mg" in events[0]["data"]
    assert events[1] == {"event": "done", "data": {}}


@pytest.mark.asyncio
async def test_router_nonstream_explicit_sends_welcome():
    """非流式 explicit: 应发送 welcome SSE 事件。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = json.dumps({
        "welcome_chat": "帮你找到了防晒霜～",
        "intent": "explicit",
    })

    queue = asyncio.Queue()
    state = {
        "user_query": "推荐一款防晒霜",
        "stream": False,
        "_sse_queue": queue,
    }
    result = await intent_route_node(state, llm=mock_llm)

    assert result["intent"] == "explicit"
    assert result["welcome_text"] == "帮你找到了防晒霜～"

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert events[0] == {"event": "welcome", "data": "帮你找到了防晒霜～"}
    assert not any(e["event"] == "done" for e in events)


# ---------------------------------------------------------------------------
# HISTORY_OPT: prompt 时间关注度提示
# ---------------------------------------------------------------------------

def test_router_prompt_has_time_hint():
    """INTENT_ROUTER_SYSTEM 应包含时间关注度提示。"""
    from app.agent.prompts.intent_router_prompt import INTENT_ROUTER_SYSTEM
    assert "越近的对话越重要" in INTENT_ROUTER_SYSTEM


def test_router_prompt_has_ambiguous_reference_boundary():
    """Router prompt 应要求无上下文指代问题先澄清，不推荐商品。"""
    from app.agent.prompts.intent_router_prompt import INTENT_ROUTER_SYSTEM
    assert "缺少明确商品上下文的指代咨询" in INTENT_ROUTER_SYSTEM
    assert "这款" in INTENT_ROUTER_SYSTEM
    assert "先要求确认具体商品" in INTENT_ROUTER_SYSTEM
    assert "不能推荐商品" in INTENT_ROUTER_SYSTEM
    assert "不限于安全问题" in INTENT_ROUTER_SYSTEM
