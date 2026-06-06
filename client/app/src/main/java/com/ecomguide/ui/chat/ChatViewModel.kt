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
import com.ecomguide.network.RetrofitClient
import com.ecomguide.repository.DemoProducts
import com.google.gson.Gson
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Call
import org.json.JSONArray
import org.json.JSONObject

/**
 * 聊天页 ViewModel — 管理对话状态和 Agent 工作流 SSE 消息（v2 协议）
 *
 * 职责：
 *   - 维护消息列表（MessageItem 多态列表，驱动 RecyclerView）
 *   - 管理会话生命周期：创建 conversation_id、多轮对话复用
 *   - 本地关键词匹配（无需后端即可展示 Demo 商品）
 *   - 接入后端 Agent 工作流 SSE 接口，解析 welcome/products/chat_reply/done/next_options 事件
 *   - 收到 products 事件时通过 batch API 获取商品详情并渲染卡片
 *
 * 后端接口协议：
 *   GET /api/conversation          → 创建会话，返回 conversation_id
 *   GET /api/search/{cid}?q=...     → SSE 流式返回 Agent 工作流结果
 *   GET /api/products/batch?ids=...    → 批量获取商品详情
 *
 * 线程说明：ChatStreamClient 回调在 OkHttp 子线程，通过 mainHandler 切换至主线程更新 LiveData。
 */
class ChatViewModel : ViewModel() {

    private val client = ChatStreamClient()
    private val gson = Gson()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(Dispatchers.Main)

    private val _messages = MutableLiveData<MutableList<MessageItem>>(mutableListOf())
    val messages: LiveData<MutableList<MessageItem>> = _messages

    private val _isStreaming = MutableLiveData(false)
    val isStreaming: LiveData<Boolean> = _isStreaming

    private val _error = MutableLiveData<String?>()
    val error: LiveData<String?> = _error

    /** 控制首页欢迎横幅的显示/隐藏（发送第一条消息后隐藏） */
    val showWelcome = MutableLiveData(true)

    /** 当前会话 ID，由 /api/conversation 创建 */
    var conversationId: String? = null
        private set

    private var activeCall: Call? = null
    private val history = mutableListOf<HistoryItem>()

    /** 收集到的 product_id 列表，用于批量请求商品详情（兜底/旧逻辑） */
    private val pendingProductIds = mutableListOf<String>()

    /**
     * 商品-推荐理由配对队列。
     *
     * 后端 SSE 事件顺序：products(p1) → chat_reply(理由1) → products(p2) → chat_reply(理由2)
     * 当收到 ProductEvent 时入队（等待后续 chat_reply），收到 ChatReply 时与最近的未配对 ProductEvent 配对，
     * 配对成功后立即发起该商品的 batch 查询，拿到详情后填入 AiMsg.inlineProducts。
     */
    private data class PendingProduct(
        val productId: String,
        val skuId: String,
        val category: String,
        val subCategory: String
    )
    private val productPairQueue = ArrayDeque<PendingProduct>()

    // ─── 会话管理 ──────────────────────────────────────────────────────────────

    /**
     * 创建新会话。应在 Fragment onViewCreated 中调用。
     * 成功后设置 conversationId，后续搜索自动使用。
     */
    fun createConversation() {
        client.createConversation(
            onSuccess = { cid ->
                conversationId = cid
            },
            onError = { msg ->
                // createConversation 回调来自 OkHttp 子线程，必须用 postValue 避免主线程约束崩溃
                _error.postValue("创建会话失败: $msg")
            }
        )
    }

    // ─── 发送消息入口 ──────────────────────────────────────────────────────────────

    /** 是否启用后端 Agent 工作流（true=始终走后端，false=使用本地 mock） */
    var useBackendAgent = true

