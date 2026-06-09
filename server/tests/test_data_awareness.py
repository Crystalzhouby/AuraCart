"""DATABASE_OPT F2: 实时数据感知集成测试。

验证插入/删除商品后 /api/search 的检索结果能感知数据库变化。

用法: cd server && python -m pytest tests/test_data_awareness.py -v -s

需 LLM + Embedding 服务可用。
"""
import json
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from app.main import app
from app.database import async_session
from app.models.product_review import ProductReview

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data" / "ecommerce_agent_dataset_" / "data"

# 检查依赖可用性
try:
    import langgraph  # noqa: F401
    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False

# 测试商品 ID 列表
_TEST_PRODUCT_IDS = ["p_test_aware_001", "p_test_aware_002", "p_test_aware_003"]
_TEST_SKU_IDS = [
    "s_test_aware_001_1", "s_test_aware_001_2",
    "s_test_aware_002_1", "s_test_aware_002_2",
    "s_test_aware_003_1", "s_test_aware_003_2",
]
_SEARCH_KEYWORD = "DATABASE_OPT_TEST_MARKER"
_SEARCH_QUERY = f"{_SEARCH_KEYWORD} 精华液推荐"
_VECTOR_DIM = 1024
_ZERO_VECTOR = [0.0] * _VECTOR_DIM


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _parse_sse_product_ids(response_text: str) -> set[str]:
    """从 SSE 响应中提取所有 products 事件的 product_id 集合。"""
    product_ids: set[str] = set()
    for line in response_text.split("\n"):
        if line.startswith("event: products"):
            continue
        if line.startswith("data: ") and "product_id" in line:
            try:
                data = json.loads(line[6:])
                if "product_id" in data:
                    product_ids.add(data["product_id"])
            except json.JSONDecodeError:
                pass
    return product_ids


async def _search(conversation_id: str, query: str) -> tuple[int, set[str]]:
    """执行一次搜索，返回 (状态码, product_id 集合)。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
        resp = await client.get(
            f"/api/search/{conversation_id}",
            params={"q": query, "stream": "false"},
        )
        return resp.status_code, _parse_sse_product_ids(resp.text)


async def _create_conversation() -> str:
    """创建新会话，返回 conversation_id。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/conversation")
        return resp.json()["conversation_id"]


async def _insert_test_products():
    """插入 3 个测试商品及其关联数据（product/sku/marketing/faq/review/product_review）。"""
    async with async_session() as session:
        for pid in _TEST_PRODUCT_IDS:
            filepath = _DATA_DIR / f"{pid}.json"
            with open(filepath, "r", encoding="utf-8") as f:
                product_data = json.load(f)

            # 1. product
            await session.execute(
                text("""
                    INSERT INTO product (product_id, title, brand, category, sub_category, base_price, image_path, is_active)
                    VALUES (:pid, :title, :brand, :cat, :sub, :price, :img, TRUE)
                """),
                {
                    "pid": product_data["product_id"],
                    "title": product_data["title"],
                    "brand": product_data["brand"],
                    "cat": product_data["category"],
                    "sub": product_data["sub_category"],
                    "price": product_data["base_price"],
                    "img": product_data["image_path"],
                },
            )

            # 2. sku
            for sku in product_data["skus"]:
                await session.execute(
                    text("""
                        INSERT INTO sku (sku_id, product_id, properties, price, stock, is_active)
                        VALUES (:sid, :pid, CAST(:props AS jsonb), :price, :stock, TRUE)
                    """),
                    {
                        "sid": sku["sku_id"],
                        "pid": product_data["product_id"],
                        "props": json.dumps(sku["properties"], ensure_ascii=False),
                        "price": sku["price"],
                        "stock": sku["stock"],
                    },
                )

            # 3. product_marketing
            marketing = product_data["rag_knowledge"]["marketing_description"]
            if marketing:
                await session.execute(
                    text("""
                        INSERT INTO product_marketing (product_id, description, is_active)
                        VALUES (:pid, :desc, TRUE)
                    """),
                    {"pid": product_data["product_id"], "desc": marketing},
                )
                # product_review (marketing)
                session.add(ProductReview(
                    product_id=product_data["product_id"],
                    source="marketing",
                    content=marketing,
                    embedding=_ZERO_VECTOR,
                    extra_data={},
                ))

            # 4. product_faq
            for faq in product_data["rag_knowledge"].get("official_faq", []):
                faq_content = f"Q: {faq['question']} A: {faq['answer']}"
                session.add(ProductReview(
                    product_id=product_data["product_id"],
                    source="faq",
                    content=faq_content,
                    embedding=_ZERO_VECTOR,
                    extra_data={},
                ))

            # 5. user_review
            for review in product_data["rag_knowledge"].get("user_reviews", []):
                await session.execute(
                    text("""
                        INSERT INTO user_review (product_id, nickname, rating, content, is_active)
                        VALUES (:pid, :nick, :rating, :content, TRUE)
                    """),
                    {
                        "pid": product_data["product_id"],
                        "nick": review["nickname"],
                        "rating": review["rating"],
                        "content": review["content"],
                    },
                )
                # product_review (user_review)
                session.add(ProductReview(
                    product_id=product_data["product_id"],
                    source="user_review",
                    content=review["content"],
                    embedding=_ZERO_VECTOR,
                    extra_data={},
                ))

        await session.commit()


