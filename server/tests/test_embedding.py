# tests/test_embedding.py
"""使用 mock HTTP 响应测试 EmbeddingService。

验证单文本与批量 embedding 调用，确保服务正确解析 API 响应
并调用 HTTP 层。
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.embedding_service import EmbeddingService


@pytest.mark.asyncio
async def test_embed_single_text():
    """验证 embed() 发送单条文本并返回正确的 embedding 向量。

    Mock httpx.AsyncClient.post 以返回预设的 [0.1, 0.2, 0.3] 向量，
    并确认：
    - 返回的向量与 mock 响应一致。
    - HTTP 客户端恰好被调用一次。
    """
    svc = EmbeddingService(
        base_url="http://fake.api",
        api_key="fake-key",
        model="test-model",
    )

    # Mock 原始 HTTP 响应
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [{"embedding": [0.1, 0.2, 0.3]}]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await svc.embed("测试文本")

    # 断言向量匹配且 post 仅调用一次
    assert result == [0.1, 0.2, 0.3]
    mock_post.assert_called_once()


@pytest.mark.asyncio
async def test_embed_batch():
    """验证 embed_batch() 发送多条文本并返回所有 embedding 向量。

    Mock HTTP 层返回两个 embedding，并确认：
    - 结果列表长度正确。
    - 每个向量按顺序与 mock 响应匹配。
    """
    svc = EmbeddingService(
        base_url="http://fake.api",
        api_key="fake-key",
        model="test-model",
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"embedding": [0.1, 0.2]},
            {"embedding": [0.3, 0.4]},
        ]
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        results = await svc.embed_batch(["文本1", "文本2"])

    assert len(results) == 2
    assert results[0] == [0.1, 0.2]
    assert results[1] == [0.3, 0.4]