    fun sendMessage(text: String) {
        if (_isStreaming.value == true) return
        if (conversationId == null) {
            _error.value = "会话未初始化，请稍后重试"
            return
        }
        showWelcome.value = false
        _isStreaming.value = true

        addItem(MessageItem.UserMsg(text))
        addItem(MessageItem.Typing)

        // 根据配置决定走后端 Agent 还是本地 mock
        if (useBackendAgent) {
            // 强制走后端 Agent 工作流（SSE 流式响应）
            searchFromBackend(text)
        } else {
            // 本地关键词匹配优先（离线 Demo 模式）
            val localReply = buildLocalReply(text)
            if (localReply != null) {
                mainHandler.postDelayed({
                    deliverLocalReply(localReply, text)
                }, 800L)
            } else {
                searchFromBackend(text)
            }
        }
    }

    // ─── 本地 mock 回复（离线 Demo 模式） ────────────────────────────────────────

    private data class LocalReply(
        val aiText: String,
        val products: List<ApiProduct> = emptyList(),
        val followTags: List<String> = emptyList(),
        val scenarioCards: List<ScenarioCard> = emptyList()
    )

    private fun buildLocalReply(text: String): LocalReply? {
        val t = text.lowercase()
        val beautyKw  = listOf("精华", "护肤", "美妆", "小棕瓶", "兰蔻", "资生堂", "抗初老", "保湿", "敏感肌", "化妆")
        val digitalKw = listOf("耳机", "蓝牙", "降噪", "airpops", "freebud", "苹果耳机", "华为耳机")
        val sportsKw  = listOf("跑鞋", "跑步", "运动鞋", "nike", "hoka", "训练鞋", "轻量跑")
        return when {
            (t.contains("对比") || t.contains("比较")) && beautyKw.any { t.contains(it) } ->
                LocalReply("好的，帮你对比三款热门抗初老精华 👇",
                    DemoProducts.beautyProducts,
                    listOf("哪款最适合干皮？", "最便宜的是哪款？", "有平价替代吗？"))
            (t.contains("对比") || t.contains("比较")) && digitalKw.any { t.contains(it) } ->
                LocalReply("帮你对比华为和苹果两款旗舰耳机 🎧",
                    DemoProducts.digitalProducts,
                    listOf("哪个性价比更高？", "安卓用户选哪款？"))
            listOf("连衣裙", "春装", "春游", "穿搭", "裙子", "法式").any { t.contains(it) } ->
                LocalReply("春游穿搭讲究的就是轻便好看还得上镜！结合你之前挑的那几款基础款风格，帮你整理了几个超实用的春游look～",
                    products = DemoProducts.sportsProducts,
                    followTags = listOf("亮点点结", "PK 对比", "选款建议", "参数解读"),
                    scenarioCards = listOf(DemoProducts.scenarioSpringDress, DemoProducts.scenarioSpringOutfit))
            beautyKw.any { t.contains(it) } ->
                LocalReply("为你精选以下热门精华，均来自品牌授权商品库 ✨",
                    DemoProducts.beautyProducts,
                    listOf("帮我对比这几款", "哪款适合敏感肌？", "有平价替代吗？"),
                    scenarioCards = listOf(DemoProducts.scenarioAntiAging))
            digitalKw.any { t.contains(it) } ->
                LocalReply("推荐两款旗舰级降噪耳机，音质和降噪都是天花板级别 🎧",
                    DemoProducts.digitalProducts,
                    listOf("哪个降噪更强？", "适合苹果用户吗？", "运动时能用吗？"),
                    scenarioCards = listOf(DemoProducts.scenarioHeadphone))
            sportsKw.any { t.contains(it) } ->
                LocalReply("推荐两款口碑很好的公路跑鞋，日常训练首选 👟",
                    DemoProducts.sportsProducts,
                    listOf("适合初跑者吗？", "尺码偏大吗？", "和竞速跑鞋有何区别？"))
            listOf("推荐", "好物", "随便", "逛逛", "有啥").any { t.contains(it) } ->
                LocalReply("这是今日热门好物推荐，覆盖美妆、数码、运动三大类 🛍️",
                    listOf(DemoProducts.beauty001, DemoProducts.digital007, DemoProducts.clothes007),
                    listOf("看更多美妆", "推荐耳机", "推荐跑鞋"),
                    scenarioCards = DemoProducts.allScenarioCards.take(2))
            else -> null
        }
    }

