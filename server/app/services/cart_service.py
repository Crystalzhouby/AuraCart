"""
购物车服务 — 对话式加购意图识别与状态管理

当前实现：关键词匹配识别加购意图，进程内内存存储购物车状态。
后续扩展方向：接入 session_id 管理、数据库持久化、支持删除/改量等 CRUD 操作。
"""

from typing import Optional

from app.schemas.cart import CartEvent, CartItem
from app.schemas.chat import RagAnswer

# 触发加购操作的关键词集合（用户说出其中任意一个即视为加购意图）
_ADD_KEYWORDS = ["加购", "加入购物车", "加到购物车"]


class CartService:
    """
    购物车服务：从对话消息中识别加购意图，并维护本次会话的购物车状态。
    当前为内存存储（进程内），重启后清空。
    """

    def __init__(self) -> None:
        # 购物车条目列表（进程内内存存储）
        self._items: list[CartItem] = []

    def try_handle(self, message: str, answer: RagAnswer) -> Optional[CartEvent]:
        """
        尝试从用户消息中识别加购意图。

        Args:
            message: 用户原始消息文本
            answer:  RAG 回复（含检索到的商品列表）

        Returns:
            CartEvent  — 若识别到加购意图，返回购物车变更事件
            None       — 若未识别到意图，返回 None（不触发 cart_update 事件）
        """
        # 去除空格后匹配关键词（兼容"加 入 购物车"等分散输入）
        normalized = message.replace(" ", "")
        if not any(kw in normalized for kw in _ADD_KEYWORDS):
            return None  # 未命中加购意图，不触发购物车事件

        if not answer.products:
            # 有加购意图但 RAG 未检索到商品
            return CartEvent(action="noop", items=self._items, message="没有可加购的商品。")

        # 默认将 RAG 结果中第一款商品加入购物车
        item = CartItem(product=answer.products[0], quantity=1)
        self._items.append(item)
        return CartEvent(action="add", items=self._items, message=f"已加入购物车：{item.product.name}")
