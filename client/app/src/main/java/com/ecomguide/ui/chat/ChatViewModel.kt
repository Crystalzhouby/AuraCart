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
 * 聊天页核心状态容器。
 *
 * 这个 ViewModel 统一负责：
 * 1) 聊天消息流（本地 mock + 后端 SSE）
 * 2) 会话 ID 生命周期
 * 3) 商品补全与图片兜底
 * 4) UI 所需的 loading / error / welcome 状态
 *
 * 设计目标：
 * - UI 层（Fragment）只关注“渲染与交互”，不关心事件编排细节
 * - SSE 事件和本地 mock 都产出统一的 MessageItem 序列
 * - 对网络异常做兜底，避免单点失败破坏完整对话
 */
class ChatViewModel : ViewModel() {

    companion object {
        /** 本地 mock 打字机效果：每块字符数量。 */
        private const val LOCAL_STREAM_CHUNK_SIZE = 6

        /** 本地 mock 打字机效果：块间隔时间。 */
        private const val LOCAL_STREAM_INTERVAL_MS = 60L

        /** 本地 mock 打字机效果：尾帧缓冲时间。 */
        private const val LOCAL_STREAM_FINISH_BUFFER_MS = 100L

        /** 用户发送消息后，本地 mock 的首包延时。 */
        private const val LOCAL_REPLY_DELAY_MS = 800L

        /** 批量取商品时的上限，避免 URL 过长和 UI 过载。 */
        private const val PRODUCT_BATCH_LIMIT = 20
    }

    // ─── 基础依赖 ──────────────────────────────────────────────────────────────

    private val client = ChatStreamClient()
    private val gson = Gson()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(Dispatchers.Main)

    // ─── 对外状态（给 UI 观察）──────────────────────────────────────────────────

    private val _messages = MutableLiveData<MutableList<MessageItem>>(mutableListOf())
    val messages: LiveData<MutableList<MessageItem>> = _messages

    private val _isStreaming = MutableLiveData(false)
    val isStreaming: LiveData<Boolean> = _isStreaming

    private val _error = MutableLiveData<String?>()
    val error: LiveData<String?> = _error

    /** 控制首页欢迎横幅显示：用户发出首条消息后隐藏。 */
    val showWelcome = MutableLiveData(true)

    // ─── 会话状态 ──────────────────────────────────────────────────────────────

    /** 当前会话 ID，由 `/api/conversation` 生成并在多轮中复用。 */
    var conversationId: String? = null
        private set

    /** 当前活跃 SSE 请求，用于 reset 或页面销毁时取消。 */
    private var activeCall: Call? = null

    /** 对话历史（role + content），用于与后端协议保持一致。 */
    private val history = mutableListOf<HistoryItem>()

    /** 收集到的 product_id，供 done 阶段兜底展示商品卡片。 */
    private val pendingProductIds = mutableListOf<String>()

    /**
     * 等待“文案段落”配对的商品队列。
     *
     * 后端典型顺序：
     * products(p1) -> chat_reply(理由1) -> products(p2) -> chat_reply(理由2)
     *
     * 处理策略：
     * - 收到 ProductEvent：入队
     * - 收到 ChatReply：出队并绑定到刚追加的文案块
     */
    private data class PendingProduct(
        val productId: String,
        val skuId: String,
        val category: String,
        val subCategory: String
    )

    private val productPairQueue = ArrayDeque<PendingProduct>()

    /**
     * 一次 SSE 对话流的渲染上下文。
     * - aiMsgIndex：当前 AI 气泡所在索引，保证 welcome/chat_reply/done 追加到同一气泡
     * - typingRemoved：打字占位消息是否已移除，保证只移除一次
     */
    private data class StreamRenderState(
        var aiMsgIndex: Int = -1,
        var typingRemoved: Boolean = false
    )

    /** 是否启用后端 Agent 工作流（true=总是走后端，false=本地 mock 优先）。 */
    var useBackendAgent = true

    // ─── 本地 mock 配置 ─────────────────────────────────────────────────────────

    private val beautyKeywords = listOf(
        "精华", "护肤", "美妆", "小棕瓶", "兰蔻", "资生堂", "抗初老", "保湿", "敏感肌", "化妆"
    )

