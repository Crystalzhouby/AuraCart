package com.ecomguide.ui.sidebar

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.ecomguide.databinding.ActivityChatHistoryBinding
import com.ecomguide.databinding.ItemHistoryBinding
import com.ecomguide.repository.SidebarMockData

class ChatHistoryActivity : AppCompatActivity() {

    private lateinit var b: ActivityChatHistoryBinding

    private val histories = SidebarMockData.histories

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityChatHistoryBinding.inflate(layoutInflater)
        setContentView(b.root)

        b.btnBack.setOnClickListener { finish() }

        b.rvHistory.apply {
            layoutManager = LinearLayoutManager(this@ChatHistoryActivity)
            adapter = HistoryAdapter(histories)
        }
    }

    inner class HistoryAdapter(private val items: List<SidebarMockData.SidebarHistory>) :
        RecyclerView.Adapter<HistoryAdapter.VH>() {

        inner class VH(val b: ItemHistoryBinding) : RecyclerView.ViewHolder(b.root) {
            fun bind(item: SidebarMockData.SidebarHistory) {
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
