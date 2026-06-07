package com.ecomguide.ui.detail

import android.os.Bundle
import android.view.View
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.bumptech.glide.Glide
import com.ecomguide.R
import com.ecomguide.databinding.ActivityProductDetailBinding
import com.ecomguide.model.ApiProduct
import com.ecomguide.model.FaqItem
import com.ecomguide.model.RagKnowledge
import com.ecomguide.model.SkuOption
import com.ecomguide.model.UserReview
import com.ecomguide.model.averageRating
import com.ecomguide.model.parcelableExtraCompat
import com.ecomguide.model.toPriceText
import com.ecomguide.network.RetrofitClient
import com.ecomguide.ui.cart.CartActivity
import com.ecomguide.ui.detail.HalfScreenProductDetailActivity
import com.google.android.material.chip.Chip
import kotlinx.coroutines.launch

class ProductDetailActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_PRODUCT = "extra_product"
    }

    private lateinit var b: ActivityProductDetailBinding
    private var product: ApiProduct? = null
    private var selectedSkuIndex: Int = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityProductDetailBinding.inflate(layoutInflater)
        setContentView(b.root)

        product = intent.parcelableExtraCompat(EXTRA_PRODUCT)
        product?.let { renderProduct(it) } ?: finish()

        // 使用 onBackPressedDispatcher 替代已废弃 onBackPressed()。
        b.btnBack.setOnClickListener { onBackPressedDispatcher.onBackPressed() }
        b.btnDetailCart.setOnClickListener {
            startActivity(android.content.Intent(this, CartActivity::class.java))
        }
        // 全屏详情页底部“加入购物车”改为进入半屏加入购物车页
        b.btnAddToCart.setOnClickListener {
            product?.let { p -> HalfScreenProductDetailActivity.start(this, p) }
        }
        b.btnBuyNow.setOnClickListener {
            product?.let { p -> HalfScreenProductDetailActivity.start(this, p) }
        }

        product?.let { p ->
            fetchFullDetails(p.resolvedId)
            fetchRagKnowledge(p.resolvedId)
        }
    }

    private fun renderProduct(p: ApiProduct) {
        // 商品图统一走 RetrofitClient 的优先级策略，避免各页面重复拼接。
        val imageSource = RetrofitClient.resolveProductImageSource(p)
        val loadUrl = imageSource.displayUrl
        if (loadUrl != null) {
            Glide.with(this)
                .load(loadUrl)
                .error(Glide.with(this).load(imageSource.errorUrl))
                .centerCrop()
                .placeholder(android.R.color.darker_gray)
                .into(b.ivDetailImage)
        } else {
            b.ivDetailImage.setImageResource(android.R.color.darker_gray)
        }

        // Price
        b.tvDetailPrice.text = p.resolvedPrice.toPriceText()

        // Title
        b.tvDetailTitle.text = p.resolvedTitle

        // Meta tags
        b.tvDetailBrand.text = p.brand
        b.tvDetailSubCat.text = p.subCategory

        // Rating from reviews
        val rk = p.ragKnowledge
        val avg = p.averageRating()
        b.tvDetailRating.text = if (avg != null) "⭐ ${"%.1f".format(avg)}" else ""

        // SKUs
        renderSkus(p.skus)

        // Description
        b.tvIntro.text = rk?.marketingDescription ?: p.description

        // Basic info
        renderBasicInfo(p)

        // FAQ & Reviews (if already loaded)
        rk?.let { renderRagKnowledge(it) }
    }

    private fun renderSkus(skus: List<SkuOption>) {
        b.cgSkus.removeAllViews()
        skus.forEachIndexed { i, sku ->
            val chip = Chip(this).apply {
                text = sku.label.ifBlank { sku.price.toPriceText() }
                isCheckable = true
                isChecked = i == selectedSkuIndex
                setOnCheckedChangeListener { _, checked -> if (checked) selectedSkuIndex = i }
            }
            b.cgSkus.addView(chip)
        }
    }

    private fun renderBasicInfo(p: ApiProduct) {
        b.llBasicInfo.removeAllViews()
        listOf("品牌" to p.brand, "类别" to p.category, "细分" to p.subCategory)
            .filter { it.second.isNotBlank() }
            .forEach { (label, value) ->
                addInfoRow(label, value)
            }
    }

    private fun addInfoRow(label: String, value: String) {
        val row = layoutInflater.inflate(R.layout.item_info_row, b.llBasicInfo, false)
        row.findViewById<TextView>(R.id.tvLabel)?.text = label
        row.findViewById<TextView>(R.id.tvValue)?.text = value
        b.llBasicInfo.addView(row)
    }

    private fun renderRagKnowledge(rk: RagKnowledge) {
        // FAQ
        if (rk.officialFaq.isNotEmpty()) {
            b.cardFaq.visibility = View.VISIBLE
            b.llFaq.removeAllViews()
            rk.officialFaq.forEach { faq -> addFaqItem(faq) }
        }

        // Reviews
        if (rk.userReviews.isNotEmpty()) {
            b.cardReviews.visibility = View.VISIBLE
            b.llReviews.removeAllViews()
            val avg = rk.averageRating() ?: return
            b.tvAvgRating.text = "%.1f".format(avg)
            b.tvReviewCount.text = getString(R.string.reviews_count, rk.userReviews.size)
            // Star bar
            b.llStars.removeAllViews()
            repeat(5) { i ->
                val star = TextView(this).apply {
                    text = "★"
                    textSize = 12f
                    setTextColor(
                        if (i < avg.toInt()) getColor(R.color.colorStarFilled)
                        else getColor(R.color.colorStarEmpty)
                    )
                }
                b.llStars.addView(star)
            }
            rk.userReviews.forEach { review -> addReviewItem(review) }
        }
    }

    private fun addFaqItem(faq: FaqItem) {
        val view = layoutInflater.inflate(R.layout.item_faq, b.llFaq, false)
        view.findViewById<TextView>(R.id.tvQuestion)?.text = faq.question
        view.findViewById<TextView>(R.id.tvAnswer)?.text = faq.answer
        b.llFaq.addView(view)
    }

    private fun addReviewItem(review: UserReview) {
        val view = layoutInflater.inflate(R.layout.item_review, b.llReviews, false)
        view.findViewById<TextView>(R.id.tvNickname)?.text = "👤 ${review.nickname}"
        view.findViewById<TextView>(R.id.tvContent)?.text = review.content
        val llStars = view.findViewById<android.widget.LinearLayout>(R.id.llStars)
        llStars?.removeAllViews()
        repeat(5) { i ->
            val star = TextView(this).apply {
                text = "★"
                textSize = 11f
                setTextColor(
                    if (i < review.rating) getColor(R.color.colorStarFilled)
                    else getColor(R.color.colorStarEmpty)
                )
            }
            llStars?.addView(star)
        }
        b.llReviews.addView(view)
    }

    private fun fetchFullDetails(productId: String) {
        if (productId.isBlank()) return
        lifecycleScope.launch {
            runCatching {
                RetrofitClient.api.getProduct(productId)
            }.onSuccess { full ->
                val merged = full.copy(
                    imageUrl = full.imageUrl ?: product?.imageUrl,
                    imagePath = full.imagePath ?: product?.imagePath,
                    img = full.img ?: product?.img,
                    ragKnowledge = full.ragKnowledge ?: product?.ragKnowledge
                )
                product = merged
                renderProduct(merged)
            }
        }
    }

    private fun fetchRagKnowledge(productId: String) {
        if (productId.isBlank()) return
        lifecycleScope.launch {
            runCatching {
                RetrofitClient.api.getProductReview(productId)
            }.onSuccess { response ->
                val rk = response.ragKnowledge ?: return@onSuccess
                val current = product ?: return@onSuccess
                val merged = current.copy(ragKnowledge = rk)
                product = merged
                renderProduct(merged)
            }
        }
    }

}

