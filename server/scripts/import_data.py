# scripts/import_data.py
"""
批量导入产品 JSON 数据并生成向量嵌入的 CLI 入口。

本脚本从本地目录读取产品 fixture 文件，通过外部嵌入服务为评论/营销/FAQ
文本生成语义嵌入，并将所有数据持久化到 PostgreSQL 数据库。设计为独立运行
（``python scripts/import_data.py [data_dir]``），自行管理异步事件循环、
数据库会话及嵌入服务的生命周期。

典型用法::

    python scripts/import_data.py ../../ecommerce_agent_dataset/data

脚本执行流程:
1. 清空数据库中所有已有的产品数据。
2. 遍历指定目录中的 JSON 文件。
3. 解析每个产品及其 SKU、评论、FAQ 和营销文案。
4. 批量嵌入文本内容并存储生成的向量。
5. 输出导入的产品总数。
"""

import argparse
import asyncio
import sys
from pathlib import Path

# 将 server/ 根目录加入 sys.path，使得直接运行本脚本（而非通过
# ``python -m``）时也能导入 ``app`` 模块。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.services.embedding import EmbeddingService
from app.services.import_data import DataImporter


def _parse_args() -> argparse.Namespace:
    """解析唯一可选的位置参数：数据目录路径。

    返回值:
        argparse.Namespace: 包含 ``data_dir`` 属性的已填充命名空间。
    """

    # 默认使用 config.yaml 中配置的数据集路径下的 data 子目录。
    default_dir = (
        Path(__file__).resolve().parents[2] / settings.dataset.dir / "data"
    ).as_posix()

    parser = argparse.ArgumentParser(
        description="将产品 JSON 数据导入 Postgres 并生成嵌入向量"
    )
    parser.add_argument(
        "data_dir",
        nargs="?",
        default=default_dir,
        help="包含产品 JSON 文件的目录 "
        "(默认: config.yaml 中 dataset.dir 下的 data 子目录)",
    )
    return parser.parse_args()


async def main() -> None:
    """异步入口：组装各服务、执行导入、并清理资源。

    异常:
        FileNotFoundError: 如果提供的数据目录不存在。
    """

    args = _parse_args()
    data_dir = str(Path(args.data_dir).resolve())

    # 前置检查：若目录不存在则中止并显示明确提示。
    if not Path(data_dir).exists():
        raise FileNotFoundError(
            f"数据目录未找到: {data_dir}。 "
            "示例: python scripts/import_data.py data/ecommerce_agent_dataset_/data"
        )

    # ------------------------------------------------------------------
    # 数据库引擎与会话工厂（异步，由 config.yaml 驱动）。
    # ------------------------------------------------------------------
    engine = create_async_engine(settings.database.url)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # ------------------------------------------------------------------
    # 嵌入服务 – 外部 LLM/嵌入 API 的统一客户端。
    # ------------------------------------------------------------------
    embedding_svc = EmbeddingService(
        base_url=settings.embedding.base_url,
        api_key=settings.embedding.api_key,
        model=settings.embedding.model,
        batch_size=settings.embedding.batch_size,
    )

    # 在单一会话中执行导入。
    async with session_factory() as session:
        importer = DataImporter(session, embedding_svc)
        # 从干净状态开始。
        await importer.clear_all()
        count = await importer.import_json_dir(data_dir)
        print(f"已导入 {count} 个产品")

    # 清理嵌入客户端和引擎连接池所持有的资源。
    await embedding_svc.close()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
