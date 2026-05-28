# app/rag/merger.py
"""
RAG 结果合并模块 — RRF (Reciprocal Rank Fusion)。

将 keyword 和 semantic 两路已排名的 SKUHit 列表通过 RRF 公式
融合为单一排序结果。RRF 仅依赖排名而非原始分数，天然适合
异构检索源（全文排名 vs 余弦相似度）的融合。

RRF 公式: RRF(sku) = Σ 1/(k + rank_i)    (k=60, rank 从 1 开始)
"""

from app.services.retriever import SKUHit


class Merger:
    """将 keyword/semantic 两路排名结果通过 RRF 融合。

    属性:
        rrf_k: RRF 平滑参数（默认 60），用于调节排名差异权重。
        final_limit: 融合后返回的最大 SKU 数量（默认 10）。
    """

    def __init__(self, rrf_k: int = 60, final_limit: int = 10):
        self.rrf_k = rrf_k
        self.final_limit = final_limit

    def merge(
        self,
        keyword_ranked: list[SKUHit],
        semantic_ranked: list[SKUHit],
    ) -> list[SKUHit]:
        """通过 RRF 融合两路排名结果。

        参数:
            keyword_ranked: 关键词检索的排名结果（按分数降序）。
            semantic_ranked: 语义检索的排名结果（按分数降序）。

        返回值:
            按 RRF 得分降序排列的 SKUHit 列表，最多 final_limit 条。
        """
        rrf_scores: dict[str, float] = {}
        sku_map: dict[str, SKUHit] = {}

        for rank, hit in enumerate(keyword_ranked, start=1):
            rrf = 1.0 / (self.rrf_k + rank)
            rrf_scores[hit.sku_id] = rrf_scores.get(hit.sku_id, 0.0) + rrf
            if hit.sku_id not in sku_map:
                sku_map[hit.sku_id] = hit

        for rank, hit in enumerate(semantic_ranked, start=1):
            rrf = 1.0 / (self.rrf_k + rank)
            rrf_scores[hit.sku_id] = rrf_scores.get(hit.sku_id, 0.0) + rrf
            if hit.sku_id not in sku_map:
                sku_map[hit.sku_id] = hit

        ranked_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)

        return [
            SKUHit(
                sku_id=sku_map[sid].sku_id,
                product_id=sku_map[sid].product_id,
                score=rrf_scores[sid],
            )
            for sid in ranked_ids[:self.final_limit]
        ]
