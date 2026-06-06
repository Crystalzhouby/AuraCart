"""
router_node 的 LangSmith 监控集成 — 演示 / 测试文件
====================================================

本文件演示如何为 Intent Router 节点接入 LangSmith 可观测性平台，
包含 4 种集成方案，从最轻量到最深度，覆盖不同场景。

**重要**：本文件不会修改任何现有工程代码，仅作示范用途。

依赖安装::

    pip install langsmith

环境变量::

    set LANGCHAIN_TRACING_V2=true
    set LANGCHAIN_API_KEY=ls__your_api_key
    set LANGCHAIN_PROJECT=auracart

方案概览
--------
1. **装饰器方案** — 用 ``@traceable`` 包裹整个节点函数，最低侵入。
2. **手动上下文管理器** — 用 ``trace()`` 精确控制 span 边界与子 span。
3. **OpenAI 客户端包装** — 用 ``wrap_openai`` 自动记录每次 LLM 调用。
4. **LangGraph 原生集成** — 利用 LangGraph 的 ``Callbacks`` 全链路追踪。

推荐路径: 方案 1 + 方案 3 组合 → 覆盖节点级 + LLM 调用级两个维度。
"""

from __future__ import annotations

import json
import os
import re
import structlog
from typing import Any

# ============================================================================
# LangSmith 环境配置
# ============================================================================

# 方式 A：直接设置环境变量（通常放在入口文件或 .env 中）
os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGCHAIN_API_KEY", "ls__your_api_key_here")  # ← 替换为真实 key
os.environ.setdefault("LANGCHAIN_PROJECT", "auracart-router-test")
# 可选：自定义端点（自建 LangSmith Hub 时使用）
# os.environ.setdefault("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")


# ============================================================================
# 原版 router 代码（直接复制，不 import 原模块，保持完全隔离）
# ============================================================================

logger = structlog.get_logger("agent.router_smith")

ROUTER_SYSTEM = """你是一个电商导购意图分类器。将用户查询分为以下三类之一：

## 意图分类
- **chat**：与商品导购完全无关的闲聊。
  例："今天天气怎么样"、"你好"、"讲个笑话"
- **explicit**：用户明确提出了具体的商品需求，可直接用品类关键词匹配。
  例："蓝牙耳机"、"200元以下的跑鞋"、"保湿面霜推荐"
- **scenario**：用户描述使用场景而非具体商品，无法直接用品类关键词概括，需先分析场景再拆解品类。
  例："去三亚旅游"、"怕晒黑怎么办"、"换季护肤需要买什么"

## 分类原则
- 多轮对话中历史已确立推荐意图的追问，归入 explicit 或 scenario。
- 无法确定时优先归入 explicit（宁可多做推荐也不错失导购机会）。

## 输出格式
只返回 JSON，不返回其他内容：
{"intent": "chat"}
{"intent": "explicit"}
{"intent": "scenario"}

## 用户提问
{user_query}"""


def _parse_router_response(raw: str) -> dict[str, Any]:
    """从 LLM 原始响应中提取 JSON，失败返回 fallback 默认值。

    增强容错：
    - markdown 代码围栏 (```json ... ```)
    - 尾随逗号（常见 LLM 错误）
    - JSON 前后的说明文字
    """
    if not raw:
        return {"intent": "explicit"}

    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start < 0 or end <= start:
        return {"intent": "explicit"}

    json_str = raw[start:end]

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    cleaned = re.sub(r",\s*([}\]])", r"\1", json_str)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    return {"intent": "explicit"}


# ============================================================================
# 方案 1：@traceable 装饰器（推荐首选）
# ============================================================================
#
# 优点：
# - 侵入最小，一行装饰器即可
# - 自动记录输入 / 输出 / 耗时 / 异常
# - 嵌套调用自动建立父子关系
#
# 适用：
# - 所有节点函数（router / extraction / scenario_gen / retrieval / option_gen / chitchat）
# - 任何希望追踪的异步或同步函数

