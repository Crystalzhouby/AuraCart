"""MCL-A4: Chit-Chat 节点测试。

验证 Chit-Chat 节点的输入输出，使用 mock LLM。
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agent.nodes.chitchat import chitchat_node


async def _async_gen(*items):
    """将多个字符串转为异步生成器。"""
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_chitchat_returns_reply():
    """ChitChat 应使用流式调用并返回 chat_reply。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.return_value = _async_gen(
        "你好！", "我主要可以帮助您推荐和比较商品，", "有需要的话随时告诉我！"
    )

    state = {
        "user_query": "你好",
        
    }
    result = await chitchat_node(state, llm=mock_llm)

    assert "chat_reply" in result
    assert len(result["chat_reply"]) > 0
    assert "商品" in result["chat_reply"]


@pytest.mark.asyncio
async def test_chitchat_fallback_on_error():
    """LLM 失败时 ChitChat 应返回硬编码兜底消息。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.side_effect = Exception("LLM error")

    state = {
        "user_query": "你好",
        
    }
    result = await chitchat_node(state, llm=mock_llm)

    assert "chat_reply" in result
    assert len(result["chat_reply"]) > 0
    assert "商品" in result["chat_reply"]  # fallback 消息提及服务范围


@pytest.mark.asyncio
async def test_chitchat_sends_sse_chat_reply_event():
    """非流式模式: ChitChat 应通过 _sse_queue 发送 chat_reply SSE 事件。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.return_value = _async_gen("你好！", "有需要随时告诉我！")

    queue = asyncio.Queue()
    state = {
        "user_query": "你好",
        "stream": False,
        "_sse_queue": queue,
    }
    await chitchat_node(state, llm=mock_llm)

    # 验证 SSE 事件已发送
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert len(events) >= 1
    assert events[0]["event"] == "chat_reply"
    assert len(events[0]["data"]) > 0


@pytest.mark.asyncio
async def test_chitchat_sends_stream_events():
    """流式模式: ChitChat 应推送 chat_reply_stream (start → delta* → end) + done。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.return_value = _async_gen("你好！", "有需要随时告诉我！")

    queue = asyncio.Queue()
    state = {
        "user_query": "你好",
        "stream": True,
        "_sse_queue": queue,
    }
    await chitchat_node(state, llm=mock_llm)

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert events[0] == {"event": "chat_reply_stream", "data": {"type": "start"}}
    assert events[1] == {"event": "chat_reply_stream", "data": {"type": "delta", "text": "你好！"}}
    assert events[2] == {"event": "chat_reply_stream", "data": {"type": "delta", "text": "有需要随时告诉我！"}}
    assert events[3] == {"event": "chat_reply_stream", "data": {"type": "end"}}
    assert events[4] == {"event": "done", "data": {}}


@pytest.mark.asyncio
async def test_chitchat_no_sse_when_no_queue():
    """没有 _sse_queue 时 ChitChat 应正常工作不抛异常。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.return_value = _async_gen("你好！")

    state = {
        "user_query": "你好",
        
    }
    result = await chitchat_node(state, llm=mock_llm)

    assert "chat_reply" in result
    assert result["chat_reply"] == "你好！"


@pytest.mark.asyncio
async def test_chitchat_handles_empty_stream_response():
    """chat_stream 返回空内容时 ChitChat 应使用 fallback。"""
    mock_llm = MagicMock()
    mock_llm.chat_stream.return_value = _async_gen()  # 空生成器

    state = {
        "user_query": "测试",
        
    }
    result = await chitchat_node(state, llm=mock_llm)

    assert "chat_reply" in result
    # 空响应应触发 fallback
    assert len(result["chat_reply"]) > 0
