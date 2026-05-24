package com.ecomguide.ui.cart

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.ecomguide.databinding.ItemCartBinding
import com.ecomguide.model.CartItem
import com.ecomguide.network.RetrofitClient

/**
 * 购物车列表适配器
 *
 * 使用 ListAdapter + DiffUtil 实现高效差量更新：
 *   - areItemsTheSame：按 productId 判断是否同一商品
 *   - areContentsTheSame：data class == 比较所有字段（包括 qty）
 *
 * 注意：qty 变更必须通过 CartRepository.updateQty() 生成新 CartItem 对象（copy()），
 * 而非就地修改，否则 DiffUtil 检测不到变化导致 UI 不刷新。
 *
 * @param onIncrease  点击"+"回调，由 CartActivity 调用 CartRepository.updateQty(+1)
 * @param onDecrease  点击"-"回调，由 CartActivity 调用 CartRepository.updateQty(-1)
 * @param onItemClick 点击商品卡片回调，跳转至商品详情页
 */
class CartAdapter(
    private val onIncrease: (CartItem) -> Unit,
    private val onDecrease: (CartItem) -> Unit,
    private val onItemClick: (CartItem) -> Unit = {}
) : ListAdapter<CartItem, CartAdapter.VH>(DIFF) {

    companion object {
        private val DIFF = object : DiffUtil.ItemCallback<CartItem>() {
            override fun areItemsTheSame(a: CartItem, b: CartItem) = a.productId == b.productId
            override fun areContentsTheSame(a: CartItem, b: CartItem) = a == b
        }
    }

    inner class VH(val b: ItemCartBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(item: CartItem) {
            b.tvCartName.text = item.title
            b.tvCartSku.text = item.skuLabel
            b.tvCartPrice.text = "¥${formatPrice(item.price)}"
            b.tvQty.text = item.qty.toString()

            val primaryUrl = item.imageUrl?.let {
                if (it.startsWith("http")) it else "${RetrofitClient.BASE_URL.trimEnd('/')}$it"
            }
            val fallbackUrl = "https://picsum.photos/seed/${item.productId}/400/400"
            val req = Glide.with(b.root.context)
            if (primaryUrl != null) {
                req.load(primaryUrl).error(req.load(fallbackUrl))
                    .centerCrop().placeholder(android.R.color.darker_gray).into(b.ivCartImg)
            } else {
                req.load(fallbackUrl).centerCrop()
                    .placeholder(android.R.color.darker_gray).into(b.ivCartImg)
            }

            b.btnIncrease.setOnClickListener { onIncrease(item) }
            b.btnDecrease.setOnClickListener { onDecrease(item) }

            // 点击商品图片或名称跳转详情页
            b.ivCartImg.setOnClickListener { onItemClick(item) }
            b.tvCartName.setOnClickListener { onItemClick(item) }
            b.root.setOnClickListener { onItemClick(item) }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
        VH(ItemCartBinding.inflate(LayoutInflater.from(parent.context), parent, false))

    override fun onBindViewHolder(holder: VH, position: Int) = holder.bind(getItem(position))

    private fun formatPrice(price: Double): String =
        if (price == price.toLong().toDouble()) price.toLong().toString()
        else "%.2f".format(price)
}
