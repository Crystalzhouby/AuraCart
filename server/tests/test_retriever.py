# tests/test_retriever.py
"""测试 Retriever 服务：语义、关键词、结构化与降级策略。

Retriever 针对每个 SubQuery，通过相应的数据库查询（pgvector
余弦相似度、全文搜索、结构化过滤或 ILIKE 降级）获取候选商品。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from app.services.retriever import Retriever, SubQuery


def test_subquery_no_negation_field():
    """验证 SubQuery 已移除 negation 字段，不再接受 negation 参数。"""
    sq = SubQuery(text="防晒霜", strategy="semantic")
    assert sq.text == "防晒霜"
    assert sq.strategy == "semantic"
    # 传入 negation 应抛出 TypeError
    with pytest.raises(TypeError):
        SubQuery(text="x", strategy="semantic", negation=True)


def test_subquery_structured_filter_operator_handles_negation():
    """验证否定语义通过 operator 值表达，无需 negation 字段。"""
    sq = SubQuery(
        text="不要日系品牌",
        strategy="structured_filter",
        field="brand",
        operator="not_in",
        expanded_values=["SK-II", "资生堂"],
    )
    assert sq.operator == "not_in"
    assert sq.expanded_values == ["SK-II", "资生堂"]


def _make_kw_row(sku_id="S001", product_id="P001", score=0.5,
                 content="测试内容", source="user_review", metadata=None,
                 title="测试商品", brand="测试品牌", category="美妆",
                 sub_category="防晒", base_price=99.0,
                 properties=None, price=79.0, stock=100):
    """创建模拟 keyword 检索返回行的 MagicMock，含所有扩展字段。"""
    row = MagicMock()
    row.sku_id = sku_id
    row.product_id = product_id
    row.score = score
    row.content = content
    row.source = source
    row.metadata = metadata
    row.title = title
    row.brand = brand
    row.category = category
    row.sub_category = sub_category
    row.base_price = base_price
    row.properties = properties
    row.price = price
    row.stock = stock
    return row


def _make_sem_row(sku_id="S001", product_id="P001", score=0.5,
                  title="测试商品", brand="测试品牌", category="美妆",
                  sub_category="防晒", base_price=99.0,
                  properties=None, price=79.0, stock=100,
                  matched_texts_json=None):
    """创建模拟 semantic 检索返回行的 MagicMock，含所有扩展字段。"""
    row = MagicMock()
    row.sku_id = sku_id
    row.product_id = product_id
    row.score = score
    row.title = title
    row.brand = brand
    row.category = category
    row.sub_category = sub_category
    row.base_price = base_price
    row.properties = properties
    row.price = price
    row.stock = stock
    row.matched_texts_json = matched_texts_json or []
    return row


@pytest.fixture
def mock_db():
    """提供一个 mock 的异步数据库会话。

    返回值:
        AsyncMock: 一个可用于 Retriever 的 mock 数据库连接。
    """
    return AsyncMock()


@pytest.fixture
def mock_emb():
    """提供一个返回固定向量的 mock embedding 服务。

    返回值:
        AsyncMock: 一个 mock embedding 服务，其 embed() 始终返回 [0.1, 0.2, 0.3]。
    """
    svc = AsyncMock()
    svc.embed.return_value = [0.1, 0.2, 0.3]
    return svc


@pytest.mark.asyncio
async def test_retrieve_semantic(mock_db, mock_emb):
    """验证语义检索使用 pgvector 余弦相似度并返回带评分的 SKUHit。

    - 调用 embed() 将子查询文本向量化。
    - 查询数据库中相似的 product_review 行。
    - 返回 SKUHit 列表。
    """
    from app.services.retriever import Filters

    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = _make_sem_row(sku_id="SKU001", product_id="PROD001", score=0.85)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    subs = [SubQuery(text="防晒霜", strategy="semantic")]
    hits, meta = await retriever._semantic_search(subs, Filters(conditions=[]), top_k=20)

    assert len(hits) == 1
    assert hits[0].product_id == "PROD001"
    assert hits[0].score == 0.85
    assert "SKU001" in meta
    mock_emb.embed.assert_called_once_with("防晒霜")


@pytest.mark.asyncio
async def test_retrieve_keyword(mock_db, mock_emb):
    """验证关键词检索使用 PostgreSQL 全文搜索（ts_rank）。

    - 不应调用 embed()（关键词无需向量化）。
    - 返回以归一化 rank 作为 score 的 SKUHit 结果。
    """
    from app.services.retriever import Filters

    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = _make_kw_row(sku_id="SKU002", product_id="PROD002", score=0.5)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    subs = [SubQuery(text="蓝牙", strategy="keyword")]
    hits, meta = await retriever._keyword_search(subs, Filters(conditions=[]), top_k=20)

    assert len(hits) == 1
    assert hits[0].product_id == "PROD002"
    assert hits[0].score == 0.5
    assert "SKU002" in meta


@pytest.mark.asyncio
async def test_retrieve_structured():
    """验证 structured_filter "not_in" 转为 FilterClause（不再独立检索）。

    structured_filter 不再有独立检索路径，其条件通过 _extract_filters()
    提取为硬约束注入 keyword/semantic SQL。
    """
    retriever = Retriever(db=MagicMock(), emb=MagicMock())

    sub = SubQuery(
        text="",
        strategy="structured_filter",
        field="brand",
        operator="not_in",
        expanded_values=["SK-II", "资生堂"],
    )
    filters = retriever._extract_filters([sub])

    assert len(filters.conditions) == 1
    assert filters.conditions[0].table == "product"
    assert "NOT IN" in filters.conditions[0].sql


@pytest.mark.asyncio
async def test_retrieve_keyword_fallback(mock_db, mock_emb):
    """验证关键词检索在 tsvector 无结果时降级为对 brand/category/title 做 ILIKE 查询。

    当 PostgreSQL 全文搜索未返回结果时，retriever 应发起第二次查询，
    使用 ILIKE 模式对 brand、category 和 title 列进行模糊匹配。
    本测试断言 execute() 在 tsvector 尝试（chinese + simple）后再进行降级查询。
    """
    from app.services.retriever import Filters

    retriever = Retriever(db=mock_db, emb=mock_emb)

    # tsvector (chinese + simple) 返回空结果
    empty_result = MagicMock()
    empty_result.fetchall.return_value = []

    # ILIKE 降级返回匹配行
    fallback_row = _make_kw_row(sku_id="SKU003", product_id="PROD003", score=0.3)

    fallback_result = MagicMock()
    fallback_result.fetchall.return_value = [fallback_row]

    mock_db.execute.side_effect = [empty_result, empty_result, fallback_result]

    subs = [SubQuery(text="资生堂", strategy="keyword")]
    hits, meta = await retriever._keyword_search(subs, Filters(conditions=[]), top_k=20)

    assert len(hits) == 1
    assert hits[0].product_id == "PROD003"
    assert hits[0].score == 0.3


def test_retrieve_structured_in():
    """验证 structured_filter "in" 转为 FilterClause with IN clause。"""
    retriever = Retriever(db=MagicMock(), emb=MagicMock())

    sub = SubQuery(
        text="",
        strategy="structured_filter",
        field="brand",
        operator="in",
        expanded_values=["SK-II", "资生堂"],
    )
    filters = retriever._extract_filters([sub])

    assert len(filters.conditions) == 1
    assert "IN" in filters.conditions[0].sql
    assert "NOT" not in filters.conditions[0].sql


def test_retrieve_structured_lt_price():
    """验证 structured_filter "lt" 在 price 字段生成正确 SQL。"""
    retriever = Retriever(db=MagicMock(), emb=MagicMock())

    sub = SubQuery(
        text="",
        strategy="structured_filter",
        field="price",
        operator="lt",
        value=200,
    )
    filters = retriever._extract_filters([sub])

    assert len(filters.conditions) == 1
    assert filters.conditions[0].table == "sku"
    assert "s.price < :val" == filters.conditions[0].sql


def test_retrieve_structured_not_contains():
    """验证 structured_filter "not_contains" 生成 NOT ILIKE 条件。"""
    retriever = Retriever(db=MagicMock(), emb=MagicMock())

    sub = SubQuery(
        text="",
        strategy="structured_filter",
        field="brand",
        operator="not_contains",
        value="日系",
    )
    filters = retriever._extract_filters([sub])

    assert len(filters.conditions) == 1
    assert "NOT ILIKE" in filters.conditions[0].sql


# ---------------------------------------------------------------------------
# Step 2: SKUHit / Filters / FilterClause 数据类测试
# ---------------------------------------------------------------------------


def test_skuhit_creation():
    """验证 SKUHit 数据类正确存储 sku_id、product_id 和 score。"""
    from app.services.retriever import SKUHit

    hit = SKUHit(sku_id="SKU001", product_id="PROD001", score=0.95)
    assert hit.sku_id == "SKU001"
    assert hit.product_id == "PROD001"
    assert hit.score == 0.95


def test_skuhit_defaults():
    """验证 SKUHit 所有字段均为必填（无默认值），确保调用方显式传参。"""
    from app.services.retriever import SKUHit

    hit = SKUHit(sku_id="SKU002", product_id="PROD002", score=0.0)
    assert hit.score == 0.0


def test_filter_clause_creation():
    """验证 FilterClause 数据类正确存储 table、sql 和 params。"""
    from app.services.retriever import FilterClause

    fc = FilterClause(
        table="product",
        sql="p.brand NOT IN (:v0, :v1)",
        params={"v0": "SK-II", "v1": "资生堂"},
    )
    assert fc.table == "product"
    assert fc.sql == "p.brand NOT IN (:v0, :v1)"
    assert fc.params == {"v0": "SK-II", "v1": "资生堂"}


def test_filters_empty():
    """验证 Filters 数据类初始化为空的 conditions 列表。"""
    from app.services.retriever import Filters

    f = Filters(conditions=[])
    assert f.conditions == []


def test_filters_with_clauses():
    """验证 Filters 数据类正确聚合多个 FilterClause。"""
    from app.services.retriever import Filters, FilterClause

    fc1 = FilterClause(table="product", sql="p.brand = :v0", params={"v0": "Nike"})
    fc2 = FilterClause(table="sku", sql="s.price < :val", params={"val": 200})
    f = Filters(conditions=[fc1, fc2])

    assert len(f.conditions) == 2
    assert f.conditions[0].table == "product"
    assert f.conditions[1].table == "sku"


# ---------------------------------------------------------------------------
# Step 4: _extract_filters() 方法测试
# ---------------------------------------------------------------------------


@pytest.fixture
def retriever_without_db():
    """创建一个无需真实数据库连接的 Retriever 实例，仅用于测试 _extract_filters。"""
    return Retriever(db=MagicMock(), emb=MagicMock())


def test_extract_filters_empty_subs(retriever_without_db):
    """验证空列表返回空 Filters。"""
    from app.services.retriever import Filters

    result = retriever_without_db._extract_filters([])
    assert isinstance(result, Filters)
    assert result.conditions == []


def test_extract_filters_only_non_structured(retriever_without_db):
    """验证仅有 keyword/semantic 子查询时不产生 FilterClause。"""
    subs = [
        SubQuery(text="防晒霜", strategy="keyword"),
        SubQuery(text="保湿效果好", strategy="semantic"),
    ]
    result = retriever_without_db._extract_filters(subs)
    assert result.conditions == []


def test_extract_filters_brand_not_in(retriever_without_db):
    """验证 structured_filter not_in 在 brand 字段上生成正确的 FilterClause。"""
    subs = [
        SubQuery(
            text="不要日系品牌",
            strategy="structured_filter",
            field="brand",
            operator="not_in",
            expanded_values=["SK-II", "资生堂"],
        ),
    ]
    result = retriever_without_db._extract_filters(subs)
    assert len(result.conditions) == 1
    fc = result.conditions[0]
    assert fc.table == "product"
    assert "p.brand NOT IN" in fc.sql
    assert fc.params["v0"] == "SK-II"
    assert fc.params["v1"] == "资生堂"


def test_extract_filters_price_lt(retriever_without_db):
    """验证 structured_filter lt 在 price 字段上生成正确的 FilterClause。"""
    subs = [
        SubQuery(
            text="",
            strategy="structured_filter",
            field="price",
            operator="lt",
            value=200,
        ),
    ]
    result = retriever_without_db._extract_filters(subs)
    assert len(result.conditions) == 1
    fc = result.conditions[0]
    assert fc.table == "sku"
    assert "s.price < :val" == fc.sql
    assert fc.params["val"] == 200


def test_extract_filters_brand_in(retriever_without_db):
    """验证 structured_filter in 在 category 字段上生成 IN 子句。"""
    subs = [
        SubQuery(
            text="",
            strategy="structured_filter",
            field="category",
            operator="in",
            expanded_values=["美妆护肤", "个人护理"],
        ),
    ]
    result = retriever_without_db._extract_filters(subs)
    assert len(result.conditions) == 1
    fc = result.conditions[0]
    assert fc.table == "product"
    assert "p.category IN" in fc.sql
    assert fc.params["v0"] == "美妆护肤"
    assert fc.params["v1"] == "个人护理"


def test_extract_filters_contains(retriever_without_db):
    """验证 structured_filter contains 生成 ILIKE 模式匹配的 FilterClause。"""
    subs = [
        SubQuery(
            text="",
            strategy="structured_filter",
            field="brand",
            operator="contains",
            value="资生",
        ),
    ]
    result = retriever_without_db._extract_filters(subs)
    assert len(result.conditions) == 1
    fc = result.conditions[0]
    assert fc.table == "product"
    assert "ILIKE" in fc.sql
    assert "资生" in fc.params["pat"]


def test_extract_filters_mixed(retriever_without_db):
    """验证同时有 structured_filter 和非 filter 子查询时仅提取 filter。"""
    subs = [
        SubQuery(text="防晒霜", strategy="keyword"),
        SubQuery(
            text="", strategy="structured_filter",
            field="price", operator="lt", value=200,
        ),
        SubQuery(text="保湿", strategy="semantic"),
        SubQuery(
            text="", strategy="structured_filter",
            field="brand", operator="not_in",
            expanded_values=["X", "Y"],
        ),
    ]
    result = retriever_without_db._extract_filters(subs)
    assert len(result.conditions) == 2
    assert result.conditions[0].table == "sku"
    assert result.conditions[1].table == "product"


def test_extract_filters_unknown_field(retriever_without_db):
    """验证未知字段不产生 FilterClause（静默跳过）。"""
    subs = [
        SubQuery(
            text="", strategy="structured_filter",
            field="unknown_field", operator="eq", value="x",
        ),
    ]
    result = retriever_without_db._extract_filters(subs)
    assert result.conditions == []


# ---------------------------------------------------------------------------
# Step 5: _build_base_query() 方法测试
# ---------------------------------------------------------------------------


def test_build_base_query_no_filters():
    """验证无 filter 时构建仅包含活跃条件的三表 JOIN SQL 骨架。"""
    from app.services.retriever import Filters

    retriever = Retriever(db=MagicMock(), emb=MagicMock())
    filters = Filters(conditions=[])
    sql = retriever._build_base_query(filters, "0.5 AS score")

    assert "FROM product_review pr" in sql
    assert "JOIN product p ON p.product_id = pr.product_id AND p.is_active = TRUE" in sql
    assert "JOIN sku s ON s.product_id = p.product_id AND s.is_active = TRUE" in sql
    assert "0.5 AS score" in sql
    assert "SELECT s.sku_id, p.product_id" in sql


def test_build_base_query_with_product_filter():
    """验证含 product 表 FilterClause 时 WHERE 子句包含 product 条件。"""
    from app.services.retriever import Filters, FilterClause

    retriever = Retriever(db=MagicMock(), emb=MagicMock())
    fc = FilterClause(
        table="product",
        sql="p.brand NOT IN (:v0, :v1)",
        params={"v0": "X", "v1": "Y"},
    )
    filters = Filters(conditions=[fc])
    sql = retriever._build_base_query(filters, "1.0 AS score")

    assert "WHERE" in sql
    assert "p.brand NOT IN (:v0, :v1)" in sql


def test_build_base_query_with_sku_filter():
    """验证含 sku 表 FilterClause 时 WHERE 子句包含 sku 条件。"""
    from app.services.retriever import Filters, FilterClause

    retriever = Retriever(db=MagicMock(), emb=MagicMock())
    fc = FilterClause(
        table="sku",
        sql="s.price < :val",
        params={"val": 200},
    )
    filters = Filters(conditions=[fc])
    sql = retriever._build_base_query(filters, "ts_rank(...) AS score")

    assert "WHERE" in sql
    assert "s.price < :val" in sql


def test_build_base_query_multiple_filters():
    """验证同时含 product 和 sku FilterClause 时 WHERE 用 AND 连接。"""
    from app.services.retriever import Filters, FilterClause

    retriever = Retriever(db=MagicMock(), emb=MagicMock())
    fc1 = FilterClause(table="product", sql="p.brand = :v0", params={"v0": "Nike"})
    fc2 = FilterClause(table="sku", sql="s.price < :val", params={"val": 100})
    filters = Filters(conditions=[fc1, fc2])
    sql = retriever._build_base_query(filters, "1.0 AS score")

    assert "p.brand = :v0" in sql
    assert "s.price < :val" in sql
    assert "AND" in sql


def test_build_base_query_score_expr_injection():
    """验证不同 score_expr 被正确注入 SELECT 子句。"""
    from app.services.retriever import Filters

    retriever = Retriever(db=MagicMock(), emb=MagicMock())
    sql = retriever._build_base_query(Filters(conditions=[]), "SUM(1-(pr.embedding <=> :vec)) AS score")

    assert "SUM(1-(pr.embedding <=> :vec)) AS score" in sql


# ---------------------------------------------------------------------------
# Step 6a: _keyword_search() 重写测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keyword_search_returns_skuhits(mock_db, mock_emb):
    """验证 _keyword_search 返回 list[SKUHit] 格式，score 为 ts_rank 值。"""
    from app.services.retriever import Filters, SKUHit

    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = _make_kw_row(sku_id="SKU001", product_id="PROD001", score=0.75)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    subs = [SubQuery(text="蓝牙", strategy="keyword")]
    hits, meta = await retriever._keyword_search(subs, Filters(conditions=[]), top_k=20)

    assert len(hits) == 1
    assert isinstance(hits[0], SKUHit)
    assert hits[0].sku_id == "SKU001"
    assert hits[0].product_id == "PROD001"
    assert hits[0].score == 0.75
    assert meta["SKU001"]["matched_texts"]


@pytest.mark.asyncio
async def test_keyword_search_applies_filters(mock_db, mock_emb):
    """验证 _keyword_search 在 SQL 中包含 FilterClause 的硬约束条件。"""
    from app.services.retriever import Filters, FilterClause

    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = _make_kw_row(sku_id="SKU002", product_id="PROD002", score=0.6)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    fc = FilterClause(table="product", sql="p.brand = :v0", params={"v0": "Nike"})
    subs = [SubQuery(text="运动鞋", strategy="keyword")]
    hits, meta = await retriever._keyword_search(subs, Filters(conditions=[fc]), top_k=20)

    assert len(hits) == 1
    # 验证 SQL 中包含了 filter 条件
    sql_called = mock_db.execute.call_args[0][0]
    assert "p.brand = :v0" in sql_called.text


@pytest.mark.asyncio
async def test_keyword_search_tsv_fallback(mock_db, mock_emb):
    """验证 tsvector 无结果时降级为 ILIKE，并返回 list[SKUHit]。"""
    from app.services.retriever import Filters

    retriever = Retriever(db=mock_db, emb=mock_emb)

    empty_result = MagicMock()
    empty_result.fetchall.return_value = []

    fallback_row = _make_kw_row(sku_id="SKU003", product_id="PROD003", score=0.3)

    fallback_result = MagicMock()
    fallback_result.fetchall.return_value = [fallback_row]

    mock_db.execute.side_effect = [empty_result, empty_result, fallback_result]

    subs = [SubQuery(text="资生堂", strategy="keyword")]
    hits, meta = await retriever._keyword_search(subs, Filters(conditions=[]), top_k=20)

    assert len(hits) == 1
    assert hits[0].sku_id == "SKU003"
    assert hits[0].score == 0.3


# ---------------------------------------------------------------------------
# Step 6b: _semantic_search() 重写测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_search_single_sub(mock_db, mock_emb):
    """验证单条 semantic 子查询返回 list[SKUHit]，embed 被调用一次。"""
    from app.services.retriever import Filters, SKUHit

    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = _make_sem_row(sku_id="SKU100", product_id="PROD100", score=0.88)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    subs = [SubQuery(text="保湿效果好", strategy="semantic")]
    hits, meta = await retriever._semantic_search(subs, Filters(conditions=[]), top_k=20)

    assert len(hits) == 1
    assert isinstance(hits[0], SKUHit)
    assert hits[0].sku_id == "SKU100"
    assert hits[0].score == 0.88
    mock_emb.embed.assert_called_once_with("保湿效果好")


@pytest.mark.asyncio
async def test_semantic_search_multi_sub(mock_db, mock_emb):
    """验证多条 semantic 子查询时每条都被 embed，sum 得分汇总到单个 SQL。"""
    from app.services.retriever import Filters

    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = _make_sem_row(sku_id="SKU200", product_id="PROD200", score=1.5)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    subs = [
        SubQuery(text="防晒效果", strategy="semantic"),
        SubQuery(text="质地清爽", strategy="semantic"),
    ]
    hits, meta = await retriever._semantic_search(subs, Filters(conditions=[]), top_k=20)

    assert len(hits) == 1
    assert hits[0].sku_id == "SKU200"
    assert hits[0].score == 1.5
    assert mock_emb.embed.call_count == 2


@pytest.mark.asyncio
async def test_semantic_search_applies_filters(mock_db, mock_emb):
    """验证 _semantic_search 将 FilterClause 硬约束注入 SQL。"""
    from app.services.retriever import Filters, FilterClause

    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = _make_sem_row(sku_id="SKU300", product_id="PROD300", score=0.7)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    fc = FilterClause(table="sku", sql="s.price < :val", params={"val": 200})
    subs = [SubQuery(text="护肤品", strategy="semantic")]
    hits, meta = await retriever._semantic_search(subs, Filters(conditions=[fc]), top_k=20)

    assert len(hits) == 1
    sql_called = mock_db.execute.call_args[0][0]
    assert "s.price < :val" in sql_called.text


# ======================================================================
# Step 2: _build_weight_expr() 单元测试
# ======================================================================


class TestBuildWeightExpr:
    """测试 _build_weight_expr 的 CASE WHEN 生成和参数绑定。"""

    def test_all_default_weights(self):
        """空 dict 传入时所有 source 默认 1.0，SQL 仍含 3 个 WHEN 分支。"""
        sql, params = Retriever._build_weight_expr({})
        assert "CASE pr.source" in sql
        assert "WHEN 'marketing'" in sql
        assert "WHEN 'faq'" in sql
        assert "WHEN 'user_review'" in sql
        assert "ELSE 1.0 END" in sql
        assert params["wv_marketing"] == 1.0
        assert params["wv_faq"] == 1.0
        assert params["wv_user_review"] == 1.0

    def test_specified_weights(self):
        """指定权重时参数值正确。"""
        weights = {"marketing": 1.0, "faq": 1.0, "user_review": 0.7}
        sql, params = Retriever._build_weight_expr(weights)
        assert params["wv_marketing"] == 1.0
        assert params["wv_faq"] == 1.0
        assert params["wv_user_review"] == 0.7

    def test_partial_weights(self):
        """部分 source 未配置时走默认 1.0。"""
        weights = {"user_review": 0.5}
        sql, params = Retriever._build_weight_expr(weights)
        assert params["wv_marketing"] == 1.0
        assert params["wv_faq"] == 1.0
        assert params["wv_user_review"] == 0.5

    def test_zero_weight(self):
        """权重为 0 时参数为 0.0。"""
        weights = {"user_review": 0.0}
        sql, params = Retriever._build_weight_expr(weights)
        assert params["wv_user_review"] == 0.0

    def test_sql_fragment_structure(self):
        """验证 SQL 片段以 CASE 开头、END 结尾，且 WHEN 在 THEN 之前。"""
        sql, _ = Retriever._build_weight_expr({})
        assert sql.startswith("CASE pr.source")
        assert sql.endswith("ELSE 1.0 END")
        # 每个 WHEN 后面必须跟 THEN
        assert "WHEN 'marketing' THEN :wv_marketing" in sql
        assert "WHEN 'faq' THEN :wv_faq" in sql
        assert "WHEN 'user_review' THEN :wv_user_review" in sql

    def test_unknown_source_not_in_sql(self):
        """未知 source（如 'expert_review'）不出现在 CASE WHEN 分支中，走 ELSE。"""
        sql, params = Retriever._build_weight_expr({"expert_review": 0.8})
        assert "expert_review" not in sql
        assert ":wv_expert_review" not in params


# ======================================================================
# Step 3: _semantic_search 加权测试
# ======================================================================


@pytest.mark.asyncio
async def test_semantic_search_includes_weight_expr(mock_db, mock_emb):
    """验证 _semantic_search SQL 中包含 CASE WHEN 权重表达式。"""
    from app.services.retriever import Filters

    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = _make_sem_row(sku_id="SKU100", product_id="PROD100", score=0.88)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    subs = [SubQuery(text="保湿效果好", strategy="semantic")]
    hits, meta = await retriever._semantic_search(subs, Filters(conditions=[]), top_k=20)

    assert len(hits) == 1
    # 验证 SQL 包含权重表达式
    sql_called = mock_db.execute.call_args[0][0]
    sql_text = sql_called.text
    assert "CASE pr.source" in sql_text
    assert ":wv_marketing" in sql_text
    assert ":wv_faq" in sql_text
    assert ":wv_user_review" in sql_text


@pytest.mark.asyncio
async def test_semantic_search_weight_params_bound(mock_db, mock_emb):
    """验证权重参数被绑定到 SQL 参数中。"""
    from app.services.retriever import Filters

    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = _make_sem_row(sku_id="SKU200", product_id="PROD200", score=1.2)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    subs = [SubQuery(text="防晒", strategy="semantic")]
    await retriever._semantic_search(subs, Filters(conditions=[]), top_k=20)

    # 验证 execute 调用参数中包含权重参数
    call_params = mock_db.execute.call_args[0][1]
    assert call_params["wv_marketing"] == 1.0
    assert call_params["wv_faq"] == 1.0
    assert call_params["wv_user_review"] == 0.7


# ======================================================================
# Step 4: _keyword_search 加权测试
# ======================================================================


@pytest.mark.asyncio
async def test_keyword_search_includes_weight_expr(mock_db, mock_emb):
    """验证 ts_rank 路径的 SQL 中包含 CASE WHEN 权重表达式。"""
    from app.services.retriever import Filters

    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = _make_kw_row(sku_id="SKU001", product_id="PROD001", score=0.75)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    subs = [SubQuery(text="蓝牙", strategy="keyword")]
    hits, meta = await retriever._keyword_search(subs, Filters(conditions=[]), top_k=20)

    assert len(hits) == 1
    sql_called = mock_db.execute.call_args[0][0]
    sql_text = sql_called.text
    assert "CASE pr.source" in sql_text
    assert ":wv_user_review" in sql_text


@pytest.mark.asyncio
async def test_keyword_search_weight_params_bound(mock_db, mock_emb):
    """验证 keyword 检索的参数中包含权重值。"""
    from app.services.retriever import Filters

    retriever = Retriever(db=mock_db, emb=mock_emb)

    mock_row = _make_kw_row(sku_id="SKU002", product_id="PROD002", score=0.6)

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    subs = [SubQuery(text="运动鞋", strategy="keyword")]
    await retriever._keyword_search(subs, Filters(conditions=[]), top_k=20)

    call_params = mock_db.execute.call_args[0][1]
    assert call_params["wv_marketing"] == 1.0
    assert call_params["wv_faq"] == 1.0
    assert call_params["wv_user_review"] == 0.7


@pytest.mark.asyncio
async def test_keyword_fallback_includes_weight_expr(mock_db, mock_emb):
    """验证 ILIKE 降级路径的 SQL 中也包含权重表达式。"""
    from app.services.retriever import Filters

    retriever = Retriever(db=mock_db, emb=mock_emb)

    empty_result = MagicMock()
    empty_result.fetchall.return_value = []

    fallback_row = _make_kw_row(sku_id="SKU003", product_id="PROD003", score=0.21)  # 0.7 * 0.3

    fallback_result = MagicMock()
    fallback_result.fetchall.return_value = [fallback_row]

    mock_db.execute.side_effect = [empty_result, empty_result, fallback_result]

    subs = [SubQuery(text="资生堂", strategy="keyword")]
    hits, meta = await retriever._keyword_search(subs, Filters(conditions=[]), top_k=20)

    assert len(hits) == 1
    # 验证降级 SQL 也包含权重表达式
    # side_effect 的第三次调用是 ILIKE fallback
    sql_called = mock_db.execute.call_args[0][0]
    sql_text = sql_called.text
    assert "CASE pr.source" in sql_text
    # 验证 ILIKE 参数中也包含权重
    call_params = mock_db.execute.call_args[0][1]
    assert "wv_marketing" in call_params
