"""
Intent Extraction 节点 — 明确商品需求路径。

三步流程：
1. LLM 提取品类/品牌意图 + Tool 校验合法性
2. 从 session_memory 按品类检索历史查询并拼接
3. LLM 分组提取结构化+语义意图

输出新格式: [{category, sub_category, text, min_price, max_price, order_num, brand}]
"""
import json
import re
import structlog
from app.agent.prompts.extraction_prompt import EXTRACTION_STEP1_SYSTEM, EXTRACTION_STEP3_SYSTEM
from app.agent.memory import get_queries_by_category
from app.services.llm_service import LLMService

logger = structlog.get_logger("agent.extraction")


def _parse_json_array(raw: str) -> list:
    """从 LLM 原始响应中提取 JSON 数组，失败返回空列表。

    增强容错：去除 markdown 代码围栏、尾随逗号、JSON 前后文字。
    """
    if not raw:
        return []

    raw = raw.strip()
    # 去除 markdown 代码围栏
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()

    # 提取 JSON 数组
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start >= 0 and end > start:
        json_str = raw[start:end]
    else:
        return []

    # 1. 直接解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # 2. 移除尾随逗号后重试
    cleaned = re.sub(r",\s*([}\]])", r"\1", json_str)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    return []


def _build_context_with_memory(
    user_query: str,
    categories: list[dict],
    session_memory: list[dict],
) -> str:
    """Step 2: 按品类从 session_memory 检索历史查询，与当前查询拼接。

    每个品类的历史查询按时间升序编号，末尾追加当前查询。
    所有品类拼接为一个文本块供 Step 3 一次性处理。

    参数:
        user_query: 用户查询。
        categories: Step 1 输出的品类列表 [{category, sub_category, ...}]。
        session_memory: session_memory 列表。

    返回值:
        str: 拼接后的文本，多品类分段展示。
    """
    parts = []

    for i, cat in enumerate(categories, 1):
        cat_name = cat.get("category")
        sub_name = cat.get("sub_category")
        label = f"{cat_name or '未知'}/{sub_name or '未知'}"

        # 检索该品类的历史查询
        history = get_queries_by_category(session_memory, cat_name, sub_name)
        sorted_history = sorted(history, key=lambda q: q.get("timestamp", ""))

        lines = [f"## 品类 {i}: {label}"]
        if sorted_history:
            lines.append("历史查询（按时间顺序）：")
            for j, hq in enumerate(sorted_history, 1):
                lines.append(f"  #{j} [{hq.get('timestamp', '')}] {hq.get('query', '')}")
        else:
            lines.append("历史查询：(无)")
        lines.append(f"当前查询: {user_query}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts) if parts else user_query


async def _extract_categories_and_brands(
    user_query: str,
    llm: LLMService,
    db_session_factory,
) -> list[dict]:
    """Step 1: LLM 提取品类/品牌 + Tool 校验合法性。

    参数:
        user_query: 用户查询。
        llm: LLMService 实例。
        db_session_factory: async_session 工厂函数。

    返回值:
        [{"category": "美妆护肤", "sub_category": "防晒", "brand": ["安热沙"]}, ...]
    """
    # 加载品类上下文用于提示词注入
    category_list = ""
    valid_categories = None
    try:
        from app.services.category_lookup_service import fetch_category_context
        async with db_session_factory() as session:
            category_list, valid_categories = await fetch_category_context(session)
    except Exception as e:
        logger.warning("extraction Step1 品类加载失败", error=str(e))

    prompt = EXTRACTION_STEP1_SYSTEM.replace("{category_list}", category_list)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        raw = await llm.chat(messages, temperature=0.1)
        parsed = _parse_json_array(raw)
    except Exception as e:
        logger.warning("extraction Step1 LLM 调用失败", error=str(e))
        return []

    if not parsed:
        return []

    # Tool 校验：brand 取值需在 product 表中存在
    result = []
    for item in parsed:
        cat = item.get("category")
        sub = item.get("sub_category")
        brands = item.get("brand", [])

        # 品类校验（精确匹配）
        if valid_categories and cat and sub:
            if (cat, sub) not in valid_categories:
                logger.debug("Step1 品类不合法，置 null", category=cat, sub_category=sub)
                cat = None
                sub = None

        # 品牌校验
        valid_brands = []
        if brands and cat and sub:
            try:
                from app.agent.tools import query_field_values
                async with db_session_factory() as session:
                    valid_brands = await query_field_values(
                        session, "product", "brand",
                        {"category": cat, "sub_category": sub},
                    )
            except Exception as e:
                logger.warning("Step1 brand 校验失败", error=str(e))

        verified_brands = [b for b in brands if b in valid_brands] if valid_brands else brands

        result.append({
            "category": cat,
            "sub_category": sub,
            "brand": verified_brands if verified_brands else None,
        })

    return result


async def _extract_intents_per_category(
    context: str,
    llm: LLMService,
    brand_reference: str = "",
) -> list[dict]:
    """Step 3: 从拼接文本中按品类分组提取结构化+语义意图。

    参数:
        context: Step 2 输出的拼接文本。
        llm: LLMService 实例。
        brand_reference: 格式化的品牌参考文本，注入到 prompt。

    返回值:
        [{category, sub_category, text, min_price, max_price, order_num, brand}, ...]
    """
    prompt = (EXTRACTION_STEP3_SYSTEM
              .replace("{brand_reference}", brand_reference or "(品牌数据暂不可用)")
              .replace("{context}", context))
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "请提取意图"},
    ]

    try:
        raw = await llm.chat(messages, temperature=0.1)
        parsed = _parse_json_array(raw)
    except Exception as e:
        logger.warning("extraction Step3 LLM 调用失败", error=str(e))
        return []

    # 字段标准化
    result = []
    for item in parsed:
        result.append({
            "category": item.get("category"),
            "sub_category": item.get("sub_category"),
            "text": (item.get("text") or "").strip(),
            "min_price": int(item.get("min_price", 0) or 0),
            "max_price": int(item.get("max_price", 4294967295) or 4294967295),
            "order_num": int(item.get("order_num", 1) or 1),
            "brand": item.get("brand") if item.get("brand") else [],
        })

    return result


