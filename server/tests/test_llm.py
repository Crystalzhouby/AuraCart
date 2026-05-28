# tests/test_llm.py
"""使用 mock HTTP 测试 LLMService 的 chat 与 streaming 接口。

验证同步 chat 与异步 streaming 调用是否正确解析 LLM API 的响应，
并生成预期输出。
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.llm import LLMService


@pytest.mark.asyncio
async def test_chat_simple():
    """验证 chat() 通过 HTTP POST 发送消息并返回模型的文本响应。

    Mock 一个简单的 LLM 回复 "你好！"，并确认：
    - 函数返回模型的消息内容。
    - HTTP 客户端恰好被调用一次。
    """
    svc = LLMService(
        base_url="http://fake.api",
        api_key="fake-key",
        model="test-model",
    )

    # Mock 一个标准的 chat-completion 响应
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "你好！"}}]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        result = await svc.chat([{"role": "user", "content": "你好"}])

    assert result == "你好！"
    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_chat_stream():
    """验证 chat_stream() 从 Server-Sent Events（SSE）响应中逐 token 产出。

    模拟一个流式 LLM 响应，包含两个内容片段和一个 [DONE] 结束标记。
    预期按顺序产出 "你好" 和 "！" 两个内容 token。
    """
    svc = LLMService(
        base_url="http://fake.api",
        api_key="fake-key",
        model="test-model",
    )

    class FakeStream:
        """模拟 LLM provider 返回的 SSE 行异步迭代器。"""

        async def __aiter__(self):
            chunks = [
                'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n',
                'data: {"choices":[{"delta":{"content":"！"}}]}\n\n',
                'data: [DONE]\n\n',
            ]
            for c in chunks:
                yield c

    mock_resp = MagicMock()
    mock_resp.aiter_lines.return_value = FakeStream()

    with patch("httpx.AsyncClient.send", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_resp
        tokens = []
        async for token in svc.chat_stream([{"role": "user", "content": "你好"}]):
            tokens.append(token)

    # 流式输出应产出两个内容 token，不含 [DONE] 标记
    assert tokens == ["你好", "！"]
