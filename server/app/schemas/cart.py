from pydantic import BaseModel, Field

from app.schemas.product import Product


class CartItem(BaseModel):
    product: Product
    quantity: int = 1


class CartEvent(BaseModel):
    action: str
    items: list[CartItem] = Field(default_factory=list)
    message: str