    /**
     * 以流式效果投递本地回复（模拟打字机效果）。
     */
    private fun deliverLocalReply(reply: LocalReply, userText: String) {
        removeLast<MessageItem.Typing>()

        if (reply.scenarioCards.isNotEmpty()) {
            val chunks = reply.aiText.chunked(6)
            addItem(MessageItem.ScenarioReply(
                text = chunks.firstOrNull() ?: "",
                scenarioCards = emptyList(), products = reply.products, followTags = reply.followTags
            ))
            val replyIdx = currentList().lastIndex
            chunks.drop(1).forEachIndexed { i, chunk ->
                mainHandler.postDelayed({
                    val list = currentList()
                    if (replyIdx < list.size) {
                        val prev = list[replyIdx] as? MessageItem.ScenarioReply ?: return@postDelayed
                        list[replyIdx] = prev.copy(text = reply.aiText.take(chunks.take(i + 2).sumOf { it.length }))
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
                        text = reply.aiText, scenarioCards = reply.scenarioCards,
                        products = reply.products, followTags = reply.followTags
                    )
                    _messages.value = list
                }
                _isStreaming.value = false
                history.add(HistoryItem("user", userText))
                history.add(HistoryItem("assistant", reply.aiText))
                if (reply.followTags.isNotEmpty()) addItem(MessageItem.FollowTags(reply.followTags))
            }, totalDelay)
            return
        }

        val chunks = reply.aiText.chunked(6)
        addItem(MessageItem.ScenarioReply(
            text = chunks.firstOrNull() ?: "",
            scenarioCards = emptyList(), products = emptyList(), followTags = reply.followTags
        ))
        val replyIdx = currentList().lastIndex
        chunks.drop(1).forEachIndexed { i, _ ->
            mainHandler.postDelayed({
                val list = currentList()
                if (replyIdx < list.size) {
                    val prev = list[replyIdx] as? MessageItem.ScenarioReply ?: return@postDelayed
                    list[replyIdx] = prev.copy(text = reply.aiText.take(chunks.take(i + 2).sumOf { it.length }))
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
                    text = reply.aiText, scenarioCards = emptyList(),
                    products = reply.products, followTags = reply.followTags
                )
                _messages.value = list
            }
            if (reply.followTags.isNotEmpty()) addItem(MessageItem.FollowTags(reply.followTags))
            _isStreaming.value = false
            history.add(HistoryItem("user", userText))
            history.add(HistoryItem("assistant", reply.aiText))
        }, totalDelay)
    }

    // ─── 后端 Agent 工作流 SSE 流式回复（v2 协议） ─────────────────────────────────────

