package com.ecomguide.ui.detail

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.bumptech.glide.Glide
import com.ecomguide.R
import com.ecomguide.databinding.ActivityProductDetailHalfBinding
import com.ecomguide.model.ApiProduct
import com.ecomguide.model.SkuOption
import com.ecomguide.model.parcelableExtraCompat
import com.ecomguide.model.toPriceText
import com.ecomguide.network.RetrofitClient
import com.ecomguide.repository.CartRepository
import com.google.android.material.chip.Chip
import kotlinx.coroutines.launch

/**
 * 半屏商品详情页 — 从聊天横向卡片点击后底部滑出
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
    private var skuOptions: List<SkuOption> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityProductDetailHalfBinding.inflate(layoutInflater)
        setContentView(b.root)

        product = intent.parcelableExtraCompat(EXTRA_PRODUCT)

        if (product == null) { finish(); return }

        setupToolbar()
        bindData()
        setupSkus()
        setupActions()
        fetchAllSkus()
        fetchRagKnowledge()
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

        // 大图统一使用共享加载策略，减少页面内重复拼接 URL 逻辑。
        val imageSource = RetrofitClient.resolveProductImageSource(product!!)
        val loadUrl = imageSource.displayUrl
        if (loadUrl != null) {
            Glide.with(this)
                .load(loadUrl)
                .error(Glide.with(this).load(imageSource.errorUrl))
                .centerCrop()
                .placeholder(android.R.color.darker_gray)
                .into(b.ivProductImage)
        } else {
            b.ivProductImage.setImageResource(android.R.color.darker_gray)
        }

        // 价格
        b.tvPrice.text = product!!.resolvedPrice.toPriceText()

        // 介绍
        b.tvDescription.text = product!!.ragKnowledge?.marketingDescription
            ?: product!!.description

        // 库存状态
        updateStockStatus()
    }

    private fun setupSkus() {
        skuOptions = product?.skus ?: emptyList()
        renderSkus(skuOptions)
    }

    private fun renderSkus(skus: List<SkuOption>) {
        b.cgSkus.removeAllViews()
        skus.forEachIndexed { i, sku ->
            val chip = Chip(this).apply {
                text = sku.label.ifBlank { sku.price.toPriceText() }
                isCheckable = true
                isChecked = i == selectedSkuIndex
                setEnsureMinTouchTargetSize(false)
                setChipBackgroundColorResource(if (i == selectedSkuIndex) R.color.colorAccentBg else R.color.colorSurface)
                setChipStrokeColorResource(R.color.colorPrimary)
                chipStrokeWidth = 1f
                setTextColor(getColor(if (i == selectedSkuIndex) R.color.colorPrimary else R.color.colorTextPrimary))
                shapeAppearanceModel = shapeAppearanceModel.withCornerSize(10f)
                setOnClickListener {
                    selectedSkuIndex = i
                    b.tvPrice.text = sku.price.toPriceText()
                    updateStockStatus()
                    renderSkus(skus)
                }
            }
            b.cgSkus.addView(chip)
        }
        b.cgSkus.visibility = if (skus.isNotEmpty()) View.VISIBLE else View.GONE
    }

    private fun fetchAllSkus() {
        val productId = product?.resolvedId.orEmpty()
        if (productId.isBlank()) return
        lifecycleScope.launch {
            runCatching {
                RetrofitClient.api.getAllSkus(productId)
            }.onSuccess { response ->
                if (response.skus.isNotEmpty()) {
                    skuOptions = response.skus
                    selectedSkuIndex = 0
                    b.tvPrice.text = skuOptions.first().price.toPriceText()
                    renderSkus(skuOptions)
                    updateStockStatus()
                }
            }
        }
    }

    private fun fetchRagKnowledge() {
        val productId = product?.resolvedId.orEmpty()
        if (productId.isBlank()) return
        lifecycleScope.launch {
            runCatching {
                RetrofitClient.api.getProductReview(productId)
            }.onSuccess { response ->
                val rk = response.ragKnowledge ?: return@onSuccess
                val current = product ?: return@onSuccess
                val merged = current.copy(ragKnowledge = rk)
                product = merged
                b.tvDescription.text = rk.marketingDescription ?: merged.description
            }
        }
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
        val selectedSku = skuOptions.getOrNull(selectedSkuIndex)
        val skuLabel = selectedSku?.label ?: p.skus.getOrNull(selectedSkuIndex)?.label.orEmpty()
        CartRepository.add(p, skuLabel, quantity)
        Toast.makeText(this, "✅ 已加入购物车", Toast.LENGTH_SHORT).show()
        setResult(RESULT_OK)
        finish()
    }

    private fun updateStockStatus() {
        val selectedSkuStock = skuOptions.getOrNull(selectedSkuIndex)?.stock
        val stock = selectedSkuStock ?: product?.stock
        b.tvStockStatus.text = when {
            stock == null -> ""
            stock > 0 -> "有货"
            stock == 0 -> "缺货"
            else -> ""
        }
        b.tvStockStatus.visibility = if (b.tvStockStatus.text.isBlank()) View.GONE else View.VISIBLE
    }

}
