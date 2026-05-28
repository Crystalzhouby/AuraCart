# tests/test_sync.py
"""测试 SyncService：商品数据的增量同步至向量存储。

SyncService 定期轮询数据库表以发现新增或更新的记录，
并在 product_review 表中插入或更新 embedding。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime


class FakeCursor:
    """模拟数据库游标，对所有查询方法返回空结果。

    模拟一个无待处理变更的数据库，使同步服务可在无真实数据库
    交互的情况下完成执行。
    """

    def fetchall(self):
        return []

    def scalars(self):
        return self

    def all(self):
        return []

    def one_or_none(self):
        return None


@pytest.mark.asyncio
async def test_sync_polls_tables():
    """验证 SyncService.run_once() 查询所有必需的源表以获取增量数据。

    使用对所有查询返回空结果的 FakeCursor。
    断言 execute() 被调用至少 5 次，分别对应服务轮询的
    marketing、FAQ、user_review、SKU 和 product 表。
    """
    mock_db = AsyncMock()
    fake_cursor = FakeCursor()
    mock_db.execute.return_value = fake_cursor

    # 支持 async context manager 用法（async with db as session）
    mock_db.__aenter__.return_value = mock_db
    mock_db.__aexit__.return_value = None

    mock_emb = AsyncMock()
    mock_emb.embed.return_value = [0.1, 0.2]

    from app.services.sync import SyncService
    svc = SyncService(db_session_factory=lambda: mock_db, emb=mock_emb)
    await svc.run_once(last_sync=datetime(2026, 1, 1))

    # 服务至少需要查询 marketing、FAQ、user_review、SKU 和 product
    # 这 5 张表，故 execute 调用次数 >= 5
    assert mock_db.execute.call_count >= 5
