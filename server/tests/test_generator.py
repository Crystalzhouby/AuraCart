# tests/test_generator.py
"""测试 Generator 服务：流式推荐生成与上下文构建。"""

import pytest
from unittest.mock import AsyncMock, patch
from app.rag.generator import Generator


# ---------------------------------------------------------------------------
# _build_context — 新扁平 SKU 格式（选项 A：内部按 product_id 分组）
# ---------------------------------------------------------------------------

def test_build_context_single_sku():
    """单条 SKU → 渲染为一个 product 下的一条 SKU。"""
    generator = Generator(llm=AsyncMock())

    skus = [
        {
            "product_id": "p1",
            "title": "安耐晒小金瓶",
            "brand": "安耐晒",
            "category": "美妆护肤",
            "base_price": 198.0,
            "sku_id": "s_p1_60ml",
            "properties": {"容量": "60ml"},
            "price": 198.0,
            "stock": 42,
        }
    ]

    ctx = generator._build_context(skus)

    assert "安耐晒小金瓶" in ctx
    assert "安耐晒" in ctx
    assert "美妆护肤" in ctx
    assert "198.0" in ctx
    assert "s_p1_60ml" in ctx
    assert "60ml" in ctx


def test_build_context_multi_sku_same_product():
    """同一 product 下多个 SKU → 合并到一个 product 分组下。"""
    generator = Generator(llm=AsyncMock())

    skus = [
        {
            "product_id": "p1",
            "title": "安耐晒小金瓶",
            "brand": "安耐晒",
            "category": "美妆护肤",
            "base_price": 198.0,
            "sku_id": "s_p1_60ml",
            "properties": {"容量": "60ml"},
            "price": 198.0,
            "stock": 42,
        },
        {
            "product_id": "p1",
            "title": "安耐晒小金瓶",
            "brand": "安耐晒",
            "category": "美妆护肤",
            "base_price": 198.0,
            "sku_id": "s_p1_30ml",
            "properties": {"容量": "30ml"},
            "price": 128.0,
            "stock": 15,
        },
    ]

    ctx = generator._build_context(skus)

    # product 标题只出现一次
    assert ctx.count("安耐晒小金瓶") == 1
    # 两个 SKU 都在
    assert "s_p1_60ml" in ctx
    assert "s_p1_30ml" in ctx
    assert "60ml" in ctx
    assert "30ml" in ctx


def test_build_context_multi_sku_different_products():
    """不同 product 的 SKU → 各自独立分组。"""
    generator = Generator(llm=AsyncMock())

    skus = [
        {
            "product_id": "p1",
            "title": "安耐晒小金瓶",
            "brand": "安耐晒",
            "category": "美妆护肤",
            "base_price": 198.0,
            "sku_id": "s_p1_60ml",
            "properties": {"容量": "60ml"},
            "price": 198.0,
            "stock": 42,
        },
        {
            "product_id": "p2",
            "title": "碧柔水感防晒霜",
            "brand": "碧柔",
            "category": "美妆护肤",
            "base_price": 79.0,
            "sku_id": "s_p2_50g",
            "properties": {"容量": "50g"},
            "price": 79.0,
            "stock": 88,
        },
    ]

    ctx = generator._build_context(skus)

    # 两个 product 标题各出现一次
    assert "1. 安耐晒小金瓶" in ctx
    assert "2. 碧柔水感防晒霜" in ctx
    assert "安耐晒" in ctx
    assert "碧柔" in ctx


def test_build_context_sku_without_optional_fields():
    """SKU 缺少 brand/category/properties → 不崩溃，优雅跳过。"""
    generator = Generator(llm=AsyncMock())

    skus = [
        {
            "product_id": "p1",
            "title": "某商品",
            "brand": None,
            "category": None,
            "base_price": None,
            "sku_id": "s_p1_x",
            "properties": None,
            "price": 50.0,
            "stock": 0,
        }
    ]

    ctx = generator._build_context(skus)

    assert "某商品" in ctx
    assert "s_p1_x" in ctx
    assert "50.0" in ctx
    # brand/category 不出现
    assert "品牌" not in ctx
    assert "品类" not in ctx


def test_build_context_empty_skus():
    """空 SKU 列表 → 返回空字符串。"""
    generator = Generator(llm=AsyncMock())
    ctx = generator._build_context([])
    assert ctx == ""


