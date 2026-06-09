# CON_PLAN.md — 编码级详细设计

> 输入：`PLAN.md` → 输出：本文件
> 日期：2026-06-09

## 1. 执行策略

分 3 波执行，每波流程：`git mv` 文件 → 更新 import/引用 → 跑测试验证。每波通过后才进入下一波。

---

## 2. 波 1：Prompt 文件重命名（6 文件）

### 2.1 文件操作

```bash
cd server/app/agent/prompts

git mv category_intro_prompt.py category_introduct_prompt.py
git mv extraction_prompt.py intent_extract_prompt.py
git mv option_gen_prompt.py option_generate_prompt.py
git mv product_reason_prompt.py product_recommendation_prompt.py
git mv scenario_gen_prompt.py scene_generate_prompt.py
git mv unified_router_prompt.py intent_router_prompt.py
```

### 2.2 常量重命名（在同文件内）

| 文件 | 旧名 → 新名 |
|------|------------|
| `category_introduct_prompt.py` | `CATEGORY_INTRO_SYSTEM` → `CATEGORY_INTRODUCT_SYSTEM` |
| `intent_extract_prompt.py` | `EXTRACTION_STEP1_SYSTEM` → `INTENT_EXTRACT_STEP1_SYSTEM` |
| `intent_extract_prompt.py` | `EXTRACTION_STEP3_SYSTEM` → `INTENT_EXTRACT_STEP3_SYSTEM` |
| `option_generate_prompt.py` | `ENDING_OPTION_SYSTEM` → `OPTION_GENERATE_SYSTEM` |
| `product_recommendation_prompt.py` | `PRODUCT_REASON_SYSTEM` → `PRODUCT_RECOMMENDATION_SYSTEM` |
| `scene_generate_prompt.py` | `SCENARIO_GEN_SYSTEM` → `SCENE_GENERATE_SYSTEM` |
| `intent_router_prompt.py` | `UNIFIED_ROUTER_SYSTEM` → `INTENT_ROUTER_SYSTEM` |

### 2.3 import 引用更新

#### `app/agent/nodes/router.py` (即未来的 `intent_route_agent.py`)

```python
# 旧
from app.agent.prompts.unified_router_prompt import UNIFIED_ROUTER_SYSTEM

# 新
from app.agent.prompts.intent_router_prompt import INTENT_ROUTER_SYSTEM
```
内部引用 `UNIFIED_ROUTER_SYSTEM` 的所有位置 → `INTENT_ROUTER_SYSTEM`

#### `app/agent/nodes/extraction.py` (即未来的 `intent_extract_agent.py`)

```python
# 旧
from app.agent.prompts.extraction_prompt import EXTRACTION_STEP1_SYSTEM, EXTRACTION_STEP3_SYSTEM

# 新
from app.agent.prompts.intent_extract_prompt import INTENT_EXTRACT_STEP1_SYSTEM, INTENT_EXTRACT_STEP3_SYSTEM
```
内部引用 `EXTRACTION_STEP1_SYSTEM` → `INTENT_EXTRACT_STEP1_SYSTEM`
内部引用 `EXTRACTION_STEP3_SYSTEM` → `INTENT_EXTRACT_STEP3_SYSTEM`

#### `app/agent/nodes/retriever.py` (即未来的 `product_retrieve_agent.py`)

```python
# 旧
from app.agent.prompts.category_intro_prompt import CATEGORY_INTRO_SYSTEM
from app.agent.prompts.product_reason_prompt import PRODUCT_REASON_SYSTEM

# 新
from app.agent.prompts.category_introduct_prompt import CATEGORY_INTRODUCT_SYSTEM
from app.agent.prompts.product_recommendation_prompt import PRODUCT_RECOMMENDATION_SYSTEM
```
内部引用 `CATEGORY_INTRO_SYSTEM` → `CATEGORY_INTRODUCT_SYSTEM`
内部引用 `PRODUCT_REASON_SYSTEM` → `PRODUCT_RECOMMENDATION_SYSTEM`

#### `app/agent/nodes/option_gen.py` (即未来的 `option_generate_agent.py`)

```python
# 旧
from app.agent.prompts.option_gen_prompt import ENDING_OPTION_SYSTEM

# 新
from app.agent.prompts.option_generate_prompt import OPTION_GENERATE_SYSTEM
```
内部引用 `ENDING_OPTION_SYSTEM` → `OPTION_GENERATE_SYSTEM`

#### `app/agent/nodes/scenario_gen.py` (即未来的 `scene_generate_agent.py`)

```python
# 旧
from app.agent.prompts.scenario_gen_prompt import SCENARIO_GEN_SYSTEM

# 新
from app.agent.prompts.scene_generate_prompt import SCENE_GENERATE_SYSTEM
```
内部引用 `SCENARIO_GEN_SYSTEM` → `SCENE_GENERATE_SYSTEM`

### 2.4 测试文件更新

