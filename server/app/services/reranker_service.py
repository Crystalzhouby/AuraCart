"""
Reranker API 客户端模块。

封装 bge-reranker-v2-m3 精排模型通过 SiliconFlow API 的调用。
提供异步 rerank 方法和完善的超时/错误处理。

API 规范参考: https://docs.siliconflow.cn/cn/api-reference/rerank/create-rerank
"""

import httpx
import structlog

logger = structlog.get_logger("services.reranker")


class RerankerService:
    """bge-reranker-v2-m3 SiliconFlow API 异步客户端。

    对 RRF 融合后的候选文档进行精排重排序，返回按 relevance_score 降序排列的结果。
    API 失败时返回空列表，由调用方 fallback 到 RRF top-K。
    """

    def __init__(
        self,
        base_url: str = "https://api.siliconflow.cn/v1",
        api_key: str = "",
        model: str = "BAAI/bge-reranker-v2-m3",
        timeout: float = 5.0,
    ):
        """初始化 Reranker 服务。

        参数:
            base_url: SiliconFlow API 端点的基础 URL。
            api_key: API 认证密钥。
            model: 精排模型名称。
            timeout: HTTP 请求超时时间（秒）。
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """延迟初始化 httpx AsyncClient（避免提前创建 event loop 冲突）。"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def rerank(
        self, query: str, documents: list[str], top_n: int = 5
    ) -> list[dict]:
        """对文档列表进行重排序，返回最相关的 top_n 条。

        参数:
            query: 搜索查询字符串（用户的语义查询文本）。
            documents: 待重排序的文档列表（每条为商品标题+评价摘要）。
            top_n: 返回的最相关文档数量。

        返回值:
            [{"index": 0, "relevance_score": 0.6406}, ...]
            按 relevance_score 降序排列。API 失败返回空列表。
        """
        if not documents:
            return []

        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": min(top_n, len(documents)),
            "return_documents": False,
            "max_chunks_per_doc": 1024,
            "overlap_tokens": 80,
        }

        try:
            client = await self._get_client()
            resp = await client.post("/v1/rerank", json=payload)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            logger.debug(
                "Reranker API 调用成功",
                query_preview=query[:80],
                doc_count=len(documents),
                result_count=len(results),
            )
            return results
        except httpx.TimeoutException:
            logger.warning("Reranker API 超时，使用 fallback",
                          timeout=self.timeout, query_preview=query[:80])
            return []
        except Exception as e:
            logger.warning("Reranker API 失败，使用 fallback",
                          error=str(e), query_preview=query[:80])
            return []

    async def close(self):
        """释放底层 httpx 客户端资源。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
