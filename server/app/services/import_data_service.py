# app/services/import_data.py
"""
数据导入服务模块
================
处理从 JSON 文件批量导入产品数据到数据库。

核心功能：
- 产品数据分块（将 JSON 拆分为可 Embedding 的文本片段）
- 结构化记录的事务性插入（Product、SKU、FAQ、用户评价）
- 所有文本分块的批量 Embedding 生成
- 为中文全文搜索自动设置 tsvector 触发器

导入过程采用事务机制：先刷新所有记录，再生成并插入 Embedding，
最后统一提交。
"""

import json
import os
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.models import Product, Sku, ProductMarketing, ProductFaq, UserReview, ProductReview
from app.services.embedding_service import EmbeddingService


def chunk_product(product_data: dict) -> list[tuple[str, str, dict]]:
    """
    将单个产品 JSON 字典拆分为可 Embedding 的文本分块。

    从 rag_knowledge 部分提取营销描述、官方 FAQ 和用户评价，
    并将每项格式化为带有相关元数据的可搜索文本块。

    参数：
        product_data (dict)：完整的产品 JSON 数据字典，预期包含
                            'rag_knowledge' 键。

    返回值：
        list[tuple[str, str, dict]]：(来源, 内容, 元数据) 三元组列表。
            - 来源 (str)：分块的类别（"marketing"、"faq"、"user_review"）。
            - 内容 (str)：格式化后可供 Embedding 的文本。
            - 元数据 (dict)：附加的结构化信息（如问题、昵称、评分）。
    """
    chunks = []
    rag = product_data.get("rag_knowledge", {})

    # 营销描述：作为一个整体分块处理
    marketing = rag.get("marketing_description", "")
    if marketing:
        chunks.append(("marketing", marketing, {}))

    # 官方 FAQ：每个问答对作为一个分块
    for faq in rag.get("official_faq", []):
        q = faq.get("question", "")
        a = faq.get("answer", "")
        content = f"问题：{q}\n回答：{a}"
        chunks.append(("faq", content, {"question": q}))

    # 用户评价：每个评价作为一个分块，在文本中包含昵称和评分
    for review in rag.get("user_reviews", []):
        nickname = review.get("nickname", "")
        rating = review.get("rating", 0)
        content_text = review.get("content", "")
        content = f"用户{nickname}评分{rating}分，评价：{content_text}"
        chunks.append(("user_review", content, {"nickname": nickname, "rating": rating}))

    return chunks


