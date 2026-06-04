# 问题

## SQL查询信息不完备

**当前SQL节点的Product Retrieval的SQL语句只检索了product_id,sku_id和score，没有返回相应的product_review**，把这些product_review作为状态中的matched_texts。
不需要retrieval.py中RRF之后再去查一遍数据库，不需要以下代码：
```
# 4. 获取 SKU 详情
skus = await _get_skus(db, ranked)
```
后续生成推荐理由时，也用上述检索到的matched_texts。

## 日志打印不完备
**现在请将调用大模型时使用的提示词也打印出来，打印的提示词其占位符需要已经填充了具体的内容。**

## 完善SQL语句的生成
当前在生成SQL语句时，我在日志server\log\app_20260602_201918.log中看到了生成的以下两个SQL语句。
首先我有一个疑问，为什么关键词检索不需要GROUP BY s.sku_id, p.product_id？
此外，**由于LLM给出的关键词与评论所用的关键词有偏离，如果强制检索的评论必须含有LLM给出的关键词，可能会导致查询结果为空，这会导致漏掉大量检索结果，需要将"WHERE pr.content_tsv @@ plainto_tsquery('chinese', '防晒霜')"条件给删除掉。**
```
# 关键词检索
SELECT 
    s.sku_id, 
    p.product_id, 
    (CASE pr.source 
        WHEN 'marketing'   THEN 1.0 
        WHEN 'faq'         THEN 1.0 
        WHEN 'user_review' THEN 0.7 
        ELSE 1.0 
     END * ts_rank(pr.content_tsv, plainto_tsquery('chinese', '防晒霜'))
    ) AS score 
FROM product_review pr 
JOIN product p ON p.product_id = pr.product_id AND p.is_active = TRUE 
JOIN sku s ON s.product_id = p.product_id AND s.is_active = TRUE 
WHERE 
    pr.content_tsv @@ plainto_tsquery('chinese', '防晒霜')
ORDER BY score DESC 
LIMIT 20;

# 语义检索
SELECT 
    s.sku_id, 
    p.product_id, 
    SUM(CASE pr.source 
            WHEN 'marketing'   THEN 1.0 
            WHEN 'faq'         THEN 1.0 
            WHEN 'user_review' THEN 0.7 
            ELSE 1.0 
        END * (1 - (pr.embedding <=> '[0.09198962897062302, -0.02875818870961666, -0.031089933589100838, -0.0019602661]'))
    ) AS score 
FROM product_review pr 
JOIN product p ON p.product_id = pr.product_id AND p.is_active = TRUE 
JOIN sku s ON s.product_id = p.product_id AND s.is_active = TRUE 
GROUP BY s.sku_id, p.product_id 
ORDER BY score DESC 
LIMIT 20;
```