"""集成测试：用真实 LLM 验证自然语言价格调整效果（SPEC.md 示例）。

用法: cd server && python -m pytest tests/test_price_adjust_integration.py -v -s

需要网络连接和 LLM API 可用。
"""
import pytest
from app.config import settings
from app.services.llm_service import LLMService
from app.agent.nodes.intent_extract_agent import _extract_intents_per_category
from app.agent.prompts.intent_extract_prompt import INTENT_EXTRACT_STEP3_SYSTEM


@pytest.mark.integration
@pytest.mark.asyncio
async def test_spec_example_price_down_with_real_llm():
    """SPEC.md 示例: 第一轮"300元以下防晒霜" → 第二轮"更平价的产品"。

    期望: max_price 从 300 下调（如降至 200-280 范围）。
    """
    llm = LLMService(
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
        temperature=0.1,
    )

    # 模拟 Step 2 产出的 context（含历史 + 当前查询）
    context = """## 品类 1: 美妆护肤/防晒
历史查询（按时间顺序）：
  #1 [2026-06-04T10:00:00] 推荐300元以下的防晒霜
当前查询: 请推荐更平价的产品"""

    result = await _extract_intents_per_category(
        context=context,
        llm=llm,
        brand_reference="(无)",
        category_list="美妆护肤/防晒",
        valid_categories={("美妆护肤", "防晒")},
    )

    assert len(result) >= 1, f"应至少返回一个品类，实际: {result}"
    req = result[0]
    print(f"\n提取结果: min_price={req['min_price']}, max_price={req['max_price']}")

    max_p = req["max_price"]
    assert max_p < 300, (
        f"期望 max_price 从 300 下调，实际 {max_p}。"
        f"自然语言价格调整未生效，需迭代 prompt。"
    )
    assert max_p >= 1, f"max_price 不应跌破底线，实际 {max_p}"

    print(f"PASS: max_price 从 300 下调至 {max_p} (降幅 {(300-max_p)/300*100:.0f}%)")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_spec_example_price_down_mild():
    """轻微降价: '稍微便宜一点就行'。"""
    llm = LLMService(
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
        temperature=0.1,
    )

    context = """## 品类 1: 美妆护肤/防晒
历史查询（按时间顺序）：
  #1 [2026-06-04T10:00:00] 推荐300元以下的防晒霜
当前查询: 稍微便宜一点就行"""

    result = await _extract_intents_per_category(
        context=context,
        llm=llm,
        brand_reference="(无)",
        category_list="美妆护肤/防晒",
        valid_categories={("美妆护肤", "防晒")},
    )

    assert len(result) >= 1
    req = result[0]
    print(f"\n轻微降价: min_price={req['min_price']}, max_price={req['max_price']}")

    max_p = req["max_price"]
    assert max_p < 300, f"期望下调，实际 {max_p}"
    # 轻微调整应在 5%-10% 范围 → 270-285
    assert max_p >= 270, f"轻微调整不应降太多，实际 {max_p}"
    print(f"PASS: max_price 从 300 轻微下调至 {max_p}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_spec_example_price_down_strong():
    """强烈降价: '越便宜越好，预算很紧'。"""
    llm = LLMService(
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
        temperature=0.1,
    )

    context = """## 品类 1: 美妆护肤/防晒
历史查询（按时间顺序）：
  #1 [2026-06-04T10:00:00] 推荐300元以下的防晒霜
当前查询: 越便宜越好，预算很紧"""

    result = await _extract_intents_per_category(
        context=context,
        llm=llm,
        brand_reference="(无)",
        category_list="美妆护肤/防晒",
        valid_categories={("美妆护肤", "防晒")},
    )

    assert len(result) >= 1
    req = result[0]
    print(f"\n强烈降价: min_price={req['min_price']}, max_price={req['max_price']}")

    max_p = req["max_price"]
    assert max_p < 300, f"期望下调，实际 {max_p}"
    # 强烈调整应在 25%-50% 范围 → 150-225
    assert max_p <= 225, f"强烈降价应降幅较大，实际 {max_p}"
    print(f"PASS: max_price 从 300 强烈下调至 {max_p}")
