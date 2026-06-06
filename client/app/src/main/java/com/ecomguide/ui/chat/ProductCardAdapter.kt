package com.ecomguide.ui.chat

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.ecomguide.databinding.ItemProductCardBinding
import com.ecomguide.model.ApiProduct
import com.ecomguide.network.RetrofitClient

class ProductCardAdapter(
    private val onProductClick: (ApiProduct) -> Unit,
    private val onAddToCart: (ApiProduct) -> Unit
) : ListAdapter<ApiProduct, ProductCardAdapter.VH>(DIFF) {

    companion object {
        private val DIFF = object : DiffUtil.ItemCallback<ApiProduct>() {
            override fun areItemsTheSame(a: ApiProduct, b: ApiProduct) = a.resolvedId == b.resolvedId
            override fun areContentsTheSame(a: ApiProduct, b: ApiProduct) = a == b
        }
    }

    inner class VH(val b: ItemProductCardBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(product: ApiProduct, isFirst: Boolean) {
            b.tvName.text = product.resolvedTitle
            b.tvPrice.text = "¥${product.resolvedPrice.let {
                if (it == it.toLong().toDouble()) it.toLong().toString() else String.format("%.2f", it)
            }}"

            // Hot badge for first card
            b.tvHotLabel.visibility = if (isFirst) android.view.View.VISIBLE else android.view.View.GONE

            // Rating (computed from reviews if available)
            val avgRating = product.ragKnowledge?.userReviews?.let { reviews ->
                if (reviews.isEmpty()) null
                else reviews.sumOf { it.rating }.toFloat() / reviews.size
            }
            b.tvRating.text = if (avgRating != null) "⭐ ${"%.1f".format(avgRating)}" else ""

            // Image：优先商品字段，其次 /api/products/image/{id} 兜底，最后 fallback 图
            val primaryUrl = RetrofitClient.resolveImageUrl(product.resolvedImageUrl)
            val endpointUrl = RetrofitClient.productImageUrl(product.resolvedId)
            val fallbackUrl = RetrofitClient.resolveImageUrl(product.img)
            val loadUrl = primaryUrl ?: endpointUrl ?: fallbackUrl
            if (loadUrl != null) {
                val req = Glide.with(b.root.context)
                when {
                    primaryUrl != null -> req.load(primaryUrl)
                        .error(req.load(endpointUrl ?: fallbackUrl))
                        .centerCrop()
                        .placeholder(android.R.color.darker_gray)
                        .into(b.ivProduct)

                    endpointUrl != null -> req.load(endpointUrl)
                        .error(req.load(fallbackUrl))
                        .centerCrop()
                        .placeholder(android.R.color.darker_gray)
                        .into(b.ivProduct)

                    else -> req.load(loadUrl).centerCrop()
                        .placeholder(android.R.color.darker_gray)
                        .into(b.ivProduct)
                }
            } else {
                b.ivProduct.setImageResource(android.R.color.darker_gray)
            }

            b.root.setOnClickListener { onProductClick(product) }
            b.btnAddCart.setOnClickListener { onAddToCart(product) }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
        VH(ItemProductCardBinding.inflate(LayoutInflater.from(parent.context), parent, false))

    override fun onBindViewHolder(holder: VH, position: Int) =
        holder.bind(getItem(position), position == 0)

}