    private val digitalKeywords = listOf(
        "耳机", "蓝牙", "降噪", "airpops", "freebud", "苹果耳机", "华为耳机"
    )

    private val sportsKeywords = listOf(
        "跑鞋", "跑步", "运动鞋", "nike", "hoka", "训练鞋", "轻量跑"
    )

    private data class LocalReply(
        val aiText: String,
        val products: List<ApiProduct> = emptyList(),
        val followTags: List<String> = emptyList(),
        val scenarioCards: List<ScenarioCard> = emptyList()
    )

    // ─── 对外入口：会话与发送 ────────────────────────────────────────────────────

    /**
     * 创建新会话。
     *
     * 建议在页面初始化时调用一次。成功后会把 conversationId 写入当前 ViewModel。
     */
    fun createConversation() {
        client.createConversation(
            onSuccess = { cid ->
                conversationId = cid
            },
            onError = { msg ->
                // createConversation 回调来自 OkHttp 子线程，需用 postValue
                _error.postValue("创建会话失败: $msg")
            }
        )
    }

    /**
     * 发送用户消息。
     *
     * 统一流程：
     * 1) 校验会话与流状态
     * 2) 先落地 UserMsg + Typing
     * 3) 按配置走后端 SSE 或本地 mock
     */
    fun sendMessage(text: String) {
        if (!prepareForUserRequest(text)) return

        if (useBackendAgent) {
            searchFromBackend(text)
            return
        }

        val localReply = buildLocalReply(text)
        if (localReply != null) {
            mainHandler.postDelayed(
                { deliverLocalReply(localReply, text) },
                LOCAL_REPLY_DELAY_MS
            )
        } else {
            // 本地规则未命中时退化到后端，保证总有响应。
            searchFromBackend(text)
        }
    }

    // ─── 本地 mock：规则匹配与流式渲染 ───────────────────────────────────────────

    /**
     * 对输入做关键词规则匹配，返回可直接渲染的本地回复。
     *
     * 这个方法保持纯函数特性：只做匹配，不写入任何状态，便于后续维护规则表。
     */
    private fun buildLocalReply(text: String): LocalReply? {
        val lower = text.lowercase()
        return when {
            (lower.contains("对比") || lower.contains("比较")) && beautyKeywords.any { lower.contains(it) } -> {
                LocalReply(
                    aiText = "好的，帮你对比三款热门抗初老精华 👇",
                    products = DemoProducts.beautyProducts,
                    followTags = listOf("哪款最适合干皮？", "最便宜的是哪款？", "有平价替代吗？")
                )
            }

            (lower.contains("对比") || lower.contains("比较")) && digitalKeywords.any { lower.contains(it) } -> {
                LocalReply(
                    aiText = "帮你对比华为和苹果两款旗舰耳机 🎧",
                    products = DemoProducts.digitalProducts,
                    followTags = listOf("哪个性价比更高？", "安卓用户选哪款？")
                )
            }

            listOf("连衣裙", "春装", "春游", "穿搭", "裙子", "法式").any { lower.contains(it) } -> {
                LocalReply(
                    aiText = "春游穿搭讲究的就是轻便好看还得上镜！结合你之前挑的那几款基础款风格，帮你整理了几个超实用的春游look～",
                    products = DemoProducts.sportsProducts,
                    followTags = listOf("亮点点结", "PK 对比", "选款建议", "参数解读"),
                    scenarioCards = listOf(
                        DemoProducts.scenarioSpringDress,
                        DemoProducts.scenarioSpringOutfit
                    )
                )
            }

            beautyKeywords.any { lower.contains(it) } -> {
                LocalReply(
                    aiText = "为你精选以下热门精华，均来自品牌授权商品库 ✨",
                    products = DemoProducts.beautyProducts,
                    followTags = listOf("帮我对比这几款", "哪款适合敏感肌？", "有平价替代吗？"),
                    scenarioCards = listOf(DemoProducts.scenarioAntiAging)
                )
            }

            digitalKeywords.any { lower.contains(it) } -> {
                LocalReply(
                    aiText = "推荐两款旗舰级降噪耳机，音质和降噪都是天花板级别 🎧",
                    products = DemoProducts.digitalProducts,
                    followTags = listOf("哪个降噪更强？", "适合苹果用户吗？", "运动时能用吗？"),
                    scenarioCards = listOf(DemoProducts.scenarioHeadphone)
                )
            }

            sportsKeywords.any { lower.contains(it) } -> {
                LocalReply(
                    aiText = "推荐两款口碑很好的公路跑鞋，日常训练首选 👟",
                    products = DemoProducts.sportsProducts,
                    followTags = listOf("适合初跑者吗？", "尺码偏大吗？", "和竞速跑鞋有何区别？")
                )
            }

            listOf("推荐", "好物", "随便", "逛逛", "有啥").any { lower.contains(it) } -> {
                LocalReply(
                    aiText = "这是今日热门好物推荐，覆盖美妆、数码、运动三大类 🛍️",
                    products = listOf(
                        DemoProducts.beauty001,
                        DemoProducts.digital007,
                        DemoProducts.clothes007
                    ),
                    followTags = listOf("看更多美妆", "推荐耳机", "推荐跑鞋"),
                    scenarioCards = DemoProducts.allScenarioCards.take(2)
                )
            }

            else -> null
        }
    }

