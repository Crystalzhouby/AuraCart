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

class MessagesActivity : AppCompatActivity() {

    private lateinit var b: ActivityMessagesBinding

    enum class MsgType { PROMO, ORDER, SYSTEM }

    data class MsgItem(
        val icon: String,
        val type: MsgType,
        val title: String,
        val preview: String,
        val time: String,
        val unread: Boolean = false
    )

    private val mockMessages = listOf(
        MsgItem("🎉", MsgType.PROMO,  "专属优惠来啦！",
            "您关注的雅诗兰黛小棕瓶降价了，现在仅需¥680！", "1小时前", unread = true),
        MsgItem("📦", MsgType.ORDER, "订单物流更新",
            "您的华为 FreeBuds Pro 5 正在派送，预计今天送达", "3小时前", unread = true),
        MsgItem("🔔", MsgType.SYSTEM, "系统通知",
            "您的订单 #20240521001 已成功签收，欢迎评价！", "昨天"),
        MsgItem("✨", MsgType.PROMO,  "每日好物种草",
            "今日精选：兰蔻小黑瓶特价活动开始了，限时优惠…", "2天前"),
        MsgItem("⭐", MsgType.SYSTEM, "评价邀请",
            "购买的 Nike Air Zoom Pegasus 41 到货了，分享你的使用感受吧", "3天前"),
    )

    // Icon background colors by type
    private val iconBgColor = mapOf(
        MsgType.PROMO  to 0x26FDCB6E.toInt(),
        MsgType.ORDER  to 0x2000A878.toInt(),
        MsgType.SYSTEM to 0x2074B9FF.toInt()
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        b = ActivityMessagesBinding.inflate(layoutInflater)
        setContentView(b.root)

        b.btnBack.setOnClickListener { finish() }

        b.rvMessages.apply {
            layoutManager = LinearLayoutManager(this@MessagesActivity)
            adapter = MsgAdapter(mockMessages)
        }
    }

    inner class MsgAdapter(private val items: List<MsgItem>) :
        RecyclerView.Adapter<MsgAdapter.VH>() {

        inner class VH(val b: ItemMessageBinding) : RecyclerView.ViewHolder(b.root) {
            fun bind(msg: MsgItem) {
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