    /**
     * 调用后端 /api/search/{conversation_id}?q=... 接入 Agent 工作流。
     *
     * 事件处理逻辑：
     *   Welcome      → 在同一个 AiMsg 中追加开头段
     *   ProductEvent → 入队等待下一条推荐理由配对
     *   ChatReply    → 在同一个 AiMsg 中按“单换行”追加推荐理由，并绑定对应商品卡片
     *   Done         → 在同一个 AiMsg 中追加结束段并结束流
     *   NextOptions  → 追问标签显示在气泡外
     *   Error        → 兜底本地数据
     */
    private fun searchFromBackend(text: String) {
        pendingProductIds.clear()
        productPairQueue.clear()
        var aiMsgIndex = -1
        var typingRemoved = false

        fun ensureTypingRemoved() {
            if (!typingRemoved) {
                removeLast<MessageItem.Typing>()
                typingRemoved = true
            }
        }

        fun ensureAiMsg(): Int {
            if (aiMsgIndex != -1) return aiMsgIndex
            ensureTypingRemoved()
            aiMsgIndex = currentList().size
            addItem(MessageItem.AiMsg(text = "", isStreaming = true))
            return aiMsgIndex
        }

        activeCall = client.search(
            query = text,
            conversationId = conversationId!!,
            onEvent = { event ->
                mainHandler.post {
                    when (event) {
                        is ChatStreamEvent.Welcome -> {
                            val idx = ensureAiMsg()
                            appendSegmentToAiMsg(idx, event.text)
                        }
                        is ChatStreamEvent.ProductEvent -> {
                            if (event.productId.isNotBlank()) {
                                productPairQueue.add(PendingProduct(
                                    productId = event.productId,
                                    skuId = event.skuId,
                                    category = event.category,
                                    subCategory = event.subCategory
                                ))
                                // 作为 done 兜底使用：若没配对成功可统一补卡片
                                pendingProductIds.add(event.productId)
                            }
                        }
                        is ChatStreamEvent.ChatReply -> {
                            val idx = ensureAiMsg()
                            appendSegmentToAiMsg(idx, event.text)

                            // 优先把当前推荐理由与最近一个未配对商品绑定
                            val pending = productPairQueue.removeFirstOrNull()
                            if (pending != null) {
                                pendingProductIds.remove(pending.productId)
                                fetchProductForMessage(idx, pending.productId)
                            }
                        }
                        is ChatStreamEvent.Done -> {
                            if (!event.text.isNullOrBlank()) {
                                val idx = ensureAiMsg()
                                appendSegmentToAiMsg(idx, event.text)
                            }

                            val list = currentList()
                            if (aiMsgIndex in list.indices) {
                                val cur = list[aiMsgIndex] as? MessageItem.AiMsg
                                if (cur != null) {
                                    list[aiMsgIndex] = cur.copy(isStreaming = false)
                                    _messages.value = list
                                }
                            }

                            conversationId = event.conversationId ?: conversationId
                            _isStreaming.value = false
                            history.add(HistoryItem("user", text))

                            // 兜底：若仍有未配对商品，作为独立商品卡片补充展示
                            if (productPairQueue.isNotEmpty()) {
                                productPairQueue.clear()
                                fetchAndShowProductCards()
                            }
                        }
                        is ChatStreamEvent.NextOptions -> {
                            if (event.options.isNotEmpty()) {
                                addItem(MessageItem.FollowTags(event.options))
                            }
                        }
                        is ChatStreamEvent.Error -> {
                            ensureTypingRemoved()
                            if (aiMsgIndex == -1) {
                                addItem(MessageItem.AiMsg("抱歉，服务暂时不可用，以下是相关商品推荐 🛍️"))
                                addItem(MessageItem.ProductCards(DemoProducts.allProducts.take(3)))
                            }
                            _isStreaming.value = false
                        }
                    }
                }
            }
        )
    }

    /**
     * 将商品卡片绑定到指定推荐理由消息下方。
     */
    private fun fetchProductForMessage(aiMsgIndex: Int, productId: String) {
        scope.launch {
            try {
                val product = withContext(Dispatchers.IO) {
                    val batchUrl = "${RetrofitClient.BASE_URL}api/products/batch?ids=$productId"
                    val fromBatch = runCatching {
                        val json = java.net.URL(batchUrl).readText()
                        val arr = parseProductsArray(json)
                        if (arr.length() > 0) {
                            runCatching {
                                gson.fromJson<ApiProduct>(arr.getJSONObject(0).toString(), ApiProduct::class.java)
                            }.getOrNull()?.takeIf { it.resolvedId.isNotBlank() }
                        } else null
                    }.getOrNull()

                    // 兼容旧服务端路由顺序问题：batch 命中失败时退化到单商品接口
                    fromBatch ?: fetchProductById(productId)
                }

                mainHandler.post {
                    if (product != null) {
                        val list = currentList()
                        if (aiMsgIndex in list.indices) {
                            val cur = list[aiMsgIndex] as? MessageItem.AiMsg ?: return@post
                            list[aiMsgIndex] = cur.copy(inlineProducts = cur.inlineProducts + product)
                            _messages.value = list
                        }
                    }
                }
            } catch (_: Exception) {
                // 单个商品查询失败不影响整体流程，静默忽略
            }
        }
    }