    /**
     * 用打字机效果投递本地回复。
     *
     * 兼容两个展示形态：
     * - 含场景卡：首帧就带商品列表，最终补齐场景卡
     * - 纯文本/商品：最终统一落在 ScenarioReply
     */
    private fun deliverLocalReply(reply: LocalReply, userText: String) {
        removeLast<MessageItem.Typing>()

        val chunks = chunkText(reply.aiText)
        val initialReply = MessageItem.ScenarioReply(
            text = chunks.firstOrNull().orEmpty(),
            scenarioCards = emptyList(),
            products = if (reply.scenarioCards.isNotEmpty()) reply.products else emptyList(),
            followTags = reply.followTags
        )

        addItem(initialReply)
        val replyIndex = currentList().lastIndex

        scheduleScenarioReplyTyping(
            replyIndex = replyIndex,
            chunks = chunks,
            fullText = reply.aiText,
            finalize = { prev ->
                prev.copy(
                    text = reply.aiText,
                    scenarioCards = reply.scenarioCards,
                    products = reply.products,
                    followTags = reply.followTags
                )
            },
            onCompleted = {
                finishLocalReply(userText, reply.aiText, reply.followTags)
            }
        )
    }

    /** 把文本按固定大小拆分，供打字机动画使用。 */
    private fun chunkText(text: String): List<String> {
        val chunks = text.chunked(LOCAL_STREAM_CHUNK_SIZE)
        return if (chunks.isEmpty()) listOf("") else chunks
    }

    /**
     * 调度 ScenarioReply 文本逐帧更新。
     *
     * 为什么抽成独立方法：
     * - 原先“有场景卡/无场景卡”两套逻辑几乎一致，容易改漏
     * - 集中后，后续只需改一个地方即可调整打字节奏
     */
    private fun scheduleScenarioReplyTyping(
        replyIndex: Int,
        chunks: List<String>,
        fullText: String,
        finalize: (MessageItem.ScenarioReply) -> MessageItem.ScenarioReply,
        onCompleted: () -> Unit
    ) {
        chunks.drop(1).forEachIndexed { i, _ ->
            val visibleChunkCount = i + 2
            mainHandler.postDelayed(
                {
                    updateScenarioReply(replyIndex) { prev ->
                        prev.copy(
                            text = visibleTextByChunks(
                                chunks = chunks,
                                fullText = fullText,
                                visibleChunkCount = visibleChunkCount
                            )
                        )
                    }
                },
                (i + 1) * LOCAL_STREAM_INTERVAL_MS
            )
        }

        val totalDelay = chunks.size * LOCAL_STREAM_INTERVAL_MS + LOCAL_STREAM_FINISH_BUFFER_MS
        mainHandler.postDelayed(
            {
                updateScenarioReply(replyIndex, finalize)
                onCompleted()
            },
            totalDelay
        )
    }

    /** 根据当前显示 chunk 数，计算应该展示的前缀文本。 */
    private fun visibleTextByChunks(
        chunks: List<String>,
        fullText: String,
        visibleChunkCount: Int
    ): String {
        val safeChunkCount = visibleChunkCount.coerceIn(1, chunks.size)
        val length = chunks.take(safeChunkCount).sumOf { it.length }
        return fullText.take(length)
    }

