package com.ecomguide.ui.chat

import android.os.Handler
import android.os.Looper
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import com.ecomguide.model.ApiProduct
import com.ecomguide.model.ChatStreamEvent
import com.ecomguide.model.HistoryItem
import com.ecomguide.model.MessageItem
import com.ecomguide.model.ScenarioCard
import com.ecomguide.network.ChatStreamClient
import com.ecomguide.repository.DemoProducts
import com.google.gson.Gson
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import okhttp3.Call

/**
 * 聊天页 ViewModel — 管理对话状态和 SSE 流式消息
 *
 * 职责：
 *   - 维护消息列表（MessageItem 多态列表，驱动 RecyclerView）
 *   - 本地关键词匹配（无需后端即可展示 Demo 商品）
 *   - 接入后端 SSE 流式接口，逐字渲染 AI 回复
 *   - 管理 session_id 实现多轮对话上下文
 *
 * 线程说明：ChatStreamClient 回调在 OkHttp 子线程，通过 mainHandler 切换至主线程更新 LiveData。
 */
class ChatViewModel : ViewModel() {

    private val client = ChatStreamClient()
    private val gson = Gson()
    private val mainHandler = Handler(Looper.getMainLooper())

    private val _messages = MutableLiveData<MutableList<MessageItem>>(mutableListOf())
    val messages: LiveData<MutableList<MessageItem>> = _messages

    private val _isStreaming = MutableLiveData(false)
    val isStreaming: LiveData<Boolean> = _isStreaming

    private val _error = MutableLiveData<String?>()
    val error: LiveData<String?> = _error

    /** 控制首页欢迎横幅的显示/隐藏（发送第一条消息后隐藏） */
    val showWelcome = MutableLiveData(true)

    private var sessionId: String? = null
    private var activeCall: Call? = null
    private val history = mutableListOf<HistoryItem>()

    // ─── 发送消息入口 ──────────────────────────────────────────────────────────────

    fun sendMessage(text: String) {
        if (_isStreaming.value == true) return
        showWelcome.value = false
        _isStreaming.value = true

        addItem(MessageItem.UserMsg(text))
        addItem(MessageItem.Typing)

        // 本地关键词匹配优先，匹配不到则调后端 SSE
        val localReply = buildLocalReply(text)
        if (localReply != null) {
            mainHandler.postDelayed({
                deliverLocalReply(localReply, text)
            }, 800L)
        } else {
            streamFromBackend(text)
        }
    }

    // ─── 本地 mock 回复（参照 HTML 原型 aiReply 逻辑，使用真实商品数据） ────────────

    private data class LocalReply(
        val aiText: String,
        val products: List<ApiProduct> = emptyList(),
        val followTags: List<String> = emptyList(),
        val scenarioCards: List<ScenarioCard> = emptyList()   // 场景推荐卡片
    )

    /**
     * 本地关键词回复（离线 Demo 模式）
     *
     * 匹配用户输入的关键词，直接返回预设商品数据，无需调用后端。
     * 未命中任何关键词时返回 null，由 streamFromBackend() 接管。
     *
     * 关键词分组：
     *   beautyKw  → 美妆精华类商品
     *   digitalKw → 蓝牙耳机类商品
     *   sportsKw  → 跑步鞋类商品
     */
    private fun buildLocalReply(text: String): LocalReply? {
        val t = text.lowercase()
        val beautyKw  = listOf("精华", "护肤", "美妆", "小棕瓶", "兰蔻", "资生堂", "抗初老", "保湿", "敏感肌", "化妆")
        val digitalKw = listOf("耳机", "蓝牙", "降噪", "airpods", "freebud", "苹果耳机", "华为耳机")
        val sportsKw  = listOf("跑鞋", "跑步", "运动鞋", "nike", "hoka", "训练鞋", "轻量跑")
        return when {
            // 对比（优先判断）
            (t.contains("对比") || t.contains("比较")) && beautyKw.any { t.contains(it) } ->
                LocalReply(
                    "好的，帮你对比三款热门抗初老精华 👇",
                    DemoProducts.beautyProducts,
                    listOf("哪款最适合干皮？", "最便宜的是哪款？", "有平价替代吗？")
                )
            (t.contains("对比") || t.contains("比较")) && digitalKw.any { t.contains(it) } ->
                LocalReply(
                    "帮你对比华为和苹果两款旗舰耳机 🎧",
                    DemoProducts.digitalProducts,
                    listOf("哪个性价比更高？", "安卓用户选哪款？")
                )

            // ── 场景推荐：连衣裙 / 穿搭 / 春装 — 返回场景卡片 ───────────────
            listOf("连衣裙", "春装", "春游", "穿搭", "裙子", "法式").any { t.contains(it) } ->
                LocalReply(
                    aiText = "春游穿搭讲究的就是轻便好看还得上镜！结合你之前挑的那几款基础款风格，帮你整理了几个超实用的春游look～",
                    products = DemoProducts.sportsProducts,
                    followTags = listOf("亮点点结", "PK 对比", "选款建议", "参数解读"),
                    scenarioCards = listOf(DemoProducts.scenarioSpringDress, DemoProducts.scenarioSpringOutfit)
                )

            // 精华 / 护肤
            beautyKw.any { t.contains(it) } ->
                LocalReply(
                    "为你精选以下热门精华，均来自品牌授权商品库 ✨",
                    DemoProducts.beautyProducts,
                    listOf("帮我对比这几款", "哪款适合敏感肌？", "有平价替代吗？"),
                    scenarioCards = listOf(DemoProducts.scenarioAntiAging)
                )

            // 耳机 / 蓝牙 / 降噪
            digitalKw.any { t.contains(it) } ->
                LocalReply(
                    "推荐两款旗舰级降噪耳机，音质和降噪都是天花板级别 🎧",
                    DemoProducts.digitalProducts,
                    listOf("哪个降噪更强？", "适合苹果用户吗？", "运动时能用吗？"),
                    scenarioCards = listOf(DemoProducts.scenarioHeadphone)
                )

            // 跑鞋 / 运动
            sportsKw.any { t.contains(it) } ->
                LocalReply(
                    "推荐两款口碑很好的公路跑鞋，日常训练首选 👟",
                    DemoProducts.sportsProducts,
                    listOf("适合初跑者吗？", "尺码偏大吗？", "和竞速跑鞋有何区别？")
                )

            // 随便推荐 / 逛逛
            listOf("推荐", "好物", "随便", "逛逛", "有啥").any { t.contains(it) } ->
                LocalReply(
                    "这是今日热门好物推荐，覆盖美妆、数码、运动三大类 🛍️",
                    listOf(DemoProducts.beauty001, DemoProducts.digital007, DemoProducts.clothes007),
                    listOf("看更多美妆", "推荐耳机", "推荐跑鞋"),
                    scenarioCards = DemoProducts.allScenarioCards.take(2)
                )

            else -> null  // 未命中，交给后端 SSE 处理
        }
    }

