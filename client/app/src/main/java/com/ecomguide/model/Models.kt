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
    @SerializedName("image_path") val imagePath: String? = null,
    val img: String? = null,
    val tags: List<String> = emptyList(),
    val reason: String = "",
    val skus: List<SkuOption> = emptyList(),
    @SerializedName("rag_knowledge") val ragKnowledge: RagKnowledge? = null
) : Parcelable {
    val resolvedId: String get() = productId ?: id ?: ""
    val resolvedTitle: String get() = title ?: name ?: ""
    val resolvedPrice: Double get() = basePrice ?: price ?: 0.0
    val resolvedImageUrl: String? get() = imageUrl ?: imagePath ?: img
}

@Parcelize
data class SkuOption(
    @SerializedName("sku_id") val skuId: String = "",
    val properties: Map<String, String> = emptyMap(),
    val price: Double = 0.0,
    val stock: Int? = null
) : Parcelable {
    val label: String get() = properties.entries.joinToString(" | ") { "${it.key}: ${it.value}" }
}

@Parcelize
data class RagKnowledge(
    @SerializedName("marketing_description") val marketingDescription: String? = null,
    @SerializedName("official_faq") val officialFaq: List<FaqItem> = emptyList(),
    @SerializedName("user_reviews") val userReviews: List<UserReview> = emptyList()
) : Parcelable

data class ReviewResponse(
    @SerializedName("rag_knowledge") val ragKnowledge: RagKnowledge? = null
)

data class ProductSkusResponse(
    val skus: List<SkuOption> = emptyList()
)

@Parcelize
data class FaqItem(val question: String = "", val answer: String = "") : Parcelable

@Parcelize
data class UserReview(
    val nickname: String = "",
    val rating: Int = 5,
    val content: String = ""
) : Parcelable

// ─── SSE events (后端 Agent 工作流 v2 协议) ─────────────────────────────────────

/**
 * 后端 /api/search/{conversation_id} 返回的 SSE 事件类型：
 *   welcome     → 欢迎语文本
 *   products    → 单个商品对象 {product_id, sku_id, category, sub_category}
 *   chat_reply  → 品类介绍或推荐理由文本
 *   done        → 结束语 + conversation_id
 *   next_options → 后续追问选项列表
 *   error       → 错误信息
 */
sealed class ChatStreamEvent {
    /** 欢迎语 — Retrieval 节点第一条事件 */
    data class Welcome(val text: String) : ChatStreamEvent()

    /** 单个商品对象 — 后跟该商品的 chat_reply 推荐理由 */
    data class ProductEvent(
        val productId: String,
        val skuId: String,
        val category: String = "",
        val subCategory: String = ""
    ) : ChatStreamEvent()

    /** 品类介绍过渡语（多品类）或单商品推荐理由 */
    data class ChatReply(val text: String) : ChatStreamEvent()

    /** 流式文本增量事件（start / delta / end）。 */
    data class StreamText(
        val channel: Channel,
        val phase: Phase,
        val text: String = ""
    ) : ChatStreamEvent() {
        enum class Channel {
            WELCOME,
            CATEGORY_INTRO,
            ENDING
        }

        enum class Phase {
            START,
            DELTA,
            END
        }
    }

    /** 流结束 — 含结束语 text 和 conversation_id */
    data class Done(
        val text: String? = null,
        val conversationId: String? = null
    ) : ChatStreamEvent()

    /** 后续追问选项 */
    data class NextOptions(val options: List<String>) : ChatStreamEvent()

    /** 错误信息 */
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
    val scenarioId: String,               // 场景唯一标识
    val scenarioName: String,             // 入口名称，如 "春日连衣裙"、"春游穿搭"
    val emoji: String = "🌸",            // 场景图标 emoji
    val subtitle: String = "",           // 副标题描述，如 "（一件搞定懒人必备）"
    val reason: String = "",             // 推荐理由（用于入口卡片与落地页展示）
    val category: String = "",           // 品类名
    val subCategory: String = "",        // 子品类名
    val products: List<ApiProduct> = emptyList(),  // 该场景下的商品列表
    val firstProductTitle: String = "",  // 第一款商品名称
    val firstProductPrice: Double = 0.0,  // 第一款商品价格
    val firstProductImage: String? = null, // 第一款商品图片
    val productCount: Int = 0,            // 商品总数，用于展示 "X件商品在售"
    val shopHint: String = ""             // 店铺提示，如 "夕蒙seemon等多店在售"
) : Parcelable

// ─── UI message items ──────────────────────────────────────────────────────────

sealed class MessageItem {
    data class UserMsg(val text: String) : MessageItem()

    /** 单个 AI 回复段：一段推荐文案 +（可选）对应商品卡片 */
    data class AiReplyBlock(
        val text: String,
        val product: ApiProduct? = null,
        val scenarioCard: ScenarioCard? = null,
        val placeholderToken: String = ""
    )

    /**
     * AI 文本消息（单气泡）— 支持分段文本与“段内商品卡片”绑定展示。
     *
     * @param text           AI 回复全文（段落拼接，主要用于兼容旧渲染逻辑）
     * @param isStreaming    是否仍在接收 SSE 流
     * @param inlineProducts 兼容字段：历史逻辑使用的内嵌商品列表
     * @param blocks         新逻辑：按段组织的文案与对应商品，支持“每段文案下方卡片”
     */
    data class AiMsg(
        val text: String,
        val isStreaming: Boolean = false,
        val inlineProducts: List<ApiProduct> = emptyList(),
        val blocks: List<AiReplyBlock> = emptyList()
    ) : MessageItem()
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
