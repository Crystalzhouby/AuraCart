package com.ecomguide.network

import com.ecomguide.model.ChatRequest
import com.ecomguide.model.ChatResponse
import retrofit2.http.Body
import retrofit2.http.POST

interface ApiService {
    @POST("/api/chat")
    suspend fun sendMessage(@Body request: ChatRequest): ChatResponse
}