from langsmith import traceable


@traceable(
    # run_type 决定 LangSmith UI 中如何渲染该 span
    run_type="chain",
    # name 显示在 trace 树中
    name="Intent Router",
    # metadata 附加到 span，可用于过滤 / 搜索
    metadata={
        "node": "router",
        "graph": "AuraCart",
        "version": "1.0",
        "role": "intent-classifier",
    },
    # tags 用于快速分组 / 筛选
    tags=["production", "intent", "v1"],
    # project_name 可覆盖环境变量中的 LANGCHAIN_PROJECT
    # project_name="auracart-router-test",
)
async def router_node_v1(state: dict, llm: Any = None) -> dict:
    """方案 1：使用 @traceable 装饰器的最小侵入版本。

    LangSmith 自动捕获：
    - 输入 state（自动序列化为 JSON）
    - 输出 {"intent": str}（chat / explicit / scenario）
    - 执行耗时（毫秒）
    - 异常（含 traceback）
    - 嵌套的 @traceable 子调用
    """
    user_query = state.get("user_query", "")

    prompt = ROUTER_SYSTEM.replace("{user_query}", user_query)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        if llm is not None:
            raw_response = await llm.chat(messages, temperature=0.1)
            parsed = _parse_router_response(raw_response)
        else:
            parsed = {"intent": "explicit"}
    except Exception:
        logger.warning("Router LLM 调用失败，使用 fallback", exc_info=True)
        parsed = {"intent": "explicit"}

    return {"intent": parsed.get("intent", "explicit")}


# ============================================================================
# 方案 2：手动 trace() 上下文管理器（精细控制）
# ============================================================================
#
# 优点：
# - 可在 span 内创建子 span
# - 灵活添加自定义 metadata / feedback
# - 手动控制 span 边界（例如：只追踪 LLM 调用，不追踪预处理）
#
# 适用：
# - 复杂节点需要多级 span 的场景
# - 需要在运行时动态设置 tags / metadata

from langsmith import trace
from langsmith.run_helpers import get_current_run_tree  # 获取当前 run context
import uuid


async def router_node_v2(state: dict, llm: Any = None) -> dict:
    """方案 2：使用 trace() 上下文管理器的手动控制版本。

    手动划分 3 个子 span：
    1. router.prompt_build  — 构建提示词
    2. router.llm_call      — LLM API 调用
    3. router.parse         — 解析响应
    """
    user_query = state.get("user_query", "")

    # 外层 trace 包裹整个 router 调用
    with trace(
        name="Intent Router (manual)",
        run_type="chain",
        inputs={"user_query": user_query},
        metadata={"approach": "trace-manager"},
        tags=["manual-span"],
    ) as root_span:
        # ---- 子 span 1: 构建提示词 ----
        with trace(
            name="Build Prompt",
            run_type="chain",
            inputs={"user_query": user_query},
        ):
            prompt = ROUTER_SYSTEM.replace("{user_query}", user_query)
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_query},
            ]

        # ---- 子 span 2: LLM 调用 ----
        raw_response = ""
        with trace(
            name="LLM Call",
            run_type="llm",
            inputs={"messages": messages, "temperature": 0.1},
        ) as llm_span:
            try:
                if llm is not None:
                    raw_response = await llm.chat(messages, temperature=0.1)
                llm_span.end(outputs={"raw_response": raw_response})
            except Exception as e:
                llm_span.end(error=e)
                raw_response = ""

        # ---- 子 span 3: 解析响应 ----
        with trace(
            name="Parse Response",
            run_type="chain",
            inputs={"raw_response": raw_response},
        ) as parse_span:
            try:
                parsed = _parse_router_response(raw_response)
                parse_span.end(outputs=parsed)
            except Exception as e:
                parsed = {"intent": "explicit"}
                parse_span.end(error=e, outputs=parsed)

        output = {
            "intent": parsed.get("intent", "explicit"),
        }

        # 可选：通过 root_span 添加自定义 metadata（在 UI 中可搜索/过滤）
        root_span.add_metadata({
            "intent": output["intent"],
            "user_query_length": len(user_query),
            # 用 metadata 标记 fallback 情况，方便后期筛选分析
            "fallback": int(output["intent"] == "explicit" and not raw_response),
        })

        # 可选：手动附加 feedback（例如正确率标注、用户满意度等）
        # 这在测试 / 标注阶段很有用
        # root_span.add_feedback(key="human_label", score=1.0, comment="分类正确")

    return output


