package com.ecomguide.ui.cart

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.ecomguide.databinding.ActivityCartBinding
import com.ecomguide.model.ApiProduct
import com.ecomguide.model.CartItem
import com.ecomguide.model.toPriceText
import com.ecomguide.network.RetrofitClient
import com.ecomguide.repository.CartRepository
import com.ecomguide.ui.detail.ProductDetailActivity
import kotlinx.coroutines.launch

class CartActivity : AppCompatActivity() {

    private lateinit var b: ActivityCartBinding
    private lateinit var cartAdapter: CartAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityCartBinding.inflate(layoutInflater)
        setContentView(b.root)

        b.btnBack.setOnClickListener { finish() }

        cartAdapter = CartAdapter(
            onIncrease = { item -> CartRepository.updateQty(item.productId, +1) },
            onDecrease = { item -> CartRepository.updateQty(item.productId, -1) },
            onItemClick = { item -> openProductDetail(item) }
        )

        b.rvCart.apply {
            adapter = cartAdapter
            layoutManager = LinearLayoutManager(this@CartActivity)
        }

        b.btnCheckout.setOnClickListener {
            CartRepository.clear()
            Toast.makeText(this, "🎉 下单成功！预计3-5天送达", Toast.LENGTH_SHORT).show()
            finish()
        }

        CartRepository.items.observe(this) { items ->
            cartAdapter.submitList(items.toList())
            val isEmpty = items.isEmpty()
            b.layoutEmpty.visibility = if (isEmpty) View.VISIBLE else View.GONE
            b.rvCart.visibility = if (isEmpty) View.GONE else View.VISIBLE
            b.layoutBottom.visibility = if (isEmpty) View.GONE else View.VISIBLE

            if (!isEmpty) {
                val total = CartRepository.total()
                val count = CartRepository.count()
                b.tvTotal.text = total.toPriceText()
                b.btnCheckout.text = "结算($count)"
            }
        }
    }

    /** 点击购物车商品 → 跳转详情页 */
    private fun openProductDetail(item: CartItem) {
        lifecycleScope.launch {
            val product = runCatching {
                RetrofitClient.api.getProduct(item.productId)
            }.getOrElse {
                // API 失败时，用 CartItem 构造最小可展示商品，保证详情页可打开。
                ApiProduct(
                    productId = item.productId,
                    title = item.title,
                    basePrice = item.price,
                    imageUrl = item.imageUrl
                )
            }
            navigateToDetail(product)
        }
    }

    private fun navigateToDetail(product: ApiProduct) {
        startActivity(Intent(this, ProductDetailActivity::class.java).apply {
            putExtra(ProductDetailActivity.EXTRA_PRODUCT, product)
        })
    }

}