#### `tests/test_router.py`
```python
from app.agent.prompts.unified_router_prompt import UNIFIED_ROUTER_SYSTEM
→
from app.agent.prompts.intent_router_prompt import INTENT_ROUTER_SYSTEM
```
断言中 `UNIFIED_ROUTER_SYSTEM` → `INTENT_ROUTER_SYSTEM`

#### `tests/test_extraction.py`
```python
from app.agent.prompts.extraction_prompt import EXTRACTION_STEP1_SYSTEM
→
from app.agent.prompts.intent_extract_prompt import INTENT_EXTRACT_STEP1_SYSTEM
```
```python
from app.agent.prompts.extraction_prompt import EXTRACTION_STEP3_SYSTEM
→
from app.agent.prompts.intent_extract_prompt import INTENT_EXTRACT_STEP3_SYSTEM
```
断言中对应常量名更新。

#### `tests/test_option_gen.py`
```python
from app.agent.prompts.option_gen_prompt import ENDING_OPTION_SYSTEM
→
from app.agent.prompts.option_generate_prompt import OPTION_GENERATE_SYSTEM
```

#### `tests/test_scenario_gen.py`
```python
from app.agent.prompts.scenario_gen_prompt import SCENARIO_GEN_SYSTEM
→
from app.agent.prompts.scene_generate_prompt import SCENE_GENERATE_SYSTEM
```

#### `tests/test_price_adjust_integration.py`
```python
from app.agent.prompts.extraction_prompt import EXTRACTION_STEP3_SYSTEM
→
from app.agent.prompts.intent_extract_prompt import INTENT_EXTRACT_STEP3_SYSTEM
```

### 2.5 波 1 验证

```bash
cd server && python -m pytest tests/ -v --ignore=tests/TMP --ignore=tests/test_e2e.py \
  --ignore=tests/test_llm.py --ignore=tests/test_embedding.py --ignore=tests/test_sync.py \
  --ignore=tests/test_search.py --ignore=tests/test_retriever.py --ignore=tests/test_generator.py \
  --ignore=tests/test_products.py --ignore=tests/test_category_lookup.py \
  --ignore=tests/test_query_parser.py --ignore=tests/test_sku_utils.py \
  --ignore=tests/test_merger.py -k "not test_real_llm"
```

---

## 3. 波 2：Agent 文件重命名（5 文件）

### 3.1 文件操作

```bash
cd server/app/agent/nodes

git mv extraction.py intent_extract_agent.py
git mv option_gen.py option_generate_agent.py
git mv retriever.py product_retrieve_agent.py
git mv router.py intent_route_agent.py
git mv scenario_gen.py scene_generate_agent.py
```

### 3.2 函数/常量重命名（在同文件内）

| 文件 | 旧名 → 新名 |
|------|------------|
| `intent_route_agent.py` | `router_node` → `intent_route_node` |
| `intent_route_agent.py` | `_parse_router_response` → `_parse_route_response` |
| `intent_extract_agent.py` | `extraction_node` → `intent_extract_node` |
| `option_generate_agent.py` | `option_gen_node` → `option_generate_node` |
| `product_retrieve_agent.py` | `retrieval_node` → `product_retrieve_node` |
| `scene_generate_agent.py` | `scenario_gen_node` → `scene_generate_node` |

### 3.3 `graph.py` 更新

```python
# 旧
from app.agent.nodes.router import router_node
from app.agent.nodes.extraction import extraction_node
from app.agent.nodes.scenario_gen import scenario_gen_node
from app.agent.nodes.retriever import retrieval_node
from app.agent.nodes.option_gen import option_gen_node

# 新
from app.agent.nodes.intent_route_agent import intent_route_node
from app.agent.nodes.intent_extract_agent import intent_extract_node
from app.agent.nodes.scene_generate_agent import scene_generate_node
from app.agent.nodes.product_retrieve_agent import product_retrieve_node
from app.agent.nodes.option_generate_agent import option_generate_node
```

`graph.py` 内所有旧的函数名调用同步替换：
- `router_node` → `intent_route_node`
- `extraction_node` → `intent_extract_node`
- `scenario_gen_node` → `scene_generate_node`
- `retrieval_node` → `product_retrieve_node`
- `option_gen_node` → `option_generate_node`

### 3.4 测试文件更新

#### `tests/test_router.py`
```python
# 旧
from app.agent.nodes.router import router_node, _parse_router_response, _format_recent_queries
# 新
from app.agent.nodes.intent_route_agent import intent_route_node, _parse_route_response, _format_recent_queries
```
所有 `router_node(...)` → `intent_route_node(...)`
所有 `_parse_router_response(...)` → `_parse_route_response(...)`

#### `tests/test_extraction.py`
```python
# 旧
from app.agent.nodes.extraction import (
    extraction_node, _build_context_with_memory, _extract_categories_and_brands, _parse_json_array,
)
# 新
from app.agent.nodes.intent_extract_agent import (
    intent_extract_node, _build_context_with_memory, _extract_categories_and_brands, _parse_json_array,
)
```
所有 `extraction_node(...)` → `intent_extract_node(...)`

