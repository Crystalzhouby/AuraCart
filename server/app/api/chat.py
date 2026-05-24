"""
对话 API — RAG 驱动的商品导购接口

提供两个端点：
  POST /api/chat          同步接口（调试用）
  POST /api/chat/stream   SSE 流式接口（Android App 使用）

SSE 事件格式（流式接口按序推送）：
  event: delta         {"text": "..."}          AI 回复文字片段（逐字流式）
  event: product_cards {"products": [...]}       检索到的商品列表
  event: cart_update   {"action":"add", ...}     购物车操作（命中加购意图时）
  event: done          {"session_id": "..."}     流结束信号
"""

import json
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.cart_service import CartService
from app.services.rag_service import RagService

router = APIRouter()

# 服务单例：进程级共享，避免每次请求重复初始化
rag_service = RagService()
cart_service = CartService()


def _sse(event: str, data: dict) -> str:
    """将事件名和数据序列化为标准 SSE 文本块（RFC 8895）。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat", response_model=ChatResponse)
async def chat_once(request: ChatRequest) -> ChatResponse:
    """
    同步对话接口（主要用于后端调试）。
    流程：用户消息 → RAG 检索 → 组合回复 → 返回完整 JSON
    """
    result = rag_service.answer(request)
    return ChatResponse(
        reply=result.text,
        session_id=result.session_id,
        products=result.products,
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """
    SSE 流式对话接口（Android App 主要调用此端点）。

    RAG 链路：
      1. 调用 RagService.answer() 完成商品检索 + 回复生成
      2. 将回复文本切成 12 字符片段，逐片推送 delta（打字机效果）
      3. 若检索到商品，推送 product_cards 事件（客户端渲染商品卡片）
      4. 检测购物车意图（"加入购物车"等），命中则推送 cart_update
      5. 推送 done 事件，携带 session_id 供后续多轮对话使用
    """
    async def events() -> AsyncIterator[str]:
        # ── Step 1: RAG 检索 + 回复生成 ─────────────────────────────────
        result = rag_service.answer(request)

        # ── Step 2: 逐片推送文字（delta），实现打字机效果 ─────────────────
        for chunk in result.text_chunks:
            yield _sse("delta", {"text": chunk})

        # ── Step 3: 推送商品卡片（仅当 RAG 检索到相关商品时） ─────────────
        if result.products:
            yield _sse("product_cards", {"products": [p.model_dump() for p in result.products]})

        # ── Step 4: 识别购物车意图（关键词匹配） ─────────────────────────
        cart_event = cart_service.try_handle(request.message, result)
        if cart_event:
            yield _sse("cart_update", cart_event.model_dump())

        # ── Step 5: 流结束信号 ───────────────────────────────────────────
        yield _sse("done", {"session_id": result.session_id})

    return StreamingResponse(events(), media_type="text/event-stream")
