import argparse
import json
from pathlib import Path


def build_index(products_path: Path, output_path: Path) -> int:
    """Build a lightweight text index placeholder before Chroma is wired in."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    docs = []
    with products_path.open("r", encoding="utf-8") as reader:
        for line in reader:
            product = json.loads(line)
            text = " ".join(
                [
                    product.get("name", ""),
                    product.get("category", ""),
                    product.get("description", ""),
                    " ".join(product.get("tags", [])),
                ]
            )
            docs.append({"id": product["id"], "text": text, "metadata": product})

    with output_path.open("w", encoding="utf-8") as writer:
        json.dump(docs, writer, ensure_ascii=False, indent=2)
    return len(docs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build local retrieval index.")
    parser.add_argument("--products", default="data/processed/products.jsonl")
    parser.add_argument("--output", default="data/processed/text_index.json")
    args = parser.parse_args()
    count = build_index(Path(args.products), Path(args.output))
    print(f"Built index with {count} product chunks at {args.output}")


if __name__ == "__main__":
    main()