# ============================================================================
# 方案 3：OpenAI 客户端包装（自动记录 LLM 调用）
# ============================================================================
#
# 优点：
# - 自动记录 token 用量、模型名称、请求参数
# - 无需在业务逻辑中加任何代码
# - OpenAI 流式调用也支持
#
# 适用：
# - 任何使用 openai >= 1.0.0 SDK 的场景
# - 需要精确追踪 token 消耗和模型调用

from langsmith.wrappers import wrap_openai


def wrap_llm_service_for_smith(llm_service: Any) -> Any:
    """用 LangSmith wrap_openai 包装 LLMService 的底层 AsyncOpenAI 客户端。

    调用此函数后，所有通过 LLMService.chat() / chat_stream() 发起的
    OpenAI 调用都会自动在 LangSmith 中产生 LLM 类型的 run。

    用法::

        llm = LLMService(...)
        llm = wrap_llm_service_for_smith(llm)  # ← 包装后正常使用即可

    注意：wrap_openai 直接修改客户端对象，不需要额外改造 LLMService。
    """
    client = getattr(llm_service, "_client", None)
    if client is not None:
        llm_service._client = wrap_openai(client)
        logger.info("langsmith.wrap_openai applied", model=llm_service.model)
    else:
        logger.warning("LLMService 没有 _client 属性，wrap_openai 跳过")
    return llm_service


async def router_node_v3(state: dict, llm: Any = None) -> dict:
    """方案 3：与方案 1 完全相同的逻辑，但 LLM 调用自动被 LangSmith 记录。

    前提：llm 已通过 wrap_llm_service_for_smith() 包装。
    效果：LangSmith trace 树将同时包含：
     - Intent Router (chain)    ← @traceable 记录
       └── ChatOpenAI (llm)    ← wrap_openai 自动记录

    这就是推荐的生产方案：装饰器 + OpenAI 包装的组合。
    """
    user_query = state.get("user_query", "")

    prompt = ROUTER_SYSTEM.replace("{user_query}", user_query)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_query},
    ]

    try:
        if llm is not None:
            raw_response = await llm.chat(messages, temperature=0.1)
            parsed = _parse_router_response(raw_response)
        else:
            parsed = {"intent": "explicit"}
    except Exception:
        logger.warning("Router LLM 调用失败，使用 fallback", exc_info=True)
        parsed = {"intent": "explicit"}

    return {"intent": parsed.get("intent", "explicit")}


# 给方案 3 也加上 @traceable，形成完整链路
router_node_v3 = traceable(
    run_type="chain",
    name="Intent Router (wrapped LLM)",
    metadata={"node": "router", "has_openai_tracing": True},
    tags=["production", "intent", "v3"],
)(router_node_v3)


# ============================================================================
# 方案 4：LangGraph 原生 Callback 集成
# ============================================================================
#
# LangSmith 与 LangGraph 深度集成，通过在 graph.compile() 或
# graph.ainvoke() 时传入 callbacks，即可自动追踪所有节点。
#
# 优点：
# - 零节点代码侵入
# - 自动捕获 state 在各节点间的流转
# - 条件边路由决策也可追踪
#
# 适用：
# - 已使用 LangGraph StateGraph 的项目
# - 需要全链路追踪（包括框架层事件）

