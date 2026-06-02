# Retrieval Node SSE 重构 — 实现方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SSE 发送职责从 `_category_task` 剥离到 `retrieval_node`，实现检索与推送的清晰分离。

**Architecture:** 保持并行检索不变，`_category_task` 只做检索+生成返回结构化数据，`retrieval_node` 统一按品类顺序单线程发送 `products` → `reasoning` SSE 事件。删除中间函数 `_send_reasoning_sequential`。

**Tech Stack:** Python 3.12, asyncio, structlog, pytest + unittest.mock

---

## 文件结构

| 文件 | 职责 | 变更类型 |
|---|---|---|
| `server/app/agent/nodes/retrieval.py` | 3 个函数修改 + 1 个函数删除 | 修改 |
| `server/tests/test_retrieval_node.py` | 测试适配新接口 | 修改 |

---

### Task 1: `_category_task` — 移除 `queue` 参数和内部 SSE 发送

**文件:**
- 修改: `server/app/agent/nodes/retrieval.py:106-222`

- [ ] **Step 1: 修改 `_category_task` 函数签名，移除 `queue` 参数**

```python
# 将 line 106-114 的函数签名从:
async def _category_task(
    group_key: str,
    sub_queries: list[dict],
    user_query: str,
    async_session_factory,
    emb_service,
    llm,
    queue,
) -> dict:

# 改为:
async def _category_task(
    group_key: str,
    sub_queries: list[dict],
    user_query: str,
    async_session_factory,
    emb_service,
    llm,
) -> dict:
```

同时更新 docstring（line 115-118）去掉对 `queue` 的引用。

- [ ] **Step 2: 移除产品 SSE 发送逻辑（lines 165-173）**

删除以下代码块：
```python
            # 5. 发送 products SSE 事件
            product_ids = [
                {"product_id": s["product_id"], "sku_id": s["sku_id"],
                 "category": category, "sub_category": sub_category}
                for s in skus
            ]
            if queue:
                await queue.put({"event": "products", "data": product_ids})
```

将 `product_ids` 构建移到 summary 构建之前，并保留为变量供返回值使用：

```python
            # 5. 构建 product_ids（供 retrieval_node 发送 SSE）
            product_ids = [
                {"product_id": s["product_id"], "sku_id": s["sku_id"],
                 "category": category, "sub_category": sub_category}
                for s in skus
            ]
```

- [ ] **Step 3: 修改正常返回结构（lines 206-212）**

将 `reasoning_tokens`（list）改为 `reasoning_text`（str），并新增 `product_ids` 字段：

```python
            # 返回结构化结果供 retrieval_node 统一发送 SSE
            return {
                "category": category,
                "sub_category": sub_category,
                "products_summary": summary,
                "product_ids": product_ids,
                "reasoning_text": "".join(tokens),
                "error": None,
            }
```

- [ ] **Step 4: 修改空结果返回（lines 156-161）**

在 `if not ranked:` 分支增加 `product_ids` 和 `reasoning_text` 字段：

```python
            if not ranked:
                return {
                    "category": category,
                    "sub_category": sub_category,
                    "products_summary": [],
                    "product_ids": [],
                    "reasoning_text": "",
                    "error": None,
                }
```

- [ ] **Step 5: 修改异常返回（lines 214-222）**

将 `reasoning_tokens: []` 改为 `reasoning_text: ""`，新增 `product_ids: []`：

```python
    except Exception as e:
        logger.error(f"品类检索失败: {category}/{sub_category}", error=str(e))
        return {
            "category": category,
            "sub_category": sub_category,
            "products_summary": [],
            "product_ids": [],
            "reasoning_text": "",
            "error": str(e),
        }
```

- [ ] **Step 6: 更新 `_bounded_task` 调用处（line 306-309）**

`retrieval_node` 内部 `_bounded_task` 不再传递 `queue`：

```python
    async def _bounded_task(key, subs):
        async with semaphore:
            return await _category_task(
                key, subs, user_query, async_session_factory, emb_service, llm
            )
```

---

### Task 2: 删除 `_send_reasoning_sequential`

**文件:**
- 修改: `server/app/agent/nodes/retrieval.py:225-267`
- 修改: `server/tests/test_retrieval_node.py:1-11`（import）

- [ ] **Step 1: 删除 `_send_reasoning_sequential` 函数**

删除 `server/app/agent/nodes/retrieval.py` 的 lines 225-267（整个函数及其 docstring）。

- [ ] **Step 2: 从测试文件中移除相关 import**

