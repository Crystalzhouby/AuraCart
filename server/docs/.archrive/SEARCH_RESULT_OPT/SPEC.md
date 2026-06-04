# /search/stream检索结果优化
```
# ---- 阶段 3: RRF 融合与排序 ----
ranked_skuhits = merger.merge(
    keyword_ranked=keyword_hits,
    semantic_ranked=semantic_hits,
)
ranked_pids = [h.product_id for h in ranked_skuhits]
products = await _get_products(db, ranked_pids)

products_summary = [
    {"product_id": p["product_id"], "title": p["title"],
        "brand": p["brand"], "base_price": p["base_price"]}
    for p in products
]
pipeline_log.info("阶段3: 合并排序结果",
                    ranked_count=len(ranked_pids),
                    products=products_summary)

yield {"event": "products", "data": json.dumps(products, ensure_ascii=False)}
```
以上检索返回结果的单位是product，这不正确，返回的单位应该是sku，上一步检索的结果包含了sku_id和product_id。

最终期望的返回结果包含了sku_id对应销售单品所属的商品的product_id、title、brand、category、sub_category以及sku_id对应销售单品的sku_id、properties、price和stock。