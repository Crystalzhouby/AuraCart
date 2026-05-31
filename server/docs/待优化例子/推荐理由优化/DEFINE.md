# 推荐理由优化 — 问题定义

> 来源：[SPEC.md](SPEC.md) + [example.txt](example.txt) | 日期：2026-05-30

---

## 1. 功能需求

| # | 需求 | 说明 |
|---|------|------|
| F1 | **推荐理由覆盖全部商品** | LLM 生成的 reasoning 必须为 `products` 列表中的每一个独立 product 说明推荐理由，不能只介绍其中 1 个 |
| F2 | **推荐理由回应全部用户意图** | LLM 需逐条回应用户查询中的每个约束/意图（如"不含酒精""非日系品牌""200 元以下"等），不能遗漏 |
| F3 | **子查询信息注入 LLM 上下文** | 将查询解析阶段产出的 `sub_queries` 列表（含 text / strategy / field / operator / value）传入 `Generator`，作为 LLM 理解用户意图的辅助信息 |

> **关于商品推荐排序**：经代码确认，`products` 列表的排序依据是 RRF 融合得分（`Merger.merge()` 产出 `ranked_skuhits` → `_get_skus()` 保持顺序）。排名第 1 的 SKU 即 RRF 综合得分最高。

---

## 2. 性能需求

无新增性能需求。改动仅涉及 prompt 模板修改和方法签名扩展，不增加 DB 查询、LLM 调用次数或网络 IO。

---

## 3. 最终交付物

1. **`Generator.generate()` 签名扩展**：新增 `sub_queries` 参数（`list[dict] | None`，默认 `None`），向后兼容
2. **`GENERATOR_SYSTEM` 提示词更新**：新增 `{sub_queries}` 占位符，追加"覆盖全部商品"和"回应全部意图"的规则约束
3. **用户消息模板更新**：将 `sub_queries` 格式化后注入用户消息，帮助 LLM 理解已解析的用户意图
4. **`search.py` `_run_pipeline` 适配**：将 `subs_detail` 传入 `Generator.generate()`
5. **更新测试**：修改 `test_search.py` / `test_generator.py` 适配新签名和 prompt 变更

---

## 4. 硬约束

1. **不改 RAG 管线外部接口**：`GET /api/search` 的请求/响应 schema 不变，SSE 事件类型不变
2. **不增加 LLM 调用次数**：仅在现有单次 LLM 调用中修改 prompt 内容，不引入多轮对话或额外摘要调用
3. **`sub_queries` 参数向后兼容**：默认值 `None` 时 prompt 退化到当前行为
4. **prompt token 预算不显著膨胀**：`sub_queries` 文本约 100-300 字符，不会显著增加 token 消耗
5. **不修改检索/排序逻辑**：Retriever、Merger、`_get_skus` 均不改

---

## 5. 隐含要求

1. **sub_queries 的格式化**：只需 `text` 非空的子查询（`strategy="structured_filter"` 的 text 通常为空），格式化后以自然语言呈现给 LLM，而非直接输出 JSON
2. **推荐理由按 product 维度组织**：多 SKU 属于同一 product 时，合并推荐（如"巴黎欧莱雅有两款规格可选"），而不是重复介绍每个 SKU
3. **意图匹配指导**：prompt 应引导 LLM 将每个 `sub_query.text` 作为"用户关心的维度"，逐条对照 check
4. **降级行为**：`sub_queries` 为空或 `None` 时，用户消息退化为当前格式 `"请根据以上商品信息，为用户推荐：{user_query}"`，行为不变

---

## 6. 任务完成边界

### 范围内

| 项 | 说明 |
|---|------|
| 修改 `Generator.generate()` | 新增 `sub_queries: list[dict] | None = None` 参数 |
| 修改 `GENERATOR_SYSTEM` prompt | 追加规则 8（覆盖全部商品）和规则 9（回应全部意图）；新增 `{sub_queries}` 占位符 |
| 修改用户消息模板 | 将 sub_queries 格式化为"用户关心以下方面："列表注入 |
| 修改 `search.py` `_run_pipeline` | 将 `subs_detail` 传入 `generator.generate(products, q, sub_queries=...)` |
| 修改 `search.py` 非流式模式 | 同上适配 |
| 更新测试 | `test_search.py` 和 `test_generator.py` |

### 范围外

- 不修改 RRF 排序算法
- 不修改 Retriever / Merger / `_get_skus`
- 不新增 API 端点或 SSE 事件类型
- 不修改前端/客户端
- 不新增 LLM 调用做意图校验/摘要

---

## 7. 潜在风险点

| 风险 | 影响 | 缓解方向 |
|------|------|----------|
| **prompt 长度增加导致 LLM 生成质量下降**：追加规则和 sub_queries 后 system prompt 增长约 200-400 字符，可能触及 LLM 的"指令跟随衰减"效应 | 旧规则被稀释，生成质量反而下降 | 规则精简为强约束短句，避免冗长说明；必要时缩短 `【用户评价与描述】` 段落以平衡总长度 |
| **sub_queries 格式影响 LLM 理解**：直接传入 JSON 数组可能导致 LLM "角色混淆"（开始输出 JSON 而非推荐文本） | 生成内容格式异常 | 将 sub_queries 格式化为自然语言列表（如"你需要注意用户关注以下方面：1. 防晒效果... 2. 不含酒精..."），而非 JSON |
| **"必须覆盖所有商品"可能导致推荐冗长**：单次查询可能返回 10 个 SKU / 5-6 个 product，LLM 逐条推荐后 reasoning 可能超过 800 字 | 用户阅读体验下降，SSE 流生成延迟增加 | 在 prompt 中约束每个商品的推荐理由 1-2 句，总 reasoning 控制在合理范围；【不确定】是否需要配置项控制推荐理由总长度上限 |
| **product 维度的合并推荐与 SKU 维度的差异说明**：同一 product 下不同 SKU 的价格/规格差异需要说明，但 prompt 当前只按 SKU 维度提供数据 | LLM 可能单独描述每个 SKU 增加输出冗余，或遗漏 SKU 差异信息 | prompt 中明确要求"同一商品有多个 SKU 时，合并介绍商品优点，再简要说明各 SKU 规格差异和价格" |

# 不确定项

1. 是否需要配置项控制推荐理由总长度上限？
是的，需要设置。