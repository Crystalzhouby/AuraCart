from app.core.config import settings


class LlmClient:
    """Ark/Doubao client placeholder.

    The RAG skeleton can run without a real API key. Replace this class with
    an OpenAI-compatible streaming client when connecting Doubao in depth.
    """

    async def stream(self, prompt: str):
        if not settings.ark_api_key:
            yield "当前未配置 ARK_API_KEY，后端使用本地降级回复。"
            return
        yield prompt
