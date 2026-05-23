from typing import Optional
from uuid import uuid4

from app.schemas.chat import ChatRequest, RagAnswer
from app.schemas.product import Product
from app.services.product_repository import ProductRepository


class RagService:
    def __init__(self, repository: Optional[ProductRepository] = None) -> None:
        self.repository = repository or ProductRepository()

    def answer(self, request: ChatRequest) -> RagAnswer:
        products = self.repository.search(request.message, limit=3)
        text = self._compose_grounded_answer(products)
        return RagAnswer(
            text=text,
            session_id=request.session_id or str(uuid4()),
            products=products,
        )

    def _compose_grounded_answer(self, products: list[Product]) -> str:
        if not products:
            return "我目前只会基于商品库回答。没有检索到足够匹配的商品，建议换个预算、类目或使用场景。"

        names = "、".join(product.name for product in products)
        return (
            f"我从商品库里找到 {len(products)} 款比较匹配的商品：{names}。"
            "价格、库存和推荐理由都来自检索结果，下面我把商品卡片发给你，方便继续对比或加购。"
        )
