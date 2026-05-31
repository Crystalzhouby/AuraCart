"""
Memory 工具模块。

提供 token 计数（char/4 估算）和写时截断功能。
纯函数，无副作用，易于测试。
"""
import json
import logging


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
            "Memory 截断",
            original_token_count=before_count,
            after_token_count=after_count,
            removed_rounds=len(history) - len(truncated),
        )

    return truncated