    /** 本地回复完结：落历史、结束流、补追问标签。 */
    private fun finishLocalReply(userText: String, assistantText: String, followTags: List<String>) {
        completeRequest(userText = userText, assistantText = assistantText)
        if (followTags.isNotEmpty()) {
            addItem(MessageItem.FollowTags(followTags))
        }
    }

    /** 安全更新某个 ScenarioReply；若 index 已失效则忽略。 */
    private fun updateScenarioReply(
        replyIndex: Int,
        transform: (MessageItem.ScenarioReply) -> MessageItem.ScenarioReply
    ) {
        val list = currentList()
        if (replyIndex !in list.indices) return
        val prev = list[replyIndex] as? MessageItem.ScenarioReply ?: return
        list[replyIndex] = transform(prev)
        _messages.value = list
    }

    // ─── 后端 SSE：事件编排 ─────────────────────────────────────────────────────

    /**
     * 发起后端 Agent 工作流搜索。
     *
     * 协议入口：`/api/search/{conversation_id}?q=...`
     */
    private fun searchFromBackend(text: String) {
        pendingProductIds.clear()
        productPairQueue.clear()

        val renderState = StreamRenderState()

        activeCall = client.search(
            query = text,
            conversationId = conversationId!!,
            onEvent = { event ->
                mainHandler.post {
                    handleStreamEvent(
                        event = event,
                        userText = text,
                        renderState = renderState
                    )
                }
            }
        )
    }

    /** 统一处理 SSE 事件，保证事件逻辑集中、可读。 */
    private fun handleStreamEvent(
        event: ChatStreamEvent,
        userText: String,
        renderState: StreamRenderState
    ) {
        when (event) {
            is ChatStreamEvent.Welcome -> {
                val index = ensureAiMsg(renderState)
                appendSegmentToAiMsg(index, event.text)
            }

            is ChatStreamEvent.ProductEvent -> {
                handleProductEvent(event)
            }

            is ChatStreamEvent.ChatReply -> {
                val index = ensureAiMsg(renderState)
                val blockIndex = appendSegmentToAiMsg(index, event.text)

                // 优先把“这段文案”与最近一个商品配对。
                val pending = productPairQueue.removeFirstOrNull()
                if (pending != null && blockIndex >= 0) {
                    pendingProductIds.remove(pending.productId)
                    fetchProductForMessage(index, blockIndex, pending.productId)
                }
            }

            is ChatStreamEvent.Done -> {
                handleDoneEvent(event, userText, renderState)
            }

            is ChatStreamEvent.NextOptions -> {
                if (event.options.isNotEmpty()) {
                    addItem(MessageItem.FollowTags(event.options))
                }
            }

            is ChatStreamEvent.Error -> {
                handleStreamError(renderState)
            }
        }
    }

    /** 收到 products 事件：先入配对队列，同时登记兜底 id。 */
    private fun handleProductEvent(event: ChatStreamEvent.ProductEvent) {
        if (event.productId.isBlank()) return

        productPairQueue.add(
            PendingProduct(
                productId = event.productId,
                skuId = event.skuId,
                category = event.category,
                subCategory = event.subCategory
            )
        )

        // done 阶段兜底：若没有被 chat_reply 成功消费，还能补一组卡片。
        pendingProductIds.add(event.productId)
    }

    /** 收到 done 事件：收尾同一 AI 气泡、更新会话、结束流。 */
    private fun handleDoneEvent(
        event: ChatStreamEvent.Done,
        userText: String,
        renderState: StreamRenderState
    ) {
        if (!event.text.isNullOrBlank()) {
            val index = ensureAiMsg(renderState)
            appendSegmentToAiMsg(index, event.text)
        }

        markAiMsgStreamingDone(renderState.aiMsgIndex)
        conversationId = event.conversationId ?: conversationId

        completeRequest(userText = userText, assistantText = null)

        // 若还有未配对商品，作为独立卡片兜底补充。
        if (productPairQueue.isNotEmpty()) {
            productPairQueue.clear()
            fetchAndShowProductCards()
        }
    }

    /** 收到错误事件：优先移除 typing；若尚未创建 AI 气泡则插入兜底内容。 */
    private fun handleStreamError(renderState: StreamRenderState) {
        ensureTypingRemoved(renderState)

        if (renderState.aiMsgIndex == -1) {
            addItem(MessageItem.AiMsg("抱歉，服务暂时不可用，以下是相关商品推荐 🛍️"))
            addItem(MessageItem.ProductCards(DemoProducts.allProducts.take(3)))
        }

        _isStreaming.value = false
    }

