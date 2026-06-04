# tests/test_merger.py
"""测试 Merger 服务：加权 RRF (Reciprocal Rank Fusion) 排名融合。

Merger 将 keyword 和 semantic 两路已排名的 SKUHit 列表
通过加权 RRF 公式融合为单一排序结果。

加权 RRF: score = sw/(k + sem_rank) + kw/(k + kw_rank)
默认权重: semantic=0.7, keyword=0.3, k=60
"""

import pytest
from app.services.retriever_service import SKUHit, Merger


# ---------------------------------------------------------------------------
# 构造函数测试
# ---------------------------------------------------------------------------


def test_merger_default_params():
    """验证 Merger 默认参数。"""
    merger = Merger()
    assert merger.rrf_k == 60
    assert merger.semantic_weight == 0.7
    assert merger.keyword_weight == 0.3
    assert merger.final_limit == 25


def test_merger_custom_params():
    """验证 Merger 接受自定义参数。"""
    merger = Merger(rrf_k=40, semantic_weight=0.8, keyword_weight=0.2, final_limit=5)
    assert merger.rrf_k == 40
    assert merger.semantic_weight == 0.8
    assert merger.keyword_weight == 0.2
    assert merger.final_limit == 5


# ---------------------------------------------------------------------------
# 加权 RRF 融合测试
# ---------------------------------------------------------------------------


def test_rrf_basic():
    """验证两组非重叠 SKU 的加权 RRF 融合。

    关键词路:   [SKU-A (rank=1), SKU-B (rank=2)]
    语义路:     [SKU-C (rank=1), SKU-D (rank=2)]

    加权 RRF 得分（sw=0.7, kw=0.3）:
      SKU-A: 0.3/(60+1) = 0.00492
      SKU-B: 0.3/(60+2) = 0.00484
      SKU-C: 0.7/(60+1) = 0.01148
      SKU-D: 0.7/(60+2) = 0.01129

    排序: 语义路权重更高，SKU-C, SKU-D 排前面
    """
    merger = Merger(rrf_k=60)

    kw = [
        SKUHit(sku_id="SKU-A", product_id="PA", score=0.9),
        SKUHit(sku_id="SKU-B", product_id="PB", score=0.8),
    ]
    sem = [
        SKUHit(sku_id="SKU-C", product_id="PC", score=0.95),
        SKUHit(sku_id="SKU-D", product_id="PD", score=0.85),
    ]

    result = merger.merge(keyword_ranked=kw, semantic_ranked=sem)

    assert len(result) == 4
    # 语义路权重 0.7 > 关键词路权重 0.3，语义结果排前面
    assert result[0].sku_id == "SKU-C"
    assert result[1].sku_id == "SKU-D"
    assert result[2].sku_id == "SKU-A"
    assert result[3].sku_id == "SKU-B"


def test_rrf_overlapping():
    """验证同一 SKU 出现在两路时的加权 RRF 得分会累加。

    关键词路: [SKU-X (rank=1), SKU-Y (rank=2)]
    语义路:   [SKU-X (rank=1)]

    加权 RRF 得分:
      SKU-X: 0.3/(60+1) + 0.7/(60+1) = 1.0/61 ≈ 0.01639
      SKU-Y: 0.3/(60+2) ≈ 0.00484

    SKU-X 应在 SKU-Y 之前。
    """
    merger = Merger(rrf_k=60)

    kw = [
        SKUHit(sku_id="SKU-X", product_id="PX", score=0.9),
        SKUHit(sku_id="SKU-Y", product_id="PY", score=0.8),
    ]
    sem = [
        SKUHit(sku_id="SKU-X", product_id="PX", score=0.95),
    ]

    result = merger.merge(keyword_ranked=kw, semantic_ranked=sem)

    assert len(result) == 2
    assert result[0].sku_id == "SKU-X"
    assert result[1].sku_id == "SKU-Y"


def test_rrf_empty_keyword():
    """验证关键词路为空时，仅返回语义路的结果（按加权 RRF 得分排序）。"""
    merger = Merger(rrf_k=60)

    sem = [
        SKUHit(sku_id="SKU-B", product_id="PB", score=0.8),
        SKUHit(sku_id="SKU-A", product_id="PA", score=0.9),
    ]

    result = merger.merge(keyword_ranked=[], semantic_ranked=sem)

    assert len(result) == 2
    # rank=1 的排在前面
    assert result[0].sku_id == "SKU-B"
    assert result[1].sku_id == "SKU-A"


def test_rrf_empty_semantic():
    """验证语义路为空时，仅返回关键词路的结果。"""
    merger = Merger(rrf_k=60)

    kw = [
        SKUHit(sku_id="SKU-Z", product_id="PZ", score=0.7),
    ]

    result = merger.merge(keyword_ranked=kw, semantic_ranked=[])

    assert len(result) == 1
    assert result[0].sku_id == "SKU-Z"


def test_rrf_both_empty():
    """验证两路均为空时返回空列表。"""
    merger = Merger()
    result = merger.merge(keyword_ranked=[], semantic_ranked=[])
    assert result == []


def test_rrf_final_limit():
    """验证 final_limit 截断效果——结果数不超过 final_limit。

    5 个不同 SKU，但 final_limit=3，应只返回前 3 个。
    """
    merger = Merger(rrf_k=60, final_limit=3)

    kw = [
        SKUHit(sku_id="S1", product_id="P1", score=0.9),
        SKUHit(sku_id="S2", product_id="P2", score=0.8),
    ]
    sem = [
        SKUHit(sku_id="S3", product_id="P3", score=0.7),
        SKUHit(sku_id="S4", product_id="P4", score=0.6),
        SKUHit(sku_id="S5", product_id="P5", score=0.5),
    ]

    result = merger.merge(keyword_ranked=kw, semantic_ranked=sem)

    assert len(result) <= 3


def test_rrf_score_values():
    """验证返回的 SKUHit.score 为正确的加权 RRF 得分。

    关键词路单 SKU: RRF = 0.3/(60+1) ≈ 0.00492
    """
    merger = Merger(rrf_k=60)

    kw = [SKUHit(sku_id="SKU-1", product_id="P1", score=0.9)]

    result = merger.merge(keyword_ranked=kw, semantic_ranked=[])

    assert len(result) == 1
    assert result[0].sku_id == "SKU-1"
    assert result[0].product_id == "P1"
    assert abs(result[0].score - (0.3 / 61.0)) < 0.0001