    /**
     * 以流式效果投递本地回复（模拟打字机效果）。
     *
     * 统一使用 ScenarioReply：
     * - 有场景卡片：文字 + 场景卡片 + 商品卡片都在同一 AI 气泡内
     * - 无场景卡片：文字 + 商品卡片也在同一 AI 气泡内
     *
     * 追问标签仍作为独立 FollowTags 消息，显示在气泡外。
     */
    private fun deliverLocalReply(reply: LocalReply, userText: String) {
        // 移除 Typing
        removeLast<MessageItem.Typing>()

        // ── 有场景卡片：合并为一条 ScenarioReply ────────────────────────────
        if (reply.scenarioCards.isNotEmpty()) {
            // 流式文字效果
            val chunks = reply.aiText.chunked(6)
            addItem(MessageItem.ScenarioReply(
                text = chunks.firstOrNull() ?: "",
                scenarioCards = emptyList<ScenarioCard>(),   // 先不显示卡片，等流式结束
                products = reply.products,
                followTags = reply.followTags
            ))
            val replyIdx = currentList().lastIndex

            chunks.drop(1).forEachIndexed { i, chunk ->
                mainHandler.postDelayed({
                    val list = currentList()
                    if (replyIdx < list.size) {
                        val prev = list[replyIdx] as? MessageItem.ScenarioReply ?: return@postDelayed
                        list[replyIdx] = prev.copy(
                            text = reply.aiText.take(chunks.take(i + 2).sumOf { it.length })
                        )
                        _messages.value = list
                    }
                }, (i + 1) * 60L)
            }

            // 流式结束后一次性展示完整内容（含场景卡片）
            val totalDelay = chunks.size * 60L + 100L
            mainHandler.postDelayed({
                val list = currentList()
                if (replyIdx < list.size) {
                    val prev = list[replyIdx] as? MessageItem.ScenarioReply ?: return@postDelayed
                    list[replyIdx] = prev.copy(
                        text = reply.aiText,
                        scenarioCards = reply.scenarioCards,   // ← 展示场景卡片
                        products = reply.products,
                        followTags = reply.followTags
                    )
                    _messages.value = list
                }
                _isStreaming.value = false
                history.add(HistoryItem("user", userText))
                history.add(HistoryItem("assistant", reply.aiText))

                // 追问标签作为独立消息追加到气泡外
                if (reply.followTags.isNotEmpty()) {
                    addItem(MessageItem.FollowTags(reply.followTags))
                }
            }, totalDelay)
            return
        }

        // ── 无场景卡片：仍使用 ScenarioReply，保证商品卡片展示在同一对话气泡内 ─────────
        val chunks = reply.aiText.chunked(6)
        addItem(
            MessageItem.ScenarioReply(
                text = chunks.firstOrNull() ?: "",
                scenarioCards = emptyList(),
                products = emptyList(),   // 先不显示商品卡片，等流式文字结束后展示
                followTags = reply.followTags
            )
        )
        val replyIdx = currentList().lastIndex

        chunks.drop(1).forEachIndexed { i, _ ->
            mainHandler.postDelayed({
                val list = currentList()
                if (replyIdx < list.size) {
                    val prev = list[replyIdx] as? MessageItem.ScenarioReply ?: return@postDelayed
                    list[replyIdx] = prev.copy(
                        text = reply.aiText.take(chunks.take(i + 2).sumOf { it.length })
                    )
                    _messages.value = list
                }
            }, (i + 1) * 60L)
        }

        val totalDelay = chunks.size * 60L + 100L
        mainHandler.postDelayed({
            val list = currentList()
            if (replyIdx < list.size) {
                val prev = list[replyIdx] as? MessageItem.ScenarioReply ?: return@postDelayed
                list[replyIdx] = prev.copy(
                    text = reply.aiText,
                    scenarioCards = emptyList(),
                    products = reply.products,
                    followTags = reply.followTags
                )
                _messages.value = list
            }

            if (reply.followTags.isNotEmpty()) addItem(MessageItem.FollowTags(reply.followTags))
            _isStreaming.value = false
            history.add(HistoryItem("user", userText))
            history.add(HistoryItem("assistant", reply.aiText))
        }, totalDelay)
    }

