package com.ecomguide.ui.chat

import android.animation.ObjectAnimator
import android.content.Intent
import android.content.res.ColorStateList
import android.os.Bundle
import android.util.TypedValue
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.animation.AccelerateDecelerateInterpolator
import android.view.inputmethod.EditorInfo
import android.widget.Toast
import androidx.core.content.ContextCompat
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.recyclerview.widget.LinearLayoutManager
import com.ecomguide.R
import com.ecomguide.databinding.FragmentChatBinding
import com.ecomguide.model.ApiProduct
import com.ecomguide.model.ScenarioCard
import com.ecomguide.repository.CartRepository
import com.ecomguide.ui.detail.CategoryProductsActivity
import com.ecomguide.ui.detail.HalfScreenProductDetailActivity
import com.ecomguide.ui.detail.ProductDetailActivity
import com.google.android.material.chip.Chip
import java.util.Calendar

class ChatFragment : Fragment() {

    private var _b: FragmentChatBinding? = null
    private val b get() = _b!!

    private val vm: ChatViewModel by activityViewModels()
    private lateinit var messageAdapter: MessageAdapter

    // 猜你想问：标签文本 → 发送的查询语句（匹配 ChatViewModel 关键词表）
    private val quickTags = listOf(
        "✨ 抗初老精华" to "推荐一款抗初老精华",
        "🎧 200元耳机"  to "200元以下的蓝牙耳机推荐",
        "👟 轻量跑鞋"   to "帮我推荐一双轻量跑鞋",
        "🔍 精华对比"   to "对比一下小棕瓶和红腰子精华",
        "☀️ 温和防晒"   to "推荐防晒霜，不要含酒精的",
        "🌿 敏感肌推荐" to "敏感肌能用哪些精华？"
    )

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _b = FragmentChatBinding.inflate(inflater, container, false)
        return b.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        setupBanner()
        setupQuickTags()
        setupRecyclerView()
        setupInput()
        observeViewModel()