`server/tests/test_retrieval_node.py` line 10：
```python
# 旧:
from app.agent.nodes.retrieval import (
    _group_sub_queries, _aggregate_results, retrieval_node, _send_reasoning_sequential
)
# 新:
from app.agent.nodes.retrieval import (
    _group_sub_queries, _aggregate_results, retrieval_node
)
```

- [ ] **Step 3: 删除对应的 3 个测试函数**

删除以下测试（它们测试的函数已不存在）：
- `test_send_reasoning_sequential_ordered_by_groups` (lines 120-155)
- `test_send_reasoning_sequential_skips_failed` (lines 157-179)
- `test_send_reasoning_sequential_empty_queue` (lines 182-187)

---

### Task 3: `retrieval_node` — 内联品类顺序式 SSE 发送

**文件:**
- 修改: `server/app/agent/nodes/retrieval.py:270-338`

- [ ] **Step 1: 替换 `_send_reasoning_sequential` 调用为内联 SSE 循环**

删除 lines 328-329：
```python
    # Step 4: 品类顺序式发送 reasoning（Q1 方案B）
    await _send_reasoning_sequential(safe_results, group_key_list, queue)
```

替换为：
```python
    # Step 4: 品类顺序式发送 products + reasoning（Q1 方案B）
    if queue:
        for r in safe_results:
            if r.get("error"):
                continue
            # 发送 products 事件
            product_ids = r.get("product_ids", [])
            if product_ids:
                await queue.put({"event": "products", "data": product_ids})
            # 发送 reasoning 事件
            reason = r.get("reasoning_text", "")
            if reason:
                await queue.put({
                    "event": "reasoning",
                    "data": {
                        "token": reason,
                        "category": r.get("category", ""),
                        "sub_category": r.get("sub_category", ""),
                    }
                })
```

- [ ] **Step 2: 更新异常回退结构的字段**

在 `asyncio.gather` 的异常处理分支（lines 318-324），字段名对齐新接口：

```python
            safe_results.append({
                "category": "", "sub_category": key,
                "products_summary": [], "product_ids": [],
                "reasoning_text": "",
                "error": str(r),
            })
```

---

### Task 4: 更新测试 `test_retrieval_node_basic`

**文件:**
- 修改: `server/tests/test_retrieval_node.py:82-112`

- [ ] **Step 1: 移除 queue 断言残留引用，确保 mock 结果字段适配**

`test_retrieval_node_basic` 的 mock session 返回结果会触发 `_category_task` 异常（Mock 不完整），但测试只验证返回结构，行为不变。无需修改测试代码本身。

验证：`retrieval_node` 返回 `{"products_summary": [], "failed_categories": [...]}` 结构仍然正确。

---

### Task 5: 更新测试 `test_retrieval_node_sends_sequential_reasoning`

**文件:**
- 修改: `server/tests/test_retrieval_node.py:190-232`

- [ ] **Step 1: 替换测试，改为验证 `retrieval_node` 内联 SSE 发送**

将整个测试函数替换为：

```python
@pytest.mark.asyncio
async def test_retrieval_node_inline_sse_sends_products_and_reasoning():
    """retrieval_node 应按品类顺序内联发送 products → reasoning SSE 事件。"""
    queue = asyncio.Queue()

    # 构造 safe_results 模拟并行任务已完成
    safe_results = [
        {
            "category": "防晒", "sub_category": "防晒霜",
            "products_summary": [{"product_id": "p1", "sku_id": "s1", "title": "安热沙", "price": 198}],
            "product_ids": [{"product_id": "p1", "sku_id": "s1", "category": "防晒", "sub_category": "防晒霜"}],
            "reasoning_text": "安热沙推荐理由",
            "error": None,
        },
        {
            "category": "服饰", "sub_category": "墨镜",
            "products_summary": [{"product_id": "p2", "sku_id": "s2", "title": "雷朋", "price": 599}],
            "product_ids": [{"product_id": "p2", "sku_id": "s2", "category": "服饰", "sub_category": "墨镜"}],
            "reasoning_text": "雷朋推荐理由",
            "error": None,
        },
    ]

    # 模拟 retrieval_node 内联 SSE 发送逻辑
    for r in safe_results:
        if r.get("error"):
            continue
        product_ids = r.get("product_ids", [])
        if product_ids:
            await queue.put({"event": "products", "data": product_ids})
        reason = r.get("reasoning_text", "")
        if reason:
            await queue.put({
                "event": "reasoning",
                "data": {
                    "token": reason,
                    "category": r.get("category", ""),
                    "sub_category": r.get("sub_category", ""),
                }
            })

    # 验证事件顺序：品类1 products → 品类1 reasoning → 品类2 products → 品类2 reasoning
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert len(events) == 4
    assert events[0]["event"] == "products"
    assert events[0]["data"][0]["product_id"] == "p1"
    assert events[1]["event"] == "reasoning"
    assert events[1]["data"]["token"] == "安热沙推荐理由"
    assert events[2]["event"] == "products"
    assert events[2]["data"][0]["product_id"] == "p2"
    assert events[3]["event"] == "reasoning"
    assert events[3]["data"]["token"] == "雷朋推荐理由"
```