    /**
     * 确保打字占位消息被移除（仅一次）。
     */
    private fun ensureTypingRemoved(renderState: StreamRenderState) {
        if (renderState.typingRemoved) return
        removeLast<MessageItem.Typing>()
        renderState.typingRemoved = true
    }

    /**
     * 确保存在一个可追加的 AI 消息气泡。
     *
     * welcome/chat_reply/done 都会复用同一条 AiMsg，以便用户看到连续文本。
     */
    private fun ensureAiMsg(renderState: StreamRenderState): Int {
        if (renderState.aiMsgIndex != -1) return renderState.aiMsgIndex

        ensureTypingRemoved(renderState)
        renderState.aiMsgIndex = currentList().size
        addItem(MessageItem.AiMsg(text = "", isStreaming = true))
        return renderState.aiMsgIndex
    }

    /** 标记指定 AI 气泡流式状态结束。 */
    private fun markAiMsgStreamingDone(aiMsgIndex: Int) {
        val list = currentList()
        if (aiMsgIndex !in list.indices) return

        val aiMsg = list[aiMsgIndex] as? MessageItem.AiMsg ?: return
        list[aiMsgIndex] = aiMsg.copy(isStreaming = false)
        _messages.value = list
    }

    // ─── AI 消息块更新 ───────────────────────────────────────────────────────────

    /**
     * 追加一个文本段到 AiMsg.blocks。
     *
     * 返回值：
     * - >=0：本次追加后的 block index
     * - -1：追加失败（空文本或索引失效）
     */
    private fun appendSegmentToAiMsg(aiMsgIndex: Int, rawText: String): Int {
        val segment = formatSegmentText(rawText)
        if (segment.isBlank()) return -1

        val list = currentList()
        if (aiMsgIndex !in list.indices) return -1
        val current = list[aiMsgIndex] as? MessageItem.AiMsg ?: return -1

        val updatedBlocks = current.blocks + MessageItem.AiReplyBlock(text = segment)
        val mergedText = updatedBlocks.joinToString("\n") { it.text.trim() }.trim()

        list[aiMsgIndex] = current.copy(text = mergedText, blocks = updatedBlocks)
        _messages.value = list
        return updatedBlocks.lastIndex
    }

    /**
     * 把商品卡片绑定到某个 AiReplyBlock。
     *
     * 若 blockIndex 失效（极端时序），会兜底追加一个“纯商品块”。
     */
    private fun attachProductToAiBlock(aiMsgIndex: Int, blockIndex: Int, product: ApiProduct) {
        val list = currentList()
        if (aiMsgIndex !in list.indices) return

        val current = list[aiMsgIndex] as? MessageItem.AiMsg ?: return

        list[aiMsgIndex] = if (blockIndex in current.blocks.indices) {
            val updatedBlocks = current.blocks.toMutableList()
            updatedBlocks[blockIndex] = updatedBlocks[blockIndex].copy(product = product)
            current.copy(
                inlineProducts = current.inlineProducts + product,
                blocks = updatedBlocks
            )
        } else {
            current.copy(
                inlineProducts = current.inlineProducts + product,
                blocks = current.blocks + MessageItem.AiReplyBlock(text = "", product = product)
            )
        }

        _messages.value = list
    }

    // ─── 商品补全：单商品绑定 & 兜底卡片 ─────────────────────────────────────────

    /**
     * 把商品详情绑定到指定段落。
     *
     * 流程：
     * 1) 优先批量接口（即便只有 1 个 id 也复用同一逻辑）
     * 2) 失败后退化到单商品接口
     * 3) 缺图时补图片接口
     */
    private fun fetchProductForMessage(aiMsgIndex: Int, blockIndex: Int, productId: String) {
        scope.launch {
            try {
                val product = withContext(Dispatchers.IO) {
                    resolveSingleProduct(productId)
                }

                mainHandler.post {
                    if (product != null) {
                        attachProductToAiBlock(aiMsgIndex, blockIndex, product)
                    }
                }
            } catch (_: Exception) {
                // 单个商品失败不影响主流程，静默忽略。
            }
        }
    }

