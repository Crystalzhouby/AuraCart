"""
StateGraph 构建模块 — 将 6 个 Agent 节点组装为 LangGraph 工作流。

条件边路由：Intent Router → ChitChat / Extraction / Scenario Gen，
两条推荐路径在 retrieval 处汇合。
"""
import json
import structlog
from langgraph.graph import StateGraph, START, END
from app.agent.state import AgentState
from app.agent.nodes.router import router_node
from app.agent.nodes.extraction import extraction_node
from app.agent.nodes.scenario_gen import scenario_gen_node
from app.agent.nodes.retriever import retrieval_node
from app.agent.nodes.option_gen import option_gen_node
from app.agent.nodes.chitchat import chitchat_node

logger = structlog.get_logger("agent.graph")

# 不记录到日志的字段（不可序列化或冗余）
_SKIP_LOG_FIELDS = {"_sse_queue"}


def _preview(state_or_result: dict, max_field_len: int = 500) -> str:
    """生成 state/result 的 DEBUG 日志预览。

    对结构化字段（列表、字典）使用 json.dumps 输出完整内容，
    排除 _sse_queue 等不可序列化字段。超长字段截断并标记。
    """
    parts = []
    for key, val in state_or_result.items():
        if key in _SKIP_LOG_FIELDS:
            continue
        if isinstance(val, (list, dict)):
            text = json.dumps(val, ensure_ascii=False)
        elif isinstance(val, str):
            text = val
        else:
            text = repr(val)

        if len(text) > max_field_len:
            text = text[:max_field_len] + "...<truncated>"
        parts.append(f"{key}={text}")
    return " | ".join(parts) if parts else "(empty)"


def route_intent(state: AgentState) -> str:
    """条件边函数：根据 intent 路由。

    路由规则:
        intent == "chat"      → "chitchat"
        intent == "explicit"  → "extraction"
        intent == "scenario"  → "scenario_gen"
    """
    intent = state.get("intent", "explicit")

    if intent == "chat":
        target = "chitchat"
    elif intent == "scenario":
        target = "scenario_gen"
    else:
        target = "extraction"

    logger.debug("route_intent 路由决策", intent=intent, target=target)
    return target


def build_graph(llm, emb_service, async_session_factory, reranker_service=None):
    """构建编译后的 StateGraph。

    参数:
        llm: LLMService 实例。
        emb_service: EmbeddingService 实例。
        async_session_factory: async_session 工厂函数。
        reranker_service: 可选，RerankerService 实例（用于精排）。

    返回值:
        编译后的 CompiledStateGraph。
    """
    graph = StateGraph(AgentState)

    # ---- 注册节点 ----

    async def _router(state: AgentState) -> dict:
        logger.debug("router 输入", state=_preview(state))
        result = await router_node(state, llm=llm)
        logger.debug("router 输出", result=_preview(result))
        return result

    async def _chitchat(state: AgentState) -> dict:
        logger.debug("chitchat 输入", state=_preview(state))
        result = await chitchat_node(state, llm=llm)
        logger.debug("chitchat 输出", result=_preview(result))
        return result

    async def _extraction(state: AgentState) -> dict:
        logger.debug("extraction 输入", state=_preview(state))
        result = await extraction_node(
            state, llm=llm,
            db_session_factory=async_session_factory,
        )
        logger.debug("extraction 输出", result=_preview(result))
        return result

    async def _scenario_gen(state: AgentState) -> dict:
        logger.debug("scenario_gen 输入", state=_preview(state))
        result = await scenario_gen_node(
            state, llm=llm,
            db_session_factory=async_session_factory,
        )
        logger.debug("scenario_gen 输出", result=_preview(result))
        return result

    async def _retrieval(state: AgentState) -> dict:
        logger.debug("retrieval 输入", state=_preview(state))
        result = await retrieval_node(
            state,
            llm=llm,
            emb_service=emb_service,
            async_session_factory=async_session_factory,
            reranker=reranker_service,
        )
        logger.debug("retrieval 输出", result=_preview(result))
        return result

    async def _option_gen(state: AgentState) -> dict:
        logger.debug("option_gen 输入", state=_preview(state))
        result = await option_gen_node(state, llm=llm)
        logger.debug("option_gen 输出", result=_preview(result))
        return result

    graph.add_node("router", _router)
    graph.add_node("chitchat", _chitchat)
    graph.add_node("extraction", _extraction)
    graph.add_node("scenario_gen", _scenario_gen)
    graph.add_node("retrieval", _retrieval)
    graph.add_node("option_gen", _option_gen)

    # ---- 边 ----
    graph.add_edge(START, "router")

    graph.add_conditional_edges(
        "router",
        route_intent,
        {
            "chitchat": "chitchat",
            "extraction": "extraction",
            "scenario_gen": "scenario_gen",
        },
    )

    graph.add_edge("chitchat", END)
    graph.add_edge("extraction", "retrieval")
    graph.add_edge("scenario_gen", "retrieval")
    graph.add_edge("retrieval", "option_gen")
    graph.add_edge("option_gen", END)

    return graph.compile()
