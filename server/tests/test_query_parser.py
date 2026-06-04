# tests/test_query_parser.py
"""测试 QueryParser 服务：将 LLM 响应解析为 SubQuery 实例。

QueryParser 借助 LLM 将自然语言商品查询翻译为结构化的 SubQuery
对象，包含 keyword、semantic、structured_filter 等策略。
negation 字段已移除，否定语义由 operator 值表达。
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.query_parser_service import QueryParser, SubQuery


def test_parse_llm_response():
    """验证 _parse_response() 将 JSON 格式的 LLM 输出解码为正确的 SubQuery 对象。

    提供一个包含两个子查询的 JSON 数组：
      - 针对 "防晒霜" 的 keyword 搜索。
      - 排除特定日系品牌的 structured_filter。

    断言解析后的 SubQuery 列表长度、策略、文本、operator
    以及 expanded_values 均正确。
    """
    parser = QueryParser(llm=MagicMock())

    # 模拟 LLM 返回的原始 JSON 响应，包含 keyword + structured_filter 策略
    llm_output = json.dumps([
        {
            "text": "防晒霜",
            "strategy": "keyword",
            "field": None,
            "operator": None,
            "value": None,
            "expanded_values": None,
        },
        {
            "text": "不要日系品牌",
            "strategy": "structured_filter",
            "field": "brand",
            "operator": "not_in",
            "value": None,
            "expanded_values": ["SK-II", "资生堂", "CPB"],
        },
    ])

    subs = parser._parse_response(llm_output)

    # 验证解析出的子查询与预期一致
    assert len(subs) == 2
    assert subs[0].strategy == "keyword"
    assert subs[0].text == "防晒霜"
    assert subs[1].operator == "not_in"
    assert subs[1].expanded_values == ["SK-II", "资生堂", "CPB"]


@pytest.mark.asyncio
async def test_parse_with_mock_llm():
    """验证 parse() 端到端地调用 LLM 并将其响应转换为 SubQuery 列表。

    Mock LLM 的 chat() 返回一个 JSON 响应，包含一个 keyword 子查询
    和一个 semantic 子查询。确认两种策略在解析结果中均正确赋值。
    """
    mock_llm = AsyncMock()

    async def mock_chat_stream(messages, temperature=0.1):
        yield json.dumps([
            {
                "text": "需要洗面奶",
                "strategy": "keyword",
                "field": None,
                "operator": None,
                "value": None,
                "expanded_values": None,
            },
            {
                "text": "适合油皮",
                "strategy": "semantic",
                "field": None,
                "operator": None,
                "value": None,
                "expanded_values": None,
            },
        ])

    mock_llm.chat_stream = mock_chat_stream

    parser = QueryParser(llm=mock_llm)
    subs = await parser.parse("推荐一款适合油皮的洗面奶")

    assert len(subs) == 2
    assert subs[0].strategy == "keyword"
    assert subs[1].strategy == "semantic"
