package com.ecomguide.model

data class ChatRequest(
    val message: String,
    val sessionId: String? = null
)

data class ChatResponse(
    val reply: String,
    val sessionId: String
)

data class Product(
    val id: String,
    val name: String,
    val price: Double,
    val description: String,
    val imageUrl: String?
)
