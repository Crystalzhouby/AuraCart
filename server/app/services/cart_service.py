from typing import Optional

from app.schemas.cart import CartEvent, CartItem
from app.schemas.chat import RagAnswer


class CartService:
    def __init__(self) -> None:
        self._items: list[CartItem] = []

    def try_handle(self, message: str, answer: RagAnswer) -> Optional[CartEvent]:
        normalized = message.replace(" ", "")
        if not any(word in normalized for word in ["加购", "加入购物车", "加到购物车"]):
            return None
        if not answer.products:
            return CartEvent(action="noop", items=self._items, message="没有可加购的商品。")

        item = CartItem(product=answer.products[0], quantity=1)
        self._items.append(item)
        return CartEvent(action="add", items=self._items, message=f"已加入购物车：{item.product.name}")
