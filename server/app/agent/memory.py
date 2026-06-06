"""
Memory 工具模块。

提供 session_memory 的分组存储、检索与更新（纯函数，无副作用）。

session_memory 数据结构：
    [{
        "category": str,
        "sub_category": str,
        "queries": [{"query": str, "timestamp": str}, ...]
    }, ...]
"""


def get_recent_queries(memory: list[dict], n: int) -> list[dict]:
    """跨品类获取最近 N 轮原始查询，按时间降序排列。

    展平所有 group 的 queries → 按 timestamp 降序排序 → 取前 N 条。
    Router 节点用于查询改写。

    参数:
        memory: session_memory 列表。
        n: 返回的最近查询条数。

    返回值:
        [{"query": "预算500以内", "timestamp": "2026-06-04T10:02:00"}, ...]
    """
    if not memory or n <= 0:
        return []

    all_queries = []
    for group in memory:
        for q in group.get("queries", []):
            all_queries.append({"query": q["query"], "timestamp": q["timestamp"]})

    # 按时间戳降序（最新的在前）
    all_queries.sort(key=lambda x: x["timestamp"], reverse=True)
    return all_queries[:n]


def get_queries_by_category(
    memory: list[dict], category: str, sub_category: str
) -> list[dict]:
    """按 (category, sub_category) 精确匹配检索历史原始查询。

    Extraction 和 Scenario Gen 节点用于拼接历史上下文。

    参数:
        memory: session_memory 列表。
        category: 品类大类。
        sub_category: 品类细类。

    返回值:
        [{"query": "要轻量的", "timestamp": "2026-06-04T10:01:00"}, ...]
        无匹配时返回空列表。
    """
    if not memory:
        return []

    for group in memory:
        if (group.get("category") == category
                and group.get("sub_category") == sub_category):
            return list(group.get("queries", []))

    return []


def append_query(
    memory: list[dict],
    query: str,
    categories: list[dict],
    timestamp: str,
) -> list[dict]:
    """将原始查询追加到匹配的品类 group 中。若无匹配 group 则新建。

    纯函数：不修改入参 memory，返回新的 session_memory 列表。

    参数:
        memory: 当前 session_memory 列表。
        query: 用户原始查询文本。
        categories: 品类列表 [{"category": "服饰运动", "sub_category": "跑步鞋"}, ...]。
        timestamp: ISO 8601 时间戳字符串。

    返回值:
        更新后的 session_memory 列表（新对象）。
    """
    new_memory = _deep_copy_memory(memory)
    new_entry = {"query": query, "timestamp": timestamp}

    if not categories:
        # 无品类信息时，存入 "unknown" 组
        categories = [{"category": None, "sub_category": None}]

    for cat in categories:
        cat_key = cat.get("category")
        sub_key = cat.get("sub_category")

        # 查找匹配的已有 group
        found = False
        for group in new_memory:
            if (group.get("category") == cat_key
                    and group.get("sub_category") == sub_key):
                group["queries"].append(new_entry)
                found = True
                break

        if not found:
            new_memory.append({
                "category": cat_key,
                "sub_category": sub_key,
                "queries": [new_entry],
            })

    return new_memory


def _deep_copy_memory(memory: list[dict]) -> list[dict]:
    """深拷贝 session_memory，确保不修改原始对象。

    参数:
        memory: session_memory 列表。

    返回值:
        深拷贝后的新列表。
    """
    import copy
    return copy.deepcopy(memory)
