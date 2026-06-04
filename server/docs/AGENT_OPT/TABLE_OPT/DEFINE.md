# DEFINE.md — product_review 表更新需求分析

> 输入：`server/docs/AGENT_OPT/TABLE_OPT/SPEC.md`
> 日期：2026-06-04

## 1. 功能需求

### F1: SKU Properties 汇总生成

- 为每个 Product 汇总其所有 SKU 的 `properties` 字段信息为一句话自然人语言描述
- 使用 LLM 生成（方案 B），确保灵活处理多种属性组合
- 示例：产品 p_beauty_001 有 3 个 SKU（30ml/50ml/75ml），汇总为"本精华产品包含30ml经典装，50ml加大装和75ml家用装"

### F2: Properties 向量化写入 product_review

- 将汇总文本经 Embedding 向量化后写入 `product_review` 表
- `source` 字段设为 `"property"`
- `extra_data` 存储原始 SKU properties 列表
- `config.yaml` 的 `search.source_weights` 新增 `property: 1.0`
- `_build_weight_expr()` 的已知 source 列表新增 `"property"`

### F3: DEBUG 日志打印检索 SQL 查询结果

- 将 `_semantic_search()` 和 `_keyword_search()` 中现有 SQL 日志从 `INFO` 降为 `DEBUG`
- SQL 执行后追加 `DEBUG` 日志：`row_count` + 前 3 条结果的 `sku_id` / `content[:100]` 摘要

## 2. 性能需求

- Properties 汇总生成：全量 product 一次性处理，LLM 调用串行即可（数据量小，预估 <200 个 product）
- Embedding 可复用现有批量 API，性能无瓶颈
- DEBUG 日志仅在开发/调试场景开启，生产环境使用 INFO 级别，不影响检索性能

## 3. 最终交付物

| 交付物 | 说明 |
|--------|------|
| `server/scripts/property_summary_service.py` | 新增独立脚本，Properties 汇总 + 向量化写入 |
| `server/app/services/retriever_service.py`（修改） | `_build_weight_expr` known_sources 新增 "property"；SQL 日志级别调整 + 结果日志 |
| `server/config.yaml`（修改） | `source_weights` 新增 `property: 1.0` |
| 数据库 `product_review` 表（数据变更） | 每条 product 新增 1 行，source="property" |

## 4. 硬约束

- 不修改 `ProductReview` ORM 模型结构（source 字段长度 30，`"property"` 8 字符，足够）
- 不修改现有数据导入流程（独立脚本，方案 B）
- `source_weights` 配置项仅新增 key，不影响现有 marketing/faq/user_review 的行为
- 已存在 source="property" 的 product 需跳过，支持幂等重跑

## 5. 隐含要求

- 脚本需要支持独立运行，可访问 DB、LLM、Embedding 三个外部依赖
- LLM 调用需有错误处理和重试（与现有 LLMService 风格一致）
- Properties 汇总文本需在向量化前做好截断（适配 Embedding 模型 token 限制）
- DEBUG 日志截断行数据避免日志爆炸（content 截断到 100 字符）

## 6. 任务完成边界

- ✅ Properties 汇总脚本可独立运行，完成全量 product 处理
- ✅ `product_review` 表新增 source="property" 记录，向量化完成
- ✅ 后续数据导入（`import_json_dir`）无需感知此变更
- ✅ 检索链路正确加权 property source
- ✅ DEBUG 级别下可观测 keyword_search / semantic_search 查询结果
- ❌ 不做增量更新（变更 product SKU 时自动重生成汇总）—— 超出范围
- ❌ 不修改 `import_json_dir` 管道 —— 独立脚本

## 7. 风险点

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 生成质量不稳定 | 汇总文本不通顺/遗漏属性 | Prompt 中提供示例约束格式；生成后做基本校验（非空、含关键词） |
| SKU 无 properties 字段 | 空汇总，无意义记录 | 跳过无 properties 的 SKU 或整个 product |
| LLM/Embedding API 不可用 | 脚本中断 | 单条失败不阻断整体，记录失败 product_id 到日志；支持重跑（幂等跳过已处理） |
| DEBUG 日志量过大 | 调试时终端刷屏 | 仅打印前 3 条，content 截断 100 字符 |

---

## 已确认决策

1. **脚本入口方式**：使用 `if __name__ == "__main__"` + `asyncio.run()` 方式，与 `run.py` 一致。
2. **LLM prompt**：直接在脚本中硬编码，不单独创建 prompt 文件。
