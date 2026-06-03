# DEFINE.md — 查询解析品类约束优化

> 输入：`server/docs/AGENT_OPT/QUERY_PARSE_OPT/SPEC.md`
> 输出：需求分析文档

## 1. 功能需求

| ID | 需求 | 说明 |
|----|------|------|
| **FR1** | 品类取值约束 | LLM 生成的 `category` / `sub_category` 必须来自 `category_lookup` 表 |
| **FR2** | 动态注入 | 合法 (category, sub_category) 值对在运行时查询并注入提示词，不硬编码 |
| **FR3** | 双入口覆盖 | `QueryParser.parse()`（非流式管线）和 `extraction_node()`（Agent 管线）均需生效 |
| **FR4** | 向后兼容 | 不改变 `SubQuery` 数据结构、`/api/search` 接口签名和现有解析行为 |
| **FR5** | 查询失败降级 | category_lookup 查询失败时，回退到未约束提示词，不阻塞搜索 |

## 2. 性能需求

| ID | 需求 | 说明 |
|----|------|------|
| **PR1** | 低延迟查询 | category_lookup 表仅 37 行，单次 SELECT 应在 ms 级完成 |
| **PR2** | Token 可控 | 注入的品类清单应在 ~500-800 tokens 以内，不超过当前提示词 2x |
| **PR3** | 请求级缓存 | 同一次搜索中两个入口（QueryParser + extraction_node）不应重复查询 |

## 3. 最终交付物

1. 修改后的 `QUERY_PARSE_SYSTEM` 提示词模板（含品类注入点）
2. 品类查询函数（从 `category_lookup` 表加载合法值对）
3. `QueryParser` 适配：parse() 中注入品类列表
4. `extraction_node` 适配：LLM 调用前注入品类列表
5. 更新相关测试

## 4. 硬约束

- **不修改数据库 schema**：`category_lookup` 表结构不变
- **不修改 SubQuery 数据类**：字段不变（已有 `category` / `sub_category` 字段）
- **不修改 `/api/search` 接口**：请求/响应签名不变
- **不引入新的依赖**：仅使用已有的 SQLAlchemy + structlog

## 5. 隐含要求

- 品类清单格式应简洁，避免 LLM 忽略（已知 LLM 对长列表的注意力衰减）
- 提示词修改后需保持可维护性——品类列表不应手工维护
- `extraction_node` 已有独立 DB session 能力（可通过 `graph.build_graph` 注入）

## 6. 任务完成边界

**范围内：**
- 修改 `QUERY_PARSE_SYSTEM` 模板，添加 `{category_list}` 占位符
- 新增品类查询辅助函数
- 修改 `QueryParser` 和 `extraction_node` 调用链

**范围外：**
- 不修改 `category_lookup` 表结构或数据
- 不修改 RRF 融合、推荐生成等其他管线阶段
- 不添加品类"模糊匹配"或"语义扩展"——仅做硬约束

## 7. 风险点

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 仍输出不存在的品类 | FR1 失效 | 提示词中强调"只能从列表中选择"，必要时在解析层做后校验 + 修正 |
| 品类清单过长导致 token 膨胀 | 成本增加、LLM 注意力衰减 | 当前仅 37 行，按 `category: [sub1, sub2, ...]` 聚合后约 400 tokens |
| category_lookup 表为空 | 品类约束完全失效 | 检测空表 → fallback 到未约束提示词 + WARNING 日志 |
| DB 查询失败 | 搜索被阻断 | FR5: catch 异常 → fallback + WARNING 日志 |

## 8. [NEEDS CLARIFICATION] 待确认

1. **品类格式**：提示词中应如何展示合法品类列表？
   - 方案 A：按 category 分组——`面部护肤: [防晒霜, 洗面奶, 面霜, ...]`（紧凑，~400 tokens）
   - 方案 B：逐行列出——`(面部护肤, 防晒霜) (面部护肤, 洗面奶) ...`（冗长，~700 tokens）
   - **推荐 A**，更紧凑且 LLM 易于参照
方案A

2. **后校验策略**：当 LLM 仍然输出不在列表中的 category/sub_category 时，是否需要代码层兜底？
   - 方案 A：仅依赖提示词约束（简单，LLM 遵循度较高）
   - 方案 B：提示词约束 + 代码层后校验，将不在列表中的值置 null（兜底更稳）
   - **推荐 B**，校验逻辑简单（O(1) set lookup），成本极低
方案B

3. **无品类匹配场景**：当用户查询确实无法匹配任何已知品类时（如"送朋友的礼物"），LLM 应输出 null 还是尝试匹配最近似品类？当前提示词已写"无法确定时保持 null"——是否保持此行为？
保障后续该用户查询能够可以匹配任一category即可（因为无法确定，所以用户想要的物品可能属于任一品类）
