"""MCL-A4: Chit-Chat 节点测试。

验证 Chit-Chat 节点的输入输出，使用 mock LLM。
"""
import pytest
from unittest.mock import AsyncMock
from app.agent.nodes.chitchat import chitchat_node


@pytest.mark.asyncio
async def test_chitchat_returns_reply():
    """ChitChat 应返回 chat_reply 包含 LLM 生成的文本。"""
    mock_llm = AsyncMock()
    mock_llm.chat.return_value = "你好！我主要可以帮助您推荐和比较商品，有需要的话随时告诉我！"

    state = {
        "user_query": "你好",
        "conversation_history": [],
    }
    result = await chitchat_node(state, llm=mock_llm)

    assert "chat_reply" in result
    assert len(result["chat_reply"]) > 0


@pytest.mark.asyncio
async def test_chitchat_fallback_on_error():
    """LLM 失败时 ChitChat 应返回硬编码兜底消息。"""
    mock_llm = AsyncMock()
    mock_llm.chat.side_effect = Exception("LLM error")

    state = {
        "user_query": "你好",
        "conversation_history": [],
    }
    result = await chitchat_node(state, llm=mock_llm)

    assert "chat_reply" in result
    assert len(result["chat_reply"]) > 0
    assert "商品" in result["chat_reply"]  # fallback 消息提及服务范围