    /**
     * 兜底：通过 batch API 批量获取商品详情（旧逻辑保留，用于非 SSE 场景）。
     */
    private fun fetchAndShowProductCards() {
        if (pendingProductIds.isEmpty()) return
        val idList = pendingProductIds.distinct().take(20)
        val ids = idList.joinToString(",")
        pendingProductIds.clear()

        scope.launch {
            try {
                val products = withContext(Dispatchers.IO) {
                    val batchProducts = runCatching {
                        val url = "${RetrofitClient.BASE_URL}api/products/batch?ids=$ids"
                        val json = java.net.URL(url).readText()
                        val arr = parseProductsArray(json)
                        (0 until arr.length()).mapNotNull { idx ->
                            runCatching {
                                gson.fromJson<ApiProduct>(arr.getJSONObject(idx).toString(), ApiProduct::class.java)
                            }.getOrNull()
                        }.filter { it.resolvedId.isNotBlank() }
                    }.getOrElse { emptyList() }

                    if (batchProducts.isNotEmpty()) batchProducts
                    else idList.mapNotNull { fetchProductById(it) }
                }

                mainHandler.post {
                    if (products.isNotEmpty()) {
                        addItem(MessageItem.ProductCards(products))
                    }
                }
            } catch (e: Exception) {
                mainHandler.post {
                    _error.value = "获取商品详情失败: ${e.message}"
                }
            }
        }
    }

    // ─── 工具方法 ──────────────────────────────────────────────────────────────────

    private fun parseProductsArray(json: String): JSONArray {
        val payload = json.trim()
        if (payload.isBlank()) return JSONArray()
        if (payload.startsWith("[")) {
            return runCatching { JSONArray(payload) }.getOrElse { JSONArray() }
        }
        return runCatching { JSONObject(payload).optJSONArray("products") ?: JSONArray() }
            .getOrElse { JSONArray() }
    }

    private fun fetchProductById(productId: String): ApiProduct? {
        return runCatching {
            val detailUrl = "${RetrofitClient.BASE_URL}api/products/$productId"
            val detailJson = java.net.URL(detailUrl).readText()
            gson.fromJson<ApiProduct>(detailJson, ApiProduct::class.java)
        }.getOrNull()?.takeIf { it.resolvedId.isNotBlank() }
    }

    private fun formatSegmentText(text: String): String {
        val cleaned = text.trim()
        return if (cleaned.isBlank()) "" else cleaned
    }

    private fun appendSegmentToAiMsg(aiMsgIndex: Int, rawText: String) {
        val segment = formatSegmentText(rawText)
        if (segment.isBlank()) return

        val list = currentList()
        if (aiMsgIndex !in list.indices) return
        val cur = list[aiMsgIndex] as? MessageItem.AiMsg ?: return

        // 段落之间只做单换行，不插入空行
        val mergedText = if (cur.text.isBlank()) segment else "${cur.text.trimEnd()}\n$segment"
        list[aiMsgIndex] = cur.copy(text = mergedText)
        _messages.value = list
    }

    fun clearError() { _error.value = null }

    fun resetChat() {
        activeCall?.cancel()
        activeCall = null
        conversationId = null
        history.clear()
        pendingProductIds.clear()
        productPairQueue.clear()
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

    override fun onCleared() { super.onCleared(); activeCall?.cancel() }
}
