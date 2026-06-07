"""文本截断工具 — 按 source 优先级排序后截断匹配文本列表。"""

_SOURCE_PRIORITY = {"faq": 0, "marketing": 1, "user_review": 2}


def truncate_texts(
    matched_texts: list[dict],
    max_count: int,
    max_chars: int,
) -> list[dict]:
    """按 source 优先级排序后截断匹配文本列表。

    优先级: faq > marketing > user_review。先按优先级排序，再依次累加
    字符数，超出 max_chars 时截断，最后截取前 max_count 条。

    参数:
        matched_texts: 待截断的文本列表，每条为 {"content","source","metadata"}。
        max_count: 最多保留条数。
        max_chars: content 字段累计字符数上限。

    返回值:
        截断后的文本列表。
    """
    if not matched_texts:
        return []

    sorted_texts = sorted(
        matched_texts,
        key=lambda t: _SOURCE_PRIORITY.get(t.get("source", ""), 99),
    )

    result: list[dict] = []
    char_total = 0
    for item in sorted_texts:
        if len(result) >= max_count:
            break
        content = item.get("content", "")
        char_total += len(content)
        if char_total > max_chars and result:
            break
        result.append(item)

    return result
