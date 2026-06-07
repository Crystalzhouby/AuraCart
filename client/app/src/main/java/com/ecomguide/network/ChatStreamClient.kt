package com.ecomguide.network

import com.ecomguide.model.ChatStreamEvent
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * SSE（Server-Sent Events）流式聊天客户端 — 后端 Agent 工作流 v2 协议
 *
 * 负责：
 *   1. 页面加载时调用 GET /api/conversation 创建会话，获取 conversation_id
 *   2. 用户发送消息时，向 GET /api/search/{conversation_id}?q=... 发起 SSE 流式请求
 *   3. 实时解析后端推送的 SSE 事件，通过回调分发给 ChatViewModel
 *
 * 后端 SSE 事件协议（Agent 工作流）：
 *   event: welcome     → data: "欢迎语文本"
 *   event: products    → data: {"product_id":"...", "sku_id":"...", "category":"...", "sub_category":"..."}
 *   event: chat_reply  → data: "推荐理由文本"
 *   event: done        → data: {"text":"结束语", "conversation_id":"..."}
 *   event: next_options→ data: ["选项1", "选项2", "选项3"]
 *   event: error       → data: {"message":"错误信息"} 或 {"detail":"..."}
 *
 * @param baseUrl       后端服务地址，模拟器默认 10.0.2.2:8000（= 宿主机 localhost）
 * @param okHttpClient  可注入自定义 OkHttpClient（便于测试）
 */