async def _delete_test_products():
    """删除所有测试商品数据。"""
    async with async_session() as session:
        tables = ["user_review", "product_review", "product_marketing",
                   "sku", "product"]
        for table in tables:
            if table == "product_review":
                await session.execute(
                    text(f"DELETE FROM {table} WHERE product_id = ANY(:pids)"),
                    {"pids": _TEST_PRODUCT_IDS},
                )
            else:
                await session.execute(
                    text(f"DELETE FROM {table} WHERE product_id = ANY(:pids)"),
                    {"pids": _TEST_PRODUCT_IDS},
                )
        await session.commit()


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_data_awareness_insert_and_delete():
    """插入/删除测试商品后，/api/search 检索结果应相应变化。"""
    if not _DEPS_AVAILABLE:
        pytest.skip("langgraph 未安装，跳过集成测试")
    try:
        cid = await _create_conversation()
    except Exception:
        pytest.skip("无法创建会话，数据库或服务不可用")

    try:
        # ---- Phase 1: 插入前搜索（基线） ----
        status_before, ids_before = await _search(cid, _SEARCH_QUERY)
        assert status_before == 200, f"搜索应返回 200，实际 {status_before}"
        for pid in _TEST_PRODUCT_IDS:
            assert pid not in ids_before, (
                f"插入前不应包含测试商品 {pid}，但出现在了结果中"
            )
        print(f"\n[Phase 1] 插入前搜索: {len(ids_before)} 个结果，不含测试商品 [OK]")

        # ---- Phase 2: 插入后搜索（应包含新商品） ----
        await _insert_test_products()

        status_after, ids_after = await _search(cid, _SEARCH_QUERY)
        assert status_after == 200, f"搜索应返回 200，实际 {status_after}"

        found = [pid for pid in _TEST_PRODUCT_IDS if pid in ids_after]
        assert len(found) > 0, (
            f"插入后搜索应至少找到一个测试商品，"
            f"实际搜索到 {len(ids_after)} 个商品: {ids_after}"
        )
        print(f"[Phase 2] 插入后搜索找到测试商品: {found} (共 {len(ids_after)} 个结果) [OK]")

        # ---- Phase 3: 删除后搜索（不应包含测试商品） ----
        await _delete_test_products()

        status_after_del, ids_after_del = await _search(cid, _SEARCH_QUERY)
        assert status_after_del == 200, f"搜索应返回 200，实际 {status_after_del}"

        still_found = [pid for pid in _TEST_PRODUCT_IDS if pid in ids_after_del]
        assert len(still_found) == 0, (
            f"删除后搜索不应包含测试商品，但仍找到: {still_found}"
        )
        print(f"[Phase 3] 删除后搜索不再包含测试商品 (共 {len(ids_after_del)} 个结果) [OK]")

    finally:
        await _delete_test_products()
