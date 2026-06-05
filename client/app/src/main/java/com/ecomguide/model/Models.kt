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

// ─── Scenario card model (场景推荐卡片) ──────────────────────────────────────

/**
 * 场景推荐卡片 — 对应用户提供的参考图（图1/图3）中的品类入口形式
 *
 * 展示样式（在聊天消息流中）：
 *   🌸 连衣裙 PARTY（一件搞定懒人必备）
 *   [商品图片]  春游连衣裙
 *             143.90元 · 夕蒙seemon等多店在售 >
 *
 * 点击后跳转到品类落地页（CategoryProductsActivity），展示该场景下的完整商品列表。
 */
@Parcelize
data class ScenarioCard(
    val scenarioId: String,              // 场景唯一标识
    val scenarioName: String,            // 入口名称，如 "春日连衣裙"、"春游穿搭"
    val emoji: String = "🌸",           // 场景图标 emoji
    val subtitle: String = "",          // 副标题描述，如 "（一件搞定懒人必备）"
    val category: String = "",           // 品类名
    val products: List<ApiProduct> = emptyList(),  // 该场景下的商品列表
    val firstProductTitle: String = "",  // 第一款商品名称
    val firstProductPrice: Double = 0.0, // 第一款商品价格
    val firstProductImage: String? = null, // 第一款商品图片
    val productCount: Int = 0,           // 商品总数，用于展示 "X件商品在售"
    val shopHint: String = ""            // 店铺提示，如 "夕蒙seemon等多店在售"
) : Parcelable

// ─── UI message items ──────────────────────────────────────────────────────────

sealed class MessageItem {
    data class UserMsg(val text: String) : MessageItem()
    data class AiMsg(val text: String, val isStreaming: Boolean = false) : MessageItem()
    object Typing : MessageItem()
    data class ProductCards(val products: List<ApiProduct>) : MessageItem()
    data class FollowTags(val tags: List<String>) : MessageItem()

    /** 注意：旧的 ScenarioCard 子类已废弃，统一使用 ScenarioReply */

    /**
     * 场景回复 — 一条合并消息：AI 开头语 + 多个场景卡片 + 商品卡片 + 追问标签
     *
     * 效果（参考图3）：一个 AI 气泡内依次展示全部内容
     */
    data class ScenarioReply(
        val text: String,
        val scenarioCards: List<ScenarioCard> = emptyList<ScenarioCard>(),
        val products: List<ApiProduct> = emptyList<ApiProduct>(),
        val followTags: List<String> = emptyList<String>()
    ) : MessageItem()

    /**
     * 横向商品卡片 — 聊天消息中的横排商品展示（参考图2/图3）
     *
     * 样式：左图(100dp) + 右信息(标题+价格+评分) + 购物车图标
     * 点击卡片 → 跳转 HalfScreenProductDetailActivity 半屏详情页
     */
    data class HorizontalProductCard(val product: ApiProduct) : MessageItem()
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