    // ─── 后端 SSE 流式回复 ─────────────────────────────────────────────────────────

    /**
     * 接入后端 SSE 流式接口（真实 RAG + LLM 模式）。
     *
     * 事件处理逻辑：
     *   Delta        → 将文字追加到最后一条 AiMsg（流式更新，不重建整个列表）
     *   ProductCards → 解析 JSON 商品列表，追加 ProductCards 消息项
     *   Done         → 保存 session_id，关闭流式状态
     *   Error        → 后端不可用时用本地 Demo 数据兜底，保证 Demo 可用
     */
    private fun streamFromBackend(text: String) {
        var aiMsgIndex = -1
        activeCall = client.send(
            message = text,
            sessionId = sessionId,
            onEvent = { event ->
                mainHandler.post {
                    when (event) {
                        is ChatStreamEvent.Delta -> {
                            val list = currentList()
                            val typingIdx = list.indexOfLast { it is MessageItem.Typing }
                            if (typingIdx != -1 && aiMsgIndex == -1) {
                                list[typingIdx] = MessageItem.AiMsg(event.text, isStreaming = true)
                                aiMsgIndex = typingIdx
                            } else if (aiMsgIndex != -1 && aiMsgIndex < list.size) {
                                val cur = list[aiMsgIndex] as? MessageItem.AiMsg ?: return@post
                                list[aiMsgIndex] = cur.copy(text = cur.text + event.text)
                            }
                            _messages.value = list
                        }
                        is ChatStreamEvent.ProductCards -> {
                            val products = parseProducts(event.productsJson)
                            if (products.isNotEmpty()) addItem(MessageItem.ProductCards(products))
                        }
                        is ChatStreamEvent.Done -> {
                            sessionId = event.sessionId
                            val list = currentList()
                            if (aiMsgIndex != -1 && aiMsgIndex < list.size) {
                                (list[aiMsgIndex] as? MessageItem.AiMsg)?.let {
                                    list[aiMsgIndex] = it.copy(isStreaming = false)
                                }
                            }
                            _messages.value = list
                            _isStreaming.value = false
                            history.add(HistoryItem("user", text))
                        }
                        is ChatStreamEvent.Error -> {
                            // 后端失败时用本地兜底回复
                            removeLast<MessageItem.Typing>()
                            if (aiMsgIndex == -1) {
                                addItem(MessageItem.AiMsg("抱歉，服务暂时不可用，以下是相关商品推荐 🛍️"))
                                addItem(MessageItem.ProductCards(DemoProducts.allProducts.take(3)))
                            }
                            _isStreaming.value = false
                        }
                        is ChatStreamEvent.CartUpdate -> { /* CartRepository handles this */ }
                    }
                }
            }
        )
    }

    // ─── 工具方法 ──────────────────────────────────────────────────────────────────

    fun clearError() { _error.value = null }

    fun resetChat() {
        activeCall?.cancel()
        activeCall = null
        sessionId = null
        history.clear()
        _messages.value = mutableListOf()
        _isStreaming.value = false
        showWelcome.value = true
    }

    private fun addItem(item: MessageItem) {
        val list = currentList()
        list.add(item)
        _messages.value = list
    }

    private inline fun <reified T : MessageItem> removeLast() {
        val list = currentList()
        val idx = list.indexOfLast { it is T }
        if (idx != -1) { list.removeAt(idx); _messages.value = list }
    }

    private fun currentList(): MutableList<MessageItem> = _messages.value ?: mutableListOf()

    private fun parseProducts(json: String): List<ApiProduct> = try {
        val obj = gson.fromJson(json, JsonObject::class.java)
        val arr = if (obj.has("products")) obj.getAsJsonArray("products")
        else gson.fromJson(json, JsonArray::class.java)
        arr.mapNotNull { runCatching { gson.fromJson(it, ApiProduct::class.java) }.getOrNull() }
    } catch (_: Exception) { emptyList() }

    override fun onCleared() { super.onCleared(); activeCall?.cancel() }
}
