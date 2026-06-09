"""
搜索 API 路由

模块: app.api.search

提供 RAG 检索接口 /api/search — SSE 流式 Agent 工作流：
查询解析 → 多策略检索 → RRF 融合 → 商品推荐
"""
import json
import asyncio
import structlog
import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse
from app.database import get_db, engine
from app.config import settings
from app.services.embedding_service import EmbeddingService
from app.services.llm_service import LLMService
from sqlalchemy.ext.asyncio import async_sessionmaker

router = APIRouter(prefix="/api", tags=["search"])


# ---------------------------------------------------------------------------
# 依赖注入工厂函数
# ---------------------------------------------------------------------------

def get_embedding_service() -> EmbeddingService:
    """
    EmbeddingService 的依赖工厂函数。

    根据应用配置创建一个新实例，包括嵌入模型的 base_url、api_key、model 名称
    和 batch_size。

    返回值:
        EmbeddingService: 可直接使用的嵌入服务实例。
    """
    return EmbeddingService(
        base_url=settings.embedding.base_url,
        api_key=settings.embedding.api_key,
        model=settings.embedding.model,
        batch_size=settings.embedding.batch_size,
    )


def get_llm_service() -> LLMService:
    """
    LLMService 的依赖工厂函数。

    根据应用配置创建一个新实例，包括 LLM 的 base_url、api_key、model 名称
    和 temperature。

    返回值:
        LLMService: 可直接使用的 LLM 服务实例。
    """
    return LLMService(
        base_url=settings.llm.base_url,
        api_key=settings.llm.api_key,
        model=settings.llm.model,
        temperature=settings.llm.temperature,
    )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.get("/search/{conversation_id}")
async def search(
    request: Request,
    conversation_id: str,
    q: str = Query(..., min_length=1, description="搜索查询字符串"),
    stream: bool = Query(True, description="是否开启 SSE 流式回答，默认 True"),
    db: AsyncSession = Depends(get_db),
    emb: EmbeddingService = Depends(get_embedding_service),
    llm: LLMService = Depends(get_llm_service),
):
    """
    基于 Agent 工作流的 AI 推理搜索，通过 SSE 流式返回结果。

    Agent 工作流各阶段：
      1. Router — 意图识别（chat/explicit/scenario）
      2. Extraction / ScenarioGen — 需求提取
      3. Retrieval — 多策略检索 + RRF 融合
      4. OptionGen — 生成后续选项

    接口: GET /api/search/{conversation_id}?q=...&stream=true

    参数:
        request (Request):       FastAPI Request 对象，用于连接管理。
        conversation_id (str):    会话ID（路径参数，必填），用于多轮对话记忆。
        q (str):                 用户提供的搜索查询字符串。
        stream (bool):           是否以 SSE 流式返回；保留参数向后兼容，始终走 Agent 工作流。
        db (AsyncSession):       通过依赖注入获取的异步 SQLAlchemy 会话。
        emb (EmbeddingService):  通过依赖注入获取的嵌入服务。
        llm (LLMService):        通过依赖注入获取的 LLM 服务。

    返回值:
        EventSourceResponse（SSE 事件流）。
    """

    # ---- 流式模式 (SSE) — Agent 工作流 ----
    async def event_stream():
        """Agent 工作流 SSE 事件生成器。"""
        try:
            # 构建 Agent Graph
            from app.agent.graph import build_graph
            agent_graph = build_graph(
                llm=llm,
                emb_service=emb,
                async_session_factory=async_sessionmaker(bind=engine),
            )

            # SSE 事件队列
            queue: asyncio.Queue = asyncio.Queue()

            # Agent 事件消费循环
            async for event in _agent_event_stream(
                user_query=q,
                graph=agent_graph,
                queue=queue,
                total_timeout=settings.timeout.total_request,
                conversation_id=conversation_id,
                stream=stream,
            ):
                yield event

        except Exception as e:
            pipeline_log = structlog.get_logger("agent_stream")
            pipeline_log.error("Agent 管道异常", error=str(e))
            try:
                await db.rollback()
            except Exception:
                pass
            yield {"event": "error", "data": json.dumps({"message": str(e)})}
            yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())


# ---------------------------------------------------------------------------
# Agent 工作流 SSE 集成 (M10)
# ---------------------------------------------------------------------------


