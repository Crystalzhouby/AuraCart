package com.ecomguide.ui.chat

import android.animation.ObjectAnimator
import android.animation.PropertyValuesHolder
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.widget.AppCompatTextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.ecomguide.R
import com.ecomguide.databinding.ItemMsgAiBinding
import com.ecomguide.databinding.ItemMsgFollowTagsBinding
import com.ecomguide.databinding.ItemMsgProductHorizontalBinding
import com.ecomguide.databinding.ItemMsgProductsBinding
import com.ecomguide.databinding.ItemMsgScenarioReplyBinding
import com.ecomguide.databinding.ItemMsgTypingBinding
import com.ecomguide.databinding.ItemMsgUserBinding
import com.ecomguide.databinding.ItemScenarioMiniCardBinding
import com.ecomguide.model.ApiProduct
import com.ecomguide.model.MessageItem
import com.ecomguide.model.ScenarioCard
import com.ecomguide.network.RetrofitClient
import com.google.android.material.chip.Chip

/**
 * 聊天消息主适配器。
 *
 * 职责：
 * 1) 根据 MessageItem 多态类型分发 ViewHolder
 * 2) 渲染 AI 气泡中的“文本块 + 商品块”混排结构
 * 3) 统一商品卡片绑定逻辑（价格/评分/图片/点击）
 *
 * 设计原则：
 * - 所有横向商品卡片都复用同一套绑定函数，避免重复造轮子
 * - 数据结构兼容新旧协议（AiMsg.blocks 与 text/inlineProducts）
 */
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
        private const val TYPE_SCENARIO_REPLY = 6
        private const val TYPE_HORIZONTAL_PRODUCT = 7
    }

    private var messageItems: List<MessageItem> = emptyList()

    /** 列表整量更新入口。 */
    fun submitMessages(items: List<MessageItem>) {
        messageItems = normalizeTypingItems(items)
        notifyDataSetChanged()
    }

    /** 把独立 Typing 消息折叠到最近的 AI 气泡，保证动画在同一气泡内显示。 */
    private fun normalizeTypingItems(items: List<MessageItem>): List<MessageItem> {
        if (items.none { it is MessageItem.Typing }) return items

        val normalized = mutableListOf<MessageItem>()
        items.forEach { item ->
            when (item) {
                is MessageItem.Typing -> {
                    val aiIndex = normalized.indexOfLast { it is MessageItem.AiMsg }
                    if (aiIndex >= 0) {
                        val ai = normalized[aiIndex] as MessageItem.AiMsg
                        if (!ai.isStreaming) {
                            normalized[aiIndex] = ai.copy(isStreaming = true)
                        }
                    } else {
                        normalized.add(MessageItem.AiMsg(text = "", isStreaming = true))
                    }
                }

                else -> normalized.add(item)
            }
        }
        return normalized
    }

    override fun getItemCount(): Int = messageItems.size

    override fun getItemViewType(position: Int): Int {
        return when (messageItems[position]) {
            is MessageItem.UserMsg -> TYPE_USER
            is MessageItem.AiMsg -> TYPE_AI
            is MessageItem.Typing -> TYPE_TYPING
            is MessageItem.ProductCards -> TYPE_PRODUCTS
            is MessageItem.FollowTags -> TYPE_FOLLOW_TAGS
            is MessageItem.ScenarioReply -> TYPE_SCENARIO_REPLY
            is MessageItem.HorizontalProductCard -> TYPE_HORIZONTAL_PRODUCT
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
                ItemMsgProductHorizontalBinding.inflate(inflater, parent, false)
            )

            else -> AiVH(ItemMsgAiBinding.inflate(inflater, parent, false))
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

    // ─── 公共绑定工具：收敛商品卡重复逻辑 ────────────────────────────────────────

    /**
     * 统一绑定横向商品卡片（名称 / 价格 / 评分 / 图片 / 点击）。
     *
     * 该方法被以下场景复用：
     * - AI 气泡内商品块
     * - ScenarioReply 内商品列表
     * - 独立 HorizontalProductCard 消息
     */
    private fun bindHorizontalProductCard(
        binding: ItemMsgProductHorizontalBinding,
        product: ApiProduct,
        cardClick: (ApiProduct) -> Unit,
        cartClick: (ApiProduct) -> Unit
    ) {
        binding.tvName.text = product.resolvedTitle
        binding.tvPrice.text = formatPrice(product.resolvedPrice)

        bindProductRating(
            product = product,
            ratingView = binding.tvRating
        )

        bindProductImage(
            imageView = binding.ivProduct,
            product = product
        )

        binding.root.setOnClickListener { cardClick(product) }
        binding.btnCart.setOnClickListener { cartClick(product) }
    }

    /** 统一评分渲染：有评分则显示，无评分则隐藏。 */
    private fun bindProductRating(product: ApiProduct, ratingView: TextView) {
        val avgRating = product.ragKnowledge?.userReviews?.let { reviews ->
            if (reviews.isEmpty()) null else reviews.sumOf { it.rating }.toFloat() / reviews.size
        }

        if (avgRating == null) {
            ratingView.visibility = View.GONE
            return
        }

        ratingView.text = "⭐ ${"%.1f".format(avgRating)}"
        ratingView.visibility = View.VISIBLE
    }

    /**
     * 统一图片加载策略：
     * 1) 商品字段图
     * 2) `/api/products/image/{id}` 接口图
     * 3) fallback 图
     */
    private fun bindProductImage(imageView: ImageView, product: ApiProduct) {
        val primaryUrl = RetrofitClient.resolveImageUrl(product.resolvedImageUrl)
        val endpointUrl = RetrofitClient.productImageUrl(product.resolvedId)
        val fallbackUrl = RetrofitClient.resolveImageUrl(product.img)
        val loadUrl = primaryUrl ?: endpointUrl ?: fallbackUrl

        if (loadUrl == null) {
            imageView.setImageResource(android.R.color.darker_gray)
            return
        }

        Glide.with(imageView.context)
            .load(loadUrl)
            .error(Glide.with(imageView.context).load(endpointUrl ?: fallbackUrl))
            .centerCrop()
            .placeholder(android.R.color.darker_gray)
            .into(imageView)
    }

    /** 统一价格文案格式。 */
    private fun formatPrice(price: Double): String {
        return if (price == price.toLong().toDouble()) "¥${price.toLong()}"
        else "¥${"%.2f".format(price)}"
    }

    /**
     * 把 AiMsg 转成块级渲染结构。
     *
     * 优先读取新协议字段 `blocks`；若为空则退化到旧字段 `text + inlineProducts`。
     */
    private fun buildAiRenderBlocks(item: MessageItem.AiMsg): List<AiRenderBlock> {
        val renderBlocks = mutableListOf<AiRenderBlock>()

        if (item.blocks.isNotEmpty()) {
            item.blocks.forEach { block ->
                val text = block.text.trim()
                if (text.isNotEmpty()) {
                    renderBlocks.add(
                        AiRenderBlock.Text(
                            text = text,
                            placeholderToken = block.placeholderToken
                        )
                    )
                }
                block.scenarioCard?.let { renderBlocks.add(AiRenderBlock.ScenarioEntry(it)) }
                block.product?.let {
                    renderBlocks.add(
                        AiRenderBlock.Product(
                            product = it,
                            placeholderToken = block.placeholderToken
                        )
                    )
                }
            }

            if (item.isStreaming) {
                renderBlocks.add(AiRenderBlock.Typing)
            }
            if (renderBlocks.isNotEmpty()) return renderBlocks
        }

        val fallbackLines = item.text.lines().map { it.trim() }.filter { it.isNotEmpty() }
        fallbackLines.forEach { line -> renderBlocks.add(AiRenderBlock.Text(line)) }
        item.inlineProducts.forEach { product -> renderBlocks.add(AiRenderBlock.Product(product)) }

        if (item.isStreaming) {
            renderBlocks.add(AiRenderBlock.Typing)
        }

        return renderBlocks
    }

    // ─── 各类型 ViewHolder ─────────────────────────────────────────────────────

    inner class UserVH(private val b: ItemMsgUserBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(item: MessageItem.UserMsg) {
            b.tvText.text = item.text
        }
    }

    /** AI 消息 ViewHolder：内部再嵌套一个块级 RecyclerView。 */
    inner class AiVH(private val b: ItemMsgAiBinding) : RecyclerView.ViewHolder(b.root) {

        private val blockAdapter = AiBlockAdapter(
            onProductClick = onProductClick,
            onHorizontalProductClick = onHorizontalProductClick
        )

        init {
            b.rvBlocks.apply {
                layoutManager = LinearLayoutManager(b.root.context, LinearLayoutManager.VERTICAL, false)
                adapter = blockAdapter
                isNestedScrollingEnabled = false
                overScrollMode = View.OVER_SCROLL_NEVER
                itemAnimator = null
            }
        }

        fun bind(item: MessageItem.AiMsg) {
            blockAdapter.submitList(buildAiRenderBlocks(item))
        }
    }

    /** “AI 正在输入”三点动画。 */
    inner class TypingVH(private val b: ItemMsgTypingBinding) : RecyclerView.ViewHolder(b.root) {
        private val dots = listOf(b.dot1, b.dot2, b.dot3)

        fun startAnimation() {
            dots.forEachIndexed { i, dot ->
                ObjectAnimator.ofPropertyValuesHolder(
                    dot,
                    PropertyValuesHolder.ofFloat("translationY", 0f, -8f, 0f)
                ).apply {
                    duration = 600
                    startDelay = (i * 150).toLong()
                    repeatCount = ObjectAnimator.INFINITE
                }.start()
            }
        }
    }

    /** 老的横向商品列表消息（ProductCards）。 */
    inner class ProductsVH(private val b: ItemMsgProductsBinding) : RecyclerView.ViewHolder(b.root) {
        private val productAdapter = ProductCardAdapter(onProductClick, onAddToCart)

        init {
            b.rvProducts.apply {
                layoutManager = LinearLayoutManager(b.root.context, LinearLayoutManager.HORIZONTAL, false)
                adapter = productAdapter
                isNestedScrollingEnabled = false
            }
        }

        fun bind(products: List<ApiProduct>) {
            productAdapter.submitList(products)
        }
    }

    /** 场景回复中的“商品列表区”（纵向摆放横向卡片样式）。 */
    private inner class HorizontalProductCardInReplyAdapter(
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
            private val binding = ItemMsgProductHorizontalBinding.bind(itemView)

            fun bind(product: ApiProduct) {
                bindHorizontalProductCard(
                    binding = binding,
                    product = product,
                    cardClick = onProductClick,
                    cartClick = onHorizontalProductClick
                )
            }
        }
    }

    /** 后续追问标签。 */
    inner class FollowTagsVH(private val b: ItemMsgFollowTagsBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(tags: List<String>) {
            b.chipGroup.removeAllViews()

            tags.forEach { tag ->
                val chip = Chip(b.root.context).apply {
                    text = tag
                    isCheckable = false
                    setChipBackgroundColorResource(R.color.colorAccentBg)
                    setChipStrokeColorResource(R.color.colorPrimary)
                    chipStrokeWidth = 2f
                    setTextColor(ContextCompat.getColor(b.root.context, R.color.colorPrimary))
                    textSize = 12f
                    setOnClickListener { onTagClick(tag) }
                }
                b.chipGroup.addView(chip)
            }
        }
    }

    /** 场景化回复（文案 + 场景卡 + 商品）。 */
    inner class ScenarioReplyVH(private val b: ItemMsgScenarioReplyBinding) : RecyclerView.ViewHolder(b.root) {

        private val horizontalProductAdapter = HorizontalProductCardInReplyAdapter(
            onProductClick,
            onHorizontalProductClick
        )

        init {
            b.rvReplyProducts.apply {
                layoutManager = LinearLayoutManager(b.root.context, LinearLayoutManager.VERTICAL, false)
                adapter = horizontalProductAdapter
                isNestedScrollingEnabled = false
            }
        }

        fun bind(reply: MessageItem.ScenarioReply) {
            bindReplyText(reply)
            bindScenarioCards(reply.scenarioCards)
            bindReplyProducts(reply.products)

            // 设计上 ScenarioReply 中不展示标签，标签统一作为独立 MessageItem.FollowTags。
            b.chipGroupReplyTags.visibility = View.GONE
        }

        private fun bindReplyText(reply: MessageItem.ScenarioReply) {
            if (reply.text.isBlank()) {
                b.tvReplyText.visibility = View.GONE
                return
            }

            b.tvReplyText.text = reply.text
            b.tvReplyText.visibility = View.VISIBLE
        }

        private fun bindScenarioCards(cards: List<ScenarioCard>) {
            val context = b.root.context
            b.scenarioCardsContainer.removeAllViews()

            cards.forEach { card ->
                val miniCard = ItemScenarioMiniCardBinding.inflate(
                    LayoutInflater.from(context),
                    b.scenarioCardsContainer,
                    false
                )
                bindMiniCard(miniCard, card)
                b.scenarioCardsContainer.addView(miniCard.root)
            }

            b.scenarioCardsContainer.visibility = if (cards.isEmpty()) View.GONE else View.VISIBLE
        }

        private fun bindReplyProducts(products: List<ApiProduct>) {
            if (products.isEmpty()) {
                b.rvReplyProducts.visibility = View.GONE
                return
            }

            horizontalProductAdapter.submitList(products)
            b.rvReplyProducts.visibility = View.VISIBLE
        }

        private fun bindMiniCard(binding: ItemScenarioMiniCardBinding, card: ScenarioCard) {
            ScenarioMiniCardBlockVH(binding.root, onScenarioClick).bind(card)
        }
    }

    /** 独立横向商品卡消息（非 AiMsg 内块结构）。 */
    inner class HorizontalProductVH(
        private val b: ItemMsgProductHorizontalBinding
    ) : RecyclerView.ViewHolder(b.root) {

        fun bind(product: ApiProduct) {
            bindHorizontalProductCard(
                binding = b,
                product = product,
                cardClick = onProductClick,
                cartClick = onHorizontalProductClick
            )
        }
    }

    /** AI 文本块 ViewHolder。 */
    private class AiTextBlockVH(
        private val tv: AppCompatTextView
    ) : RecyclerView.ViewHolder(tv) {
        fun bind(text: String) {
            tv.text = text
        }
    }

    /** AI / ScenarioReply 共用的场景入口卡片 ViewHolder。 */
    private inner class ScenarioMiniCardBlockVH(
        itemView: View,
        private val onScenarioClick: (ScenarioCard) -> Unit
    ) : RecyclerView.ViewHolder(itemView) {
        private val binding = ItemScenarioMiniCardBinding.bind(itemView)

        fun bind(card: ScenarioCard) {
            binding.root.tag = card
            binding.tvEmoji.visibility = View.GONE
            binding.tvScenarioName.text = card.firstProductTitle
            binding.tvScenarioName.setTypeface(binding.tvScenarioName.typeface, android.graphics.Typeface.BOLD)
            binding.tvSubtitle.visibility = View.GONE
            binding.tvProductTitle.visibility = View.GONE
            binding.tvProductPrice.text = formatPrice(card.firstProductPrice)
            binding.tvProductCount.text = "${card.productCount}件类似商品"

            val thumbUrl = RetrofitClient.resolveImageUrl(card.firstProductImage)
            if (!thumbUrl.isNullOrBlank()) {
                Glide.with(binding.root.context)
                    .load(thumbUrl)
                    .centerCrop()
                    .placeholder(android.R.color.darker_gray)
                    .into(binding.ivProductThumb)
            } else {
                binding.ivProductThumb.setImageResource(android.R.color.darker_gray)
            }

            binding.root.setOnClickListener { onScenarioClick(card) }
        }
    }

    /** AI 商品块 ViewHolder。 */
    private inner class AiProductBlockVH(
        itemView: View,
        private val onProductClick: (ApiProduct) -> Unit,
        private val onHorizontalProductClick: (ApiProduct) -> Unit
    ) : RecyclerView.ViewHolder(itemView) {
        private val binding = ItemMsgProductHorizontalBinding.bind(itemView)

        fun bind(product: ApiProduct) {
            bindHorizontalProductCard(
                binding = binding,
                product = product,
                cardClick = onProductClick,
                cartClick = onHorizontalProductClick
            )
        }
    }

    /** AI 气泡内的三点输入动画块。 */
    private class AiTypingBlockVH(itemView: View) : RecyclerView.ViewHolder(itemView) {
        private val dots: List<View> = (itemView as LinearLayout).let { container ->
            listOf(container.getChildAt(0), container.getChildAt(1), container.getChildAt(2))
        }
        private val animators = mutableListOf<ObjectAnimator>()

        fun bind() {
            if (animators.isNotEmpty()) return
            dots.forEachIndexed { i, dot ->
                val animator = ObjectAnimator.ofPropertyValuesHolder(
                    dot,
                    PropertyValuesHolder.ofFloat("translationY", 0f, -8f, 0f)
                ).apply {
                    duration = 600
                    startDelay = (i * 150).toLong()
                    repeatCount = ObjectAnimator.INFINITE
                }
                animator.start()
                animators.add(animator)
            }
        }

        fun stop() {
            animators.forEach { it.cancel() }
            animators.clear()
            dots.forEach { it.translationY = 0f }
        }
    }

    // ─── AI 块级渲染子适配器 ─────────────────────────────────────────────────────

    private sealed class AiRenderBlock {
        data class Text(val text: String, val placeholderToken: String = "") : AiRenderBlock()
        data class Product(val product: ApiProduct, val placeholderToken: String = "") : AiRenderBlock()
        data class ScenarioEntry(val card: ScenarioCard) : AiRenderBlock()
        data object Typing : AiRenderBlock()
    }

    /**
     * 单个 AI 气泡内部块级适配器。
     *
     * 形态：
     * - Text block：纯文本段
     * - Product block：横向商品卡
     */
    private inner class AiBlockAdapter(
        private val onProductClick: (ApiProduct) -> Unit,
        private val onHorizontalProductClick: (ApiProduct) -> Unit
    ) : RecyclerView.Adapter<RecyclerView.ViewHolder>() {

        // inner class 不能声明 companion object，改为实例常量。
        private val blockTextType = 1
        private val blockProductType = 2
        private val blockScenarioType = 3
        private val blockTypingType = 4

        private var blocks: List<AiRenderBlock> = emptyList()

        fun submitList(list: List<AiRenderBlock>) {
            blocks = list
            notifyDataSetChanged()
        }

        override fun getItemCount(): Int = blocks.size

        override fun getItemViewType(position: Int): Int {
            return when (blocks[position]) {
                is AiRenderBlock.Text -> blockTextType
                is AiRenderBlock.Product -> blockProductType
                is AiRenderBlock.ScenarioEntry -> blockScenarioType
                is AiRenderBlock.Typing -> blockTypingType
            }
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
            return when (viewType) {
                blockTextType -> {
                    val tv = AppCompatTextView(parent.context).apply {
                        layoutParams = RecyclerView.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            ViewGroup.LayoutParams.WRAP_CONTENT
                        )
                        setTextColor(ContextCompat.getColor(context, R.color.colorTextPrimary))
                        setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
                        // 段内行距收紧，避免视觉过散。
                        setLineSpacing(0f, 1.28f)
                    }
                    AiTextBlockVH(tv)
                }

                blockProductType -> {
                    val view = LayoutInflater.from(parent.context)
                        .inflate(R.layout.item_msg_product_horizontal, parent, false)
                    AiProductBlockVH(
                        itemView = view,
                        onProductClick = onProductClick,
                        onHorizontalProductClick = onHorizontalProductClick
                    )
                }

                blockScenarioType -> {
                    val view = LayoutInflater.from(parent.context)
                        .inflate(R.layout.item_scenario_mini_card, parent, false)
                    ScenarioMiniCardBlockVH(
                        itemView = view,
                        onScenarioClick = onScenarioClick
                    )
                }

                blockTypingType -> {
                    val context = parent.context
                    val dotSize = dp(context, 6)
                    val dotGap = dp(context, 4)
                    val verticalPadding = dp(context, 2)

                    val container = LinearLayout(context).apply {
                        layoutParams = RecyclerView.LayoutParams(
                            ViewGroup.LayoutParams.WRAP_CONTENT,
                            ViewGroup.LayoutParams.WRAP_CONTENT
                        )
                        orientation = LinearLayout.HORIZONTAL
                        gravity = Gravity.CENTER_VERTICAL
                        setPadding(0, verticalPadding, 0, verticalPadding)
                    }

                    repeat(3) { index ->
                        val dot = View(context).apply {
                            layoutParams = LinearLayout.LayoutParams(dotSize, dotSize).apply {
                                if (index < 2) marginEnd = dotGap
                            }
                            background = GradientDrawable().apply {
                                shape = GradientDrawable.OVAL
                                setColor(ContextCompat.getColor(context, R.color.colorPrimary))
                            }
                        }
                        container.addView(dot)
                    }
                    AiTypingBlockVH(container)
                }

                else -> throw IllegalArgumentException("Unknown block viewType=$viewType")
            }
        }

        override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
            when (val block = blocks[position]) {
                is AiRenderBlock.Text -> (holder as AiTextBlockVH).bind(block.text)
                is AiRenderBlock.Product -> (holder as AiProductBlockVH).bind(block.product)
                is AiRenderBlock.ScenarioEntry -> (holder as ScenarioMiniCardBlockVH).bind(block.card)
                is AiRenderBlock.Typing -> (holder as AiTypingBlockVH).bind()
            }
            applyBlockSpacing(holder.itemView, position)
        }

        override fun onViewRecycled(holder: RecyclerView.ViewHolder) {
            if (holder is AiTypingBlockVH) {
                holder.stop()
            }
            super.onViewRecycled(holder)
        }

        /** 根据前后块类型设置间距，控制阅读节奏。 */
        private fun applyBlockSpacing(itemView: View, position: Int) {
            val params = itemView.layoutParams as? RecyclerView.LayoutParams
                ?: RecyclerView.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
                )

            val prev = blocks.getOrNull(position - 1)
            val next = blocks.getOrNull(position + 1)
            val current = blocks.getOrNull(position)
            val textBlock = current as? AiRenderBlock.Text
            val isText = textBlock != null
            val isTyping = current is AiRenderBlock.Typing

            val prevProduct = prev as? AiRenderBlock.Product
            val nextProduct = next as? AiRenderBlock.Product
            val samePlaceholderAsPrev =
                textBlock != null &&
                    textBlock.placeholderToken.isNotBlank() &&
                    textBlock.placeholderToken == prevProduct?.placeholderToken
            val samePlaceholderAsNext =
                textBlock != null &&
                    textBlock.placeholderToken.isNotBlank() &&
                    textBlock.placeholderToken == nextProduct?.placeholderToken

            val top = when {
                position == 0 -> 0
                samePlaceholderAsPrev -> dp(itemView, 2)
                prev is AiRenderBlock.Product -> dp(itemView, 8)
                else -> dp(itemView, 4)
            }

            val bottom = when {
                position == blocks.lastIndex -> 0
                isTyping -> 0
                samePlaceholderAsNext -> dp(itemView, 2)
                isText && next is AiRenderBlock.Text -> dp(itemView, 10)
                isText && next is AiRenderBlock.Product -> dp(itemView, 6)
                else -> dp(itemView, 8)
            }
            params.topMargin = top
            params.bottomMargin = bottom
            itemView.layoutParams = params
        }

        private fun dp(itemView: View, value: Int): Int {
            return dp(itemView.context, value)
        }

        private fun dp(context: android.content.Context, value: Int): Int {
            return (value * context.resources.displayMetrics.density).toInt()
        }

    }
}