def demo_graph_integration():
    """方案 4 演示：如何在 graph 层面集成 LangSmith。

    这是 graph.py 中 build_graph() → graph.compile() → graph.ainvoke()
    的调用链中应该插入的代码片段。

    用法示例::

        from app.agent.graph import build_graph

        graph = build_graph(llm, emb_service, session_factory, cat_provider)
        compiled = graph.compile()

        # 方式 A：在 ainvoke 时传入 LangSmith callbacks
        result = await compiled.ainvoke(
            {"user_query": "推荐一款蓝牙耳机"},
            config={"callbacks": [LangSmithTracer(
                project_name="auracart-router-test",
                tags=["graph-level"],
            )]},
        )

        # 方式 B：通过 tracing_enabled() 上下文激活
        from langsmith import tracing_context
        with tracing_context(enabled=True, project_name="auracart"):
            result = await compiled.ainvoke({"user_query": "...")

    注意：LangSmithTracer 会自动捕捉每个节点的：
        - 输入 state
        - 输出 update
        - 执行时长
        - 异常信息
        - 条件边路由决策
    """
    return (
        "在 graph 的 ainvoke 调用时，"
        "通过 config={'callbacks': [LangSmithTracer(...)]} 传入即可。"
        "详见本函数 docstring 中的代码示例。"
    )


# ============================================================================
# 辅助工具：批量标注 / 反馈收集
# ============================================================================

from langsmith import Client as LangSmithClient


def get_smith_client() -> LangSmithClient:
    """获取 LangSmith 客户端实例（用于查询/标注/反馈管理）。"""
    return LangSmithClient(
        api_key=os.environ.get("LANGCHAIN_API_KEY"),
        # api_url 默认 https://api.smith.langchain.com
    )


async def send_feedback_to_smith(
    run_id: str,
    score: float,
    key: str = "correctness",
    comment: str = "",
) -> None:
    """向 LangSmith 发送人工反馈（适用于标注/评估流程）。

    参数:
        run_id: LangSmith run UUID，可从 trace UI 或代码中获取。
        score: 评分 (通常 0.0 ~ 1.0，也可自定义)。
        key: 反馈维度名称，如 "correctness", "latency_satisfaction"。
        comment: 可选备注。

    用法::

        # 在 router 返回结果后，让用户/评测者标注
        result = await router_node_v1(state, llm)
        run_id = result.get("_langsmith_run_id")  # 由 @traceable 自动注入
        await send_feedback_to_smith(run_id, score=1.0, key="intent_correct")
    """
    client = get_smith_client()
    client.create_feedback(
        run_id=run_id,
        key=key,
        score=score,
        comment=comment,
    )
    logger.info("langsmith feedback sent", run_id=run_id, key=key, score=score)


# ============================================================================
# 数据集创建：用于 LangSmith 在线评估
# ============================================================================

_ROUTER_TEST_EXAMPLES = [
    # (user_query, expected_intent)
    ("推荐一款蓝牙耳机", "explicit"),
    ("你好", "chat"),
    ("去三亚旅游需要准备什么", "scenario"),
    ("200元以下的跑鞋", "explicit"),
    ("今天天气怎么样", "chat"),
    ("怕晒黑怎么办", "scenario"),
    ("之前推荐的耳机还有别的颜色吗", "explicit"),
]


def create_router_dataset():
    """在 LangSmith 中创建 router 评估数据集（仅首次运行）。

    创建后可在 LangSmith UI 的 "Datasets & Testing" 中使用该数据集
    进行回归测试、prompt 版本对比等。
    """
    client = get_smith_client()
    dataset_name = "router-intent-classification"

    # 检查是否已存在
    existing = list(client.list_datasets(dataset_name=dataset_name))
    if existing:
        logger.info("dataset already exists", name=dataset_name, id=existing[0].id)
        return existing[0]

    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description="Intent Router 意图分类测试集 — 用于回归测试和 prompt 对比",
    )

    inputs = []
    outputs = []
    for query, intent in _ROUTER_TEST_EXAMPLES:
        inputs.append({"user_query": query})
        outputs.append({"intent": intent})

    client.create_examples(
        dataset_id=dataset.id,
        inputs=inputs,
        outputs=outputs,
    )

    logger.info("dataset created", name=dataset_name, examples=len(inputs))
    return dataset


