"""
Memory 工具模块。

提供两种记忆管理能力：
1. 旧 conversation_history 的 token 计数与截断（向后兼容）。
2. 新 session_memory 的分组存储、检索与更新（纯函数，无副作用）。

新 session_memory 数据结构：
    [{
        "category": str,
        "sub_category": str,
        "queries": [{"query": str, "timestamp": str}, ...]
    }, ...]
"""
import json
import logging


# ============================================================================
# 旧 conversation_history 工具函数（向后兼容）
# ============================================================================


def count_tokens(history: list[dict]) -> int:
    """使用 char/4 简易估算计算 conversation_history 的 token 数。

    参数:
        history: conversation_history 列表。

    返回值:
        int: 估算的 token 数量。
    """
    if not history:
        return 0
    serialized = json.dumps(history, ensure_ascii=False)
    return len(serialized) // 4


def truncate_by_tokens(
    history: list[dict],
    max_tokens: int,
    logger: logging.Logger | None = None,
) -> list[dict]:
    """从列表头部丢弃元素，直到 token 数不超过 max_tokens。

    截断策略：FIFO（最先存入的需求最先被遗忘），最小保留 1 个元素。
    截断时记录日志。

    参数:
        history: conversation_history 列表。
        max_tokens: token 数上限。
        logger: 可选日志记录器。

    返回值:
        截断后的 history 列表。
    """
    if not history:
        return history

    if logger is None:
        logger = logging.getLogger(__name__)

    before_count = count_tokens(history)
    truncated = list(history)  # 浅拷贝避免修改入参

    while len(truncated) > 1 and count_tokens(truncated) > max_tokens:
        truncated.pop(0)

    after_count = count_tokens(truncated)
    if before_count != after_count:
        logger.info(
            "Memory 截断: original=%d after=%d removed_rounds=%d",
            before_count, after_count,
            len(history) - len(truncated),
        )

    return truncated


# ============================================================================
# 新 session_memory 工具函数（按品类分组的原始查询记忆）
# ============================================================================


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
