import argparse
import json
from pathlib import Path
from typing import Optional


def _as_float(value: object, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_image_url(raw: dict, raw_dir: Path) -> Optional[str]:
    image_url = raw.get("image_url") or raw.get("main_image") or raw.get("cover")
    if image_url:
        return str(image_url)

    image_path = raw.get("image_path")
    if not image_path:
        return None

    return str(raw_dir / str(image_path))


def _normalize_description(raw: dict) -> str:
    description = raw.get("description") or raw.get("desc") or raw.get("detail")
    if description:
        return str(description)

    knowledge = raw.get("rag_knowledge") or {}
    parts: list[str] = []
    marketing = knowledge.get("marketing_description")
    if marketing:
        parts.append(str(marketing))

    for faq in knowledge.get("official_faq") or []:
        question = faq.get("question")
        answer = faq.get("answer")
        if question and answer:
            parts.append(f"问：{question} 答：{answer}")

    for review in (knowledge.get("user_reviews") or [])[:3]:
        content = review.get("content")
        rating = review.get("rating")
        if content:
            parts.append(f"用户评价{rating or ''}星：{content}")

    return "\n".join(parts)


def _normalize_tags(raw: dict) -> list[str]:
    tags = raw.get("tags") or []
    if not isinstance(tags, list):
        tags = [tags]

    values: list[str] = [str(tag) for tag in tags if tag]
    for key in ("brand", "category", "sub_category"):
        value = raw.get(key)
        if value:
            values.append(str(value))

    for sku in raw.get("skus") or []:
        properties = sku.get("properties") or {}
        for value in properties.values():
            if value:
                values.append(str(value))

    return list(dict.fromkeys(values))


def normalize_product(raw: dict, fallback_id: str, raw_dir: Path = Path("data/ecommerce_agent_dataset")) -> dict:
    return {
        "id": str(raw.get("id") or raw.get("product_id") or fallback_id),
        "name": str(raw.get("name") or raw.get("title") or "未命名商品"),
        "category": str(raw.get("category") or raw.get("cate") or ""),
        "price": _as_float(raw.get("price") or raw.get("sale_price") or raw.get("base_price")),
        "stock": _as_int(raw.get("stock") or raw.get("inventory")),
        "image_url": _normalize_image_url(raw, raw_dir),
        "description": _normalize_description(raw),
        "tags": _normalize_tags(raw),
        "reason": "",
    }


def import_products(raw_dir: Path, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as writer:
        for path in sorted(raw_dir.rglob("*.json")):
            with path.open("r", encoding="utf-8") as reader:
                raw = json.load(reader)
            product = normalize_product(raw, fallback_id=path.stem, raw_dir=raw_dir)
            writer.write(json.dumps(product, ensure_ascii=False) + "\n")
            count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize raw product JSON files to JSONL.")
    parser.add_argument("--raw-dir", default="data/ecommerce_agent_dataset")
    parser.add_argument("--output", default="data/processed/products.jsonl")
    args = parser.parse_args()
    count = import_products(Path(args.raw_dir), Path(args.output))
    print(f"Imported {count} products to {args.output}")


if __name__ == "__main__":
    main()
