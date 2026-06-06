package com.ecomguide.ui.detail

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.bumptech.glide.Glide
import com.ecomguide.R
import com.ecomguide.databinding.ActivityProductDetailHalfBinding
import com.ecomguide.model.ApiProduct
import com.ecomguide.repository.CartRepository
import com.google.android.material.chip.Chip

/**
 * 半屏商品详情页 — 从聊天横向卡片点击后底部滑出（参考图1）
 *
 * 布局（从上到下）：
 *   - 标题栏：返回 + 标题 + 关闭
 *   - 地址输入框
 *   - 商品大图
 *   - 价格 + 数量选择器（- / 数字 / +）
 *   SKU 选择 ChipGroup
 *   - 商品介绍文本
 *   - 底部加入购物车按钮（固定）
 */
class HalfScreenProductDetailActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_PRODUCT = "extra_product"

        fun start(context: AppCompatActivity, product: ApiProduct) {
            val intent = Intent(context, HalfScreenProductDetailActivity::class.java).apply {
                putExtra(EXTRA_PRODUCT, product)
            }
            context.startActivity(intent)
        }
    }

    private lateinit var b: ActivityProductDetailHalfBinding
    private var product: ApiProduct? = null
    private var selectedSkuIndex: Int = 0
    private var quantity: Int = 1

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityProductDetailHalfBinding.inflate(layoutInflater)
        setContentView(b.root)

        @Suppress("DEPRECATION")
        product = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(EXTRA_PRODUCT, ApiProduct::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(EXTRA_PRODUCT)
        }

        if (product == null) { finish(); return }

        setupToolbar()
        bindData()
        setupSkus()
        setupActions()
    }

    // ─── Toolbar ──────────────────────────────────────────────────────────────

    private fun setupToolbar() {
        b.btnBack.setOnClickListener { finish() }
        b.btnClose.setOnClickListener { finish() }
        // 按设计要求：半屏页顶部不展示商品标题
        b.tvTitle.visibility = View.GONE
    }

    // ─── 数据绑定 ───────────────────────────────────────────────────────────────

    private fun bindData() {
        if (product == null) return

        // 大图
        val primaryUrl = com.ecomguide.network.RetrofitClient.resolveImageUrl(product!!.resolvedImageUrl)
        val endpointUrl = com.ecomguide.network.RetrofitClient.productImageUrl(product!!.resolvedId)
        val fallbackUrl = com.ecomguide.network.RetrofitClient.resolveImageUrl(product!!.img)
        val loadUrl = primaryUrl ?: endpointUrl ?: fallbackUrl
        if (loadUrl != null) {
            Glide.with(this)
                .load(loadUrl)
                .error(Glide.with(this).load(endpointUrl ?: fallbackUrl))
                .centerCrop()
                .placeholder(android.R.color.darker_gray)
                .into(b.ivProductImage)
        } else {
            b.ivProductImage.setImageResource(android.R.color.darker_gray)
        }

        // 价格
        b.tvPrice.text = formatPrice(product!!.resolvedPrice)

        // 介绍
        b.tvDescription.text = product!!.ragKnowledge?.marketingDescription
            ?: product!!.description

        // 库存状态
        updateStockStatus()
    }

    private fun setupSkus() {
        renderSkus(product?.skus ?: emptyList())
    }

    private fun renderSkus(skus: List<com.ecomguide.model.SkuOption>) {
        b.cgSkus.removeAllViews()
        skus.forEachIndexed { i, sku ->
            val chip = Chip(this).apply {
                text = sku.label.ifBlank { "¥${formatPrice(sku.price)}" }
                isCheckable = true
                isChecked = i == selectedSkuIndex
                setOnCheckedChangeListener { _, _ -> selectedSkuIndex = i }
            }
            b.cgSkus.addView(chip)
        }
        b.cgSkus.visibility = if (skus.isNotEmpty()) View.VISIBLE else View.GONE
    }

    // ─── 操作事件 ──────────────────────────────────────────────────────────────

    private fun setupActions() {
        b.btnAddToCart.setOnClickListener { addToCart() }

        b.btnMinus.setOnClickListener {
            if (quantity > 1) {
                quantity--
                b.tvQuantity.text = quantity.toString()
            }
        }
        b.btnPlus.setOnClickListener {
            quantity++
            b.tvQuantity.text = quantity.toString()
        }
    }

    private fun addToCart() {
        val p = product ?: return
        CartRepository.add(p, p.skus.getOrNull(selectedSkuIndex)?.label ?: "", quantity)
        Toast.makeText(this, "✅ 已加入购物车", Toast.LENGTH_SHORT).show()
        setResult(RESULT_OK)
        finish()
    }

    private fun updateStockStatus() {
        val stock = product?.stock ?: 0
        b.tvStockStatus.text = when {
            stock > 0 -> "有货"
            stock == 0 -> "缺货"
            else -> ""
        }
        b.tvStockStatus.visibility = if (b.tvStockStatus.text.isBlank()) View.GONE else View.VISIBLE
    }

    // ─── 工具方法 ──────────────────────────────────────────────────────────────

    private fun formatPrice(price: Double): String =
        if (price == price.toLong().toDouble()) "¥${price.toLong()}"
        else "¥${"%.2f".format(price)}"
}
