"""
RAG 服务 — 检索增强生成（Retrieval-Augmented Generation）核心

当前实现为「基础 RAG 骨架」，设计原则：
  - 严格基于商品库回答，禁止模型编造价格、库存、优惠等信息（防幻觉）
  - 检索结果直接作为回复的事实依据（Grounded Answer）
  - 后续可接入向量检索（Chroma）和 LLM 生成增强此模块
"""

from typing import Optional
from uuid import uuid4

from app.schemas.chat import ChatRequest, RagAnswer
from app.schemas.product import Product
from app.services.product_repository import ProductRepository


class RagService:
    """
    RAG 编排服务：接收用户消息 → 检索商品 → 组合基于事实的回复。

    依赖注入 ProductRepository，便于测试时替换为 mock 实现。
    """

    def __init__(self, repository: Optional[ProductRepository] = None) -> None:
        # 默认使用从 products.jsonl 加载的商品库，可注入自定义仓库
        self.repository = repository or ProductRepository()

    def answer(self, request: ChatRequest) -> RagAnswer:
        """
        处理一次对话请求，返回 RAG 答案。

        流程：
          1. 使用 ProductRepository.search() 按关键词检索最相关的 3 款商品
          2. 基于检索结果（而非 LLM 凭空生成）组合回复文本
          3. 生成或透传 session_id 用于多轮对话追踪
        """
        # 关键词检索：从商品库取 Top-3 最匹配商品
        products = self.repository.search(request.message, limit=3)

        # 基于真实检索结果组合回复（Grounded，不编造）
        text = self._compose_grounded_answer(products)

        return RagAnswer(
            text=text,
            session_id=request.session_id or str(uuid4()),
            products=products,
        )

    def _compose_grounded_answer(self, products: list[Product]) -> str:
        """
        组合基于检索结果的回复文本。

        「Grounded」原则：价格、商品名、推荐理由均来自 products 参数，
        不由此函数凭空生成，确保不产生幻觉信息。
        """
        if not products:
            # 无匹配商品时的降级回复：引导用户换词重试
            return "我目前只会基于商品库回答。没有检索到足够匹配的商品，建议换个预算、类目或使用场景。"

        names = "、".join(product.name for product in products)
        return (
            f"我从商品库里找到 {len(products)} 款比较匹配的商品：{names}。"
            "价格、库存和推荐理由都来自检索结果，下面我把商品卡片发给你，方便继续对比或加购。"
        )
