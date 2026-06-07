package com.ecomguide.ui.chat

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.ecomguide.databinding.ItemProductCardBinding
import com.ecomguide.model.ApiProduct
import com.ecomguide.model.averageRating
import com.ecomguide.model.toPriceText
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
            b.tvPrice.text = product.resolvedPrice.toPriceText()

            // Hot badge for first card
            b.tvHotLabel.visibility = if (isFirst) android.view.View.VISIBLE else android.view.View.GONE

            // Rating (computed from reviews if available)
            val avgRating = product.averageRating()
            b.tvRating.text = if (avgRating != null) "⭐ ${"%.1f".format(avgRating)}" else ""

            // 图片加载使用共享策略，避免在多个商品卡里重复拼 URL 规则。
            val imageSource = RetrofitClient.resolveProductImageSource(product)
            val loadUrl = imageSource.displayUrl
            if (loadUrl != null) {
                Glide.with(b.root.context)
                    .load(loadUrl)
                    .error(Glide.with(b.root.context).load(imageSource.errorUrl))
                    .centerCrop()
                    .placeholder(android.R.color.darker_gray)
                    .into(b.ivProduct)
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
