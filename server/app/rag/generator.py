# app/rag/generator.py
"""
RAG 生成模块。

负责根据检索到的候选商品构建 LLM 提示词，并以流式方式输出面向用户的推荐回复。
作为 RAG 管线的最终阶段，将结构化的检索结果转化为自然语言的购物指导。

核心功能：
- 将商品数据（标题、品牌、品类、价格、SKU）格式化为 LLM 可读的上下文字段。
- 构建系统提示词，约束 LLM 输出诚实、有据可依的推荐（禁止捏造价格、功能或库存信息）。
- 以流式方式将生成的 token 返回给调用方，用于实时展示。
"""

from app.services.llm import LLMService
from app.rag.prompt import GENERATOR_SYSTEM

# source → 中文标签映射，用于格式化匹配文本
SOURCE_LABEL = {"user": "[用户评价]", "marketing": "[官方描述]", "faq": "[FAQ]"}


class Generator:
    """基于 LLM 的推荐生成器，将结构化的候选商品信息转化为自然语言的购物建议。

    接收上游 RAG 管线检索并合并后的商品字典列表和用户查询，以 token 流的形式
    输出对话式推荐内容。
    """

    def __init__(self, llm: LLMService):
        """初始化生成器并绑定 LLM 服务后端。

        参数：
            llm: LLMService 实例，提供 chat_stream 方法用于逐 token 生成回复。
        """
        self.llm = llm

    def _build_context(self, skus: list[dict]) -> str:
        """将扁平 SKU 列表按 product_id 分组后格式化为文本块。

        先按 product_id 将 SKU 归组，每组作为一个商品条目渲染：
        商品概要行（标题/品牌/品类/基础价格），后跟该组内每条 SKU 的详情行。
        组间以空行分隔。

        参数：
            skus: 扁平 SKU 字典列表，每个字典包含 product 字段
                  （product_id/title/brand/category/sub_category/base_price）
                  和 SKU 字段（sku_id/properties/price/stock）。

        返回值：
            适合注入 LLM 系统提示词的多行字符串，作为商品上下文。
        """
        # 按 product_id 分组，保持首次出现顺序
        grouped: dict[str, dict] = {}
        order: list[str] = []
        for item in skus:
            pid = item["product_id"]
            if pid not in grouped:
                grouped[pid] = {
                    "title": item["title"],
                    "brand": item.get("brand"),
                    "category": item.get("category"),
                    "base_price": item.get("base_price"),
                    "skus": [],
                }
                order.append(pid)
            grouped[pid]["skus"].append({
                "sku_id": item["sku_id"],
                "properties": item.get("properties"),
                "price": item["price"],
            })

        lines = []
        for i, pid in enumerate(order, 1):
            p = grouped[pid]
            lines.append(f"{i}. {p['title']}")
            if p.get("brand"):
                lines.append(f"   品牌: {p['brand']}")
            if p.get("category"):
                lines.append(f"   品类: {p['category']}")
            if p.get("base_price"):
                lines.append(f"   基础价格: ¥{p['base_price']}")

            for sku in p["skus"]:
                props_parts = []
                if sku.get("properties"):
                    props_parts = [
                        f"{k}: {v}" for k, v in sku["properties"].items()
                    ]
                props = " / ".join(props_parts)
                sku_desc = f"   - SKU {sku['sku_id']}: ¥{sku['price']}"
                if props:
                    sku_desc += f" ({props})"
                lines.append(sku_desc)

            lines.append("")

        # ---- 追加匹配文本（用户评价/官方描述/FAQ） ----
        matched_lines: list[str] = []
        for item in skus:
            for mt in item.get("matched_texts", []):
                label = SOURCE_LABEL.get(mt.get("source", ""), "[其他]")
                matched_lines.append(f"{label} {mt.get('content', '')}")

        if matched_lines:
            lines.append("【用户评价与描述】")
            lines.extend(matched_lines)
            lines.append("")

        return "\n".join(lines)

    async def generate(self, products: list[dict], user_query: str):
        """根据商品和查询构建提示词，并以流式方式生成推荐回复。

        将格式化后的商品上下文和用户原始查询注入 GENERATOR_SYSTEM 模板以构建系统提示词，
        并通过一条独立的用户消息重申请求内容，为生成过程提供接地气的上下文。

        参数：
            products: 商品字典列表，作为 LLM 在当前推荐中的知识基础。
            user_query: 终端用户的原始自然语言查询。

        生成：
            str: 生成的推荐内容 token，通过底层 LLM 服务逐 token 流式输出。
        """
        context = self._build_context(products)
        system_prompt = GENERATOR_SYSTEM.format(
            product_context=context,
            user_query=user_query,
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请根据以上商品信息，为用户推荐：{user_query}"},
        ]

        # 逐 token 流式输出，用于用户端实时展示
        async for token in self.llm.chat_stream(messages, temperature=0.3):
            yield token
