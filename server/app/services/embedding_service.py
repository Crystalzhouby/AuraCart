# app/services/embedding.py
"""
Embedding 服务模块
==================
通过 OpenAI 兼容 API 提供异步文本 Embedding 生成客户端。

核心功能：
- 单文本 Embedding 生成
- 可配置批大小的批量 Embedding 生成
- 完善的异步 HTTP 客户端生命周期管理
"""

from openai import AsyncOpenAI


class EmbeddingService:
    """
    封装 OpenAI 兼容 Embedding API 的异步服务。

    处理针对远程模型端点的单条与批量 Embedding 请求。
    支持可配置的批量大小，以实现高效的批量处理。
    """

    def __init__(self, base_url: str, api_key: str, model: str, batch_size: int = 20):
        """
        初始化 Embedding 服务。

        参数：
            base_url (str)：OpenAI 兼容 API 端点的基础 URL。
            api_key (str)：用于认证的 API 密钥。
            model (str)：所有请求使用的 Embedding 模型名称。
            batch_size (int)：embed_batch 调用中每批处理的文本数量。
                              默认值为 20。
        """
        self.model = model
        self.batch_size = batch_size
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    async def embed(self, text: str) -> list[float]:
        """
        为单个文本字符串生成 Embedding 向量。

        参数：
            text (str)：待 Embedding 的输入文本。

        返回值：
            list[float]：由浮点数值组成的 Embedding 向量列表。
        """
        resp = await self._client.embeddings.create(
            model=self.model,
            input=text,
        )
        return resp.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批量为文本列表生成 Embedding。

        将输入按 self.batch_size 大小分块，并对每个块发起并行 API 请求。
        结果按 API 返回的索引重新排序，以保持输入顺序。

        参数：
            texts (list[str])：待 Embedding 的输入文本字符串列表。

        返回值：
            list[list[float]]：Embedding 向量列表，每个向量对应同索引位置的输入文本。
        """
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            # 提取当前批次切片
            chunk = texts[i : i + self.batch_size]
            resp = await self._client.embeddings.create(
                model=self.model,
                input=chunk,
            )
            # API 可能乱序返回结果；按索引排序以匹配输入顺序
            sorted_data = sorted(resp.data, key=lambda x: x.index)
            vectors.extend(item.embedding for item in sorted_data)
        return vectors

    async def close(self):
        """
        关闭底层异步 HTTP 客户端以释放资源。

        应在不再需要该服务时调用，以防止连接泄漏。
        """
        await self._client.close()