async def _agent_event_stream(
    user_query: str,
    graph,
    queue: asyncio.Queue,
    total_timeout: float = 60.0,
    conversation_id: str = "",
    stream: bool = True,
):
    """LangGraph Agent 工作流的 SSE 事件消费循环。

    启动 graph.ainvoke 作为后台任务，消费 Queue 中的 SSE 事件，
    在完成后发送 next_options。先从 DB 校验 conversation_id 并加载
    历史记忆注入初始状态，在图执行完成后写回。

    参数:
        user_query: 用户查询字符串。
        graph: 编译后的 LangGraph StateGraph。
        queue: 节点间传递 SSE 事件的 asyncio.Queue。
        total_timeout: 总体超时（秒），默认 60s。
        conversation_id: 会话 ID，用于多轮对话记忆持久化。

    Yields:
        dict: SSE 事件 {"event": str, "data": str}。
    """
    from app.agent.state import AgentState

    stream_log = structlog.get_logger("agent_stream")

    # ---- 校验 conversation 存在性 ----
    try:
        from app.database import async_session
        from sqlalchemy import select
        from app.models.conversation import Conversation

        async with async_session() as session:
            result = await session.execute(
                select(Conversation.conversation_id).where(
                    Conversation.conversation_id == conversation_id
                )
            )
            if result.scalar_one_or_none() is None:
                yield {
                    "event": "error",
                    "data": json.dumps({"detail": "conversation not found"}),
                }
                yield {"event": "done", "data": "{}"}
                return
    except Exception as e:
        yield {
            "event": "error",
            "data": json.dumps({"detail": str(e)}),
        }
        yield {"event": "done", "data": "{}"}
        return

    # 构建初始状态
    initial_state: AgentState = {
        "user_query": user_query,
        "conversation_id": conversation_id,
        "welcome_text": "",
        "stream": stream,
        "intent": "explicit",
        "requirements": [],               # 新格式: list[dict]
        "scenario_description": None,
        "retrieval_results": [],
        "chat_reply": "",
        "next_options": [],
        "failed_categories": [],
    }
    initial_state["_sse_queue"] = queue  # type: ignore[index]

    # 后台启动 graph 执行
    graph_task = asyncio.create_task(graph.ainvoke(initial_state))
    overall_deadline = asyncio.get_event_loop().time() + total_timeout

    try:
        # ---- 从 queue 消费 SSE 事件，直到 graph 完成 ----
        while True:
            remaining = overall_deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                yield {"event": "error", "data": json.dumps({"message": "请求超时"})}
                yield {"event": "done", "data": "{}"}
                return

            try:
                event = await asyncio.wait_for(queue.get(), timeout=min(remaining, 5.0))
            except asyncio.TimeoutError:
                if graph_task.done():
                    if graph_task.exception():
                        exc = graph_task.exception()
                        yield {"event": "error", "data": json.dumps({"message": str(exc)})}
                        yield {"event": "done", "data": "{}"}
                        return
                    break  # graph 正常完成 → 退出循环处理终态
                continue  # graph 仍在运行 → 继续等待

            # chitchat 路径：收到 done → 立即结束
            if event["event"] == "done":
                data_str = json.dumps(event["data"], ensure_ascii=False)
                yield {"event": "done", "data": data_str}
                return

            # 常规事件：直接转发
            data_str = json.dumps(event["data"], ensure_ascii=False)
            yield {"event": event["event"], "data": data_str}

        # ---- graph 完成后：排空 queue 中的残留事件 ----
        while not queue.empty():
            try:
                event = queue.get_nowait()
                if event["event"] != "done":
                    data_str = json.dumps(event["data"], ensure_ascii=False)
                    yield {"event": event["event"], "data": data_str}
            except Exception:
                break

    except asyncio.CancelledError:
        if not graph_task.done():
            graph_task.cancel()
        yield {"event": "error", "data": json.dumps({"message": "客户端连接断开"})}
        yield {"event": "done", "data": "{}"}
        return

    finally:
        # 等待 graph 终态
        if not graph_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(graph_task), timeout=10.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                graph_task.cancel()

        # 读取最终 state
        final_state = None
        if graph_task.done() and not graph_task.cancelled():
            try:
                final_state = graph_task.result()
            except Exception:
                pass

        # ---- 持久化聊天记录 ----
        if final_state:
            try:
                user_query = final_state.get("user_query", "")
                chat_reply = final_state.get("chat_reply", "")
                if user_query and chat_reply:
                    from app.database import async_session as _chat_async_session
                    from app.models.chat_history import ChatHistory
                    async with _chat_async_session() as chat_session:
                        chat_session.add(ChatHistory(
                            conversation_id=conversation_id,
                            role="user",
                            content=user_query,
                        ))
                        chat_session.add(ChatHistory(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=chat_reply,
                        ))
                        await chat_session.commit()
                    stream_log.debug(
                        "聊天记录已保存",
                        conversation_id=conversation_id,
                    )
            except Exception as e:
                stream_log.warning(
                    "保存聊天记录失败",
                    conversation_id=conversation_id,
                    error=str(e),
                )

        # ---- 发送 next_options（从 graph 最终状态读取） ----
        if final_state and final_state.get("next_options"):
            try:
                yield {
                    "event": "next_options",
                    "data": json.dumps(final_state["next_options"], ensure_ascii=False),
                }
            except Exception:
                pass

        # ---- 最后发送 done 事件 ----
        done_data = json.dumps({"conversation_id": conversation_id})
        yield {"event": "done", "data": done_data}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

