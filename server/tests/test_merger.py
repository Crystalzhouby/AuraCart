# tests/test_merger.py
"""测试 Merger 服务：加权 RRF (Reciprocal Rank Fusion) 排名融合。

Merger 将 keyword 和 semantic 两路已排名的 ProductHit 列表
通过加权 RRF 公式融合为单一排序结果。

加权 RRF: score = sw/(k + sem_rank) + kw/(k + kw_rank)
默认权重: semantic=0.7, keyword=0.3, k=60
"""

import pytest
from app.services.retriever_service import ProductHit, Merger


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
    """验证两组非重叠 product 的加权 RRF 融合。

    关键词路:   [PA (rank=1), PB (rank=2)]
    语义路:     [PC (rank=1), PD (rank=2)]

    加权 RRF 得分（sw=0.7, kw=0.3）:
      PA: 0.3/(60+1) = 0.00492
      PB: 0.3/(60+2) = 0.00484
      PC: 0.7/(60+1) = 0.01148
      PD: 0.7/(60+2) = 0.01129

    排序: 语义路权重更高，PC, PD 排前面
    """
    merger = Merger(rrf_k=60)

    kw = [
        ProductHit(product_id="PA", score=0.9),
        ProductHit(product_id="PB", score=0.8),
    ]
    sem = [
        ProductHit(product_id="PC", score=0.95),
        ProductHit(product_id="PD", score=0.85),
    ]

    result = merger.merge(keyword_ranked=kw, semantic_ranked=sem)

    assert len(result) == 4
    # 语义路权重 0.7 > 关键词路权重 0.3，语义结果排前面
    assert result[0].product_id == "PC"
    assert result[1].product_id == "PD"
    assert result[2].product_id == "PA"
    assert result[3].product_id == "PB"


def test_rrf_overlapping():
    """验证同一 product 出现在两路时的加权 RRF 得分会累加。

    关键词路: [PX (rank=1), PY (rank=2)]
    语义路:   [PX (rank=1)]

    加权 RRF 得分:
      PX: 0.3/(60+1) + 0.7/(60+1) = 1.0/61 ≈ 0.01639
      PY: 0.3/(60+2) ≈ 0.00484

    PX 应在 PY 之前。
    """
    merger = Merger(rrf_k=60)

    kw = [
        ProductHit(product_id="PX", score=0.9),
        ProductHit(product_id="PY", score=0.8),
    ]
    sem = [
        ProductHit(product_id="PX", score=0.95),
    ]

    result = merger.merge(keyword_ranked=kw, semantic_ranked=sem)

    assert len(result) == 2
    assert result[0].product_id == "PX"
    assert result[1].product_id == "PY"


def test_rrf_empty_keyword():
    """验证关键词路为空时，仅返回语义路的结果（按加权 RRF 得分排序）。"""
    merger = Merger(rrf_k=60)

    sem = [
        ProductHit(product_id="PB", score=0.8),
        ProductHit(product_id="PA", score=0.9),
    ]

    result = merger.merge(keyword_ranked=[], semantic_ranked=sem)

    assert len(result) == 2
    # rank=1 的排在前面
    assert result[0].product_id == "PB"
    assert result[1].product_id == "PA"


def test_rrf_empty_semantic():
    """验证语义路为空时，仅返回关键词路的结果。"""
    merger = Merger(rrf_k=60)

    kw = [
        ProductHit(product_id="PZ", score=0.7),
    ]

    result = merger.merge(keyword_ranked=kw, semantic_ranked=[])

    assert len(result) == 1
    assert result[0].product_id == "PZ"


def test_rrf_both_empty():
    """验证两路均为空时返回空列表。"""
    merger = Merger()
    result = merger.merge(keyword_ranked=[], semantic_ranked=[])
    assert result == []


def test_rrf_final_limit():
    """验证 final_limit 截断效果——结果数不超过 final_limit。

    5 个不同 product，但 final_limit=3，应只返回前 3 个。
    """
    merger = Merger(rrf_k=60, final_limit=3)

    kw = [
        ProductHit(product_id="P1", score=0.9),
        ProductHit(product_id="P2", score=0.8),
    ]
    sem = [
        ProductHit(product_id="P3", score=0.7),
        ProductHit(product_id="P4", score=0.6),
        ProductHit(product_id="P5", score=0.5),
    ]

    result = merger.merge(keyword_ranked=kw, semantic_ranked=sem)

    assert len(result) <= 3


def test_rrf_score_values():
    """验证返回的 ProductHit.score 为正确的加权 RRF 得分。

    关键词路单 product: RRF = 0.3/(60+1) ≈ 0.00492
    """
    merger = Merger(rrf_k=60)

    kw = [ProductHit(product_id="P1", score=0.9)]

    result = merger.merge(keyword_ranked=kw, semantic_ranked=[])

    assert len(result) == 1
    assert result[0].product_id == "P1"
    assert abs(result[0].score - (0.3 / 61.0)) < 0.0001
