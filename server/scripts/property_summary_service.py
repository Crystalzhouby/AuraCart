# scripts/property_summary_service.py
"""
SKU Properties 汇总脚本
========================
独立脚本，为每个 Product 汇总其所有 SKU 的 properties 字段信息为一句自然语言描述，
经 Embedding 向量化后写入 product_review 表（source="property"）。

用法::

    cd server && python scripts/property_summary_service.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import structlog

from app.config import settings
from app.models.product_review import ProductReview
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService

logger = structlog.get_logger("property_summary")

_PROMPT = """你是一个电商商品描述助手。请根据以下商品的SKU属性信息，用一句简洁的中文自然语言概括该商品包含哪些规格/变体。

商品名称：{title}
商品品类：{category}
SKU属性列表：
{properties_list}

要求：
1. 用"本{category}品类产品包含"句式开头
2. 用逗号或顿号分隔不同SKU的属性
3. 不做任何额外解释，只输出一句话

示例：
商品名称：雅诗兰黛特润修护肌活精华露
商品品类：精华
SKU属性列表：
- 容量: 30ml 经典装
- 容量: 50ml 加大装
- 容量: 75ml 家用装
输出：本精华产品包含30ml经典装，50ml加大装和75ml家用装"""


class PropertySummaryService:
    """编排 SKU Properties 汇总生成 + 向量化写入的全流程。"""

    def __init__(self, session: AsyncSession, llm_svc: LLMService, emb_svc: EmbeddingService):
        self.session = session
        self.llm = llm_svc
        self.emb = emb_svc

    async def run(self) -> int:
        """主流程：查询未处理 product → LLM 生成汇总 → Embedding → 写入 product_review。

        返回:
            int: 新写入的记录数。
        """
        products = await self._get_unprocessed()
        if not products:
            logger.info("没有需要处理的 product")
            return 0

        logger.info(f"共 {len(products)} 个 product 待处理")
        written = 0
        failed: list[str] = []

        for prod in products:
            pid = prod["product_id"]
            try:
                summary = await self._generate_summary(
                    prod["title"], prod["category"], prod["sku_properties"]
                )
                if not summary or len(summary) < 5:
                    raise ValueError(f"LLM 生成汇总过短: {summary}")

                vec = await self.emb.embed(summary)
                await self._insert_review(pid, summary, vec, prod["sku_properties"])
                await self.session.commit()

                written += 1
                logger.info(f"[{written}/{len(products)}] {pid} 完成", summary=summary)
            except Exception as e:
                await self.session.rollback()
                failed.append(pid)
                logger.warning(f"{pid} 失败，跳过", error=str(e))

        logger.info(f"处理完成: 成功 {written}, 失败 {len(failed)}")
        if failed:
            logger.info(f"失败 product_id: {', '.join(failed)}")
        return written

    async def _get_unprocessed(self) -> list[dict]:
        """查询未处理的 product 及其 SKU properties。

        返回:
            [{product_id, title, category, sku_properties: [dict, ...]}, ...]
            仅包含至少有一个有效 properties SKU 的 product。
        """
        done = set()
        result = await self.session.execute(
            text("SELECT DISTINCT product_id FROM product_review WHERE source = 'property'")
        )
        for r in result.fetchall():
            done.add(r.product_id)

        result = await self.session.execute(
            text("""
                SELECT p.product_id, p.title, p.category, s.properties
                FROM product p
                JOIN sku s ON s.product_id = p.product_id
                WHERE p.is_active = TRUE AND s.is_active = TRUE
                ORDER BY p.product_id
            """)
        )

        products: dict[str, dict] = {}
        for r in result.fetchall():
            pid = r.product_id
            if pid in done:
                continue
            if pid not in products:
                products[pid] = {
                    "product_id": pid,
                    "title": r.title,
                    "category": r.category or "",
                    "sku_properties": [],
                }
            props = r.properties
            if props and isinstance(props, dict) and props:
                products[pid]["sku_properties"].append(props)

        return [p for p in products.values() if p["sku_properties"]]

    async def _generate_summary(self, title: str, category: str, sku_props: list[dict]) -> str:
        """调用 LLM 生成一句中文汇总。"""
        props_lines = []
        for props in sku_props:
            parts = [f"{k}: {v}" for k, v in props.items()]
            props_lines.append("- " + ", ".join(parts))

        cat_label = category or "该"
        prompt = _PROMPT.replace("{title}", title)
        prompt = prompt.replace("{category}", cat_label)
        prompt = prompt.replace("{properties_list}", "\n".join(props_lines))

        return await self.llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
        )

    async def _insert_review(self, product_id: str, summary: str,
                             embedding: list[float], sku_props: list[dict]):
        """写入 product_review 表。"""
        pr = ProductReview(
            product_id=product_id,
            source="property",
            content=summary,
            embedding=embedding,
            extra_data={"raw_properties": sku_props},
        )
        self.session.add(pr)


async def main():
    """脚本入口：初始化 DB/LLM/Embedding 并运行汇总服务。"""
    engine = create_async_engine(settings.database.url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    llm_svc = LLMService(
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
        temperature=settings.llm.temperature,
    )
    emb_svc = EmbeddingService(
        base_url=settings.embedding.base_url,
        api_key=settings.embedding.api_key,
        model=settings.embedding.model,
        batch_size=settings.embedding.batch_size,
    )

    try:
        async with session_factory() as session:
            svc = PropertySummaryService(session, llm_svc, emb_svc)
            count = await svc.run()
            logger.info(f"脚本执行完毕，共写入 {count} 条记录")
    finally:
        await llm_svc.close()
        await emb_svc.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
