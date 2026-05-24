package com.ecomguide.network

import com.ecomguide.model.ChatStreamEvent
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException

/**
 * SSE（Server-Sent Events）流式聊天客户端
 *
 * 负责向后端 /api/chat/stream 发起 HTTP 请求，并实时解析服务端推送的 SSE 事件，
 * 通过回调将事件分发给调用方（通常是 ChatViewModel）。
 *
 * SSE 协议格式：
 *   event: <事件名>\n
 *   data: <JSON字符串>\n
 *   \n               ← 空行表示一个事件块结束
 *
 * 支持的事件类型（对应 ChatStreamEvent 子类）：
 *   delta        → 文字流片段，用于逐字打字效果
 *   product_cards→ 商品推荐列表，包含完整商品数据
 *   cart_update  → 购物车状态变更（加购/删除等）
 *   done         → 流结束，携带 session_id 供多轮对话使用
 *
 * 注意：OkHttp 的回调运行在子线程，UI 更新需切换至主线程（由 ViewModel 负责）。
 *
 * @param baseUrl       后端服务地址，模拟器默认 10.0.2.2:8000（= 宿主机 localhost）
 * @param okHttpClient  可注入自定义 OkHttpClient（便于测试）
 */
class ChatStreamClient(
    private val baseUrl: String = "http://10.0.2.2:8000",
    private val okHttpClient: OkHttpClient = OkHttpClient()
) {

    /**
     * 发起流式对话请求。
     *
     * @param message    用户输入的消息文本
     * @param sessionId  会话 ID（多轮对话使用，首轮传 null 由服务端生成）
     * @param onEvent    事件回调，在 OkHttp 子线程中调用
     * @return           OkHttp Call 对象，可调用 cancel() 中断请求
     */
    fun send(
        message: String,
        sessionId: String?,
        onEvent: (ChatStreamEvent) -> Unit
    ): Call {
        // 构建请求体：包含消息、会话 ID 和对话历史
        val bodyJson = JSONObject()
            .put("message", message)
            .put("session_id", sessionId)
            .put("history", JSONArray())   // 当前版本由服务端维护历史，客户端传空数组
            .toString()

        val request = Request.Builder()
            .url("$baseUrl/api/chat/stream")
            .post(bodyJson.toRequestBody("application/json".toMediaType()))
            .build()

        val call = okHttpClient.newCall(request)
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                onEvent(ChatStreamEvent.Error(e.message ?: "网络请求失败"))
            }

            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (!response.isSuccessful) {
                        onEvent(ChatStreamEvent.Error("HTTP ${response.code}"))
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
     *
     * SSE 解析规则：
     *   - "event:" 行：提取事件名
     *   - "data:" 行：追加数据行（一个事件可有多行 data）
     *   - 空行：事件块结束，分发给 dispatch()
     */
    private fun parseSse(response: Response, onEvent: (ChatStreamEvent) -> Unit) {
        val source = response.body?.source() ?: return
        var eventName = ""
        val dataLines = mutableListOf<String>()

        while (!source.exhausted()) {
            val line = source.readUtf8Line() ?: break
            when {
                line.isBlank() -> {
                    // 空行：一个完整事件块结束，分发并重置状态
                    dispatch(eventName, dataLines.joinToString("\n"), onEvent)
                    eventName = ""
                    dataLines.clear()
                }
                line.startsWith("event:") -> eventName = line.removePrefix("event:").trim()
                line.startsWith("data:")  -> dataLines.add(line.removePrefix("data:").trim())
            }
        }
    }

    /**
     * 根据事件名将数据分发为对应的 ChatStreamEvent 子类。
     * 未知事件类型直接忽略，保持向前兼容。
     */
    private fun dispatch(eventName: String, data: String, onEvent: (ChatStreamEvent) -> Unit) {
        if (eventName.isBlank() || data.isBlank()) return
        val json = JSONObject(data)
        when (eventName) {
            "delta"         -> onEvent(ChatStreamEvent.Delta(json.optString("text")))
            "product_cards" -> onEvent(ChatStreamEvent.ProductCards(data))
            "cart_update"   -> onEvent(ChatStreamEvent.CartUpdate(data))
            "done"          -> onEvent(ChatStreamEvent.Done(json.optString("session_id").ifBlank { null }))
            // 其他事件类型：忽略，保持向前兼容
        }
    }
}
