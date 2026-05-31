"""Category Lookup 表构建与填充脚本。

用法: python -m scripts.setup_category_lookup
或:   cd server && python scripts/setup_category_lookup.py

从 product 表中 DISTINCT 提取 (category, sub_category) 值对，
填充 category_lookup 表。重复执行幂等（ON CONFLICT DO NOTHING）。
"""
import asyncio
import sys
from pathlib import Path

# 将 server/ 加入 sys.path 以支持 app.* 导入
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from app.database import engine, Base
from app.models.category_lookup import CategoryLookup


async def setup():
    """创建 category_lookup 表并从 product 表填充数据。"""
    async with engine.begin() as conn:
        # 1. 建表（幂等：IF NOT EXISTS 模式由 create_all 处理）
        await conn.run_sync(Base.metadata.create_all, tables=[CategoryLookup.__table__])

        # 2. 从 product 表 DISTINCT 填充（幂等：ON CONFLICT DO NOTHING）
        await conn.execute(
            text(
                """
                INSERT INTO category_lookup (category, sub_category)
                SELECT DISTINCT category, sub_category FROM product
                WHERE category IS NOT NULL AND sub_category IS NOT NULL
                ON CONFLICT (category, sub_category) DO NOTHING
                """
            )
        )

    print(f"[OK] category_lookup 表已就绪")


if __name__ == "__main__":
    asyncio.run(setup())