# ============================================================================
# 与现有 graph.py 的集成适配器
# ============================================================================

def build_smith_router_wrapper(original_router_func=None):
    """生成一个带 LangSmith 追踪的 router wrapper，可直接替换 graph.py 中的 _router。

    用法 — 在 graph.py 的 build_graph() 中::

        from app.agent.nodes.router_smith_test import build_smith_router_wrapper

        # 替换原来的 _router 定义：
        _router = build_smith_router_wrapper()

        # 其余代码不变：
        graph.add_node("router", _router)
        ...

    参数:
        original_router_func: 原始 router_node 函数（可选）。不传则使用内置的 v1 版本。

    返回值:
        async callable: 与 graph.py 中 _router 签名兼容的包装函数。
    """
    inner = original_router_func or router_node_v1

    @traceable(
        run_type="chain",
        name="Intent Router (graph adapter)",
        metadata={
            "node": "router",
            "integration": "langsmith-graph-adapter",
        },
        tags=["graph", "auracart", "router"],
    )
    async def _wrapped(state: dict) -> dict:
        # graph.py 的 wrapper 已注入了 llm，此处通过闭包获取
        # 如果需要在 graph.py 层面注入，参考下面的 build_graph_with_smith 示例
        return await inner(state)

    return _wrapped


def build_graph_with_smith_example():
    """演示如何在 graph.py 中完整集成 LangSmith。

    这是对 graph.py 中 build_graph() 的修改指南 —— 不修改原文件，
    仅展示需要在哪些位置做哪些改动。

    关键改动点:

    1. **在 build_graph() 开头初始化 LangSmith Client**（用于反馈/查询）
    2. **用 @traceable 包装每个节点的内部函数**
    3. **在 ainvoke 时传入 LangSmithTracer callback**
    4. **可选：用 wrap_openai 包装 LLMService**

    详细代码见本函数 docstring。
    """
    return (
        "# === graph.py 集成 LangSmith 的改动指南 ===\n"
        "#\n"
        "# 1. build_graph() 开头添加:\n"
        "#    from app.agent.nodes.router_smith_test import wrap_llm_service_for_smith\n"
        "#    llm = wrap_llm_service_for_smith(llm)\n"
        "#\n"
        "# 2. 每个节点 closure 添加 @traceable（参考 router_smith_test.py 方案1）\n"
        "#\n"
        "# 3. build_graph() 返回编译后的 graph，外部调用时传入 config:\n"
        "#    from langsmith import LangSmithTracer\n"
        "#    config = {'callbacks': [LangSmithTracer(project_name='auracart')]}\n"
        "#    result = await compiled.ainvoke(initial_state, config=config)\n"
        "#\n"
        "# 本函数完整演示了上述流程。"
    )


# ============================================================================
# 测试入口
# ============================================================================

async def _mock_llm_chat(messages: list[dict], temperature: float | None = None) -> str:
    """模拟 LLMService.chat() 的 mock 实现，用于无网络测试。"""
    content = messages[-1].get("content", "") if messages else ""
    if "推荐" in content and ("蓝牙" in content or "跑鞋" in content):
        return '{"intent": "explicit"}'
    if "三亚" in content or "怕晒黑" in content or "换季" in content:
        return '{"intent": "scenario"}'
    if "你好" in content or "天气" in content or "笑话" in content:
        return '{"intent": "chat"}'
    return '{"intent": "explicit"}'


class MockLLM:
    """模拟 LLMService，仅实现 chat() 方法，用于本地测试。"""
    def __init__(self, model: str = "mock-model"):
        self.model = model
        self.temperature = 0.3

    async def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        return await _mock_llm_chat(messages, temperature)


