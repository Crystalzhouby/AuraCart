# /search/stream 查询优化 — 问题定义

## 1. 最终交付物

优化后的 `/api/search/stream` 检索管线：

- **Phase 1**: 重写 `QUERY_PARSE_SYSTEM` prompt — semantic 输出评价短句、keyword 输出具体关键词、structured_filter 覆盖 product/sku 表字段（含 `sku.properties` JSONB）
- **Phase 2**: 重构检索执行 — structured_filter 作为 SQL 硬约束、多 semantic 独立打分后加和、keyword 用 `ts_rank` 近似 BM25、双路 `asyncio.gather` 并行后 RRF 融合
- **Phase 3**: merger 重写为 RRF 融合，检索结果单位从 product 切换为 SKU
- **配置更新**: `config.yaml` search 组（移除 `source_weights`/`min_results_threshold`，新增 `rrf_k`，重命名 `final_product_limit` → `final_sku_limit`）
- **SubQuery 简化**: 移除 `negation` 字段，否定语义由 operator（`not_in`/`not_contains`）或语义相似度自然降权表达
- 相关测试适配

---

## 2. 硬约束

1. 基础设施不变：PostgreSQL + pgvector，不引入新数据库或搜索引擎
2. SSE 事件流对外契约不变：`products` → `reasoning` → `done`/`error`
3. 模块边界不变：`api/` → `services/` → `rag/` 分层
4. LLM 查询解析方案不变（不可退化为规则引擎）
5. 超时降级兜底机制必须保留
6. `config.yaml` 作为唯一运行时配置入口

---

## 3. 隐含要求

1. **BM25 替代方案**：PostgreSQL 无原生 BM25。**已明确**：用 `ts_rank` 近似替代。

2. **SKU 级检索映射**：当前 embedding 在 `product_review` 表（product 级），非 SKU 级。**已明确**：product 级语义得分直接继承给其下所有 SKU。

3. **RRF 参数 k 值**：**已明确**：k=60。

4. **`sku.properties` 字段可过滤性**：properties 为 JSONB 且不同 sub_category 的 SKU 的 property key 不同。LLM 解析时需要知道目标 SKU 有哪些可过滤的 key。**已明确**：预扫描方式——先提取用户查询对应的 sub_category，注入 prompt 时只暴露该 sub_category 下的 properties key 集合。**注意**：此预扫描机制在当前实现中尚未完成，需后续补充。

5. **否定条件处理**：**已明确**：不保留 `negation` 标记。结构化否定（品牌/价格）→ `NOT IN`/`NOT ILIKE` SQL 子句；内容级否定（"不含酒精"）→ 转为 semantic 查询（"产品评价中是否提及酒精成分"），依赖语义相似度自然降权。

6. **内容级否定的覆盖局限**：一个产品有多条 review，embedding 是 review 级别。若大部分 review 正面且未提及某成分，即使有一条提及，产品级平均语义得分仍可能偏高导致漏过。**已明确**：当前架构下无法根本解决，属可接受精度损失。

7. **三表 JOIN**：最终检索 SQL 统一 JOIN `product_review` + `product` + `sku` 三表，结果单位为 SKU。`product_review` 与 `sku` 通过 `product_id` 间接关联。

---

## 4. 任务完成边界

**在范围内：**
- `prompt.py`：`QUERY_PARSE_SYSTEM` 重写
- `retriever.py`：检索策略重构（SubQuery 去 negation、新增 SKUHit/FilterClause/Filters、_extract_filters、_build_base_query、双路并行检索、三表 JOIN）
- `merger.py`：加权均值 → RRF 融合
- `query_parser.py`：`_parse_response` 移除 `negation` 映射
- `search.py`：SSE 编排适配新 retriever/merger 接口
- `config.yaml` + `config.py`：search 配置项更新
- 现有测试适配

**不在范围内：**
- 前端/客户端改动
- 新增 API 端点
- 数据库 schema 变更
- 新增基础设施
- `generator.py`（Phase 4 LLM 生成）逻辑改动
- sync 同步服务改动
- `/api/search`（非流式接口）改动
- `sku.properties` 预扫描注入 prompt 机制（后续补充）

---

## 5. 实现过程可能遇到的风险点

| 风险 | 影响 | 缓解 |
|------|------|------|
| `sku.properties` JSONB 查询性能 | 无 GIN 索引时全表扫描 | 当前数据量小可接受，必要时加 GIN 索引 |
| prompt 变更导致 LLM 解析质量下降 | 语义/关键词拆解不准 | 需多轮 prompt 迭代验证 |
| 多 semantic 并行向量查询 | N 次 `<=>` 计算，单条 SQL 较慢 | N 通常 ≤3，可接受 |
| RRF 参数 k=60 敏感度 | 在部分数据集非最优 | k 值对排序不敏感，先固定后续可配置化 |
| 语义否定覆盖率局限 | 多 review 产品中单条负面被平均掩盖 | 当前架构下不可解，属可接受精度损失 |
| AsyncSession 并发安全性 | keyword + semantic 双路 `asyncio.gather` 共用同一 session | 若不支持则改为各自独立 session |
| 三表 JOIN 查询性能 | product_review × product × sku JOIN 复杂度 | 数据量小可接受，必要时 EXPLAIN ANALYZE 验证 |
