package com.ecomguide.model

import android.os.Parcelable
import com.google.gson.annotations.SerializedName
import kotlinx.parcelize.Parcelize

// ─── Network models ────────────────────────────────────────────────────────────

data class ChatRequest(
    val message: String,
    @SerializedName("session_id") val sessionId: String? = null,
    val history: List<HistoryItem> = emptyList()
)

data class HistoryItem(val role: String, val content: String)

data class ChatResponse(
    val reply: String,
    @SerializedName("session_id") val sessionId: String,
    val products: List<ApiProduct> = emptyList()
)

/** Product from SSE product_cards or /api/products — handles both old and new field names */
@Parcelize
data class ApiProduct(
    @SerializedName("product_id") val productId: String? = null,
    val id: String? = null,
    val name: String? = null,
    val title: String? = null,
    val category: String = "",
    @SerializedName("sub_category") val subCategory: String = "",
    val brand: String = "",
    val price: Double? = null,
    @SerializedName("base_price") val basePrice: Double? = null,
    val stock: Int = 0,
    val description: String = "",
    @SerializedName("image_url") val imageUrl: String? = null,
    val img: String? = null,
    val tags: List<String> = emptyList(),
    val reason: String = "",
    val skus: List<SkuOption> = emptyList(),
    @SerializedName("rag_knowledge") val ragKnowledge: RagKnowledge? = null
) : Parcelable {
    val resolvedId: String get() = productId ?: id ?: ""
    val resolvedTitle: String get() = title ?: name ?: ""
    val resolvedPrice: Double get() = basePrice ?: price ?: 0.0
    val resolvedImageUrl: String? get() = imageUrl ?: img
}

@Parcelize
data class SkuOption(
    @SerializedName("sku_id") val skuId: String = "",
    val properties: Map<String, String> = emptyMap(),
    val price: Double = 0.0
) : Parcelable {
    val label: String get() = properties.entries.joinToString(" | ") { "${it.key}: ${it.value}" }
}

@Parcelize
data class RagKnowledge(
    @SerializedName("marketing_description") val marketingDescription: String? = null,
    @SerializedName("official_faq") val officialFaq: List<FaqItem> = emptyList(),
    @SerializedName("user_reviews") val userReviews: List<UserReview> = emptyList()
) : Parcelable

@Parcelize
data class FaqItem(val question: String = "", val answer: String = "") : Parcelable

@Parcelize
data class UserReview(
    val nickname: String = "",
    val rating: Int = 5,
    val content: String = ""
) : Parcelable

// ─── SSE events ────────────────────────────────────────────────────────────────

sealed class ChatStreamEvent {
    data class Delta(val text: String) : ChatStreamEvent()
    data class ProductCards(val productsJson: String) : ChatStreamEvent()
    data class CartUpdate(val cartJson: String) : ChatStreamEvent()
    data class Done(val sessionId: String?) : ChatStreamEvent()
    data class Error(val message: String) : ChatStreamEvent()
}

// ─── UI message items ──────────────────────────────────────────────────────────

sealed class MessageItem {
    data class UserMsg(val text: String) : MessageItem()
    data class AiMsg(val text: String, val isStreaming: Boolean = false) : MessageItem()
    object Typing : MessageItem()
    data class ProductCards(val products: List<ApiProduct>) : MessageItem()
    data class FollowTags(val tags: List<String>) : MessageItem()
}

// ─── Cart ──────────────────────────────────────────────────────────────────────

@Parcelize
data class CartItem(
    val productId: String,
    val title: String,
    val price: Double,
    val imageUrl: String?,
    val skuLabel: String,
    var qty: Int = 1
) : Parcelable
