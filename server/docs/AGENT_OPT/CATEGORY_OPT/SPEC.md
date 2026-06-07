# 检索结果返回优化

调用/api/search/接口返回的结果按照category

# 修改一下SSE返回的标签

修改单个product的推荐理由的event标签为product_reason；
修改每个品类的介绍语的event标签为category_intro；
修改最后的结束语的event标签为ending。

# 结束语上下文修改

当前结束语prompt的上下文不包含当前用户查询，请进行补充，并要求结束语生成主要关注回应当前用户查询，并将对话历史用于补充会话全局上下文。

# 完善scenario_gen_prompt
提示词中的{brand_map}为用户品牌映射表，当前实现是空的，请进行补充。
---- 查询全部品类品牌映射表 ----
brand_map_text = "(品牌数据暂不可用)"
pairs = list(_parse_category_list(category_list))
if pairs and db_session_factory:
    try:
        from app.agent.tools import get_brands_by_categories
        async with db_session_factory() as session:
            brand_map = await get_brands_by_categories(session, pairs)
        lines = []
        for (cat, sub), brands in sorted(brand_map.items()):
            if brands:
                lines.append(f"- {cat}/{sub}: {', '.join(brands[:10])}")
            else:
                lines.append(f"- {cat}/{sub}: (暂无)")
        brand_map_text = "\n".join(lines) if lines else "(无品类数据)"
    except Exception as e:
        logger.warning("scenario_gen 品牌查询失败", error=str(e))

# 修改_cross_validate_categories()函数
改为支持"精确匹配"数据表中的(category,sub_category)对

def _cross_validate_categories(
    category: str | None,
    sub_category: str | None,
    lookup: set[tuple[str, str]],
) -> tuple[str | None, str | None]:
    """对 LLM 输出的 category/sub_category 做交叉校验，支持模糊匹配。

    1. 精确匹配（现有逻辑）
    2. 模糊匹配：sub_category 互为子串，且 category 精确匹配
    3. 仍未匹配 → 返回 (None, None)
    """
    if not category or not sub_category:
        return None, None

    cat_stripped = category.strip()
    sub_stripped = sub_category.strip()

    # 1. 精确匹配
    if (cat_stripped, sub_stripped) in lookup:
        return cat_stripped, sub_stripped

    for lc, ls in lookup:
        if lc.strip() == cat_stripped and ls.strip() == sub_stripped:
            return lc, ls

    # 2. 模糊匹配：category 精确匹配 + sub_category 互为子串
    #    例如 LLM 输出 "防晒霜"，lookup 中有 "防晒" → 匹配成功
    for lc, ls in lookup:
        if lc.strip() == cat_stripped:
            if sub_stripped in ls or ls in sub_stripped:
                logger.info(
                    "品类模糊匹配成功",
                    llm_output=f"{cat_stripped}/{sub_stripped}",
                    lookup_value=f"{lc}/{ls}",
                )
                return lc, ls

    logger.warning("品类交叉校验失败", category=category, sub_category=sub_category)
    return None, None


# 修改测试代码和提示词代码中的错误的(category,sub_category)对
当前项目中的提示词代码和测试代码包含了大量的错误(category,sub_category)对，如test_scenario_gen。py中的"美妆护肤|洗面奶"等，这些(category,sub_category)对不存在于数据库中，影响了测试和LLM生成效果。