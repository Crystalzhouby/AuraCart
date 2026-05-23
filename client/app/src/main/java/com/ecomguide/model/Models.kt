package com.ecomguide.model

import com.google.gson.annotations.SerializedName

data class ChatRequest(
    val message: String,
    @SerializedName("session_id")
    val sessionId: String? = null
)

data class ChatResponse(
    val reply: String,
    @SerializedName("session_id")
    val sessionId: String,
    val products: List<Product> = emptyList()
)

data class Product(
    val id: String,
    val name: String,
    val category: String,
    val price: Double,
    val stock: Int,
    val description: String,
    @SerializedName("image_url")
    val imageUrl: String?,
    val tags: List<String> = emptyList(),
    val reason: String = ""
)

sealed class ChatStreamEvent {
    data class Delta(val text: String) : ChatStreamEvent()
    data class ProductCards(val productsJson: String) : ChatStreamEvent()
    data class CartUpdate(val cartJson: String) : ChatStreamEvent()
    data class Done(val sessionId: String?) : ChatStreamEvent()
    data class Error(val message: String) : ChatStreamEvent()
}
