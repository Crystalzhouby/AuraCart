"""
前端 API 路由

模块: app.api.frontend

提供前端页面所需的补充接口：
- GET /api/history/{conversation_id} — 获取会话对话历史
- GET /api/review/{product_id} — 获取商品 RAG 知识信息
- GET /api/all_skus/{product_id} — 获取商品所有 SKU
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.chat_message import ChatMessage
from app.models.conversation import Conversation
from app.models.product_marketing import ProductMarketing
from app.models.product_faq import ProductFaq
from app.models.user_review import UserReview
from app.models.sku import Sku

router = APIRouter(prefix="/api", tags=["frontend"])


# ---------------------------------------------------------------------------
# GET /api/history/{conversation_id}
# ---------------------------------------------------------------------------

@router.get("/history/{conversation_id}")
async def get_history(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取指定会话的对话历史（用户查询+助手回复，按时间排序）。

    若 conversation_id 不存在于 conversation 表，返回 404。
    若存在但 chat_message 表中无记录，返回空数组。
    """
    rows = await db.execute(
        select(ChatMessage.role, ChatMessage.content, ChatMessage.created_at)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = rows.all()

    if not messages:
        conv = await db.execute(
            select(Conversation.conversation_id).where(
                Conversation.conversation_id == conversation_id
            )
        )
        if conv.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"messages": []}

    return {
        "messages": [
            {
                "role": row.role,
                "content": row.content,
                "created_at": row.created_at.isoformat(),
            }
            for row in messages
        ]
    }


# ---------------------------------------------------------------------------
# GET /api/review/{product_id}
# ---------------------------------------------------------------------------

@router.get("/review/{product_id}")
async def get_review(
    product_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取商品的 RAG 知识信息（营销描述、FAQ、用户评价）。

    数据来源为三张结构化表，非 product_review 向量表。
    三表全空时返回 404。
    """
    marketing_q = db.execute(
        select(ProductMarketing.description).where(
            ProductMarketing.product_id == product_id,
            ProductMarketing.is_active == True,
        )
    )
    faq_q = db.execute(
        select(ProductFaq.question, ProductFaq.answer).where(
            ProductFaq.product_id == product_id,
            ProductFaq.is_active == True,
        )
    )
    reviews_q = db.execute(
        select(UserReview.nickname, UserReview.rating, UserReview.content).where(
            UserReview.product_id == product_id,
            UserReview.is_active == True,
        )
    )

    marketing_row, faq_rows, review_rows = await asyncio.gather(
        marketing_q, faq_q, reviews_q
    )

    marketing = marketing_row.scalars().first()
    faqs = faq_rows.all()
    reviews = review_rows.all()

    if marketing is None and not faqs and not reviews:
        raise HTTPException(status_code=404, detail="Product reviews not found")

    return {
        "rag_knowledge": {
            "marketing_description": marketing or "",
            "official_faq": [
                {"question": row.question, "answer": row.answer} for row in faqs
            ],
            "user_reviews": [
                {
                    "nickname": row.nickname or "",
                    "rating": row.rating or 0,
                    "content": row.content,
                }
                for row in reviews
            ],
        }
    }


# ---------------------------------------------------------------------------
# GET /api/all_skus/{product_id}
# ---------------------------------------------------------------------------

@router.get("/all_skus/{product_id}")
async def get_all_skus(
    product_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取指定商品的所有活跃 SKU 变体。

    返回值包含 sku_id、properties、price、stock。
    """
    rows = await db.execute(
        select(Sku.sku_id, Sku.properties, Sku.price, Sku.stock).where(
            Sku.product_id == product_id,
            Sku.is_active == True,
        )
    )
    skus = rows.all()

    if not skus:
        raise HTTPException(status_code=404, detail="Product SKUs not found")

    return {
        "skus": [
            {
                "sku_id": row.sku_id,
                "properties": row.properties,
                "price": float(row.price),
                "stock": row.stock,
            }
            for row in skus
        ]
    }