        // 页面加载时自动创建会话（后端 Agent 工作流需要 conversation_id）
        vm.createConversation()
    }

    /** 横幅：时段问候文案 + 礼物呼吸动效 */
    private fun setupBanner() {
        val hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
        b.tvGreeting.text = when {
            hour < 6  -> "夜深了 🌙"
            hour < 12 -> "早上好 ☀️"
            hour < 14 -> "中午好 🌤"
            hour < 18 -> "下午好 🌈"
            else      -> "晚上好 🌙"
        }
        startGiftAnimation()
    }

    /** 礼物 emoji 呼吸动效（上下浮动 + 轻微旋转） */
    private fun startGiftAnimation() {
        val gift = b.tvGift
        ObjectAnimator.ofFloat(gift, "translationY", 0f, -14f, 0f).apply {
            duration = 3000L
            repeatCount = ObjectAnimator.INFINITE
            interpolator = AccelerateDecelerateInterpolator()
        }.start()
        ObjectAnimator.ofFloat(gift, "rotation", -6f, 6f, -6f).apply {
            duration = 3000L
            repeatCount = ObjectAnimator.INFINITE
            interpolator = AccelerateDecelerateInterpolator()
        }.start()
    }

    /**
     * 猜你想问：在横幅正下方生成白色胶囊气泡标签（参考 HTML 原型 .quick-tag 样式）
     *
     * 样式：白色背景 + 1dp 紫色边框 + pill 圆角 + 轻阴影 + 12sp 灰色文字
     */
    private fun setupQuickTags() {
        val ctx = requireContext()
        val chipGroup = b.chipGroupQuick

        val borderColor    = ColorStateList.valueOf(ContextCompat.getColor(ctx, R.color.colorBorder))
        val bgColor        = ColorStateList.valueOf(ContextCompat.getColor(ctx, R.color.colorSurface))
        val textColor      = ContextCompat.getColor(ctx, R.color.colorTextSecondary)
        val stroke1dp      = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 1f, resources.displayMetrics)
        val hPad           = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 14f, resources.displayMetrics)
        val minH           = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 34f, resources.displayMetrics)

        quickTags.forEach { (label, query) ->
            val chip = Chip(ctx).apply {
                text                = label
                isCheckable         = false
                chipBackgroundColor = bgColor
                chipStrokeColor     = borderColor
                chipStrokeWidth     = stroke1dp
                // pill 圆角
                shapeAppearanceModel = shapeAppearanceModel.withCornerSize(999f)
                setTextColor(textColor)
                textSize            = 12f
                chipMinHeight       = minH
                textStartPadding    = hPad
                textEndPadding      = hPad
                iconStartPadding    = 0f
                // 无选中态 ripple（保持干净）
                rippleColor         = ColorStateList.valueOf(
                    ContextCompat.getColor(ctx, R.color.colorAccentBg))
                // 轻阴影（对应 HTML box-shadow）
                elevation           = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 2f, resources.displayMetrics)

                setOnClickListener { sendMessage(query) }
            }
            chipGroup.addView(chip)
        }
    }

    private fun setupRecyclerView() {
        val llm = LinearLayoutManager(requireContext()).apply { stackFromEnd = true }
        messageAdapter = MessageAdapter(
            onProductClick = { product -> openDetail(product) },
            onAddToCart    = { product ->
                CartRepository.add(product)
                Toast.makeText(requireContext(), "✅ 已加入购物车", Toast.LENGTH_SHORT).show()
            },
            onTagClick     = { tag -> sendMessage(tag) },
            onScenarioClick = { card -> openCategoryProducts(card) },
            onHorizontalProductClick = { product -> openHalfScreenDetail(product) }
        )
        b.rvMessages.apply {
            adapter = messageAdapter
            layoutManager = llm
            itemAnimator = null
        }
    }

    private fun setupInput() {
        b.btnSend.setOnClickListener { sendFromInput() }
        b.etInput.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_SEND) { sendFromInput(); true } else false
        }
    }

    private fun sendFromInput() {
        val text = b.etInput.text.toString().trim()
        if (text.isBlank() || vm.isStreaming.value == true) return
        b.etInput.setText("")
        sendMessage(text)
    }

    private fun sendMessage(text: String) { vm.sendMessage(text) }

    private fun observeViewModel() {
        vm.messages.observe(viewLifecycleOwner) { items ->
            messageAdapter.submitMessages(items)
            if (messageAdapter.itemCount > 0) {
                b.rvMessages.scrollToPosition(messageAdapter.itemCount - 1)
            }
        }

        vm.showWelcome.observe(viewLifecycleOwner) { show ->
            val vis = if (show) View.VISIBLE else View.GONE
            b.bannerContainer.visibility = vis
            b.quickTagsSection.visibility = vis  // 横幅和猜你想问同步显示/隐藏
        }

        vm.isStreaming.observe(viewLifecycleOwner) { streaming ->
            b.btnSend.isEnabled = !streaming
        }

        vm.error.observe(viewLifecycleOwner) { err ->
            if (err != null) {
                Toast.makeText(requireContext(), err, Toast.LENGTH_SHORT).show()
                vm.clearError()
            }
        }
    }

    private fun openDetail(product: ApiProduct) {
        startActivity(Intent(requireContext(), ProductDetailActivity::class.java).apply {
            putExtra(ProductDetailActivity.EXTRA_PRODUCT, product)
        })
    }

    /** 点击场景推荐卡片 → 跳转到品类商品落地页 */
    private fun openCategoryProducts(card: ScenarioCard) {
        CategoryProductsActivity.start(requireContext(), card)
    }

    /** 点击聊天内横向商品卡片 → 跳转半屏商品详情页 */
    private fun openHalfScreenDetail(product: ApiProduct) {
        HalfScreenProductDetailActivity.start(requireActivity() as AppCompatActivity, product)
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _b = null
    }
}
