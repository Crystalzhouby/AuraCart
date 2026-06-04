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
import structlog
from app.services.retriever_service import SubQuery
from app.services.llm_service import LLMService

logger = structlog.get_logger("query_parser")

# ---------------------------------------------------------------------------
# 查询意图解析提示词
# ---------------------------------------------------------------------------
# 该提示词驱动 RAG 管线第一阶段：将用户的自由文本查询拆解为结构化的检索指令。
# 每个子查询指定使用的检索策略、字段级过滤条件、否定条件，以及可选的世界知识
# 属性展开值（如"日系品牌"→ 日本品牌列表）。
# ---------------------------------------------------------------------------

QUERY_PARSE_SYSTEM = """你是一个电商查询意图拆解专家。将用户的自然语言查询拆分为多个子查询，每个子查询对应一种检索策略。
## 最高优先级：品类约束

以下是系统中唯一存在的合法 (category, sub_category) 组合。生成 category 和 sub_category 字段时，MUST 严格从此列表选取，不得自创、近似匹配或推断。无法确定时保持 null。

{category_list}

## 策略决策规则
按以下优先级判定每条子查询的策略类型：

**P1 — 可结构化条件** → strategy="structured_filter"
触发条件：查询包含可映射到具体字段的数值/枚举约束。
- 价格区间 → field="price", operator="lt"/"gt"/"between"
- 品牌限定/排除 → field="brand", operator="in"/"not_in"，"非日系""欧美品牌"等需世界知识展开的填入 expanded_values
- 属性条件 → field 为 sku.properties 中的 key，operator 为 eq/in/contains
- 否定条件统一使用 not_in / not_contains
- text 字段留空 ""

**P2 — 成分/内容级否定** → strategy="semantic"
触发条件：查询排除某成分/特征，但该特征不存在于结构化字段中（如"不含酒精""不含香精""不粘腻"）。
- text 格式："产品评价中是否提及{成分/特征}"
- MUST 标注 category 和 sub_category

**P3 — 具体品类/商品关键词** → strategy="keyword"
触发条件：查询包含明确的商品名、品类名、品牌名。
- text 为核心检索词，保留用户原词，不做语义扩展
- MUST 标注 category 和 sub_category

**P4 — 主观评价/体验意图** → strategy="semantic"
触发条件：查询包含主观感受词（"好用""舒服""效果好""性价比高"）。
- text 为评价短句，从用户原句中提炼关键词，保持自然
- MUST 标注 category 和 sub_category

**冲突处理**：一条子查询只选一个策略。P1 > P2 > P3 > P4。结构化条件与主观意图同时存在时，拆为两条子查询。

## 可用字段
- product: brand, category, sub_category, title
- sku: price, stock, properties (JSONB，key 因 sub_category 而异)

## 拆分原则
- 每个独立的检索维度拆为一条子查询，不做合并
- 同一维度的多个值合并在一条子查询内（如"品牌A或品牌B"→ 一条 structured_filter with expanded_values）
- 无法确定品类时 category 和 sub_category 均设为 null，不得猜测

## 输出格式
MUST 只返回一个 JSON 数组。禁止输出 Markdown 代码围栏、解释文字、或任何非 JSON 内容。

数组元素结构：
{
"text": str,                    // 子查询文本（structured_filter 时可为 ""）
"strategy": "semantic" | "keyword" | "structured_filter",
"field": str | null,            // 仅 structured_filter 时填写
"operator": "eq" | "lt" | "gt" | "in" | "not_in" | "contains" | "not_contains" | null,
"value": str | number | null,   // 单值比较时填写
"expanded_values": [str] | null, // 多值展开（世界知识），如"日系品牌"→["SK-II","资生堂",...]
"category": str | null,         // MUST 从品类列表中精确匹配
"sub_category": str | null      // MUST 从品类列表中精确匹配
}

## 示例

示例1 — 复合查询
用户: "推荐一款200元以下的不含酒精的非日系防晒霜"
输出:
[
{"text": "防晒霜", "strategy": "keyword", "field": null, "operator": null, "value": null, "expanded_values": null, "category": "面部护肤", "sub_category": "防晒霜"},
{"text": "产品防晒效果是否出色", "strategy": "semantic", "field": null, "operator": null, "value": null, "expanded_values": null, "category": "面部护肤", "sub_category": "防晒霜"},
{"text": "产品评价中是否提及酒精成分", "strategy": "semantic", "field": null, "operator": null, "value": null, "expanded_values": null, "category": "面部护肤", "sub_category": "防晒霜"},
{"text": "", "strategy": "structured_filter", "field": "price", "operator": "lt", "value": 200, "expanded_values": null, "category": "面部护肤", "sub_category": "防晒霜"},
{"text": "", "strategy": "structured_filter", "field": "brand", "operator": "not_in", "value": null, "expanded_values":
["SK-II","资生堂","CPB","雪肌精","DHC","FANCL","植村秀","SUQQU","高丝","KOSE"], "category": "面部护肤", "sub_category": "防晒霜"}
]

示例2 — 纯评价查询（无品类限定）
用户: "适合敏感肌的温和洗面奶"
输出:
[
{"text": "洗面奶", "strategy": "keyword", "field": null, "operator": null, "value": null, "expanded_values": null, "category": "面部护肤", "sub_category": "洗面奶"},
{"text": "适合敏感肌 温和不刺激", "strategy": "semantic", "field": null, "operator": null, "value": null, "expanded_values": null, "category": "面部护肤", "sub_category": "洗面奶"}
]

现在请对以下用户查询进行拆解，只返回 JSON 数组，不要其他内容："""


