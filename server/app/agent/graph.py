"""
StateGraph 构建模块 — 将 6 个 Agent 节点组装为 LangGraph 工作流。

条件边路由：Intent Router → ChitChat / Extraction / Scenario Gen，
两条推荐路径在 retrieval 处汇合。
"""
from langgraph.graph import StateGraph, START, END
from app.agent.state import AgentState
from app.agent.nodes.router import router_node
from app.agent.nodes.extraction import extraction_node
from app.agent.nodes.scenario_gen import scenario_gen_node
from app.agent.nodes.retrieval import retrieval_node
from app.agent.nodes.option_gen import option_gen_node
from app.agent.nodes.chitchat import chitchat_node


def route_intent(state: AgentState) -> str:
    """条件边函数：根据 intent 和 is_scenario 路由。

    路由规则:
        intent == "chat"                    → "chitchat"
        intent == "recommend" && !scenario  → "extraction"
        intent == "recommend" && scenario   → "scenario_gen"
    """
    intent = state.get("intent", "recommend")
    is_scenario = state.get("is_scenario", False)

    if intent == "chat":
        return "chitchat"
    if is_scenario:
        return "scenario_gen"
    return "extraction"


def build_graph(llm, emb_service, async_session_factory, category_list_provider=None):
    """构建编译后的 StateGraph。

    参数:
        llm: LLMService 实例。
        emb_service: EmbeddingService 实例。
        async_session_factory: async_session 工厂函数。
        category_list_provider: 可选，提供品类列表的异步函数（用于 Scenario Gen）。

    返回值:
        编译后的 CompiledStateGraph。
    """
    graph = StateGraph(AgentState)

    # ---- 注册节点 ----

    async def _router(state: AgentState) -> dict:
        return await router_node(state, llm=llm)

    async def _chitchat(state: AgentState) -> dict:
        return await chitchat_node(state, llm=llm)

    async def _extraction(state: AgentState) -> dict:
        return await extraction_node(state, llm=llm)

    async def _scenario_gen(state: AgentState) -> dict:
        category_list = ""
        if category_list_provider:
            category_list = await category_list_provider()
        return await scenario_gen_node(state, llm=llm, category_list=category_list)

    async def _retrieval(state: AgentState) -> dict:
        return await retrieval_node(
            state,
            llm=llm,
            emb_service=emb_service,
            async_session_factory=async_session_factory,
        )

    async def _option_gen(state: AgentState) -> dict:
        return await option_gen_node(state, llm=llm)

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
