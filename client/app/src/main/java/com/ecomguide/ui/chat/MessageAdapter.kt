package com.ecomguide.ui.chat

import android.animation.ObjectAnimator
import android.animation.PropertyValuesHolder
import android.view.animation.AccelerateDecelerateInterpolator
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.ecomguide.R
import com.ecomguide.databinding.ItemMsgAiBinding
import com.ecomguide.databinding.ItemMsgFollowTagsBinding
import com.ecomguide.databinding.ItemMsgProductsBinding
import com.ecomguide.databinding.ItemMsgTypingBinding
import com.ecomguide.databinding.ItemMsgUserBinding
import com.ecomguide.model.ApiProduct
import com.ecomguide.model.MessageItem
import com.google.android.material.chip.Chip

class MessageAdapter(
    private val onProductClick: (ApiProduct) -> Unit,
    private val onAddToCart: (ApiProduct) -> Unit,
    private val onTagClick: (String) -> Unit
) : RecyclerView.Adapter<RecyclerView.ViewHolder>() {

    companion object {
        private const val TYPE_USER = 1
        private const val TYPE_AI = 2
        private const val TYPE_TYPING = 3
        private const val TYPE_PRODUCTS = 4
        private const val TYPE_FOLLOW_TAGS = 5
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
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
        val inflater = LayoutInflater.from(parent.context)
        return when (viewType) {
            TYPE_USER -> UserVH(ItemMsgUserBinding.inflate(inflater, parent, false))
            TYPE_AI -> AiVH(ItemMsgAiBinding.inflate(inflater, parent, false))
            TYPE_TYPING -> TypingVH(ItemMsgTypingBinding.inflate(inflater, parent, false))
            TYPE_PRODUCTS -> ProductsVH(ItemMsgProductsBinding.inflate(inflater, parent, false))
            else -> FollowTagsVH(ItemMsgFollowTagsBinding.inflate(inflater, parent, false))
        }
    }

    override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
        when (val item = messageItems[position]) {
            is MessageItem.UserMsg -> (holder as UserVH).bind(item)
            is MessageItem.AiMsg -> (holder as AiVH).bind(item)
            is MessageItem.Typing -> (holder as TypingVH).startAnimation()
            is MessageItem.ProductCards -> (holder as ProductsVH).bind(item.products)
            is MessageItem.FollowTags -> (holder as FollowTagsVH).bind(item.tags)
        }
    }

    // ── ViewHolders ────────────────────────────────────────────────────────────
    inner class UserVH(val b: ItemMsgUserBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(item: MessageItem.UserMsg) { b.tvText.text = item.text }
    }

    inner class AiVH(val b: ItemMsgAiBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(item: MessageItem.AiMsg) {
            b.tvText.text = item.text
        }
    }

    inner class TypingVH(val b: ItemMsgTypingBinding) : RecyclerView.ViewHolder(b.root) {
        private val dots = listOf(b.dot1, b.dot2, b.dot3)
        fun startAnimation() {
            dots.forEachIndexed { i, dot ->
                val anim = ObjectAnimator.ofPropertyValuesHolder(
                    dot,
                    PropertyValuesHolder.ofFloat("translationY", 0f, -8f, 0f)
                ).apply {
                    duration = 600
                    startDelay = (i * 150).toLong()
                    repeatCount = ObjectAnimator.INFINITE
                }
                anim.start()
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
}
