package com.ecomguide.ui.sidebar

import android.os.Bundle
import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.ImageView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.bumptech.glide.Glide
import com.ecomguide.R
import com.ecomguide.databinding.ActivityMyOrdersBinding
import com.ecomguide.databinding.ItemOrderBinding

class MyOrdersActivity : AppCompatActivity() {

    private lateinit var b: ActivityMyOrdersBinding

    enum class OrderStatus { DELIVERED, SHIPPING, PROCESSING }

    data class OrderItem(
        val orderId: String,
        val status: OrderStatus,
        val imageUrls: List<String>,
        val itemCount: Int,
        val total: String,
        val actionLabel: String
    )

    private val mockOrders = listOf(
        OrderItem(
            orderId = "#20240521001", status = OrderStatus.DELIVERED,
            imageUrls = listOf(
                "https://picsum.photos/seed/p_beauty_001/80/80",
                "https://picsum.photos/seed/p_beauty_004/80/80"
            ),
            itemCount = 2, total = "¥1,610", actionLabel = "再次购买"
        ),
        OrderItem(
            orderId = "#20240519002", status = OrderStatus.SHIPPING,
            imageUrls = listOf("https://picsum.photos/seed/p_digital_007/80/80"),
            itemCount = 1, total = "¥1,299", actionLabel = "查看物流"
        ),
        OrderItem(
            orderId = "#20240515003", status = OrderStatus.PROCESSING,
            imageUrls = listOf("https://picsum.photos/seed/p_clothes_007/80/80"),
            itemCount = 1, total = "¥899", actionLabel = "催发货"
        ),
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityMyOrdersBinding.inflate(layoutInflater)
        setContentView(b.root)

        b.btnBack.setOnClickListener { finish() }

        b.rvOrders.apply {
            layoutManager = LinearLayoutManager(this@MyOrdersActivity)
            adapter = OrderAdapter(mockOrders)
        }
    }

    inner class OrderAdapter(private val items: List<OrderItem>) :
        RecyclerView.Adapter<OrderAdapter.VH>() {

        inner class VH(val b: ItemOrderBinding) : RecyclerView.ViewHolder(b.root) {
            fun bind(order: OrderItem) {
                b.tvOrderId.text = "订单号 ${order.orderId}"

                // Status badge
                val (label, textColor) = when (order.status) {
                    OrderStatus.DELIVERED  -> Pair("✅ 已签收", 0xFF00A878.toInt())
                    OrderStatus.SHIPPING   -> Pair("🚚 配送中", 0xFF6C5CE7.toInt())
                    OrderStatus.PROCESSING -> Pair("⏳ 待发货", 0xFFB8860B.toInt())
                }
                b.tvStatus.text = label
                b.tvStatus.setTextColor(textColor)
                b.tvStatus.setBackgroundResource(R.drawable.bg_card)

                // Product thumbnails
                b.llImages.removeAllViews()
                val density = b.root.context.resources.displayMetrics.density
                val size = (52 * density).toInt()
                val margin = (8 * density).toInt()
                order.imageUrls.forEach { url ->
                    val img = ImageView(b.root.context).apply {
                        layoutParams = ViewGroup.MarginLayoutParams(size, size).apply {
                            setMargins(0, 0, margin, 0)
                        }
                        scaleType = ImageView.ScaleType.CENTER_CROP
                        setBackgroundColor(0xFFF7F5FF.toInt())
                    }
                    Glide.with(b.root.context).load(url).centerCrop().into(img)
                    b.llImages.addView(img)
                }

                b.tvTotal.text = "共${order.itemCount}件 合计 ${order.total}"
                b.tvAction.text = order.actionLabel
                b.tvAction.setOnClickListener {
                    Toast.makeText(b.root.context, "${order.actionLabel}功能开发中", Toast.LENGTH_SHORT).show()
                }
            }
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
            VH(ItemOrderBinding.inflate(LayoutInflater.from(parent.context), parent, false))

        override fun onBindViewHolder(holder: VH, position: Int) = holder.bind(items[position])
        override fun getItemCount() = items.size
    }
}
