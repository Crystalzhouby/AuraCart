# tests/test_merger.py
"""测试 Merger 服务：RRF (Reciprocal Rank Fusion) 排名融合。

Merger 将 keyword 和 semantic 两路已排名的 SKUHit 列表
通过 RRF 公式融合为单一排序结果。RRF 仅关心排名而非原始分数，
天然适合异构检索源的融合。
"""

import pytest
from app.services.retriever import SKUHit
from app.rag.merger import Merger


# ---------------------------------------------------------------------------
# 构造函数测试
# ---------------------------------------------------------------------------


def test_merger_default_params():
    """验证 Merger 默认使用 k=60 和 final_limit=10。"""
    merger = Merger()
    assert merger.rrf_k == 60
    assert merger.final_limit == 10


def test_merger_custom_params():
    """验证 Merger 接受自定义 rrf_k 和 final_limit。"""
    merger = Merger(rrf_k=40, final_limit=5)
    assert merger.rrf_k == 40
    assert merger.final_limit == 5


# ---------------------------------------------------------------------------
# RRF 融合测试
# ---------------------------------------------------------------------------


def test_rrf_basic():
    """验证两组非重叠 SKU 的 RRF 融合。

    关键词路:   [SKU-A (rank=1), SKU-B (rank=2)]
    语义路:     [SKU-C (rank=1), SKU-D (rank=2)]

    RRF 得分:
      SKU-A: 1/(60+1) = 0.01639
      SKU-B: 1/(60+2) = 0.01613
      SKU-C: 1/(60+1) = 0.01639
      SKU-D: 1/(60+2) = 0.01613

    排序: SKU-A, SKU-C 并列第一，然后 SKU-B, SKU-D
    (分数相同时按 sku_id 字典序)
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
    assert result[0].sku_id in ("SKU-A", "SKU-C")
    assert result[1].sku_id in ("SKU-A", "SKU-C")
    assert result[2].sku_id in ("SKU-B", "SKU-D")
    assert result[3].sku_id in ("SKU-B", "SKU-D")


def test_rrf_overlapping():
    """验证同一 SKU 出现在两路时的 RRF 得分会累加。

    关键词路: [SKU-X (rank=1), SKU-Y (rank=2)]
    语义路:   [SKU-X (rank=1)]

    RRF 得分:
      SKU-X: 1/(60+1) + 1/(60+1) = 0.03279
      SKU-Y: 1/(60+2) = 0.01613

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
    """验证关键词路为空时，仅返回语义路的结果（按 RRF 得分排序）。"""
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
    """验证返回的 SKUHit.score 为正确的 RRF 得分。

    单路单 SKU: RRF = 1/(60+1) ≈ 0.01639
    """
    merger = Merger(rrf_k=60)

    kw = [SKUHit(sku_id="SKU-1", product_id="P1", score=0.9)]

    result = merger.merge(keyword_ranked=kw, semantic_ranked=[])

    assert len(result) == 1
    assert result[0].sku_id == "SKU-1"
    assert result[0].product_id == "P1"
    assert abs(result[0].score - (1.0 / 61.0)) < 0.0001
