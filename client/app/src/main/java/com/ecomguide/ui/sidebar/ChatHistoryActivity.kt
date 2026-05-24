package com.ecomguide.ui.sidebar

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.ecomguide.R
import com.ecomguide.databinding.ActivityChatHistoryBinding
import com.ecomguide.databinding.ItemHistoryBinding

class ChatHistoryActivity : AppCompatActivity() {

    private lateinit var b: ActivityChatHistoryBinding

    data class HistoryItem(val icon: String, val title: String, val preview: String, val time: String)

    /** 模拟历史对话数据（参考 HTML 原型） */
    private val mockHistory = listOf(
        HistoryItem("💄", "护肤精华推荐", "为你推荐了小棕瓶、红腰子、小黑瓶三款经典精华…", "今天"),
        HistoryItem("🎧", "降噪耳机选购", "对比了华为 FreeBuds Pro 5 和 AirPods Pro 3 的降噪…", "昨天"),
        HistoryItem("👟", "轻量跑鞋推荐", "Nike Air Zoom Pegasus 41 是日常训练的好选择…", "3天前"),
        HistoryItem("☀️", "防晒产品选择", "帮你筛选了不含酒精的物理防晒产品…", "上周"),
        HistoryItem("🛍️", "夏季穿搭建议", "从防晒到穿搭，帮你搭配了一套完整方案…", "上周"),
        HistoryItem("📱", "手机推荐", "对比了 iPhone 17 Pro 和华为 Pura 90 Pro 的拍照…", "2周前"),
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityChatHistoryBinding.inflate(layoutInflater)
        setContentView(b.root)

        b.btnBack.setOnClickListener { finish() }

        b.rvHistory.apply {
            layoutManager = LinearLayoutManager(this@ChatHistoryActivity)
            adapter = HistoryAdapter(mockHistory)
        }
    }

    inner class HistoryAdapter(private val items: List<HistoryItem>) :
        RecyclerView.Adapter<HistoryAdapter.VH>() {

        inner class VH(val b: ItemHistoryBinding) : RecyclerView.ViewHolder(b.root) {
            fun bind(item: HistoryItem) {
                b.tvIcon.text = item.icon
                b.tvTitle.text = item.title
                b.tvPreview.text = item.preview
                b.tvTime.text = item.time
                b.root.setOnClickListener {
                    // 返回主界面并恢复该对话（传入标题作为查询触发词）
                    val intent = Intent().apply { putExtra("load_history", item.title) }
                    setResult(RESULT_OK, intent)
                    finish()
                }
            }
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
            VH(ItemHistoryBinding.inflate(LayoutInflater.from(parent.context), parent, false))

        override fun onBindViewHolder(holder: VH, position: Int) = holder.bind(items[position])
        override fun getItemCount() = items.size
    }
}
