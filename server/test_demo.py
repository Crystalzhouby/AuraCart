"""
AuraCart 服务接口验证脚本
========================
验证各接口是否正常工作：

  1. GET /health                 — 健康检查
  2. GET /api/search/stream      — SSE 全链路检索（需要 LLM）
  3. GET /api/products/{id}      — 商品详情

使用方式:
    python test_demo.py
    python test_demo.py --base-url http://localhost:8000
"""

import json
import sys
import argparse
import httpx

BASE_URL = "http://localhost:8000"


def check(condition: bool, msg: str) -> int:
    """断言一次检查，返回 0（通过）或 1（失败）。"""
    if condition:
        print(f"  [PASS] {msg}")
        return 0
    else:
        print(f"  [FAIL] {msg}")
        return 1


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


def test_health(client: httpx.Client) -> int:
    """健康检查 — GET /health → {"status":"ok"}"""
    print("\n[1/3] 健康检查  GET /health")
    try:
        resp = client.get("/health")
        resp.raise_for_status()
    except httpx.RequestError as e:
        print(f"  ✗ 请求失败: {e}")
        return 1

    data = resp.json()
    errors = 0
    errors += check(resp.status_code == 200, f"HTTP {resp.status_code}")
    errors += check(data.get("status") == "ok", f"status={data.get('status')}")
    print(f"      响应: {json.dumps(data, ensure_ascii=False)}")
    return errors


def test_search_stream(client: httpx.Client) -> int:
    """SSE 全链路检索 — GET /api/search/stream?q=推荐一款200元以下的防晒霜"""
    print("\n[2/3] SSE 全链路检索  GET /api/search/stream?q=推荐一款200元以下的防晒霜")
    errors = 0
    events: dict[str, list[str]] = {}

    try:
        with client.stream(
            "GET",
            "/api/search/stream",
            params={"q": "推荐一款200元以下的防晒霜"},
            timeout=35.0,
        ) as resp:
            errors += check(resp.status_code == 200, f"HTTP {resp.status_code}")
            errors += check(
                "text/event-stream" in resp.headers.get("content-type", ""),
                f"Content-Type 为 text/event-stream",
            )

            # 逐行解析 SSE 事件
            current_event = None
            for line in resp.iter_lines():
                line = line.strip()
                if not line:
                    current_event = None
                    continue
                # SSE 的 "event:" 和 "data:" 行
                key, _, value = line.partition(": ")
                if key == "event":
                    current_event = value
                    events.setdefault(current_event, [])
                elif key == "data":
                    events.setdefault(current_event or "unknown", []).append(value)

    except httpx.RequestError as e:
        print(f"  ✗ 请求失败: {e}")
        return 1

    # 验证 SSE 事件序列
    errors += check("sub_queries" in events, "包含 sub_queries 事件")
    errors += check("products" in events, "包含 products 事件")
    errors += check("reasoning" in events, "包含 reasoning 事件")
    errors += check("done" in events, "包含 done 事件")

    if "sub_queries" in events:
        subs = json.loads(events["sub_queries"][0])
        print(f"      子查询数: {len(subs)}")
        for s in subs:
            print(f"        - [{s.get('strategy')}] {s.get('text')}")

    if "products" in events:
        prods = json.loads(events["products"][0])
        print(f"      候选商品数: {len(prods)}")
        for p in prods:
            print(f"        - {p.get('product_id')} {p.get('title')} Y{p.get('base_price')}")

    if "reasoning" in events:
        reasoning_text = "".join(events["reasoning"])
        print(f"      推理文本 ({len(reasoning_text)} 字): {reasoning_text[:120]}...")

    return errors


def test_product_detail(client: httpx.Client) -> int:
    """商品详情 — GET /api/products/PROD001"""
    print("\n[3/3] 商品详情  GET /api/products/PROD001")
    try:
        resp = client.get("/api/products/PROD001")
        resp.raise_for_status()
    except httpx.RequestError as e:
        print(f"  ✗ 请求失败: {e}")
        return 1

    data = resp.json()
    errors = 0
    errors += check(resp.status_code == 200, f"HTTP {resp.status_code}")
    errors += check(data.get("product_id") == "PROD001", f"product_id={data.get('product_id')}")
    errors += check("title" in data, "包含 title")
    errors += check("brand" in data, "包含 brand")
    errors += check("category" in data, "包含 category")
    errors += check("base_price" in data, "包含 base_price")
    errors += check("skus" in data and len(data["skus"]) >= 1, f"至少 1 个 SKU (实际: {len(data.get('skus', []))})")

    print(f"      商品: {data.get('title')} | {data.get('brand')} | Y{data.get('base_price')}")
    for sku in data.get("skus", []):
        print(f"        SKU {sku.get('sku_id')}: Y{sku.get('price')} / 库存{sku.get('stock')}")

    # 404 用例
    resp404 = client.get("/api/products/NONEXIST")
    errors += check(resp404.status_code == 404, f"不存在的商品返回 404 (实际: {resp404.status_code})")

    return errors


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="AuraCart 服务接口验证")
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help=f"服务基础 URL（默认: {BASE_URL}）",
    )
    args = parser.parse_args()

    print(f"验证目标: {args.base_url}")
    print(f"{'=' * 50}")

    total_errors = 0
    with httpx.Client(base_url=args.base_url) as client:
        total_errors += test_health(client)
        total_errors += test_search_stream(client)
        total_errors += test_product_detail(client)

    print(f"\n{'=' * 50}")
    if total_errors == 0:
        print("Result: ALL PASSED")
    else:
        print(f"Result: {total_errors} check(s) FAILED")
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
