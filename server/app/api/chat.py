import json
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.chat import ChatRequest, ChatResponse
from app.services.cart_service import CartService
from app.services.rag_service import RagService

router = APIRouter()
rag_service = RagService()
cart_service = CartService()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat", response_model=ChatResponse)
async def chat_once(request: ChatRequest) -> ChatResponse:
    result = rag_service.answer(request)
    return ChatResponse(
        reply=result.text,
        session_id=result.session_id,
        products=result.products,
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        result = rag_service.answer(request)
        for chunk in result.text_chunks:
            yield _sse("delta", {"text": chunk})

        if result.products:
            yield _sse("product_cards", {"products": [p.model_dump() for p in result.products]})

        cart_event = cart_service.try_handle(request.message, result)
        if cart_event:
            yield _sse("cart_update", cart_event.model_dump())

        yield _sse("done", {"session_id": result.session_id})

    return StreamingResponse(events(), media_type="text/event-stream")
