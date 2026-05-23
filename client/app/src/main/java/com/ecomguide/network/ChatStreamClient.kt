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

class ChatStreamClient(
    private val baseUrl: String = "http://10.0.2.2:8000",
    private val okHttpClient: OkHttpClient = OkHttpClient()
) {
    fun send(
        message: String,
        sessionId: String?,
        onEvent: (ChatStreamEvent) -> Unit
    ): Call {
        val bodyJson = JSONObject()
            .put("message", message)
            .put("session_id", sessionId)
            .put("history", JSONArray())
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

    private fun parseSse(response: Response, onEvent: (ChatStreamEvent) -> Unit) {
        val source = response.body?.source() ?: return
        var eventName = ""
        val dataLines = mutableListOf<String>()

        while (!source.exhausted()) {
            val line = source.readUtf8Line() ?: break
            if (line.isBlank()) {
                dispatch(eventName, dataLines.joinToString("\n"), onEvent)
                eventName = ""
                dataLines.clear()
            } else if (line.startsWith("event:")) {
                eventName = line.removePrefix("event:").trim()
            } else if (line.startsWith("data:")) {
                dataLines.add(line.removePrefix("data:").trim())
            }
        }
    }

    private fun dispatch(eventName: String, data: String, onEvent: (ChatStreamEvent) -> Unit) {
        if (eventName.isBlank() || data.isBlank()) return
        val json = JSONObject(data)
        when (eventName) {
            "delta" -> onEvent(ChatStreamEvent.Delta(json.optString("text")))
            "product_cards" -> onEvent(ChatStreamEvent.ProductCards(data))
            "cart_update" -> onEvent(ChatStreamEvent.CartUpdate(data))
            "done" -> onEvent(ChatStreamEvent.Done(json.optString("session_id").ifBlank { null }))
        }
    }
}