class DataImporter:
    """
    编排完整的产品数据导入流水线。

    从目录中读取 JSON 文件，插入结构化产品记录，
    批量生成所有文本分块的 Embedding，并将其存入
    支持向量检索的 product_review 表。
    """

    def __init__(self, session: AsyncSession, embedding_svc: EmbeddingService):
        """
        初始化数据导入器。

        参数：
            session (AsyncSession)：SQLAlchemy 异步数据库会话。
            embedding_svc (EmbeddingService)：用于生成文本 Embedding 的服务。
        """
        self.session = session
        self.embedding_svc = embedding_svc

    async def clear_all(self):
        """
        按依赖顺序删除所有导入相关表中的记录。

        使用 DELETE（而非 TRUNCATE）清空表数据，以遵循外键约束。
        顺序：先子表，后父表。
        """
        for table in ["product_review", "user_review", "product_faq", "product_marketing", "sku", "product"]:
            await self.session.execute(text(f"DELETE FROM {table}"))
        await self.session.commit()

    async def import_json_dir(self, data_dir: str) -> int:
        """
        将目录中所有 JSON 产品文件导入数据库。

        处理阶段：
        1. 解析每个 JSON 文件并创建 ORM 模型实例（Product、SKU、
           ProductMarketing、ProductFaq、UserReview）—— 全部暂存于会话中。
        2. 对每个产品的文本数据进行分块，收集所有 Embedding 候选项。
        3. 刷新结构化记录到数据库（在插入 product_review 行之前满足外键约束）。
        4. 通过单次批量 API 调用为所有文本分块生成 Embedding。
        5. 插入带有 Embedding 的 product_review 行并提交事务。
        6. 确保 PostgreSQL tsvector 触发器存在以支持全文搜索。

        参数：
            data_dir (str)：包含 .json 产品文件的目录路径。

        返回值：
            int：成功导入的产品文件总数。
        """
        imported = 0
        all_embeddings: list[dict] = []

        # 第 1 阶段：解析 JSON 文件并创建 ORM 实例
        for filename in os.listdir(data_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(data_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            pid = data["product_id"]

            # 核心产品记录
            product = Product(
                product_id=pid,
                title=data["title"],
                brand=data.get("brand"),
                category=data.get("category"),
                sub_category=data.get("sub_category"),
                base_price=data.get("base_price"),
                image_path=data.get("image_path"),
            )
            self.session.add(product)

            # SKU 变体
            for sku_data in data.get("skus", []):
                sku = Sku(
                    sku_id=sku_data["sku_id"],
                    product_id=pid,
                    properties=sku_data.get("properties", {}),
                    price=sku_data["price"],
                    stock=sku_data.get("stock", 0),
                )
                self.session.add(sku)

            # 营销描述
            rag = data.get("rag_knowledge", {})
            marketing = rag.get("marketing_description", "")
            if marketing:
                pm = ProductMarketing(product_id=pid, description=marketing)
                self.session.add(pm)

            # 官方 FAQ
            for faq in rag.get("official_faq", []):
                pf = ProductFaq(
                    product_id=pid,
                    question=faq["question"],
                    answer=faq["answer"],
                )
                self.session.add(pf)

            # 用户评价
            for review in rag.get("user_reviews", []):
                ur = UserReview(
                    product_id=pid,
                    nickname=review.get("nickname"),
                    rating=review.get("rating"),
                    content=review.get("content", ""),
                )
                self.session.add(ur)

            # 从当前产品收集 Embedding 候选项
            chunks = chunk_product(data)
            for source, content, metadata in chunks:
                all_embeddings.append({"product_id": pid, "source": source, "content": content, "metadata": metadata})

            imported += 1

        # 第 2 阶段：刷新结构化记录以满足外键约束
        await self.session.flush()

        # 第 3 阶段：批量生成所有文本分块的 Embedding
        texts = [e["content"] for e in all_embeddings]
        vectors = await self.embedding_svc.embed_batch(texts)

        # 第 4 阶段：插入带有 Embedding 的 product_review 行
        for i, entry in enumerate(all_embeddings):
            pr = ProductReview(
                product_id=entry["product_id"],
                source=entry["source"],
                content=entry["content"],
                embedding=vectors[i],
                extra_data=entry["metadata"],
            )
            self.session.add(pr)

        # 第 5 阶段：提交所有更改并确保全文搜索支持
        await self.session.commit()
        await self._ensure_tsvector_trigger()
        return imported

    async def _ensure_tsvector_trigger(self):
        """
        创建或替换 PostgreSQL 触发器，自动填充 content_tsv 列以支持中文全文搜索。

        需要 PostgreSQL 实例中已安装 zhparser 扩展和 jieba 中文分词器。
        若扩展不可用则跳过设置，不影响主导入流程。

        每条 DDL 语句单独执行以兼容 asyncpg（不支持一条 execute 含多条 SQL）。
        """
        tsv_config = "chinese"
        try:
            # 尝试启用 zhparser 扩展并创建中文搜索配置
            await self.session.execute(text("CREATE EXTENSION IF NOT EXISTS zhparser"))
            await self.session.execute(
                text("CREATE TEXT SEARCH CONFIGURATION IF NOT EXISTS chinese (PARSER = zhparser)")
            )
            await self.session.execute(
                text("ALTER TEXT SEARCH CONFIGURATION chinese ADD MAPPING FOR n,v,a,i,e,l WITH simple")
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            # zhparser 不可用（如 Windows 环境），回退到内置 simple 配置
            tsv_config = "simple"
            print(f"[import_data] zhparser 未安装，使用 simple 全文搜索配置")

        try:
            # 创建触发器函数（使用确定后的 tsv_config）
            await self.session.execute(
                text(f"""CREATE OR REPLACE FUNCTION product_review_tsv_trigger()
                RETURNS trigger AS $$
                BEGIN
                    NEW.content_tsv := to_tsvector('{tsv_config}', COALESCE(NEW.content, ''));
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql""")
            )

            # 删除旧触发器并创建新触发器
            await self.session.execute(
                text("DROP TRIGGER IF EXISTS trg_product_review_tsv ON product_review")
            )
            await self.session.execute(
                text("""CREATE TRIGGER trg_product_review_tsv
                    BEFORE INSERT OR UPDATE OF content ON product_review
                    FOR EACH ROW EXECUTE FUNCTION product_review_tsv_trigger()""")
            )

            # 更新已有记录的全文搜索向量
            await self.session.execute(
                text(f"UPDATE product_review SET content_tsv = to_tsvector('{tsv_config}', COALESCE(content, ''))")
            )

            await self.session.commit()
        except Exception as e:
            await self.session.rollback()
            print(f"[import_data] 跳过 tsvector 触发器设置: {e}")
