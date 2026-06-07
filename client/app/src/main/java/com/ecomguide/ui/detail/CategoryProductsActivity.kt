package com.ecomguide.ui.detail

import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.os.Build
import android.os.Bundle
import android.util.TypedValue
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.ecomguide.R
import com.ecomguide.databinding.ActivityCategoryProductsBinding
import com.ecomguide.model.ApiProduct
import com.ecomguide.model.ScenarioCard
import com.ecomguide.repository.CartRepository
import com.google.android.material.chip.Chip

/**
 * 品类商品落地页 — 场景推荐卡片点击后跳转的商品列表页（参考图2）
 *
 * 功能：
 *   - 顶部标题栏显示场景名称（如"连衣裙"）
 *   - Tab 筛选栏支持子场景切换（全部 / 春游法式 / 春季不规则 ...）
 *   - 双列瀑布流展示商品卡片（复用 item_product_card.xml 样式）
 *   - 点击商品 → 跳转 ProductDetailActivity
 *   - 加购 → 加入购物车
 */
class CategoryProductsActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_SCENARIO_CARD = "extra_scenario_card"

        fun start(context: Context, card: ScenarioCard) {
            val intent = Intent(context, CategoryProductsActivity::class.java).apply {
                putExtra(EXTRA_SCENARIO_CARD, card)
            }
            context.startActivity(intent)
        }
    }

    private lateinit var b: ActivityCategoryProductsBinding
    private lateinit var scenarioCard: ScenarioCard
    private lateinit var categoryAdapter: CategoryProductAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityCategoryProductsBinding.inflate(layoutInflater)
        setContentView(b.root)

        @Suppress("DEPRECATION")
        scenarioCard = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(EXTRA_SCENARIO_CARD, ScenarioCard::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(EXTRA_SCENARIO_CARD)
        } ?: run { finish(); return }

        setupToolbar()
        setupProductGrid()
    }

    // ─── Toolbar ──────────────────────────────────────────────────────────────

    private fun setupToolbar() {
        b.tvCategoryTitle.text = scenarioCard.scenarioName
        b.btnBack.setOnClickListener { finish() }
    }

    // ─── 商品网格 ─────────────────────────────────────────────────────────────

    private fun setupProductGrid() {
        categoryAdapter = CategoryProductAdapter(
            products = scenarioCard.products,
            onProductClick = { product ->
                startActivity(Intent(this, ProductDetailActivity::class.java).apply {
                    putExtra(ProductDetailActivity.EXTRA_PRODUCT, product)
                })
            },
            onAddToCart = { product ->
                CartRepository.add(product)
                Toast.makeText(this, "✅ 已加入购物车", Toast.LENGTH_SHORT).show()
            }
        )

        b.rvCategoryProducts.apply {
            layoutManager = GridLayoutManager(this@CategoryProductsActivity, 2)
            adapter = categoryAdapter
            itemAnimator = null
        }
    }

    // ─── 工具方法 ─────────────────────────────────────────────────────────────

    private fun dpToPx(dp: Int): Float =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, dp.toFloat(), resources.displayMetrics)

    // ════════════════════════════════════════════════════════════════════════════
    //  内部 Adapter — 双列商品卡片（复用 item_product_card.xml 样式）
    // ════════════════════════════════════════════════════════════════════════════

    private class CategoryProductAdapter(
        private val products: List<ApiProduct>,
        private val onProductClick: (ApiProduct) -> Unit,
        private val onAddToCart: (ApiProduct) -> Unit
    ) : RecyclerView.Adapter<CategoryProductAdapter.VH>() {

        override fun getItemCount(): Int = products.size

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
            // 落地页使用更宽的横向卡片布局
            val view = LayoutInflater.from(parent.context)
                .inflate(R.layout.item_product_card_wide, parent, false)
            return VH(view)
        }

        override fun onBindViewHolder(holder: VH, position: Int) {
            holder.bind(products[position])
        }

        inner class VH(itemView: View) : RecyclerView.ViewHolder(itemView) {
            // 通过 findViewById 绑定（因为使用 inflate 而非 Binding，避免 ViewStub 冲突）
            private val ivProduct: android.widget.ImageView = itemView.findViewById(R.id.ivProduct)
            private val tvName: TextView = itemView.findViewById(R.id.tvName)
            private val tvPrice: TextView = itemView.findViewById(R.id.tvPrice)
            private val tvRating: TextView = itemView.findViewById(R.id.tvRating)
            private val tvHotLabel: TextView = itemView.findViewById(R.id.tvHotLabel)
            private val btnAddCart: TextView = itemView.findViewById(R.id.btnAddCart)

            fun bind(product: ApiProduct) {
                tvName.text = product.resolvedTitle
                tvPrice.text = formatPrice(product.resolvedPrice)

                // Hot badge：每个都隐藏（落地页不需要爆款角标）
                tvHotLabel.visibility = View.GONE

                // Rating
                val avgRating = product.ragKnowledge?.userReviews?.let { reviews ->
                    if (reviews.isEmpty()) null
                    else reviews.sumOf { it.rating }.toFloat() / reviews.size
                }
                tvRating.text = if (avgRating != null) "⭐ ${"%.1f".format(avgRating)}" else ""

                // Image
                val primaryUrl = com.ecomguide.network.RetrofitClient.resolveImageUrl(product.resolvedImageUrl)
                val endpointUrl = com.ecomguide.network.RetrofitClient.productImageUrl(product.resolvedId)
                val fallbackUrl = com.ecomguide.network.RetrofitClient.resolveImageUrl(product.img)
                val loadUrl = primaryUrl ?: endpointUrl ?: fallbackUrl
                if (loadUrl != null) {
                    val req = Glide.with(itemView.context)
                    when {
                        primaryUrl != null -> req.load(primaryUrl)
                            .error(req.load(endpointUrl ?: fallbackUrl))
                            .centerCrop()
                            .placeholder(android.R.color.darker_gray)
                            .into(ivProduct)

                        endpointUrl != null -> req.load(endpointUrl)
                            .error(req.load(fallbackUrl))
                            .centerCrop()
                            .placeholder(android.R.color.darker_gray)
                            .into(ivProduct)

                        else -> req.load(loadUrl).centerCrop()
                            .placeholder(android.R.color.darker_gray)
                            .into(ivProduct)
                    }
                } else {
                    ivProduct.setImageResource(android.R.color.darker_gray)
                }

                itemView.setOnClickListener { onProductClick(product) }
                btnAddCart.setOnClickListener { onAddToCart(product) }
            }

            private fun formatPrice(price: Double): String =
                if (price == price.toLong().toDouble()) "¥${price.toLong()}"
                else "¥${"%.2f".format(price)}"

        }
    }
}
