# PLAN.md — 查询解析品类约束优化

> 输入：`DEFINE.md`（已确认）
> 输出：架构方案文档

## 1. 整体实现架构

```mermaid
graph TD
    subgraph "请求入口"
        API["/api/search"]
    end

    subgraph "品类加载层（新增）"
        LOAD["fetch_category_list()"]
        DB[("category_lookup<br/>37 rows")]
    end

    subgraph "提示词构建层"
        PROMPT["build_parse_prompt()"]
        TPL["QUERY_PARSE_SYSTEM<br/>{category_list} 占位符"]
    end

    subgraph "调用方（已有）"
        QP["QueryParser.parse()"]
        EX["extraction_node()"]
    end

    subgraph "后校验层（新增）"
        VAL["validate_categories()"]
    end

    DB -->|SELECT| LOAD
    LOAD -->|"category: [sub1, sub2, ...]"| PROMPT
    TPL --> PROMPT
    PROMPT -->|含品类列表的提示词| QP
    PROMPT -->|含品类列表的提示词| EX
    QP -->|SubQuery[]| VAL
    EX -->|SubQuery[]| VAL
    VAL -->|修正后的 SubQuery[]| 下游
```

## 2. 核心功能接口 & FR 映射

| 接口/函数 | 覆盖 FR | 说明 |
|-----------|---------|------|
| `fetch_category_list(db_session) → str` | FR1, FR5 | 查询 category_lookup → 格式化为分组字符串；异常返回 "" |
| `build_parse_prompt(db_session) → str` | FR2 | 调用 fetch → 填充 QUERY_PARSE_SYSTEM 模板 |
| `validate_categories(sub_queries, valid_set) → list` | FR1 | 后校验：不在合法集合中的 category/sub_category 置 null |
| `QueryParser.parse()` 改造 | FR3 | 接收 category_list 参数，注入提示词 |
| `extraction_node()` 改造 | FR3 | 调用前查询品类列表，注入提示词 |

## 3. 模块设计

### 3.1 `app/services/category_lookup_service.py`（新增）

- **输入**：`AsyncSession`
- **输出**：`str` — 格式化的品类清单文本
- **功能**：
  - 查询 `category_lookup` 表获取所有 (category, sub_category) 对
  - 按 category 分组聚合：`面部护肤: [防晒霜, 洗面奶, ...]`
  - 返回格式化字符串，约 400 tokens
  - 异常/空表返回 `""`

### 3.2 `app/rag/prompt.py`（修改）

- **输入**：`category_list: str`
- **输出**：完整的系统提示词
- **功能**：
  - `QUERY_PARSE_SYSTEM` 尾部添加 `{category_list}` 占位符
  - 新增 `build_parse_prompt(category_list: str) → str` 函数：填充占位符
  - 品类列表为空时，输出不含品类约束的提示词（fallback）

### 3.3 `app/services/query_parser.py`（修改）

- **输入**：`user_query: str`, `category_list: str`
- **输出**：`list[SubQuery]`
- **功能**：
  - `parse()` 新增可选参数 `category_list: str = ""`
  - 调用 `build_parse_prompt()` 组装提示词
  - 解析后调用 `validate_categories()` 做后校验

### 3.4 `app/agent/nodes/extraction.py`（修改）

- **输入**：`state: dict`, `llm: LLMService`, `valid_categories: set | None`
- **输出**：`dict`（requirements）
- **功能**：
  - 调用前通过注入的 `async_session` 查询品类列表
  - 使用 `build_parse_prompt()` 组装提示词
  - 解析后调用 `validate_categories()` 做后校验

### 3.5 `app/agent/graph.py`（修改）

- **功能**：`build_graph()` 传入品类查询所需的 db session 能力

## 4. 主要优点

- **精准约束**：LLM 只能输出数据库中实际存在的品类，消除幻读
- **动态更新**：品类随 `category_lookup` 表同步更新，无需改代码
- **双重保障**：提示词约束 + 代码后校验，防御深度足够
- **零侵入**：不修改接口签名，不修改 SubQuery 数据结构
- **降级安全**：DB 查询失败 → WARNING 日志 → 回退到未约束提示词

## 5. 主要风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| 品类列表 token 膨胀 | 低 | 37 行仅 ~400 tokens，远低于安全阈值 |
| LLM 忽略约束 | 中 | 后校验兜底 + 提示词强化"只能从列表中选择" |
| 新增 DB 查询增加延迟 | 极低 | 37 行查询 < 5ms |
| extraction_node 无 db session | 低 | `build_graph()` 已有 `async_session_factory` 参数 |

## 6. 实现复杂度评估

- **新增文件**：1 个（`category_lookup_service.py`，~40 行）
- **修改文件**：4 个（`prompt.py` +10、`query_parser.py` +15、`extraction.py` +10、`graph.py` +5）
- **新增测试**：~3 个测试用例
- **总代码量**：~100 行
- **复杂度**：🟢 低

## 7. 可测试性评估

- **单元测试友好**：品类查询函数纯 SQL，可 mock DB 返回值
- **后校验逻辑纯函数**：`validate_categories()` 无副作用，输入/输出可精确验证
- **提示词构建可验证**：检查输出字符串是否包含合法品类关键词
- **集成测试**：已有 `test_query_parser.py`（需网络），可在其中验证

## 8. 可交付性评估

- **无新增依赖**：仅使用已有 SQLAlchemy + structlog
- **无 schema 变更**：不需要迁移
- **向后兼容**：category_list 默认空字符串 → 行为与改造前一致
- **回滚简单**：删除 category_list 参数即可恢复