- [ ] **Step 2: 新增失败品类跳过测试**

```python
@pytest.mark.asyncio
async def test_retrieval_node_inline_sse_skips_failed_categories():
    """失败品类不应发送 products 或 reasoning 事件。"""
    queue = asyncio.Queue()

    safe_results = [
        {
            "category": "", "sub_category": "防晒霜",
            "products_summary": [], "product_ids": [],
            "reasoning_text": "", "error": "timeout",
        },
    ]

    for r in safe_results:
        if r.get("error"):
            continue
        product_ids = r.get("product_ids", [])
        if product_ids:
            await queue.put({"event": "products", "data": product_ids})
        reason = r.get("reasoning_text", "")
        if reason:
            await queue.put({"event": "reasoning", "data": {"token": reason, "category": r.get("category", ""), "sub_category": r.get("sub_category", "")}})

    assert queue.empty()
```

---

### Task 6: 运行测试并修复回归

- [ ] **Step 1: 运行 retrieval node 测试**

```bash
cd server && D:/anaconda_env/envs/AuraCart/python.exe -m pytest tests/test_retrieval_node.py -v
```
期望: 8 passed（6 原有 - 3 删除 + 2 新增 + 1 不变 = 6? No... 原有 11 个测试，删 3 个，test_retrieval_node_sends_sequential_reasoning 被替换，test_retrieval_node_basic 不变。应该是 11 - 3 - 1 + 2 = 9 个测试）

原有测试：
1. test_group_sub_queries_by_sub_category
2. test_group_sub_queries_fallback_to_category
3. test_group_sub_queries_fallback_to_default
4. test_aggregate_results_success
5. test_aggregate_results_with_failures
6. test_aggregate_results_empty_input
7. test_retrieval_node_basic
8. test_send_reasoning_sequential_ordered_by_groups (删除)
9. test_send_reasoning_sequential_skips_failed (删除)
10. test_send_reasoning_sequential_empty_queue (删除)
11. test_retrieval_node_sends_sequential_reasoning (替换)

替换后 + 新增：8 个（原 7 保留 + 2 新增 = 9）

- [ ] **Step 2: 运行全量离线测试确保无回归**

```bash
cd server && D:/anaconda_env/envs/AuraCart/python.exe -m pytest tests/ -v --ignore=tests/test_e2e.py --ignore=tests/test_llm.py --ignore=tests/test_embedding.py --ignore=tests/test_sync.py --ignore=tests/test_search.py --ignore=tests/test_retriever.py --ignore=tests/test_generator.py --ignore=tests/test_products.py --ignore=tests/test_category_lookup.py --ignore=tests/test_query_parser.py --ignore=tests/test_sku_utils.py --ignore=tests/test_merger.py
```
期望: 全部通过，0 回归。

- [ ] **Step 3: Commit**

```bash
git add server/app/agent/nodes/retrieval.py server/tests/test_retrieval_node.py
git commit -m "refactor(retrieval): move SSE sending from _category_task to retrieval_node"
```

---

### 变更汇总

| 函数 | 变更 |
|---|---|
| `_category_task` | 移除 `queue` 参数；移除 `queue.put("products")`；`reasoning_tokens` → `reasoning_text`；新增 `product_ids` 返回字段 |
| `retrieval_node` | `_bounded_task` 不再传 `queue`；内联品类顺序 SSE 循环替代 `_send_reasoning_sequential`；异常回退字段对齐 |
| `_send_reasoning_sequential` | **删除** |

| SSE 事件 | 发送方（旧） | 发送方（新） |
|---|---|---|
| `products` | `_category_task`（并行，无序） | `retrieval_node`（串行，品类序） |
| `reasoning` | `_send_reasoning_sequential`（串行） | `retrieval_node`（串行，品类序） |

> 品类别间的顺序保持不变（Python 3.7+ dict 保序），`products` 事件从并行发送变为串行发送，但因发送的是已缓存数据，延迟可忽略。
