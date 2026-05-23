from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.product import Product


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    history: list[dict] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    products: list[Product] = Field(default_factory=list)


class RagAnswer(BaseModel):
    text: str
    session_id: str
    products: list[Product] = Field(default_factory=list)

    @property
    def text_chunks(self) -> list[str]:
        chunks: list[str] = []
        cursor = 0
        step = 12
        while cursor < len(self.text):
            chunks.append(self.text[cursor : cursor + step])
            cursor += step
        return chunks
