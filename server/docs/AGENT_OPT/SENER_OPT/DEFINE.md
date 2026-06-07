# DEFINE.md — Retrieve 节点 Product 级别重构需求分析

## 输入

- **SPEC**: `server/docs/AGENT_OPT/SENER_OPT/SPEC.md`

## 1. 功能需求

| ID | 描述 |
|----|------|
| F1 | keyword 和 semantic 检索 SQL 返回结果不再包含 `sku_id`，改为 product 粒度 |
| F2 | SQL 仍需 JOIN sku 表获取价格信息，聚合为 SKU 列表 |
| F3 | 每个 product_id 最多保留 N 条 product_review 数据（N 可配置，默认 5） |
| F4 | 下游链路（Merger、_category_task、SSE 输出）全部适配 product 粒度 |

### F1 详细说明

- `_build_base_query` 的 SELECT 移除 `s.sku_id`，GROUP BY 移除 `s.sku_id`
- `SKUHit` 数据类改为 `ProductHit`（`product_id` + `score`）
- `hit_metadata` 的 key 从 `sku_id` 改为 `product_id`
- sku 信息（`properties`/`price`/`stock`）聚合为 JSON 数组存入每个 product 的 metadata

### F2 详细说明

- `_build_base_query` 保留 `JOIN sku s ON s.product_id = p.product_id AND s.is_active = TRUE`
- 聚合方式：`jsonb_agg(jsonb_build_object('sku_id', s.sku_id, 'properties', s.properties, 'price', s.price, 'stock', s.stock)) AS skus_json`

### F3 详细说明

- 使用子查询 + `ROW_NUMBER() OVER (PARTITION BY pr.product_id ORDER BY score DESC)` 限制每个 product 最多 N 行
- N 从 `config.yaml` 的 `search.max_chunks_per_product` 读取
- 子查询在外层 GROUP BY 之前执行

### F4 详细说明

- `Merger.merge()`: 按 `product_id` 去重/融合（原按 `sku_id`）
- `_category_task`: 结果遍历和 SSE 发送适配 product 粒度
- `retrieval_node`: `retrieval_results` 返回 product 级别数据
- `_build_product_context`: 适配 product 级别输入（SKU 列表已嵌套在内部）

## 2. 性能需求

- SQL 子查询增加 `ROW_NUMBER()` 窗口函数，需确保 `product_id` 和 `score` 有适当索引
- `product_id` 已有索引（product_review.product_id, product.product_id, sku.product_id）
- 预期影响：单次查询增加 ~±5% 延迟（窗口函数开销）

## 3. 最终交付物

### 修改文件

| 文件 | 变更程度 | 说明 |
|------|----------|------|
| `app/services/retriever_service.py` | 重度 | SKUHit→ProductHit；SQL 重构（子查询+窗口函数）；GROUP BY 改为 product 级别 |
| `app/agent/nodes/retriever.py` | 重度 | Merger 适配；_category_task 适配；SSE 适配；_build_product_context 适配 |
| `app/config.py` | 轻度 | SearchSettings 新增 `max_chunks_per_product` |
| `config.yaml` | 轻度 | `search` 段新增 `max_chunks_per_product: 5` |
| `app/services/sku_utils_service.py` | 轻度 | `_truncate_texts` 参数适配（sku→product） |
| `tests/` | 中度 | retriever/search/merger 相关测试适配新数据结构 |

## 4. 硬约束

- 不改变对外的 SSE 事件格式（products 事件仍含 `product_id`，去掉 `sku_id` 即可）
- 不改变 RRF 融合算法本身，只改变去重的 key
- 不改变 reranker 调用方式

## 5. 隐含要求

- `sku_utils_service.py` 中 `_truncate_texts` 的 `max_match_texts_per_sku` 参数名需改名为 product 级别
- `match_texts_per_product` 替代 `match_texts_per_sku`（仅命名，逻辑不变）
- `match_chars_per_product` 替代 `match_chars_per_sku`（仅命名，逻辑不变）
- `rerank_top_k` 和 `rrf_top_k` 现在表示 product 数量而非 SKU 数量

## 6. 任务完成边界

- keyword/semantic 检索 SQL 返回 product 粒度结果
- 每个 product 的 product_review chunk 数不超过 `max_chunks_per_product`
- 下游链路全部适配，SSE 输出正常工作
- 现有测试适配通过，无新增失败

## 7. 风险点

| 风险 | 影响 | 缓解 |
|------|------|------|
| 窗口函数性能退化 | 查询变慢 | product_id 已有索引；生产数据量小，影响可控 |
| hit_metadata key 变更导致 NPE | SSE 中断 | 全局搜索所有 sku_id 引用，逐一适配 |
| `_build_product_context` 结构变化导致推荐理由质量下降 | LLM 上下文格式变化 | 保持输出格式与原来相似，只是 SKU 信息已嵌套 |
| 配置字段重命名导致旧测试失败 | CI 失败 | 同步更新 config.yaml 和所有引用点 |
