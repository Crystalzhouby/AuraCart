package com.ecomguide.ui.sidebar

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.ecomguide.databinding.ActivityMessagesBinding
import com.ecomguide.databinding.ItemMessageBinding
import com.ecomguide.repository.SidebarMockData

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
        setContentView(b.root)

        b.btnBack.setOnClickListener { finish() }

        b.rvMessages.apply {
            layoutManager = LinearLayoutManager(this@MessagesActivity)
            adapter = MsgAdapter(messages)
        }
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