class ChatStreamClient(
    private val baseUrl: String = "http://10.0.2.2:8000",
    private val okHttpClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)      // SSE 长连接需要足够长的读取超时
        .writeTimeout(30, TimeUnit.SECONDS)
        .pingInterval(30, TimeUnit.SECONDS)       // 保持连接活跃
        .build()
) {

    /**
     * 创建新会话，返回 conversation_id。
     * 应在页面/Fragment 初始化时调用一次。
     */
    fun createConversation(
        onSuccess: (conversationId: String) -> Unit,
        onError: (String) -> Unit
    ) {
        val request = Request.Builder()
            .url("$baseUrl/api/conversation")
            .get()
            .build()

        okHttpClient.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                onError("网络请求失败: ${e.message}")
            }

            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (!response.isSuccessful) {
                        onError("创建会话失败 HTTP ${response.code}")
                        return
                    }
                    try {
                        val json = JSONObject(response.body?.string() ?: "{}")
                        val cid = json.optString("conversation_id", "")
                        if (cid.isNotBlank()) onSuccess(cid) else onError("响应中无 conversation_id")
                    } catch (e: Exception) {
                        onError("解析会话ID失败: ${e.message}")
                    }
                }
            }
        })
    }

    /**
     * 发起 Agent 工作流搜索请求（SSE 流式）。
     *
     * @param query             用户查询文本
     * @param conversationId   会话 ID（由 createConversation 获取）
     * @param onEvent           事件回调，在 OkHttp 子线程中调用
     * @return                  OkHttp Call 对象，可调用 cancel() 中断请求
     */
    fun search(
        query: String,
        conversationId: String,
        onEvent: (ChatStreamEvent) -> Unit
    ): Call {
        // GET /api/search/{conversation_id}?q=xxx&stream=true
        val url = baseUrl.toHttpUrl()
            .newBuilder()
            .addPathSegment("api")
            .addPathSegment("search")
            .addPathSegment(conversationId)
            .addQueryParameter("q", query)
            .addQueryParameter("stream", "true")
            .build()

        val request = Request.Builder()
            .url(url)
            .get()
            .build()

        val call = okHttpClient.newCall(request)
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                onEvent(ChatStreamEvent.Error("网络请求失败: ${e.message}"))
            }

            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (!response.isSuccessful) {
                        // 尝试读取错误体
                        val body = response.body?.string() ?: ""
                        val msg = try { JSONObject(body).optString("detail") } catch (_: Exception) { null }
                            ?: "HTTP ${response.code}"
                        onEvent(ChatStreamEvent.Error(msg))
                        return
                    }
                    parseSse(response, onEvent)
                }
            }
        })
        return call
    }

    /**
     * 逐行读取 SSE 响应流，按 SSE 规范解析事件块。
     */
    private fun parseSse(response: Response, onEvent: (ChatStreamEvent) -> Unit) {
        val source = response.body?.source() ?: return
        var eventName = ""
        val dataLines = mutableListOf<String>()

        while (!source.exhausted()) {
            val line = source.readUtf8Line() ?: break
            when {
                line.isBlank() -> {
                    dispatch(
                        eventName = eventName,
                        data = dataLines.joinToString("\n"),
                        onEvent = onEvent
                    )
                    eventName = ""
                    dataLines.clear()
                }
                line.startsWith("event:") -> eventName = line.removePrefix("event:").trim()
                line.startsWith("data:") -> dataLines.add(line.removePrefix("data:").trim())
            }
        }
    }

    /**
     * 根据事件名将数据分发为对应的 ChatStreamEvent 子类（v2 协议）。
     */
    private fun dispatch(
        eventName: String,
        data: String,
        onEvent: (ChatStreamEvent) -> Unit
    ) {
        if (eventName.isBlank() || data.isBlank()) return

        when (eventName) {
            "welcome" -> onEvent(ChatStreamEvent.Welcome(normalizeTextPayload(data)))

            "welcome_chat_stream" -> emitStreamTextEvent(
                channel = ChatStreamEvent.StreamText.Channel.WELCOME,
                data = data,
                onEvent = onEvent
            )

            "products" -> {
                // data 是单个商品 JSON 对象 {product_id, sku_id, category, sub_category}
                try {
                    val json = JSONObject(data)
                    onEvent(
                        ChatStreamEvent.ProductEvent(
                            productId = json.optString("product_id"),
                            skuId = json.optString("sku_id"),
                            category = json.optString("category"),
                            subCategory = json.optString("sub_category")
                        )
                    )
                } catch (_: Exception) {
                    // 忽略格式错误的 products 事件
                }
            }

            "chat_reply",
            "category_intro",
            "product_reason" -> {
                onEvent(ChatStreamEvent.ChatReply(normalizeTextPayload(data)))
            }

            "category_intro_stream" -> emitStreamTextEvent(
                channel = ChatStreamEvent.StreamText.Channel.CATEGORY_INTRO,
                data = data,
                onEvent = onEvent
            )

            "ending_stream" -> emitStreamTextEvent(
                channel = ChatStreamEvent.StreamText.Channel.ENDING,
                data = data,
                onEvent = onEvent
            )

            "ending" -> {
                val text = normalizeTextPayload(data)
                if (text.isNotBlank()) {
                    onEvent(
                        ChatStreamEvent.StreamText(
                            channel = ChatStreamEvent.StreamText.Channel.ENDING,
                            phase = ChatStreamEvent.StreamText.Phase.DELTA,
                            text = text
                        )
                    )
                }
            }

            "done" -> {
                try {
                    val json = JSONObject(data)
                    ChatStreamEvent.Done(
                        text = if (json.has("text")) json.optString("text") else null,
                        conversationId = if (json.has("conversation_id")) json.optString("conversation_id") else null
                    )
                } catch (_: Exception) {
                    ChatStreamEvent.Done(text = null, conversationId = null)
                }.let { onEvent(it) }
            }

            "next_options" -> {
                try {
                    val opts = mutableListOf<String>()
                    val trimmed = data.trim()
                    if (trimmed.startsWith("[")) {
                        val arr = org.json.JSONArray(trimmed)
                        for (i in 0 until arr.length()) {
                            opts.add(arr.optString(i))
                        }
                    } else {
                        val json = JSONObject(trimmed)
                        val arr = json.optJSONArray("options")
                        if (arr != null) {
                            for (i in 0 until arr.length()) {
                                opts.add(arr.optString(i))
                            }
                        }
                    }
                    onEvent(ChatStreamEvent.NextOptions(opts.filter { it.isNotBlank() }))
                } catch (_: Exception) {
                    // 忽略
                }
            }

            "error" -> {
                val msg = try {
                    val json = JSONObject(data)
                    json.optString("detail").ifBlank {
                        json.optString("message")
                    }
                } catch (_: Exception) {
                    data
                }
                onEvent(ChatStreamEvent.Error(msg.ifBlank { data }))
            }
            // 其他未知事件：忽略，保持向前兼容
        }
    }

    private fun emitStreamTextEvent(
        channel: ChatStreamEvent.StreamText.Channel,
        data: String,
        onEvent: (ChatStreamEvent) -> Unit
    ) {
        val payload = runCatching { JSONObject(data) }.getOrNull()
        val phase = when (payload?.optString("type")) {
            "start" -> ChatStreamEvent.StreamText.Phase.START
            "delta" -> ChatStreamEvent.StreamText.Phase.DELTA
            "end" -> ChatStreamEvent.StreamText.Phase.END
            else -> null
        }

        if (phase != null) {
            val text = payload?.optString("text").orEmpty()
            onEvent(ChatStreamEvent.StreamText(channel = channel, phase = phase, text = text))
            return
        }

        val fallbackText = normalizeTextPayload(data)
        if (fallbackText.isNotBlank()) {
            onEvent(
                ChatStreamEvent.StreamText(
                    channel = channel,
                    phase = ChatStreamEvent.StreamText.Phase.DELTA,
                    text = fallbackText
                )
            )
        }
    }

    private fun normalizeTextPayload(data: String): String {
        val trimmed = data.trim()
        if (trimmed.isBlank()) return ""

        return if (trimmed.startsWith("\"") && trimmed.endsWith("\"")) {
            runCatching { JSONObject("{\"value\":$trimmed}").optString("value") }
                .getOrElse { trimmed.trim('"') }
                .trim()
        } else {
            trimmed
        }
    }
}
