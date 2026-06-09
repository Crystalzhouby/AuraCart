"""滑动窗口对话历史查询。

从 ChatHistory 表查询最近 N 轮对话，格式化为统一文本注入各 Agent 节点 prompt。
"""
import structlog

logger = structlog.get_logger("agent.history")


async def get_chat_history_window(
    db_session,
    conversation_id: str,
    max_rounds: int,
    category_filter: list[str] | None = None,
    max_chars_per_msg: int = 200,
) -> str:
    """查询滑动窗口内的对话历史，返回格式化文本。

    参数:
        db_session: 异步 SQLAlchemy session。
        conversation_id: 会话 ID。
        max_rounds: 最大轮数。
        category_filter: 可选品类列表，注入"重点关注"提示词。
        max_chars_per_msg: 单条消息最大字符数，防 prompt 超长。

    返回值:
        格式化历史文本。无历史时返回 "(无历史记录)"。
    """
    from sqlalchemy import select
    from app.models.chat_history import ChatHistory

    result = await db_session.execute(
        select(ChatHistory.role, ChatHistory.content)
        .where(ChatHistory.conversation_id == conversation_id)
        .order_by(ChatHistory.created_at.desc())
        .limit(max_rounds * 2)
    )
    rows = list(result.all())
    if not rows:
        return "(无历史记录)"

    # 翻转为时间正序
    rows.reverse()

    lines: list[str] = []
    if category_filter:
        cats = "、".join(category_filter)
        lines.append(f"（重点关注与以下品类相关的部分：{cats}）")

    for row in rows:
        label = "用户" if row.role == "user" else "助手"
        content = row.content or ""
        if len(content) > max_chars_per_msg:
            content = content[:max_chars_per_msg] + "..."
        lines.append(f"{label}: {content}")

    return "\n".join(lines)