    /**
     * done 阶段兜底：把还没配对成功的商品，作为独立横向卡片展示。
     */
    private fun fetchAndShowProductCards() {
        if (pendingProductIds.isEmpty()) return

        val idList = sanitizeProductIds(pendingProductIds)
        pendingProductIds.clear()
        if (idList.isEmpty()) return

        scope.launch {
            try {
                val products = withContext(Dispatchers.IO) {
                    resolveProductsByIds(idList)
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

    /** 解析并补全单个商品（优先 batch，再降级 detail）。 */
    private fun resolveSingleProduct(productId: String): ApiProduct? {
        val fromBatch = fetchProductsFromBatch(listOf(productId)).firstOrNull()
        val base = fromBatch ?: fetchProductById(productId)
        return base?.let { enrichProductWithImage(it) }
    }

    /** 批量解析并补全多个商品。 */
    private fun resolveProductsByIds(productIds: List<String>): List<ApiProduct> {
        val sanitizedIds = sanitizeProductIds(productIds)
        if (sanitizedIds.isEmpty()) return emptyList()

        val productsFromBatch = fetchProductsFromBatch(sanitizedIds)
        val baseProducts = if (productsFromBatch.isNotEmpty()) {
            productsFromBatch
        } else {
            sanitizedIds.mapNotNull { fetchProductById(it) }
        }

        return enrichProductsWithImages(baseProducts)
    }

    /** 统一批量接口解析，失败时返回空集合。 */
    private fun fetchProductsFromBatch(productIds: List<String>): List<ApiProduct> {
        val sanitizedIds = sanitizeProductIds(productIds)
        if (sanitizedIds.isEmpty()) return emptyList()

        return runCatching {
            val url = "${RetrofitClient.BASE_URL}api/products/batch?ids=${sanitizedIds.joinToString(",")}"
            val json = java.net.URL(url).readText()
            val arr = parseProductsArray(json)

            (0 until arr.length())
                .mapNotNull { idx ->
                    runCatching {
                        gson.fromJson<ApiProduct>(arr.getJSONObject(idx).toString(), ApiProduct::class.java)
                    }.getOrNull()
                }
                .filter { it.resolvedId.isNotBlank() }
        }.getOrElse { emptyList() }
    }

    /** 单商品详情接口。 */
    private fun fetchProductById(productId: String): ApiProduct? {
        return runCatching {
            val detailUrl = "${RetrofitClient.BASE_URL}api/products/$productId"
            val detailJson = java.net.URL(detailUrl).readText()
            gson.fromJson<ApiProduct>(detailJson, ApiProduct::class.java)
        }.getOrNull()?.takeIf { it.resolvedId.isNotBlank() }
    }

    // ─── 图片补全 ────────────────────────────────────────────────────────────────

    /** 批量商品图片接口解析。 */
    private fun fetchProductImageMap(productIds: List<String>): Map<String, String> {
        val ids = sanitizeProductIds(productIds)
        if (ids.isEmpty()) return emptyMap()

        return runCatching {
            val url = "${RetrofitClient.BASE_URL}api/products/image/batch?ids=${ids.joinToString(",")}"
            val json = java.net.URL(url).readText()
            val arr = parseImageArray(json)

            buildMap {
                for (i in 0 until arr.length()) {
                    val obj = arr.optJSONObject(i) ?: continue
                    val productId = obj.optString("product_id").trim()
                    val imageUrl = normalizeImagePath(
                        obj.optString("image_url").ifBlank { obj.optString("image_path") }
                    )

                    if (productId.isNotEmpty() && !imageUrl.isNullOrEmpty()) {
                        put(productId, imageUrl)
                    }
                }
            }
        }.getOrElse { emptyMap() }
    }

    /** 给单个商品补图（仅在缺图时调用）。 */
    private fun enrichProductWithImage(product: ApiProduct): ApiProduct {
        if (product.resolvedId.isBlank() || !product.resolvedImageUrl.isNullOrBlank()) {
            return product
        }

        val imageUrl = fetchProductImageMap(listOf(product.resolvedId))[product.resolvedId] ?: return product
        return product.copy(imageUrl = imageUrl, imagePath = imageUrl)
    }

    /** 给批量商品补图（仅处理缺图商品）。 */
    private fun enrichProductsWithImages(products: List<ApiProduct>): List<ApiProduct> {
        if (products.isEmpty()) return products

        val missingImageIds = products
            .filter { it.resolvedId.isNotBlank() && it.resolvedImageUrl.isNullOrBlank() }
            .map { it.resolvedId }
            .distinct()

        if (missingImageIds.isEmpty()) return products

        val imageMap = fetchProductImageMap(missingImageIds)
        if (imageMap.isEmpty()) return products

        return products.map { product ->
            val imageUrl = imageMap[product.resolvedId]
            if (imageUrl.isNullOrBlank()) product
            else product.copy(imageUrl = imageUrl, imagePath = imageUrl)
        }
    }

    // ─── JSON / 文本工具 ─────────────────────────────────────────────────────────

    /** 兼容数组和对象包装两种 products 响应结构。 */
    private fun parseProductsArray(json: String): JSONArray {
        val payload = json.trim()
        if (payload.isBlank()) return JSONArray()

        if (payload.startsWith("[")) {
            return runCatching { JSONArray(payload) }.getOrElse { JSONArray() }
        }

        return runCatching {
            JSONObject(payload).optJSONArray("products") ?: JSONArray()
        }.getOrElse { JSONArray() }
    }

    /** 兼容 images/items/products 三种字段命名。 */
    private fun parseImageArray(json: String): JSONArray {
        val payload = json.trim()
        if (payload.isBlank()) return JSONArray()

        if (payload.startsWith("[")) {
            return runCatching { JSONArray(payload) }.getOrElse { JSONArray() }
        }

        return runCatching {
            val obj = JSONObject(payload)
            obj.optJSONArray("images")
                ?: obj.optJSONArray("items")
                ?: obj.optJSONArray("products")
                ?: JSONArray()
        }.getOrElse { JSONArray() }
    }

    /** 统一路径标准化：复用 RetrofitClient 的规则。 */
    private fun normalizeImagePath(path: String?): String? = RetrofitClient.resolveImageUrl(path)

    /** 过滤空 id、去重并截断。 */
    private fun sanitizeProductIds(productIds: List<String>): List<String> {
        return productIds
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .distinct()
            .take(PRODUCT_BATCH_LIMIT)
    }

    /** 文本段标准化：当前仅做 trim，保留扩展点。 */
    private fun formatSegmentText(text: String): String {
        val cleaned = text.trim()
        return if (cleaned.isBlank()) "" else cleaned
    }

    // ─── 通用状态操作 ─────────────────────────────────────────────────────────────

    /**
     * 在真正触发请求前做前置状态更新。
     */
    private fun prepareForUserRequest(text: String): Boolean {
        if (_isStreaming.value == true) return false

        if (conversationId == null) {
            _error.value = "会话未初始化，请稍后重试"
            return false
        }

        showWelcome.value = false
        _isStreaming.value = true

        addItem(MessageItem.UserMsg(text))
        addItem(MessageItem.Typing)
        return true
    }

    /** 请求结束统一收口：结束 loading，并记录历史。 */
    private fun completeRequest(userText: String, assistantText: String?) {
        _isStreaming.value = false
        history.add(HistoryItem("user", userText))
        if (!assistantText.isNullOrBlank()) {
            history.add(HistoryItem("assistant", assistantText))
        }
    }

    /** 追加消息到末尾。 */
    private fun addItem(item: MessageItem) {
        val list = currentList()
        list.add(item)
        _messages.value = list
    }

    /** 删除最后一个指定类型消息（典型用于移除 Typing 占位）。 */
    private inline fun <reified T : MessageItem> removeLast() {
        val list = currentList()
        val idx = list.indexOfLast { it is T }
        if (idx == -1) return
        list.removeAt(idx)
        _messages.value = list
    }

    /** 当前消息列表快照（Mutable，便于原地替换后整体回写 LiveData）。 */
    private fun currentList(): MutableList<MessageItem> = _messages.value ?: mutableListOf()

    // ─── 对外辅助接口 ────────────────────────────────────────────────────────────

    fun clearError() {
        _error.value = null
    }

    /** 清空当前聊天状态并恢复欢迎态。 */
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

    override fun onCleared() {
        super.onCleared()
        activeCall?.cancel()
    }
}