# ---------------------------------------------------------------------------
# generate() 流式输出 — 适配新格式后保持不变
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_stream():
    """验证 generate() 从 LLM chat_stream 中按 token 异步产出。"""
    mock_llm = AsyncMock()

    async def fake_stream(messages, temperature=None):
        yield "为您"
        yield "推荐"
        yield "以下商品"

    mock_llm.chat_stream = fake_stream

    generator = Generator(llm=mock_llm)

    skus = [
        {
            "product_id": "P1",
            "title": "安耐晒小金瓶",
            "brand": "安耐晒",
            "category": "美妆护肤",
            "base_price": 198.0,
            "sku_id": "P1_60ml",
            "properties": {"容量": "60ml"},
            "price": 198.0,
            "stock": 42,
        }
    ]

    user_query = "推荐一款防晒霜"
    tokens = []
    async for token in generator.generate(skus, user_query):
        tokens.append(token)

    assert tokens == ["为您", "推荐", "以下商品"]


# ---------------------------------------------------------------------------
# _format_sub_queries 单元测试
# ---------------------------------------------------------------------------


class TestFormatSubQueries:
    """测试 _format_sub_queries 静态方法的各种输入。"""

    def test_none_returns_empty(self):
        """sub_queries=None → 返回空字符串。"""
        result = Generator._format_sub_queries(None)
        assert result == ""

    def test_empty_list_returns_empty(self):
        """sub_queries=[] → 返回空字符串。"""
        result = Generator._format_sub_queries([])
        assert result == ""

    def test_all_text_empty_returns_empty(self):
        """所有 sub_query 的 text 为空或空白 → 返回空字符串。"""
        sub_queries = [
            {"text": "", "strategy": "structured_filter", "field": "price"},
            {"text": "   ", "strategy": "keyword"},
        ]
        result = Generator._format_sub_queries(sub_queries)
        assert result == ""

    def test_mixed_text(self):
        """混合空/非空 text → 只输出 text 非空的项。"""
        sub_queries = [
            {"text": "防晒霜", "strategy": "keyword"},
            {"text": "", "strategy": "structured_filter", "field": "price"},
            {"text": "产品评价中是否提及酒精成分", "strategy": "semantic"},
        ]
        result = Generator._format_sub_queries(sub_queries)
        assert "1. 防晒霜" in result
        assert "2. 产品评价中是否提及酒精成分" in result
        # structured_filter 不应出现
        assert "structured_filter" not in result

    def test_format_structure(self):
        """输出格式为"用户关心以下方面："开头的编号列表。"""
        sub_queries = [
            {"text": "方面A", "strategy": "semantic"},
            {"text": "方面B", "strategy": "semantic"},
        ]
        result = Generator._format_sub_queries(sub_queries)
        lines = result.split("\n")
        assert lines[0] == "用户关心以下方面："
        assert lines[1] == "1. 方面A"
        assert lines[2] == "2. 方面B"

    def test_missing_text_key(self):
        """sub_query 缺少 text 键 → 不抛异常，跳过。"""
        sub_queries = [
            {"strategy": "keyword"},  # no "text" key
            {"text": "有效方面", "strategy": "semantic"},
        ]
        result = Generator._format_sub_queries(sub_queries)
        assert "有效方面" in result
        assert result.count("1.") == 1

    def test_output_is_not_json(self):
        """输出是自然语言文本，不是 JSON。"""
        sub_queries = [
            {"text": "测试意图", "strategy": "semantic"},
        ]
        result = Generator._format_sub_queries(sub_queries)
        assert not result.startswith("[")
        assert not result.startswith("{")
        assert "用户关心" in result


# ---------------------------------------------------------------------------
# generate() 新签名测试（sub_queries 参数）
# ---------------------------------------------------------------------------