# ---------------------------------------------------------------------------
# 提示词构建函数
# ---------------------------------------------------------------------------


def build_parse_prompt(category_list: str = "") -> str:
    """构建查询解析提示词，注入品类列表。

    将品类清单填入 QUERY_PARSE_SYSTEM 模板的 {category_list} 占位符。
    品类列表为空时，输出不含品类约束的提示词（向后兼容）。

    参数:
        category_list: 按 category 分组的品类清单字符串，由
                       fetch_category_context() 生成。

    返回值:
        str: 完整的系统提示词。
    """
    if category_list:
        return QUERY_PARSE_SYSTEM.replace("{category_list}", category_list)
    else:
        return QUERY_PARSE_SYSTEM.replace("{category_list}", "")

__all__ = ["QueryParser", "SubQuery", "QUERY_PARSE_SYSTEM", "build_parse_prompt"]


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

    async def parse(
        self,
        user_query: str,
        category_list: str = "",
        valid_categories: set[tuple[str, str]] | None = None,
    ) -> list[SubQuery]:
        """
        将用户的自然语言查询解析为结构化的子查询。

        将查询与系统提示一同发送给 LLM，并将 JSON 响应
        解析为 SubQuery 对象。若传入 category_list，则将其注入提示词
        以约束 LLM 只输出合法品类值。

        参数：
            user_query (str)：原始用户查询字符串。
            category_list (str)：按 category 分组的品类清单，
                由 fetch_category_context() 生成。默认 "" 表示不注入。
            valid_categories (set|None)：合法 (category, sub_category) 对集合，
                用于后校验。默认 None 表示跳过后校验。

        返回值：
            list[SubQuery]：解析后的子查询列表，每个子查询指定
                            文本、策略、否定标记和可选过滤条件。
        """
        system_prompt = build_parse_prompt(category_list)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query},
        ]

        # 使用流式调用降低首 token 延迟（non-stream 需等完整响应 ~18s，
        # stream 首 token ~10.5s），低温度保证输出确定性
        parts = []
        async for token in self.llm.chat_stream(messages, temperature=0.1):
            parts.append(token)
        response = "".join(parts)
        sub_queries = self._parse_response(response)

        # 后校验：确保 LLM 输出的品类值严格合法
        if valid_categories:
            from app.services.category_lookup_service import validate_categories
            sub_queries = validate_categories(sub_queries, valid_categories)

        return sub_queries

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
                category=item.get("category"),
                sub_category=item.get("sub_category"),
            ))
        return subs
