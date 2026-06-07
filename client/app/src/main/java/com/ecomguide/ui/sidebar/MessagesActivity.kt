package com.ecomguide.ui.sidebar

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.viewbinding.ViewBinding
import com.ecomguide.databinding.ActivityMessagesBinding
import com.ecomguide.databinding.ItemMessageBinding
import com.ecomguide.repository.SidebarMockData

/** 侧边栏二级页通用列表初始化：设置内容视图 + 线性列表 + 适配器。 */
internal fun AppCompatActivity.bindCommonSidebarList(
    binding: ViewBinding,
    recyclerView: RecyclerView,
    adapter: RecyclerView.Adapter<*>
) {
    setContentView(binding.root)
    recyclerView.layoutManager = LinearLayoutManager(this)
    recyclerView.adapter = adapter
}

class MessagesActivity : AppCompatActivity() {

    private lateinit var b: ActivityMessagesBinding

    private val messages = SidebarMockData.messages

    // Icon background colors by type
    private val iconBgColor = mapOf(
        SidebarMockData.SidebarMessageType.PROMO to 0x26FDCB6E.toInt(),
        SidebarMockData.SidebarMessageType.ORDER to 0x2000A878.toInt(),
        SidebarMockData.SidebarMessageType.SYSTEM to 0x2074B9FF.toInt()
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityMessagesBinding.inflate(layoutInflater)
        bindCommonSidebarList(
            binding = b,
            recyclerView = b.rvMessages,
            adapter = MsgAdapter(messages)
        )

        // 统一返回行为：侧边栏二级页点击左上角直接关闭。
        b.btnBack.setOnClickListener { finish() }
    }

    inner class MsgAdapter(private val items: List<SidebarMockData.SidebarMessage>) :
        RecyclerView.Adapter<MsgAdapter.VH>() {

        inner class VH(val b: ItemMessageBinding) : RecyclerView.ViewHolder(b.root) {
            fun bind(msg: SidebarMockData.SidebarMessage) {
                b.tvMsgIcon.text = msg.icon
                b.tvMsgIcon.setBackgroundColor(iconBgColor[msg.type] ?: 0x22000000)
                b.tvMsgTitle.text = msg.title
                b.tvMsgPreview.text = msg.preview
                b.tvMsgTime.text = msg.time
                b.viewUnread.visibility = if (msg.unread) View.VISIBLE else View.GONE
                b.root.setOnClickListener {
                    Toast.makeText(b.root.context, msg.title, Toast.LENGTH_SHORT).show()
                }
            }
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
            VH(ItemMessageBinding.inflate(LayoutInflater.from(parent.context), parent, false))

        override fun onBindViewHolder(holder: VH, position: Int) = holder.bind(items[position])
        override fun getItemCount() = items.size
    }
}
