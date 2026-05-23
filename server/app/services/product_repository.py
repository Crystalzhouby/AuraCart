import json
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.schemas.product import Product


class ProductRepository:
    def __init__(self, data_path: Optional[str] = None) -> None:
        self.data_path = self._resolve_data_path(data_path or settings.product_data_path)

    def list_products(self) -> list[Product]:
        if not self.data_path.exists():
            return self._demo_products()

        products: list[Product] = []
        with self.data_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    products.append(Product.model_validate(json.loads(line)))
        return products

    def search(self, query: str, limit: int = 3) -> list[Product]:
        products = self.list_products()
        terms = [term for term in query.lower().replace("，", " ").replace(",", " ").split() if term]

        def score(product: Product) -> int:
            haystack = " ".join(
                [product.name, product.category, product.description, " ".join(product.tags)]
            ).lower()
            return sum(1 for term in terms if term in haystack)

        return sorted(products, key=score, reverse=True)[:limit]

    def _resolve_data_path(self, data_path: str) -> Path:
        path = Path(data_path)
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parents[3] / path

    def _demo_products(self) -> list[Product]:
        return [
            Product(
                id="p_demo_001",
                name="清透控油氨基酸洁面乳",
                category="美妆个护",
                price=89,
                stock=120,
                image_url="",
                description="温和洁面，适合油皮和混油皮日常清洁。",
                tags=["油皮", "控油", "洁面", "氨基酸"],
                reason="匹配油皮、清爽洁面的需求。",
            ),
            Product(
                id="p_demo_002",
                name="轻量缓震跑鞋",
                category="服饰运动",
                price=399,
                stock=58,
                image_url="",
                description="轻量鞋面，适合日常跑步和通勤。",
                tags=["跑鞋", "轻量", "500以内", "运动"],
                reason="满足轻量和 500 元以内预算。",
            ),
            Product(
                id="p_demo_003",
                name="主动降噪蓝牙耳机",
                category="数码家电",
                price=199,
                stock=86,
                image_url="",
                description="支持主动降噪和通透模式，适合通勤使用。",
                tags=["蓝牙耳机", "降噪", "200以下", "通勤"],
                reason="符合 200 元以下蓝牙耳机需求。",
            ),
        ]
