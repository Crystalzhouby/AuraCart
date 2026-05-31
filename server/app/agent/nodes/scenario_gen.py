"""
Scenario Gen 节点 — 场景化需求路径。

从 category_lookup 表获取可用品类列表，与 user_query 一起注入提示词，
单次 LLM 调用端到端输出带品类标签的 SubQuery 列表。
"""
import json
import structlog
from app.config import settings
from app.agent.prompts.scenario_gen_prompt import SCENARIO_GEN_SYSTEM
from app.services.llm import LLMService

logger = structlog.get_logger("agent.scenario_gen")


def _parse_category_list(category_list: str) -> set[tuple[str, str]]:
    """将 category_list 字符串解析为 (category, sub_category) 集合。

    格式: "面部护肤|防晒霜\\n服饰|墨镜\\n..."
    """
    result = set()
    if not category_list:
        return result
    for line in category_list.strip().split("\n"):
        line = line.strip()
        if "|" in line:
            parts = line.split("|", 1)
            cat = parts[0].strip()
            sub = parts[1].strip() if len(parts) > 1 else ""
            if cat and sub:
                result.add((cat, sub))
    return result


def _cross_validate_categories(
    category: str | None,
    sub_category: str | None,
    lookup: set[tuple[str, str]],
) -> tuple[str | None, str | None]:
    """对 LLM 输出的 category/sub_category 做交叉校验。

    策略：
    1. 精确匹配 → 保留
    2. 去除前后空格后匹配 → 修正为精确值
    3. 不匹配 → 返回 (None, None)

    参数:
        category: LLM 输出的品类大类。
        sub_category: LLM 输出的品类细类。
        lookup: 从 category_lookup 表中解析的合法 (category, sub_category) 集合。

    返回值:
        (category, sub_category) 或 (None, None)。
    """
    if not category or not sub_category:
        return None, None

    cat_stripped = category.strip()
    sub_stripped = sub_category.strip()

    # 1. 精确匹配
    if (cat_stripped, sub_stripped) in lookup:
        return cat_stripped, sub_stripped

    # 2. 模糊匹配：在 lookup 中搜索去除空格和大小写差异后的匹配项
    for lc, ls in lookup:
        if lc.strip() == cat_stripped and ls.strip() == sub_stripped:
            return lc, ls

    # 3. 无法匹配
    logger.warning(
        "品类交叉校验失败，回退到 default 组",
        category=category, sub_category=sub_category,
    )
    return None, None


async def scenario_gen_node(state: dict, llm: LLMService, category_list: str = "") -> dict:
    """Scenario Gen 节点函数。

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。
        category_list: 从 category_lookup 表查询的可用品类列表字符串。

    返回值:
        dict: {"scenario_description": str, "requirements": {"sub_queries": [...]}}
    """
    user_query = state.get("user_query", "")
    conversation_history = state.get("conversation_history", [])

    prompt = SCENARIO_GEN_SYSTEM.replace("{category_list}", category_list).replace("{user_query}", user_query)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        raw_response = await llm.chat(messages, temperature=0.3)

        # 解析 LLM JSON 响应
        start = raw_response.find("{")
        end = raw_response.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(raw_response[start:end])
        else:
            raise ValueError("无法从 LLM 响应中提取 JSON")

        scenario_description = data.get("scenario_description", user_query)
        sub_queries = data.get("requirements", {}).get("sub_queries", [])

    except Exception as e:
        logger.warning("Scenario Gen LLM 调用失败，返回空结果", error=str(e))
        return {
            "scenario_description": user_query,
            "requirements": {"sub_queries": []},
        }

    # 构建品类查找表用于交叉校验
    lookup = _parse_category_list(category_list)

    # 标准化 SubQuery 字典格式 + 交叉校验
    subs_dicts = []
    for sq in sub_queries:
        raw_category = sq.get("category")
        raw_sub_category = sq.get("sub_category")
        # 交叉校验：修正或回退
        validated_category, validated_sub_category = _cross_validate_categories(
            raw_category, raw_sub_category, lookup
        )
        subs_dicts.append({
            "text": sq.get("text", ""),
            "strategy": sq.get("strategy", "semantic"),
            "field": sq.get("field"),
            "operator": sq.get("operator"),
            "value": sq.get("value"),
            "expanded_values": sq.get("expanded_values"),
            "category": validated_category,
            "sub_category": validated_sub_category,
        })

    # 追加到 conversation_history + 截断
    new_entry = {"sub_queries": subs_dicts}
    new_history = conversation_history + [new_entry]
    from app.agent.memory import truncate_by_tokens
    new_history = truncate_by_tokens(new_history, max_tokens=settings.search.memory_max_tokens, logger=logger)

    return {
        "scenario_description": scenario_description,
        "requirements": {"sub_queries": subs_dicts},
        "conversation_history": new_history,
    }
