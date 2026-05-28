# app/services/query_parser.py
"""
查询解析模块
============
使用 LLM 将自然语言用户查询解析为结构化的 SubQuery 对象。

核心功能：
- 使用包含解析语法的系统提示，将用户查询发送给 LLM
- 清除 LLM 输出中的 Markdown 代码围栏
- 将 JSON 响应反序列化为 SubQuery 数据类实例列表

每个 SubQuery 编码：子查询文本、搜索策略（semantic/keyword/structured_filter）、
可选否定标记，以及可选的结构化过滤参数（字段、操作符、值）。
"""

import json
from app.services.retriever import SubQuery
from app.services.llm import LLMService
from app.rag.prompt import QUERY_PARSE_SYSTEM


__all__ = ["QueryParser", "SubQuery"]


class QueryParser:
    """
    通过 LLM 将用户查询解析为结构化的 SubQuery 对象。

    使用专门的系统提示指导 LLM 将自然语言查询分解为
    一个或多个子查询，每个子查询包含指定的搜索策略
    和可选的过滤参数。
    """

    def __init__(self, llm: LLMService):
        """
        初始化查询解析器。

        参数：
            llm (LLMService)：用于解析用户查询的 LLM 服务。
        """
        self.llm = llm

    async def parse(self, user_query: str) -> list[SubQuery]:
        """
        将用户的自然语言查询解析为结构化的子查询。

        将查询与系统提示一同发送给 LLM，并将 JSON 响应
        解析为 SubQuery 对象。

        参数：
            user_query (str)：原始用户查询字符串。

        返回值：
            list[SubQuery]：解析后的子查询列表，每个子查询指定
                            文本、策略、否定标记和可选过滤条件。
        """
        messages = [
            {"role": "system", "content": QUERY_PARSE_SYSTEM},
            {"role": "user", "content": user_query},
        ]

        # 使用流式调用降低首 token 延迟（non-stream 需等完整响应 ~18s，
        # stream 首 token ~10.5s），低温度保证输出确定性
        parts = []
        async for token in self.llm.chat_stream(messages, temperature=0.1):
            parts.append(token)
        response = "".join(parts)
        return self._parse_response(response)

    def _parse_response(self, llm_output: str) -> list[SubQuery]:
        """
        将 LLM 原始输出字符串解析为 SubQuery 对象。

        处理某些 LLM 在 JSON 输出外包裹的可选 Markdown 代码围栏
        （```json ... ```）。

        参数：
            llm_output (str)：LLM 的原始文本输出。

        返回值：
            list[SubQuery]：反序列化的 SubQuery 实例列表。
        """
        text = llm_output.strip()

        # 如果存在 Markdown 代码围栏则将其移除（例如 ```json ... ```）
        if text.startswith("```"):
            lines = text.split("\n")
            # 移除首行和末行（围栏标记）
            text = "\n".join(lines[1:-1])

        data = json.loads(text)
        subs = []
        for item in data:
            subs.append(SubQuery(
                text=item.get("text", ""),
                strategy=item.get("strategy", "semantic"),
                field=item.get("field"),
                operator=item.get("operator"),
                value=item.get("value"),
                expanded_values=item.get("expanded_values"),
            ))
        return subs