#### `tests/test_option_gen.py`
```python
# 旧
from app.agent.nodes.option_gen import option_gen_node
# 新
from app.agent.nodes.option_generate_agent import option_generate_node
```
所有 `option_gen_node(...)` → `option_generate_node(...)`

#### `tests/test_scenario_gen.py`
```python
# 旧
from app.agent.nodes.scenario_gen import scenario_gen_node, _cross_validate_categories
# 新
from app.agent.nodes.scene_generate_agent import scene_generate_node, _cross_validate_categories
```
所有 `scenario_gen_node(...)` → `scene_generate_node(...)`

#### `tests/test_retrieval_node.py`
```python
# 旧
from app.agent.nodes.retriever import (
# 新
from app.agent.nodes.product_retrieve_agent import (
```
所有 `retrieval_node(...)` → `product_retrieve_node(...)`

#### `tests/test_price_adjust_integration.py`
```python
# 旧
from app.agent.nodes.extraction import _extract_intents_per_category
# 新
from app.agent.nodes.intent_extract_agent import _extract_intents_per_category
```

### 3.5 波 2 验证

同波 1 验证命令。

---

## 4. 波 3：API 文件重命名（2 文件）

### 4.1 文件操作

```bash
cd server/app/api

git mv products.py get_product_info.py
git mv conversation.py get_conversation.py
```

### 4.2 `main.py` 更新

```python
# 旧
from app.api import search, products, admin, conversation
app.include_router(products.router)
app.include_router(conversation.router)

# 新
from app.api import search, get_product_info, admin, get_conversation
app.include_router(get_product_info.router)
app.include_router(get_conversation.router)
```

注意：`products` 的 router 注册也在第 33 行附近，`conversation` 在第 35 行附近。

### 4.3 `tests/test_batch_api.py` 更新

```python
# 旧
from app.api.products import _normalize_ids
# 新
from app.api.get_product_info import _normalize_ids
```

### 4.4 波 3 验证

```bash
# 验证 API 路由可正常导入
cd server && python -c "from app.main import app; print('OK')"
```

---

## 5. 设计文档引用更新

`server/docs/` 下 `.md` 文件中的旧文件名/模块名同步更名。

```bash
# 扫描 docs 中旧引用
grep -rn "extraction\.py\|option_gen\.py\|retriever\.py\|router\.py\|scenario_gen\.py" server/docs/
grep -rn "unified_router_prompt\|extraction_prompt\|option_gen_prompt\|scenario_gen_prompt\|product_reason_prompt\|category_intro_prompt" server/docs/
grep -rn "api/products\|api/conversation" server/docs/
```

逐文件替换旧引用。

---

## 6. 期望目录结构（改动后）

```
server/app/
├── agent/
│   ├── nodes/
│   │   ├── intent_extract_agent.py      # 原 extraction.py
│   │   ├── intent_route_agent.py        # 原 router.py
│   │   ├── option_generate_agent.py     # 原 option_gen.py
│   │   ├── product_retrieve_agent.py    # 原 retriever.py
│   │   └── scene_generate_agent.py      # 原 scenario_gen.py
│   ├── prompts/
│   │   ├── category_introduct_prompt.py # 原 category_intro_prompt.py
│   │   ├── intent_extract_prompt.py     # 原 extraction_prompt.py
│   │   ├── intent_router_prompt.py      # 原 unified_router_prompt.py
│   │   ├── option_generate_prompt.py    # 原 option_gen_prompt.py
│   │   ├── product_recommendation_prompt.py # 原 product_reason_prompt.py
│   │   └── scene_generate_prompt.py     # 原 scenario_gen_prompt.py
│   ├── graph.py                         # import 更新
│   ├── memory.py                        # 不变
│   ├── state.py                         # 不变
│   └── utils/
├── api/
│   ├── get_product_info.py              # 原 products.py
│   ├── get_conversation.py              # 原 conversation.py
│   ├── search.py                        # 不变
│   └── admin.py                         # 不变
└── main.py                              # import + include_router 更新
```

---

## 7. 风险点和注意事项

| 项 | 说明 |
|-----|------|
| `graph.py` 中函数调用必须同步 | 不仅是 import，graph 内部 add_node/add_edge 参数中的函数名也要改 |
| `_format_recent_queries` 不改名 | 内部辅助函数，SPEC 未要求 |
| `_build_context_with_memory` 等不改名 | 内部辅助函数 |
| `_cross_validate_categories` 不改名 | 内部辅助，但有测试引用 — 路径更新即可 |
| `test_batch_api.py` 的 `_normalize_ids` | 仅 import 路径更新，函数名不变 |
| design docs 引用 | `CON_PLAN.md`、`PLAN.md`、`DEFINE.md` 等有旧文件名的，同步更新 |

---

> 编码可直接开始。执行策略：波 1 → 验证 → 波 2 → 验证 → 波 3 → 验证 → 全量测试。
