# app/services/sync.py
"""
同步服务模块
============
提供增量数据同步服务，使 product_review 表中的 Embedding
与上游源表保持同步。

核心功能：
- 使用咨询锁保护的同步运行，防止并发执行
- 对 Product、ProductMarketing、ProductFaq 和 UserReview 变更进行增量同步
- 对更新的记录自动重新生成 Embedding
- 对已停用/已删除记录清理其 Embedding
- 可选的轮询循环，用于周期性的后台同步

架构设计：
使用 PostgreSQL 咨询锁确保跨多个应用实例同时只有一个
同步进程运行。通过比较 updated_at 时间戳与上次同步时间戳
来检测变更。
"""

import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
from app.models import Product, ProductMarketing, ProductFaq, UserReview
from app.models.product_review import ProductReview
from app.services.embedding_service import EmbeddingService


class SyncService:
    """
    增量同步服务，将源表变更镜像到 product_review Embedding 表。

    跟踪上次同步时间戳，每次运行时仅处理自该时间以来
    被修改的记录。
    """

    def __init__(self, db_session_factory, emb: EmbeddingService):
        """
        初始化同步服务。

        参数：
            db_session_factory：异步会话工厂可调用对象（例如，
                                async_sessionmaker 或返回异步
                                上下文管理器的 lambda）。
            emb (EmbeddingService)：用于生成文本 Embedding 的服务。
        """
        self.db_session_factory = db_session_factory
        self.emb = emb
        self._last_sync: datetime | None = None

    async def run_once(self, last_sync: datetime | None = None):
        """
        执行单次同步周期。

        获取 PostgreSQL 咨询锁以保证独占执行，
        然后按顺序同步所有源表。首次运行时
        （self._last_sync 为 None），仅执行产品停用清理；
        不对内容表进行增量同步。

        参数：
            last_sync (datetime | None)：覆盖上次同步时间戳。
                                        若提供，则在处理前设置
                                        self._last_sync。
        """
        if last_sync is not None:
            self._last_sync = last_sync

        async with self.db_session_factory() as db:
            # 获取咨询锁以防止并发同步运行
            await db.execute(text("SELECT pg_advisory_lock(12345)"))

            try:
                # 将每个源表同步到 product_review Embedding 表
                await self._sync_product(db)
                await self._sync_table(db, ProductMarketing, "marketing", "description")
                await self._sync_faq(db)
                await self._sync_table(db, UserReview, "user_review", "content")
                await db.commit()
            finally:
                # 即使出错也始终释放锁
                await db.execute(text("SELECT pg_advisory_unlock(12345)"))

    async def _sync_product(self, db: AsyncSession):
        """
        移除自上次同步以来已被停用的产品对应的 product_review 条目。

        已停用的产品（is_active = False）不应再出现在搜索结果中，
        因此删除其所有关联的 Embedding 行。

        参数：
            db (AsyncSession)：活跃的异步数据库会话。
        """
        if self._last_sync:
            # 查找自上次同步以来被停用的产品
            sql = text("""
                SELECT product_id FROM product
                WHERE updated_at > :ts AND is_active = FALSE
            """)
            result = await db.execute(sql, {"ts": self._last_sync})
            pids = [r.product_id for r in result.fetchall()]
            if pids:
                # 删除停用产品的所有 product_review 行
                placeholders = ", ".join([f":p{i}" for i in range(len(pids))])
                params = {f"p{i}": pid for i, pid in enumerate(pids)}
                await db.execute(
                    text(f"DELETE FROM product_review WHERE product_id IN ({placeholders})"),
                    params,
                )

    async def _sync_table(self, db: AsyncSession, model_cls, source: str, content_field: str):
        """
        对源表执行通用的增量同步。

        针对自上次同步以来被修改的记录，处理两种情况：
        - 活跃记录：重新生成 Embedding，替换已有的 product_review 行。
        - 非活跃（软删除）记录：移除所有关联的 product_review 行。

        参数：
            db (AsyncSession)：活跃的异步数据库会话。
            model_cls：SQLAlchemy ORM 模型类（如 ProductMarketing、UserReview）。
            source (str)：存储在 product_review.source 中的来源标识字符串
                         （如 "marketing"、"user_review"）。
            content_field (str)：包含待 Embedding 文本内容的模型属性名称。
        """
        if not self._last_sync:
            return

        # 查询自上次同步以来更新的活跃记录
        rows = (await db.execute(
            select(model_cls).where(
                model_cls.updated_at > self._last_sync,
                model_cls.is_active == True,
            )
        )).scalars().all()

        # 重新生成 Embedding 并更新活跃记录
        for row in rows:
            content = getattr(row, content_field, "")
            vec = await self.emb.embed(content)

            # 在插入前删除此来源+产品的旧 Embedding 行
            await db.execute(
                text("DELETE FROM product_review WHERE product_id = :pid AND source = :src"),
                {"pid": row.product_id, "src": source},
            )
            db.add(ProductReview(
                product_id=row.product_id,
                source=source,
                content=content,
                embedding=vec,
                extra_data={},
            ))

        # 查询已停用的记录并删除其 Embedding
        deleted = (await db.execute(
            select(model_cls).where(
                model_cls.updated_at > self._last_sync,
                model_cls.is_active == False,
            )
        )).scalars().all()

        for row in deleted:
            await db.execute(
                text("DELETE FROM product_review WHERE product_id = :pid AND source = :src"),
                {"pid": row.product_id, "src": source},
            )

    async def _sync_faq(self, db: AsyncSession):
        """
        对 ProductFaq 表进行增量同步。

        处理 FAQ 特有的内容格式化（问答对拼接），
        并使用问题文本作为元数据 JSON 中的唯一键，
        以便在重新插入前精确删除对应行。

        参数：
            db (AsyncSession)：活跃的异步数据库会话。
        """
        if not self._last_sync:
            return

        # 查询自上次同步以来更新的活跃 FAQ
        rows = (await db.execute(
            select(ProductFaq).where(
                ProductFaq.updated_at > self._last_sync,
                ProductFaq.is_active == True,
            )
        )).scalars().all()

        # 为活跃 FAQ 记录重新生成 Embedding，内容使用问答格式
        for row in rows:
            content = f"问题：{row.question}\n回答：{row.answer}"
            vec = await self.emb.embed(content)

            # 通过 product_id、source 和 question 删除特定的 FAQ 行
            await db.execute(
                text("DELETE FROM product_review WHERE product_id = :pid AND source = 'faq' AND metadata->>'question' = :q"),
                {"pid": row.product_id, "q": row.question},
            )
            db.add(ProductReview(
                product_id=row.product_id,
                source="faq",
                content=content,
                embedding=vec,
                extra_data={"question": row.question},
            ))

        # 删除已停用 FAQ 的 Embedding
        deleted = (await db.execute(
            select(ProductFaq).where(
                ProductFaq.updated_at > self._last_sync,
                ProductFaq.is_active == False,
            )
        )).scalars().all()

        for row in deleted:
            await db.execute(
                text("DELETE FROM product_review WHERE product_id = :pid AND source = 'faq' AND metadata->>'question' = :q"),
                {"pid": row.product_id, "q": row.question},
            )

    async def run_loop(self):
        """
        在轮询循环中持续运行同步。

        执行 run_once()，更新上次同步时间戳，然后休眠
        配置的时间间隔后进入下一个周期。设计用于在应用
        启动时作为后台任务启动。

        同步间隔从应用的配置中读取（settings.sync.interval_s）。
        """
        from app.config import settings
        while True:
            await self.run_once()
            # 将成功同步后的时间记录为下次增量运行的基准
            self._last_sync = datetime.utcnow()
            await asyncio.sleep(settings.sync.interval_s)
