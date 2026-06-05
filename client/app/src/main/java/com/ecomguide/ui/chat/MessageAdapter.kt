package com.ecomguide.ui.chat

import android.animation.ObjectAnimator
import android.animation.PropertyValuesHolder
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.ecomguide.R
import com.ecomguide.databinding.ItemMsgAiBinding
import com.ecomguide.databinding.ItemMsgFollowTagsBinding
import com.ecomguide.databinding.ItemMsgProductsBinding
import com.ecomguide.databinding.ItemMsgProductHorizontalBinding
import com.ecomguide.databinding.ItemMsgScenarioReplyBinding
import com.ecomguide.databinding.ItemMsgTypingBinding
import com.ecomguide.databinding.ItemMsgUserBinding
import com.ecomguide.databinding.ItemScenarioMiniCardBinding
import com.ecomguide.model.ApiProduct
import com.ecomguide.model.MessageItem
import com.ecomguide.model.ScenarioCard
import com.ecomguide.network.RetrofitClient
import com.google.android.material.chip.Chip

class MessageAdapter(
    private val onProductClick: (ApiProduct) -> Unit,
    private val onAddToCart: (ApiProduct) -> Unit,
    private val onTagClick: (String) -> Unit,
    private val onScenarioClick: (ScenarioCard) -> Unit = {},
    private val onHorizontalProductClick: (ApiProduct) -> Unit = {}
) : RecyclerView.Adapter<RecyclerView.ViewHolder>() {

    companion object {
        private const val TYPE_USER = 1
        private const val TYPE_AI = 2
        private const val TYPE_TYPING = 3
        private const val TYPE_PRODUCTS = 4
        private const val TYPE_FOLLOW_TAGS = 5
        private const val TYPE_SCENARIO_REPLY = 6   // 合并式场景回复（文字+场景卡片+商品+标签）
        private const val TYPE_HORIZONTAL_PRODUCT = 7 // 横向商品卡片
    }

    private var messageItems: List<MessageItem> = emptyList()
    fun submitMessages(items: List<MessageItem>) {
        messageItems = items
        notifyDataSetChanged()
    }

    override fun getItemCount(): Int = messageItems.size

    override fun getItemViewType(position: Int): Int {
        return when (val item = messageItems[position]) {
            is MessageItem.UserMsg -> TYPE_USER
            is MessageItem.AiMsg -> TYPE_AI
            is MessageItem.Typing -> TYPE_TYPING
            is MessageItem.ProductCards -> TYPE_PRODUCTS
            is MessageItem.FollowTags -> TYPE_FOLLOW_TAGS
            is MessageItem.ScenarioReply -> TYPE_SCENARIO_REPLY
            is MessageItem.HorizontalProductCard -> TYPE_HORIZONTAL_PRODUCT
            else -> TYPE_AI  // 兜底：未知类型按普通 AI 消息处理
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
        val inflater = LayoutInflater.from(parent.context)
        return when (viewType) {
            TYPE_USER -> UserVH(ItemMsgUserBinding.inflate(inflater, parent, false))
            TYPE_AI -> AiVH(ItemMsgAiBinding.inflate(inflater, parent, false))
            TYPE_TYPING -> TypingVH(ItemMsgTypingBinding.inflate(inflater, parent, false))
            TYPE_PRODUCTS -> ProductsVH(ItemMsgProductsBinding.inflate(inflater, parent, false))
            TYPE_FOLLOW_TAGS -> FollowTagsVH(ItemMsgFollowTagsBinding.inflate(inflater, parent, false))
            TYPE_SCENARIO_REPLY -> ScenarioReplyVH(ItemMsgScenarioReplyBinding.inflate(inflater, parent, false))
            TYPE_HORIZONTAL_PRODUCT -> HorizontalProductVH(
                com.ecomguide.databinding.ItemMsgProductHorizontalBinding.inflate(inflater, parent, false)
            )
            else -> AiVH(ItemMsgAiBinding.inflate(inflater, parent, false))  // 兜底
        }
    }

    override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
        when (val item = messageItems[position]) {
            is MessageItem.UserMsg -> (holder as UserVH).bind(item)
            is MessageItem.AiMsg -> (holder as AiVH).bind(item)
            is MessageItem.Typing -> (holder as TypingVH).startAnimation()
            is MessageItem.ProductCards -> (holder as ProductsVH).bind(item.products)
            is MessageItem.FollowTags -> (holder as FollowTagsVH).bind(item.tags)
            is MessageItem.ScenarioReply -> (holder as ScenarioReplyVH).bind(item)
            is MessageItem.HorizontalProductCard -> (holder as HorizontalProductVH).bind(item.product)
        }
    }

    // ════════════════════════════════════════════════════════════════════════
    //  ViewHolders
    // ════════════════════════════════════════════════════════════════════════

    inner class UserVH(val b: ItemMsgUserBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(item: MessageItem.UserMsg) { b.tvText.text = item.text }
    }

    inner class AiVH(val b: ItemMsgAiBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(item: MessageItem.AiMsg) { b.tvText.text = item.text }
    }

    inner class TypingVH(val b: ItemMsgTypingBinding) : RecyclerView.ViewHolder(b.root) {
        private val dots = listOf(b.dot1, b.dot2, b.dot3)
        fun startAnimation() {
            dots.forEachIndexed { i, dot ->
                ObjectAnimator.ofPropertyValuesHolder(dot,
                    PropertyValuesHolder.ofFloat("translationY", 0f, -8f, 0f)
                ).apply {
                    duration = 600
                    startDelay = (i * 150).toLong()
                    repeatCount = ObjectAnimator.INFINITE
                }.start()
            }
        }
    }

    inner class ProductsVH(val b: ItemMsgProductsBinding) : RecyclerView.ViewHolder(b.root) {
        private val productAdapter = ProductCardAdapter(onProductClick, onAddToCart)
        init {
            b.rvProducts.apply {
                layoutManager = LinearLayoutManager(b.root.context, LinearLayoutManager.HORIZONTAL, false)
                adapter = productAdapter
                isNestedScrollingEnabled = false
            }
        }
        fun bind(products: List<ApiProduct>) { productAdapter.submitList(products) }
    }

    // ════════════════════════════════════════════════════════════════════════
    //  HorizontalProductCardInReplyAdapter — ScenarioReply 内的横向商品卡片列表
    // ════════════════════════════════════════════════════════════════════════

    /**
     * 场景回复气泡内的横向商品卡片 Adapter
     * 每件商品一个横向卡片（左图+右信息+购物车图标），纵向排列
     */
    private class HorizontalProductCardInReplyAdapter(
        private val onProductClick: (ApiProduct) -> Unit,
        private val onHorizontalProductClick: (ApiProduct) -> Unit
    ) : RecyclerView.Adapter<HorizontalProductCardInReplyAdapter.VH>() {

        private var items = emptyList<ApiProduct>()

        fun submitList(list: List<ApiProduct>) {
            items = list
            notifyDataSetChanged()
        }

        override fun getItemCount(): Int = items.size

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_msg_product_horizontal, parent, false)
            return VH(view)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            holder.bind(items[position])
        }

        inner class VH(itemView: View) : RecyclerView.ViewHolder(itemView) {
            // 通过 Binding 绑定横向卡片布局
            private val binding = ItemMsgProductHorizontalBinding.bind(itemView)

            fun bind(product: ApiProduct) {
                binding.tvName.text = product.resolvedTitle
                binding.tvPrice.text = formatPrice(product.resolvedPrice)

                // 评分
                val avgRating = product.ragKnowledge?.userReviews?.let { reviews ->
                    if (reviews.isEmpty()) null else reviews.sumOf { it.rating }.toFloat() / reviews.size
                }
                if (avgRating != null) {
                    binding.tvRating.text = "⭐ ${"%.1f".format(avgRating)}"
                    binding.tvRating.visibility = View.VISIBLE
                } else {
                    binding.tvRating.visibility = View.GONE
                }

                // 图片
                val primaryUrl = resolveImageUrl(product.imageUrl)
                val fallbackUrl = product.img
                val loadUrl = primaryUrl ?: fallbackUrl
                if (loadUrl != null) {
                    Glide.with(itemView.context).load(loadUrl).centerCrop()
                        .placeholder(android.R.color.darker_gray).into(binding.ivProduct)
                } else {
                    binding.ivProduct.setImageResource(android.R.color.darker_gray)
                }

                // 点击卡片：进入全屏商品详情页
                itemView.setOnClickListener { onProductClick(product) }
                // 点击购物车图标：进入半屏加入购物车页
                binding.btnCart.setOnClickListener { onHorizontalProductClick(product) }
            }

            private fun formatPrice(price: Double): String =
                if (price == price.toLong().toDouble()) "¥${price.toLong()}"
                else "¥${"%.2f".format(price)}"

            private fun resolveImageUrl(url: String?): String? {
                if (url == null) return null
                return if (url.startsWith("http")) url
                else "${RetrofitClient.BASE_URL.trimEnd('/')}$url"
            }
        }
    }

    inner class FollowTagsVH(val b: ItemMsgFollowTagsBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(tags: List<String>) {
            b.chipGroup.removeAllViews()
            tags.forEach { tag ->
                val chip = Chip(b.root.context).apply {
                    text = tag
                    isCheckable = false
                    setChipBackgroundColorResource(R.color.colorAccentBg)
                    setChipStrokeColorResource(R.color.colorPrimary)
                    chipStrokeWidth = 2f
                    setTextColor(b.root.context.getColor(R.color.colorPrimary))
                    textSize = 12f
                    setOnClickListener { onTagClick(tag) }
                }
                b.chipGroup.addView(chip)
            }
        }
    }

    // ── ScenarioReplyVH：合并式场景回复（一个 AI 气泡包含全部内容）─────────────

    inner class ScenarioReplyVH(val b: ItemMsgScenarioReplyBinding) : RecyclerView.ViewHolder(b.root) {

        private val horizontalProductAdapter = HorizontalProductCardInReplyAdapter(onProductClick, onHorizontalProductClick)

        init {
            // 商品列表 — 使用横向卡片，纵向排列
            b.rvReplyProducts.apply {
                layoutManager = LinearLayoutManager(b.root.context, LinearLayoutManager.VERTICAL, false)
                adapter = horizontalProductAdapter
                isNestedScrollingEnabled = false
            }
        }

        fun bind(reply: MessageItem.ScenarioReply) {
            val ctx = b.root.context

            // ① 开头语文本
            if (reply.text.isNotBlank()) {
                b.tvReplyText.text = reply.text
                b.tvReplyText.visibility = View.VISIBLE
            } else {
                b.tvReplyText.visibility = View.GONE
            }

            // ② 场景小卡片列表（动态 inflate）
            b.scenarioCardsContainer.removeAllViews()
            reply.scenarioCards.forEach { card ->
                val miniCard = ItemScenarioMiniCardBinding.inflate(LayoutInflater.from(ctx), b.scenarioCardsContainer, false)
                bindMiniCard(miniCard, card)
                b.scenarioCardsContainer.addView(miniCard.root)
            }
            if (reply.scenarioCards.isEmpty()) {
                b.scenarioCardsContainer.visibility = View.GONE
            } else {
                b.scenarioCardsContainer.visibility = View.VISIBLE
            }

            // ③ 商品卡片（横向）
            if (reply.products.isNotEmpty()) {
                horizontalProductAdapter.submitList(reply.products)
                b.rvReplyProducts.visibility = View.VISIBLE
            } else {
                b.rvReplyProducts.visibility = View.GONE
            }

            // 追问标签不再在此渲染，由 ChatViewModel 作为独立 FollowTags 消息追加到气泡外
            b.chipGroupReplyTags.visibility = View.GONE
        }

        /** 绑定单个场景小卡片的数据 */
        private fun bindMiniCard(mb: ItemScenarioMiniCardBinding, card: ScenarioCard) {
            mb.root.tag = card
            mb.tvEmoji.text = card.emoji
            mb.tvScenarioName.text = card.scenarioName
            mb.tvSubtitle.text = card.subtitle
            if (card.subtitle.isBlank()) mb.tvSubtitle.visibility = View.GONE else mb.tvSubtitle.visibility = View.VISIBLE

            mb.tvProductTitle.text = card.firstProductTitle
            mb.tvProductPrice.text = formatPrice(card.firstProductPrice)
            mb.tvProductCount.text = "${card.productCount}件商品在售"

            // 缩略图
            val thumbUrl = card.firstProductImage
            if (!thumbUrl.isNullOrBlank()) {
                Glide.with(b.root.context)
                    .load(resolveImageUrl(thumbUrl))
                    .centerCrop()
                    .placeholder(android.R.color.darker_gray)
                    .into(mb.ivProductThumb)
            } else {
                mb.ivProductThumb.setImageResource(android.R.color.darker_gray)
            }

            mb.root.setOnClickListener { onScenarioClick(card) }
        }

        private fun formatPrice(price: Double): String =
            if (price == price.toLong().toDouble()) "¥${price.toLong()}"
            else "¥${"%.2f".format(price)}"

        private fun resolveImageUrl(url: String?): String? {
            if (url == null) return null
            return if (url.startsWith("http")) url
            else "${RetrofitClient.BASE_URL.trimEnd('/')}$url"
        }
    }

    // ── HorizontalProductVH：聊天消息中的横向商品卡片（左图+右信息+购物车图标）────

    inner class HorizontalProductVH(
        val b: com.ecomguide.databinding.ItemMsgProductHorizontalBinding
    ) : RecyclerView.ViewHolder(b.root) {

        fun bind(product: ApiProduct) {
            // 商品名称
            b.tvName.text = product.resolvedTitle

            // 价格
            b.tvPrice.text = formatPrice(product.resolvedPrice)

            // 评分
            val avgRating = product.ragKnowledge?.userReviews?.let { reviews ->
                if (reviews.isEmpty()) null
                else reviews.sumOf { it.rating }.toFloat() / reviews.size
            }
            if (avgRating != null) {
                b.tvRating.text = "⭐ ${"%.1f".format(avgRating)}"
                b.tvRating.visibility = View.VISIBLE
            } else {
                b.tvRating.visibility = View.GONE
            }

            // 图片
            val primaryUrl = resolveImageUrl(product.imageUrl)
            val fallbackUrl = product.img
            val loadUrl = primaryUrl ?: fallbackUrl
            if (loadUrl != null) {
                Glide.with(b.root.context).load(loadUrl).centerCrop()
                    .placeholder(android.R.color.darker_gray).into(b.ivProduct)
            } else {
                b.ivProduct.setImageResource(android.R.color.darker_gray)
            }

            // 点击卡片：进入全屏商品详情页
            itemView.setOnClickListener { onProductClick(product) }

            // 购物车图标：进入半屏加入购物车页
            b.btnCart.setOnClickListener { onHorizontalProductClick(product) }
        }

        private fun formatPrice(price: Double): String =
            if (price == price.toLong().toDouble()) "¥${price.toLong()}"
            else "¥${"%.2f".format(price)}"

        private fun resolveImageUrl(url: String?): String? {
            if (url == null) return null
            return if (url.startsWith("http")) url
            else "${RetrofitClient.BASE_URL.trimEnd('/')}$url"
        }
    }
}