async def test_all_approaches():
    """运行所有 4 种集成方案的冒烟测试。

    不依赖外部 LLM API，使用 MockLLM 模拟。
    需要 LANGCHAIN_API_KEY 环境变量才能实际发送 trace 到 LangSmith。
    """
    llm = MockLLM()

    test_cases = [
        ({"user_query": "推荐一款蓝牙耳机"}, {"intent": "explicit"}),
        ({"user_query": "你好"}, {"intent": "chat"}),
        ({"user_query": "去三亚旅游需要准备什么"}, {"intent": "scenario"}),
    ]

    print("=" * 60)
    print("LangSmith Router 监控集成 — 冒烟测试")
    print("=" * 60)

    # --- 方案 1 ---
    print("\n[方案 1] @traceable 装饰器")
    for state, expected in test_cases:
        result = await router_node_v1(state, llm=llm)
        status = "PASS" if result == expected else f"FAIL (got {result})"
        print(f"  {status}  query={state['user_query']}")

    # --- 方案 2 ---
    print("\n[方案 2] 手动 trace() 上下文管理器")
    for state, expected in test_cases:
        result = await router_node_v2(state, llm=llm)
        status = "PASS" if result == expected else f"FAIL (got {result})"
        print(f"  {status}  query={state['user_query']}")

    # --- 方案 3 ---
    print("\n[方案 3] @traceable + wrap_openai")
    wrapped_llm = wrap_llm_service_for_smith(llm)
    for state, expected in test_cases:
        result = await router_node_v3(state, llm=wrapped_llm)
        status = "PASS" if result == expected else f"FAIL (got {result})"
        print(f"  {status}  query={state['user_query']}")

    # --- 方案 4 ---
    print("\n[方案 4] LangGraph Callback（仅打印说明）")
    print("  " + demo_graph_integration())

    print("\n" + "=" * 60)
    print("测试完成。若 LANGCHAIN_API_KEY 已配置，trace 将出现在：")
    print("  https://smith.langchain.com")
    print("=" * 60)


# ============================================================================
# 环境检查工具
# ============================================================================

def check_langsmith_setup() -> dict:
    """检查 LangSmith 配置是否就绪。

    返回值:
        dict: 各项配置的检查结果，可直接打印或用于 CI 检查。
    """
    checks = {
        "langsmith_installed": False,
        "tracing_enabled": False,
        "api_key_set": False,
        "project_set": False,
    }
    try:
        import langsmith
        checks["langsmith_installed"] = True
    except ImportError:
        checks["langsmith_installed"] = False
        return checks

    checks["tracing_enabled"] = os.environ.get("LANGCHAIN_TRACING_V2", "").lower() in ("true", "1")
    checks["api_key_set"] = bool(os.environ.get("LANGCHAIN_API_KEY", "").startswith("ls__"))
    checks["project_set"] = bool(os.environ.get("LANGCHAIN_PROJECT", ""))

    return checks


# ============================================================================
# CLI 入口
# ============================================================================

if __name__ == "__main__":
    import asyncio

    # 先做环境检查
    setup = check_langsmith_setup()
    print("LangSmith 环境检查:")
    for key, ok in setup.items():
        print(f"  {'[OK]' if ok else '[MISSING]'} {key}")

    if not setup["langsmith_installed"]:
        print("\n请先安装 langsmith: pip install langsmith")
        exit(1)

    if not setup["api_key_set"]:
        print("\n[WARN] LANGCHAIN_API_KEY 未设置，trace 不会发送到 LangSmith 服务器。")
        print("  设置方式: set LANGCHAIN_API_KEY=ls__your_key")
        print("  获取 key: https://smith.langchain.com/settings")
        print("\n本次测试仍会运行（本地无网络模式）。\n")

    asyncio.run(test_all_approaches())
