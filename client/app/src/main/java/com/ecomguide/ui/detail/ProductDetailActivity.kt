package com.ecomguide.ui.detail

import android.os.Bundle
import android.view.View
import android.widget.TextView
import android.widget.Toast
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
import com.ecomguide.network.RetrofitClient
import com.ecomguide.repository.CartRepository
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

        product = intent.getParcelableExtra(EXTRA_PRODUCT)
        product?.let { renderProduct(it) } ?: finish()

        b.btnBack.setOnClickListener { onBackPressed() }
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

        // Fetch full product details (FAQ + reviews) from API
        product?.let { fetchFullDetails(it.resolvedId) }
    }

    private fun renderProduct(p: ApiProduct) {
        // Image：优先本地 API（data_api.py），失败时 fallback 到 picsum
        val primaryUrl = resolveImageUrl(p.imageUrl)
        val fallbackUrl = p.img
        val loadUrl = primaryUrl ?: fallbackUrl
        if (loadUrl != null) {
            val req = Glide.with(this)
            if (primaryUrl != null && fallbackUrl != null) {
                req.load(primaryUrl).error(req.load(fallbackUrl))
                    .centerCrop().placeholder(android.R.color.darker_gray)
                    .into(b.ivDetailImage)
            } else {
                req.load(loadUrl).centerCrop()
                    .placeholder(android.R.color.darker_gray).into(b.ivDetailImage)
            }
        }

        // Price
        b.tvDetailPrice.text = "¥${formatPrice(p.resolvedPrice)}"

        // Title
        b.tvDetailTitle.text = p.resolvedTitle

        // Meta tags
        b.tvDetailBrand.text = p.brand
        b.tvDetailSubCat.text = p.subCategory

        // Rating from reviews
        val rk = p.ragKnowledge
        val reviews = rk?.userReviews ?: emptyList()
        val avg = if (reviews.isNotEmpty()) reviews.sumOf { it.rating }.toFloat() / reviews.size else null
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
                text = sku.label.ifBlank { "¥${formatPrice(sku.price)}" }
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
            val avg = rk.userReviews.sumOf { it.rating }.toFloat() / rk.userReviews.size
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
                product = full
                full.ragKnowledge?.let { renderRagKnowledge(it) }
                renderSkus(full.skus)
                b.tvDetailPrice.text = "¥${formatPrice(full.resolvedPrice)}"
                b.tvDetailTitle.text = full.resolvedTitle
                b.tvIntro.text = full.ragKnowledge?.marketingDescription ?: full.description
                renderBasicInfo(full)
            }
        }
    }

    private fun addToCart() {
        val p = product ?: return
        val skuLabel = p.skus.getOrNull(selectedSkuIndex)?.label ?: ""
        CartRepository.add(p, skuLabel)
        Toast.makeText(this, getString(R.string.toast_added_cart), Toast.LENGTH_SHORT).show()
    }

    private fun resolveImageUrl(url: String?): String? {
        if (url == null) return null
        return if (url.startsWith("http")) url
        else "${RetrofitClient.BASE_URL.trimEnd('/')}$url"
    }

    private fun formatPrice(price: Double): String =
        if (price == price.toLong().toDouble()) price.toLong().toString()
        else "%.2f".format(price)
}

