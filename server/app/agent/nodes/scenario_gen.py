"""
Scenario Gen 节点 — 场景化需求路径。

从 rewritten_query 出发，结合可用品类列表和历史查询，
LLM 端到端输出场景描述 + 新格式的品类分组意图列表。
"""
import json
import re
import structlog
from app.agent.prompts.scenario_gen_prompt import SCENARIO_GEN_SYSTEM
from app.agent.memory import get_queries_by_category
from app.services.llm_service import LLMService

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
    """对 LLM 输出的 category/sub_category 做交叉校验。"""
    if not category or not sub_category:
        return None, None

    cat_stripped = category.strip()
    sub_stripped = sub_category.strip()

    if (cat_stripped, sub_stripped) in lookup:
        return cat_stripped, sub_stripped

    for lc, ls in lookup:
        if lc.strip() == cat_stripped and ls.strip() == sub_stripped:
            return lc, ls

    logger.warning("品类交叉校验失败", category=category, sub_category=sub_category)
    return None, None


def _build_scenario_history_context(
    rewritten_query: str,
    category_list: str,
    session_memory: list[dict],
) -> str:
    """为 Scenario Gen 构建历史查询上下文。

    先从品类列表中提取相关品类，再检索其历史查询，格式化为文本。

    参数:
        rewritten_query: Router 改写后的查询。
        category_list: 可用品类列表字符串。
        session_memory: session_memory 列表。

    返回值:
        str: 格式化的历史查询文本。无历史时返回 "(无历史记录)"。
    """
    if not session_memory:
        return "(无历史记录)"

    # 提取可能相关的品类
    lookup = _parse_category_list(category_list)

    parts = []
    for cat, sub in list(lookup)[:6]:  # 最多 6 个品类
        history = get_queries_by_category(session_memory, cat, sub)
        if history:
            sorted_h = sorted(history, key=lambda q: q.get("timestamp", ""))
            lines = [f"- {cat}/{sub}:"]
            for j, hq in enumerate(sorted_h, 1):
                lines.append(f"  #{j} [{hq.get('timestamp', '')}] {hq.get('query', '')}")
            parts.append("\n".join(lines))

    return "\n".join(parts) if parts else "(无历史记录)"


def _parse_json_dict(raw: str) -> dict | None:
    """从 LLM 原始响应中提取 JSON 对象。"""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(raw[start:end])
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw[start:end])
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None


async def scenario_gen_node(
    state: dict,
    llm: LLMService,
    category_list: str = "",
    db_session_factory=None,
) -> dict:
    """Scenario Gen 节点函数。

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。
        category_list: 可用品类列表字符串。
        db_session_factory: async_session 工厂函数（保留兼容）。

    返回值:
        dict: {"scenario_description": str, "requirements": [新格式]}
    """
    rewritten_query = state.get("rewritten_query", state.get("user_query", ""))
    session_memory = state.get("session_memory", [])

    # 构建历史查询上下文
    history_context = _build_scenario_history_context(
        rewritten_query, category_list, session_memory
    )

    prompt = (SCENARIO_GEN_SYSTEM
              .replace("{category_list}", category_list)
              .replace("{history_context}", history_context)
              .replace("{user_query}", rewritten_query))
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": rewritten_query},
    ]

    try:
        raw_response = await llm.chat(messages, temperature=0.3)
        data = _parse_json_dict(raw_response)

        if data is None:
            raise ValueError("无法从 LLM 响应中提取 JSON")

        scenario_description = data.get("scenario_description", rewritten_query)
        requirements = data.get("requirements", [])

        # 如果 requirements 是旧格式 {sub_queries: [...]}，做兼容提取
        if isinstance(requirements, dict):
            requirements = requirements.get("sub_queries", [])

    except Exception as e:
        logger.warning("Scenario Gen LLM 调用失败", error=str(e))
        return {
            "scenario_description": rewritten_query,
            "requirements": [],
        }

    # 品类交叉校验 + 标准化为新格式
    lookup = _parse_category_list(category_list)
    normalized = []
    for sq in requirements:
        raw_cat = sq.get("category")
        raw_sub = sq.get("sub_category")
        validated_cat, validated_sub = _cross_validate_categories(
            raw_cat, raw_sub, lookup
        )
        normalized.append({
            "category": validated_cat,
            "sub_category": validated_sub,
            "text": (sq.get("text") or "").strip(),
            "min_price": int(sq.get("min_price", 0) or 0),
            "max_price": int(sq.get("max_price", 4294967295) or 4294967295),
            "order_num": int(sq.get("order_num", 1) or 1),
            "brand": sq.get("brand") if sq.get("brand") else None,
        })

    return {
        "scenario_description": scenario_description,
        "requirements": normalized,
    }
