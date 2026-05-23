from typing import Optional

from pydantic import BaseModel, Field


class Product(BaseModel):
    id: str
    name: str
    category: str = ""
    price: float
    stock: int = 0
    image_url: Optional[str] = None
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    reason: str = ""


class ProductChunk(BaseModel):
    product_id: str
    text: str
    metadata: dict = Field(default_factory=dict)