class TestGenerateWithSubQueries:
    """测试 generate() 的 sub_queries 参数行为。"""

    @pytest.mark.asyncio
    async def test_sub_queries_injected_into_user_message(self):
        """传入 sub_queries → 用户消息包含格式化后的子查询文本。"""
        mock_llm = AsyncMock()

        # 捕获传入 chat_stream 的 messages
        captured_messages = []

        async def fake_stream(messages, temperature=None):
            captured_messages.extend(messages)
            yield "test"

        mock_llm.chat_stream = fake_stream

        generator = Generator(llm=mock_llm)

        skus = [{
            "product_id": "P1", "title": "测试商品", "brand": None,
            "category": None, "base_price": None,
            "sku_id": "SKU1", "properties": None, "price": 99.0,
        }]

        sub_queries = [
            {"text": "产品评价中是否提及酒精成分", "strategy": "semantic"},
        ]

        tokens = []
        async for token in generator.generate(skus, "推荐防晒霜", sub_queries=sub_queries):
            tokens.append(token)

        # 找到 user message
        user_msgs = [m["content"] for m in captured_messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "用户关心以下方面" in user_msgs[0]
        assert "产品评价中是否提及酒精成分" in user_msgs[0]

    @pytest.mark.asyncio
    async def test_sub_queries_none_degrades(self):
        """sub_queries=None → 用户消息不包含子查询段落，行为退化。"""
        mock_llm = AsyncMock()

        captured_messages = []

        async def fake_stream(messages, temperature=None):
            captured_messages.extend(messages)
            yield "test"

        mock_llm.chat_stream = fake_stream

        generator = Generator(llm=mock_llm)

        skus = [{
            "product_id": "P1", "title": "测试商品", "brand": None,
            "category": None, "base_price": None,
            "sku_id": "SKU1", "properties": None, "price": 99.0,
        }]

        tokens = []
        async for token in generator.generate(skus, "推荐防晒霜", sub_queries=None):
            tokens.append(token)

        user_msgs = [m["content"] for m in captured_messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        assert "用户关心以下方面" not in user_msgs[0]

    @pytest.mark.asyncio
    async def test_backward_compatible_no_param(self):
        """不传 sub_queries → 行为与原来一致。"""
        mock_llm = AsyncMock()

        captured_messages = []

        async def fake_stream(messages, temperature=None):
            captured_messages.extend(messages)
            yield "test"

        mock_llm.chat_stream = fake_stream

        generator = Generator(llm=mock_llm)

        skus = [{
            "product_id": "P1", "title": "测试商品", "brand": None,
            "category": None, "base_price": None,
            "sku_id": "SKU1", "properties": None, "price": 99.0,
        }]

        tokens = []
        async for token in generator.generate(skus, "推荐防晒霜"):
            tokens.append(token)

        user_msgs = [m["content"] for m in captured_messages if m["role"] == "user"]
        assert len(user_msgs) == 1
        # 退化为原有格式
        assert "用户关心以下方面" not in user_msgs[0]
        assert user_msgs[0] == "请根据以上商品信息，为用户推荐：推荐防晒霜"

    @pytest.mark.asyncio
    async def test_reasoning_max_chars_injected(self):
        """验证 reasoning_max_chars 配置值被注入到 system prompt。"""
        mock_llm = AsyncMock()

        captured_messages = []

        async def fake_stream(messages, temperature=None):
            captured_messages.extend(messages)
            yield "test"

        mock_llm.chat_stream = fake_stream

        generator = Generator(llm=mock_llm)

        skus = [{
            "product_id": "P1", "title": "测试商品", "brand": None,
            "category": None, "base_price": None,
            "sku_id": "SKU1", "properties": None, "price": 99.0,
        }]

        async for token in generator.generate(skus, "推荐防晒霜"):
            pass

        system_msgs = [m["content"] for m in captured_messages if m["role"] == "system"]
        assert len(system_msgs) == 1
        # 配置中 reasoning_max_chars=500，不应出现未填充的占位符
        assert "{reasoning_max_chars}" not in system_msgs[0]
        # 应出现实际值
        assert "500字以内" in system_msgs[0]


# ---------------------------------------------------------------------------
# GENERATOR_SYSTEM prompt 规则验证
# ---------------------------------------------------------------------------


class TestGeneratorPrompt:
    """验证 GENERATOR_SYSTEM 包含预期的行为约束规则。"""

    def test_rule_8_cover_all_products(self):
        """规则 3（硬约束）: 必须为每一个商品都说明推荐理由。"""
        from app.rag.prompt import GENERATOR_SYSTEM
        assert "必须为结果列表中每一个商品说明推荐理由" in GENERATOR_SYSTEM
        # SKU 合并说明也在同一规则中
        assert "同商品多 SKU 的，合并介绍后简要说明各 SKU 规格差异和价格" in GENERATOR_SYSTEM

    def test_rule_9_address_all_intents(self):
        """规则 4（硬约束）: 逐条回应用户关心的每个需求。"""
        from app.rag.prompt import GENERATOR_SYSTEM
        assert "用户有多条评价类需求时，逐条回应是否满足" in GENERATOR_SYSTEM
        # 缺少数据时的降级行为
        assert "目前商品信息中未提及" in GENERATOR_SYSTEM

    def test_rule_7_reasoning_max_chars_placeholder(self):
        """规则 7: 字数限制使用占位符，非硬编码。"""
        from app.rag.prompt import GENERATOR_SYSTEM
        assert "{reasoning_max_chars}" in GENERATOR_SYSTEM
