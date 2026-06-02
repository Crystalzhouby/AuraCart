# app/services/llm.py
"""
LLM 服务模块
============
提供支持流式输出的 OpenAI 兼容异步聊天补全客户端。

核心功能：
- 非流式聊天补全（单次响应）
- 流式聊天补全（通过异步生成器逐步生成内容块）
- 可配置的模型、温度和 API 端点
"""

from openai import AsyncOpenAI
import structlog

logger = structlog.get_logger("services.llm")


def _truncate_messages(messages: list[dict], max_len: int = 2000) -> list[dict]:
    """截断 messages 中每条 content 字段，防止日志爆炸。

    仅处理 str 类型的 content（多模态 content 保持不变）。
    返回浅拷贝后的列表，不修改原始对象。

    参数:
        messages: 待截断的消息列表。
        max_len: content 最大字符数。

    返回值:
        截断后的消息列表（浅拷贝）。
    """
    result: list[dict] = []
    for msg in messages:
        copy = dict(msg)
        content = copy.get("content")
        if isinstance(content, str) and len(content) > max_len:
            copy["content"] = content[:max_len] + "...<truncated>"
        result.append(copy)
    return result


class LLMService:
    """
    封装 OpenAI 兼容聊天补全 API 的异步服务。

    支持标准（单次响应）和流式（增量生成）两种补全模式，
    温度参数可配置。
    """

    def __init__(self, base_url: str, api_key: str, model: str, temperature: float = 0.3):
        """
        初始化 LLM 服务。

        参数：
            base_url (str)：OpenAI 兼容 API 端点的基础 URL。
            api_key (str)：用于认证的 API 密钥。
            model (str)：所有请求使用的聊天模型名称。
            temperature (float)：默认采样温度 (0.0–2.0)。
                                较低的值产生更确定性的输出。
                                默认值为 0.3。
        """
        self.model = model
        self.temperature = temperature
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    async def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        """
        发送非流式聊天补全请求。

        参数：
            messages (list[dict])：消息字典列表，包含 'role' 和 'content' 键，
                                  遵循 OpenAI 聊天格式。
            temperature (float | None)：覆盖本次请求的默认温度参数。
                                       若为 None，则使用实例默认值。默认为 None。

        返回值：
            str：模型响应消息的完整文本内容。
        """
        logger.debug("LLM chat request",
            model=self.model,
            temperature=temperature if temperature is not None else self.temperature,
            messages=_truncate_messages(messages),
        )
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.temperature,
        )
        return resp.choices[0].message.content

    async def chat_stream(self, messages: list[dict], temperature: float | None = None):
        """
        发送流式聊天补全请求。

        以增量方式逐步生成内容块，实现生成文本的实时展示。

        参数：
            messages (list[dict])：消息字典列表，包含 'role' 和 'content' 键，
                                  遵循 OpenAI 聊天格式。
            temperature (float | None)：覆盖本次请求的默认温度参数。
                                       若为 None，则使用实例默认值。默认为 None。

        生成：
            str：来自流式响应的增量文本内容块。
                空内容块（例如 delta.content 为 None 时）将被跳过。
        """
        logger.debug("LLM chat stream request",
            model=self.model,
            temperature=temperature if temperature is not None else self.temperature,
            messages=_truncate_messages(messages),
        )
        stream = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta
            content = delta.content
            # 仅生成非空内容；API 可能会发送带有元数据但不含
            # 文本增量的块（例如仅含 role 的块或结束原因）
            if content:
                yield content

    async def close(self):
        """
        关闭底层异步 HTTP 客户端以释放资源。

        应在不再需要该服务时调用，以防止连接泄漏。
        """
        await self._client.close()