async def extraction_node(
    state: dict,
    llm: LLMService,
    db_session_factory,
) -> dict:
    """Intent Extraction 节点函数 — 三步流程。

    参数:
        state: AgentState 字典。
        llm: LLMService 实例。
        db_session_factory: async_session 工厂函数（用于 Tools 调用）。

    返回值:
        dict: {"requirements": [新格式]}，写入 AgentState。
    """
    user_query = state.get("user_query", "")
    session_memory = state.get("session_memory", [])

    # ---- Step 1: 提取品类/品牌 ----
    categories = await _extract_categories_and_brands(
        user_query, llm, db_session_factory
    )

    if not categories:
        # 无法提取品类时，用空品类做一次尝试
        logger.warning("extraction Step1 未提取到品类，使用空品类回退")
        categories = [{"category": None, "sub_category": None, "brand": None}]

    # ---- Step 2: 检索历史并拼接 ----
    context = _build_context_with_memory(user_query, categories, session_memory)

    # ---- 查询品牌列表并注入 Step3 context ----
    brand_reference = ""
    try:
        pairs = [
            (c.get("category"), c.get("sub_category"))
            for c in categories
            if c.get("category") and c.get("sub_category")
        ]
        if pairs:
            from app.agent.tools import get_brands_by_categories
            async with db_session_factory() as session:
                brand_map = await get_brands_by_categories(session, pairs)
            brand_lines = []
            for (cat, sub), brands in brand_map.items():
                if brands:
                    brand_lines.append(f"- {cat}/{sub}: {', '.join(brands)}")
                else:
                    brand_lines.append(f"- {cat}/{sub}: (该品类暂无品牌数据)")
            brand_reference = "\n".join(brand_lines) if brand_lines else ""
    except Exception as e:
        logger.warning("Step3 品牌查询失败", error=str(e))

    # ---- Step 3: 分组提取意图 ----
    requirements = await _extract_intents_per_category(context, llm, brand_reference)

    if not requirements:
        logger.warning("extraction Step3 未提取到意图，使用 fallback")
        requirements = [{
            "category": None,
            "sub_category": None,
            "text": user_query,
            "min_price": 0,
            "max_price": 4294967295,
            "order_num": 1,
            "brand": [],
        }]

    logger.info("extraction 完成", category_count=len(categories),
                requirement_count=len(requirements))

    return {"requirements": requirements}
