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
 * 1) 聊天消息流（后端 SSE）
 * 2) 会话 ID 生命周期
 * 3) 商品补全与图片兜底
 * 4) UI 所需的 loading / error / welcome 状态
 *
 * 设计目标：
 * - UI 层（Fragment）只关注“渲染与交互”，不关心事件编排细节
 * - SSE 事件统一产出 MessageItem 序列
 * - 对网络异常做兜底，避免单点失败破坏完整对话
 */
class ChatViewModel : ViewModel() {

    companion object {
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

    /**
     * 等待 chat_reply 理由回填的商品占位队列。
     *
     * 后端典型顺序：
     * products(p1) -> chat_reply(理由1) -> products(p2) -> chat_reply(理由2)
     */
    private data class PendingProduct(
        val productId: String,
        val skuId: String,
        val category: String,
        val subCategory: String,
        val placeholderToken: String
    )

    /** 商品占位与推荐理由绑定结果，用于流式更新展示。 */
    private data class ProductReasonPair(
        val productId: String,
        val skuId: String,
        val category: String,
        val subCategory: String,
        val reason: String,
        val placeholderToken: String
    )

    private data class ResolvedRecommendation(
        val product: ApiProduct,
        val category: String,
        val subCategory: String,
        val reason: String,
        val placeholderToken: String
    )

    private val productPairQueue = ArrayDeque<PendingProduct>()
    private val productReasonPairs = mutableListOf<ProductReasonPair>()
    private var placeholderTokenSeed = 0L

    /**
     * 一次 SSE 对话流的渲染上下文。
     * - aiMsgIndex：当前 AI 气泡所在索引，保证 welcome/chat_reply/done 追加到同一气泡
     * - typingRemoved：打字占位消息是否已移除，保证只移除一次
     */
    private data class StreamRenderState(
        var aiMsgIndex: Int = -1,
        var typingRemoved: Boolean = false,
        val categoryIntroBlockIndices: MutableList<Int> = mutableListOf(),
        val introBlockByGroupKey: MutableMap<String, Int> = mutableMapOf(),
        val awaitingIntroBlockIndices: ArrayDeque<Int> = ArrayDeque(),
        val insertedScenarioGroupKeys: MutableSet<String> = mutableSetOf(),
        var currentProductGroupKey: String? = null,
        var activeStreamChannel: ChatStreamEvent.StreamText.Channel? = null,
        var activeStreamBlockIndex: Int = -1,
        var streamCompleted: Boolean = false
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
     * 3) 始终走后端 SSE
     */
    fun sendMessage(text: String) {
        if (!prepareForUserRequest(text)) return
        searchFromBackend(text)
    }

    // ─── 后端 SSE：事件编排 ─────────────────────────────────────────────────────

    /**
     * 发起后端 Agent 工作流搜索。
     *
     * 协议入口：`/api/search/{conversation_id}?q=...`
     */
    private fun searchFromBackend(text: String) {
        productReasonPairs.clear()
        productPairQueue.clear()
        placeholderTokenSeed = 0L

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
                handleProductEvent(event, renderState)
            }

            is ChatStreamEvent.StreamText -> {
                handleStreamTextEvent(event, renderState)
            }

            is ChatStreamEvent.ChatReply -> {
                // chat_reply 紧跟 products 时，视为该商品理由，直接回填到占位块。
                val pending = productPairQueue.removeFirstOrNull()
                if (pending != null) {
                    val reason = formatSegmentText(event.text)
                    updateProductReasonByToken(pending.placeholderToken, reason)
                    upsertReasonBlockForProduct(renderState.aiMsgIndex, pending.placeholderToken, reason)
                } else {
                    // 无待配对商品时，视为开场后的“品类介绍”或结尾文本，保留在气泡内。
                    val index = ensureAiMsg(renderState)
                    val blockIndex = appendSegmentToAiMsg(index, event.text)
                    if (blockIndex >= 0) {
                        registerIntroBlockForScenario(blockIndex, renderState)
                    }
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

    /** 收到 products 事件：立即插入占位卡，并异步回填详情。 */
    private fun handleProductEvent(
        event: ChatStreamEvent.ProductEvent,
        renderState: StreamRenderState
    ) {
        if (event.productId.isBlank()) return

        val groupKey = toGroupKey(event.category, event.subCategory)
        renderState.currentProductGroupKey = groupKey
        bindIntroBlockToGroupIfNeeded(groupKey, renderState)

        val placeholderToken = nextPlaceholderToken()
        val pending = PendingProduct(
            productId = event.productId,
            skuId = event.skuId,
            category = event.category,
            subCategory = event.subCategory,
            placeholderToken = placeholderToken
        )

        productPairQueue.add(pending)
        productReasonPairs.add(
            ProductReasonPair(
                productId = pending.productId,
                skuId = pending.skuId,
                category = pending.category,
                subCategory = pending.subCategory,
                reason = "",
                placeholderToken = placeholderToken
            )
        )

        val aiMsgIndex = ensureAiMsg(renderState)
        appendProductPlaceholderBlock(aiMsgIndex, pending)
        resolvePlaceholderProductAsync(aiMsgIndex, pending)
    }

    /** 收到 done 事件：只收尾流状态，不再集中补插商品卡。 */
    private fun handleDoneEvent(
        event: ChatStreamEvent.Done,
        userText: String,
        renderState: StreamRenderState
    ) {
        renderState.streamCompleted = true

        // 无论本轮是否产出文本，都要先移除 typing，避免一直显示输入动画。
        ensureTypingRemoved(renderState)

        if (!event.text.isNullOrBlank()) {
            val index = ensureAiMsg(renderState)
            val doneText = formatSegmentText(event.text)
            if (doneText.isNotBlank() && !isLastTextBlock(index, doneText)) {
                appendSegmentToAiMsg(index, doneText)
            }
        }

        markAiMsgStreamingDone(renderState.aiMsgIndex)
        conversationId = event.conversationId ?: conversationId

        completeRequest(userText = userText, assistantText = null)

        // done 只做收尾：未配对理由的商品保留占位卡，等待异步详情回填。
        productPairQueue.clear()
        renderState.currentProductGroupKey = null
    }

    /** 收到错误事件：优先移除 typing，并给出最小文本兜底。 */
    private fun handleStreamError(renderState: StreamRenderState) {
        val aiMsgIndex = ensureAiMsg(renderState)

        val aiMsg = currentList().getOrNull(aiMsgIndex) as? MessageItem.AiMsg
        val hasVisibleText = aiMsg?.blocks?.any { it.text.isNotBlank() } == true || !aiMsg?.text.isNullOrBlank()
        if (!hasVisibleText) {
            appendSegmentToAiMsg(aiMsgIndex, "抱歉，服务暂时不可用，请稍后重试。")
        }

        markAiMsgStreamingDone(aiMsgIndex)
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

        val list = currentList()
        val existingStreamingAiIndex = list.indexOfLast {
            val ai = it as? MessageItem.AiMsg
            ai?.isStreaming == true
        }
        if (existingStreamingAiIndex >= 0) {
            renderState.aiMsgIndex = existingStreamingAiIndex
            return renderState.aiMsgIndex
        }

        val insertAt = list.size
        list.add(insertAt, MessageItem.AiMsg(text = "", isStreaming = true))
        _messages.value = list

        renderState.aiMsgIndex = insertAt
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
        list[aiMsgIndex] = current.copy(text = mergeAiText(updatedBlocks), blocks = updatedBlocks)
        _messages.value = list
        return updatedBlocks.lastIndex
    }

    /** 生成本轮唯一占位 token，保证异步回填能命中原始占位块。 */
    private fun nextPlaceholderToken(): String {
        placeholderTokenSeed += 1
        return "ph_${System.nanoTime()}_$placeholderTokenSeed"
    }

    /** products 到达即插入占位商品块，先保证流式顺序。 */
    private fun appendProductPlaceholderBlock(aiMsgIndex: Int, pending: PendingProduct) {
        val list = currentList()
        if (aiMsgIndex !in list.indices) return
        val current = list[aiMsgIndex] as? MessageItem.AiMsg ?: return

        val placeholder = ApiProduct(
            productId = pending.productId,
            id = pending.productId,
            title = "商品信息加载中...",
            category = pending.category,
            subCategory = pending.subCategory,
            reason = ""
        )

        val updatedBlocks = current.blocks + MessageItem.AiReplyBlock(
            text = "",
            product = placeholder,
            placeholderToken = pending.placeholderToken
        )
        list[aiMsgIndex] = current.copy(text = mergeAiText(updatedBlocks), blocks = updatedBlocks)
        _messages.value = list
    }

    /** 异步拉取详情后，只替换占位块内容，不改变块顺序。 */
    private fun resolvePlaceholderProductAsync(aiMsgIndex: Int, pending: PendingProduct) {
        scope.launch {
            val resolved = withContext(Dispatchers.IO) {
                resolveProductsByIds(listOf(pending.productId)).firstOrNull()
            } ?: return@launch

            val reason = findProductReasonByToken(pending.placeholderToken)
            val filled = resolved.copy(
                category = pending.category.ifBlank { resolved.category },
                subCategory = pending.subCategory.ifBlank { resolved.subCategory },
                reason = reason
            )
            updateProductBlockByToken(aiMsgIndex, pending.placeholderToken, filled)
        }
    }

    /** chat_reply 回来后，更新内存中的 pair 理由。 */
    private fun updateProductReasonByToken(placeholderToken: String, reason: String) {
        val index = productReasonPairs.indexOfFirst { it.placeholderToken == placeholderToken }
        if (index < 0) return
        val current = productReasonPairs[index]
        productReasonPairs[index] = current.copy(reason = reason)
    }

    private fun findProductReasonByToken(placeholderToken: String): String {
        return productReasonPairs.firstOrNull { it.placeholderToken == placeholderToken }
            ?.reason
            .orEmpty()
    }

    /**
     * 给占位商品补充/更新推荐理由，始终放在该商品块之前。
     * 若 reason 为空则不做新增，保留占位卡。
     */
    private fun upsertReasonBlockForProduct(aiMsgIndex: Int, placeholderToken: String, reason: String) {
        if (aiMsgIndex < 0) return

        val normalizedReason = reason.trim()
        val list = currentList()
        if (aiMsgIndex !in list.indices) return
        val aiMsg = list[aiMsgIndex] as? MessageItem.AiMsg ?: return

        val blocks = aiMsg.blocks.toMutableList()
        val productIndex = blocks.indexOfFirst {
            it.placeholderToken == placeholderToken && it.product != null
        }
        if (productIndex < 0) return

        val reasonIndex = blocks.indexOfFirst {
            it.placeholderToken == placeholderToken &&
                it.product == null &&
                it.scenarioCard == null
        }

        if (normalizedReason.isBlank()) {
            if (reasonIndex >= 0) {
                blocks.removeAt(reasonIndex)
            }
        } else if (reasonIndex >= 0) {
            val reasonBlock = blocks[reasonIndex].copy(text = normalizedReason)
            blocks[reasonIndex] = reasonBlock
            if (reasonIndex > productIndex) {
                blocks.removeAt(reasonIndex)
                val latestProductIndex = blocks.indexOfFirst {
                    it.placeholderToken == placeholderToken && it.product != null
                }
                if (latestProductIndex >= 0) {
                    blocks.add(latestProductIndex, reasonBlock)
                }
            }
        } else {
            blocks.add(
                productIndex,
                MessageItem.AiReplyBlock(
                    text = normalizedReason,
                    placeholderToken = placeholderToken
                )
            )
        }

        val updated = if (normalizedReason.isNotBlank()) {
            val latestReasonIndex = blocks.indexOfFirst {
                it.placeholderToken == placeholderToken &&
                    it.product == null &&
                    it.scenarioCard == null
            }
            val latestProductIndex = blocks.indexOfFirst {
                it.placeholderToken == placeholderToken && it.product != null
            }
            if (latestReasonIndex >= 0 && latestProductIndex >= 0) {
                val product = blocks[latestProductIndex].product
                if (product != null && product.reason != normalizedReason) {
                    blocks[latestProductIndex] = blocks[latestProductIndex].copy(
                        product = product.copy(reason = normalizedReason)
                    )
                }
            }
            blocks
        } else {
            blocks
        }

        list[aiMsgIndex] = aiMsg.copy(text = mergeAiText(updated), blocks = updated)
        _messages.value = list
    }

    /** 异步详情回填：仅替换 token 对应商品块。 */
    private fun updateProductBlockByToken(aiMsgIndex: Int, placeholderToken: String, product: ApiProduct) {
        if (aiMsgIndex < 0) return

        val list = currentList()
        if (aiMsgIndex !in list.indices) return
        val aiMsg = list[aiMsgIndex] as? MessageItem.AiMsg ?: return

        val blockIndex = aiMsg.blocks.indexOfFirst {
            it.placeholderToken == placeholderToken && it.product != null
        }
        if (blockIndex < 0) return

        val blocks = aiMsg.blocks.toMutableList()
        val reason = findProductReasonByToken(placeholderToken)
        blocks[blockIndex] = blocks[blockIndex].copy(
            product = product.copy(reason = reason)
        )

        list[aiMsgIndex] = aiMsg.copy(text = mergeAiText(blocks), blocks = blocks)
        _messages.value = list
    }

    private fun isLastTextBlock(aiMsgIndex: Int, text: String): Boolean {
        val list = currentList()
        if (aiMsgIndex !in list.indices) return false
        val aiMsg = list[aiMsgIndex] as? MessageItem.AiMsg ?: return false

        val lastText = aiMsg.blocks
            .asReversed()
            .firstOrNull { it.text.isNotBlank() }
            ?.text
            ?.trim()
            .orEmpty()
        return lastText == text.trim()
    }

    /** 处理流式文本事件（start / delta / end），支持真正逐字刷新同一气泡。 */
    private fun handleStreamTextEvent(
        event: ChatStreamEvent.StreamText,
        renderState: StreamRenderState
    ) {
        when (event.phase) {
            ChatStreamEvent.StreamText.Phase.START -> {
                if (event.channel == ChatStreamEvent.StreamText.Channel.CATEGORY_INTRO) {
                    renderState.currentProductGroupKey = null
                }

                val aiMsgIndex = ensureAiMsg(renderState)
                val blockIndex = ensureStreamingBlock(aiMsgIndex, event.channel, renderState)
                if (blockIndex >= 0) {
                    renderState.activeStreamChannel = event.channel
                    renderState.activeStreamBlockIndex = blockIndex
                }
            }

            ChatStreamEvent.StreamText.Phase.DELTA -> {
                if (event.text.isEmpty()) return
                val aiMsgIndex = ensureAiMsg(renderState)
                val blockIndex = ensureStreamingBlock(aiMsgIndex, event.channel, renderState)
                if (blockIndex >= 0) {
                    appendTextToAiBlock(aiMsgIndex, blockIndex, event.text)
                    renderState.activeStreamChannel = event.channel
                    renderState.activeStreamBlockIndex = blockIndex
                }
            }

            ChatStreamEvent.StreamText.Phase.END -> {
                val activeChannel = renderState.activeStreamChannel
                if (activeChannel != event.channel) return

                removeBlankBlockIfNeeded(
                    aiMsgIndex = renderState.aiMsgIndex,
                    blockIndex = renderState.activeStreamBlockIndex,
                    renderState = renderState
                )
                renderState.activeStreamChannel = null
                renderState.activeStreamBlockIndex = -1
            }
        }
    }

    /** 确保存在当前流式通道对应的文本块，若缺失则自动创建。 */
    private fun ensureStreamingBlock(
        aiMsgIndex: Int,
        channel: ChatStreamEvent.StreamText.Channel,
        renderState: StreamRenderState
    ): Int {
        if (renderState.activeStreamChannel == channel && renderState.activeStreamBlockIndex >= 0) {
            return renderState.activeStreamBlockIndex
        }

        val blockIndex = appendEmptyBlock(aiMsgIndex)
        if (blockIndex >= 0 && channel == ChatStreamEvent.StreamText.Channel.CATEGORY_INTRO) {
            registerIntroBlockForScenario(blockIndex, renderState)
        }
        return blockIndex
    }

    /** 在 AI 气泡末尾追加一个空文本块（供流式增量写入）。 */
    private fun appendEmptyBlock(aiMsgIndex: Int): Int {
        val list = currentList()
        if (aiMsgIndex !in list.indices) return -1
        val current = list[aiMsgIndex] as? MessageItem.AiMsg ?: return -1

        val updatedBlocks = current.blocks + MessageItem.AiReplyBlock(text = "")
        list[aiMsgIndex] = current.copy(text = mergeAiText(updatedBlocks), blocks = updatedBlocks)
        _messages.value = list
        return updatedBlocks.lastIndex
    }

    /** 把流式增量文本写入指定块。 */
    private fun appendTextToAiBlock(aiMsgIndex: Int, blockIndex: Int, delta: String) {
        val list = currentList()
        if (aiMsgIndex !in list.indices) return
        val current = list[aiMsgIndex] as? MessageItem.AiMsg ?: return
        if (blockIndex !in current.blocks.indices) return

        val blocks = current.blocks.toMutableList()
        val block = blocks[blockIndex]
        blocks[blockIndex] = block.copy(text = block.text + delta)

        list[aiMsgIndex] = current.copy(text = mergeAiText(blocks), blocks = blocks)
        _messages.value = list
    }

    /** end 阶段清理无内容空块，避免影响后续场景卡片插入索引。 */
    private fun removeBlankBlockIfNeeded(
        aiMsgIndex: Int,
        blockIndex: Int,
        renderState: StreamRenderState
    ) {
        val list = currentList()
        if (aiMsgIndex !in list.indices) return
        val current = list[aiMsgIndex] as? MessageItem.AiMsg ?: return
        if (blockIndex !in current.blocks.indices) return

        val target = current.blocks[blockIndex]
        if (target.text.isNotBlank() || target.product != null || target.scenarioCard != null) return

        val blocks = current.blocks.toMutableList()
        blocks.removeAt(blockIndex)

        list[aiMsgIndex] = current.copy(text = mergeAiText(blocks), blocks = blocks)
        _messages.value = list

        shiftIntroTrackingOnRemove(blockIndex, renderState)
    }

    /** 记录一个可插入场景卡片的“品类介绍”块索引。 */
    private fun registerIntroBlockForScenario(blockIndex: Int, renderState: StreamRenderState) {
        if (blockIndex < 0) return

        if (!renderState.categoryIntroBlockIndices.contains(blockIndex)) {
            renderState.categoryIntroBlockIndices.add(blockIndex)
        }

        val alreadyBound = renderState.introBlockByGroupKey.values.any { it == blockIndex }
        val alreadyQueued = renderState.awaitingIntroBlockIndices.any { it == blockIndex }
        if (!alreadyBound && !alreadyQueued) {
            renderState.awaitingIntroBlockIndices.addLast(blockIndex)
        }
    }

    /** 新分组到来时，把“最早未绑定”的介绍块分配给该分组。 */
    private fun bindIntroBlockToGroupIfNeeded(groupKey: String, renderState: StreamRenderState) {
        if (groupKey.isBlank()) return
        if (renderState.introBlockByGroupKey.containsKey(groupKey)) return
        if (renderState.awaitingIntroBlockIndices.isEmpty()) return

        val introIndex = renderState.awaitingIntroBlockIndices.removeFirst()
        renderState.introBlockByGroupKey[groupKey] = introIndex
    }

    /** 分组收束时立即插入该分组场景卡片。 */
    private fun emitScenarioCardForGroup(
        aiMsgIndex: Int,
        groupKey: String,
        renderState: StreamRenderState
    ) {
        if (!renderState.streamCompleted) return
        if (aiMsgIndex < 0 || groupKey.isBlank()) return
        if (renderState.insertedScenarioGroupKeys.contains(groupKey)) return

        val groupPairs = productReasonPairs
            .filter { pair -> toGroupKey(pair.category, pair.subCategory) == groupKey }
        if (groupPairs.isEmpty()) return

        renderState.insertedScenarioGroupKeys.add(groupKey)

        scope.launch {
            try {
                val resolved = withContext(Dispatchers.IO) {
                    resolveRecommendations(groupPairs)
                }
                if (resolved.isEmpty()) {
                    renderState.insertedScenarioGroupKeys.remove(groupKey)
                    return@launch
                }

                val grouped = resolved.groupBy { toGroupKey(it.category, it.subCategory) }
                val card = buildScenarioCards(grouped)
                    .associateBy { toGroupKey(it.category, it.subCategory) }[groupKey]
                    ?: buildScenarioCards(grouped).firstOrNull()

                if (card == null) {
                    renderState.insertedScenarioGroupKeys.remove(groupKey)
                    return@launch
                }

                val inserted = insertScenarioCard(aiMsgIndex, groupKey, card, renderState)
                if (inserted) {
                    removeProductPairsByGroup(groupKey)
                } else {
                    renderState.insertedScenarioGroupKeys.remove(groupKey)
                }
            } catch (_: Exception) {
                renderState.insertedScenarioGroupKeys.remove(groupKey)
            }
        }
    }

    /** done 后按模式输出推荐：多分组用场景卡片，单分组用横向商品卡片。 */
    private fun emitRecommendationCardsByMode(renderState: StreamRenderState) {
        val pairs = productReasonPairs.toList()
        if (pairs.isEmpty()) return

        val aiMsgIndex = renderState.aiMsgIndex
        if (aiMsgIndex < 0) return

        scope.launch {
            try {
                val resolved = withContext(Dispatchers.IO) {
                    resolveRecommendations(pairs)
                }
                if (resolved.isEmpty()) return@launch

                val grouped = resolved.groupBy { rec -> toGroupKey(rec.category, rec.subCategory) }

                if (shouldRenderAsScenario(grouped)) {
                    emitRemainingScenarioCards(renderState, grouped)
                } else {
                    emitSingleGroupHorizontalProducts(aiMsgIndex, grouped)
                }

                productReasonPairs.clear()
            } catch (e: Exception) {
                _error.value = "获取推荐卡片失败: ${e.message}"
            }
        }
    }

    /** done 后一次性补齐全部场景入口卡片，避免异步并发导致顺序错乱。 */
    private fun emitRemainingScenarioCards(
        renderState: StreamRenderState,
        grouped: Map<String, List<ResolvedRecommendation>>
    ) {
        val aiMsgIndex = renderState.aiMsgIndex
        if (aiMsgIndex < 0) return

        val cards = buildScenarioCards(grouped)
        if (cards.isEmpty()) return

        val aiMsg = (currentList().getOrNull(aiMsgIndex) as? MessageItem.AiMsg) ?: return
        val orderedGroupKeys = reorderGroupBindingsByIntro(aiMsg, cards, renderState)
        val cardsByGroup = cards.associateBy { card -> toGroupKey(card.category, card.subCategory) }

        orderedGroupKeys.forEach { groupKey ->
            val card = cardsByGroup[groupKey] ?: return@forEach
            if (insertScenarioCard(aiMsgIndex, groupKey, card, renderState)) {
                renderState.insertedScenarioGroupKeys.add(groupKey)
            }
        }
    }

    /** 单分组输出：把每个推荐商品作为 Ai 气泡内横向商品卡片。 */
    private fun emitSingleGroupHorizontalProducts(
        aiMsgIndex: Int,
        grouped: Map<String, List<ResolvedRecommendation>>
    ) {
        val recommendations = grouped.values.flatten()
        if (recommendations.isEmpty()) return

        val products = recommendations
            .map { recommendation -> recommendation.product.copy(reason = recommendation.reason) }

        appendProductsToAiMsg(aiMsgIndex, products)
    }

    /** 判定规则：有效分组数 > 1 即场景化，否则按单品（横向商品卡）渲染。 */
    private fun shouldRenderAsScenario(grouped: Map<String, List<ResolvedRecommendation>>): Boolean {
        val validGroupCount = grouped.values.count { items -> items.isNotEmpty() }
        return validGroupCount > 1
    }

    /** 追加单品推荐块到同一 Ai 气泡内：插在收尾文案前（若存在）。 */
    private fun appendProductsToAiMsg(aiMsgIndex: Int, products: List<ApiProduct>) {
        if (products.isEmpty()) return

        val list = currentList()
        if (aiMsgIndex !in list.indices) return
        val aiMsg = list[aiMsgIndex] as? MessageItem.AiMsg ?: return

        val blocks = aiMsg.blocks.toMutableList()

        // 单品流通常是「welcome -> (可选intro) -> ending」，
        // 商品理由+卡片应插在最后一段收尾文案之前，避免顺序颠倒。
        val textOnlyIndices = blocks.indices.filter { index ->
            val block = blocks[index]
            block.text.isNotBlank() && block.product == null && block.scenarioCard == null
        }
        val insertAt = if (textOnlyIndices.size >= 2) textOnlyIndices.last() else blocks.size

        var cursor = insertAt
        products.forEach { product ->
            val reason = product.reason.trim()
            if (reason.isNotEmpty()) {
                blocks.add(cursor, MessageItem.AiReplyBlock(text = reason))
                cursor += 1
            }
            blocks.add(cursor, MessageItem.AiReplyBlock(text = "", product = product))
            cursor += 1
        }

        list[aiMsgIndex] = aiMsg.copy(text = mergeAiText(blocks), blocks = blocks)
        _messages.value = list
    }

    /**
     * 根据介绍段落顺序重建 group->intro 映射，确保卡片顺序稳定且和文案对应。
     */
    private fun reorderGroupBindingsByIntro(
        aiMsg: MessageItem.AiMsg,
        cards: List<ScenarioCard>,
        renderState: StreamRenderState
    ): List<String> {
        val validIntroIndices = renderState.categoryIntroBlockIndices
            .distinct()
            .filter { it in aiMsg.blocks.indices }
            .sorted()

        val remainingCardsByGroup = cards
            .associateBy { card -> toGroupKey(card.category, card.subCategory) }
            .toMutableMap()

        renderState.introBlockByGroupKey.clear()
        renderState.awaitingIntroBlockIndices.clear()

        val orderedGroupKeys = mutableListOf<String>()
        val unboundIntroIndices = validIntroIndices.toMutableList()

        validIntroIndices.forEach { introIndex ->
            val introText = aiMsg.blocks[introIndex].text
            val matchedCard = remainingCardsByGroup.values.firstOrNull { card ->
                introLikelyMatchesCard(introText, card)
            } ?: return@forEach

            val groupKey = toGroupKey(matchedCard.category, matchedCard.subCategory)
            renderState.introBlockByGroupKey[groupKey] = introIndex
            orderedGroupKeys.add(groupKey)
            remainingCardsByGroup.remove(groupKey)
            unboundIntroIndices.remove(introIndex)
        }

        if (remainingCardsByGroup.isNotEmpty() && unboundIntroIndices.isNotEmpty()) {
            val introIterator = unboundIntroIndices.iterator()
            val groupIterator = remainingCardsByGroup.keys.toList().iterator()
            while (introIterator.hasNext() && groupIterator.hasNext()) {
                val introIndex = introIterator.next()
                val groupKey = groupIterator.next()
                renderState.introBlockByGroupKey[groupKey] = introIndex
                orderedGroupKeys.add(groupKey)
                remainingCardsByGroup.remove(groupKey)
            }
        }

        orderedGroupKeys.addAll(remainingCardsByGroup.keys)
        return orderedGroupKeys.distinct()
    }

    /** 仅移除指定分组的 pair，避免重复渲染同一入口卡片。 */
    private fun removeProductPairsByGroup(groupKey: String) {
        val iterator = productReasonPairs.iterator()
        while (iterator.hasNext()) {
            val pair = iterator.next()
            if (toGroupKey(pair.category, pair.subCategory) == groupKey) {
                iterator.remove()
            }
        }
    }

    /** 把场景入口卡片插入到目标介绍段落后方；无介绍段时追加到末尾。 */
    private fun insertScenarioCard(
        aiMsgIndex: Int,
        groupKey: String,
        card: ScenarioCard,
        renderState: StreamRenderState
    ): Boolean {
        val list = currentList()
        if (aiMsgIndex !in list.indices) return false
        val aiMsg = list[aiMsgIndex] as? MessageItem.AiMsg ?: return false

        val blocks = aiMsg.blocks.toMutableList()
        val introIndex = resolveIntroIndexForScenario(aiMsg, groupKey, card, renderState)
        if (introIndex == null && !renderState.streamCompleted) {
            return false
        }

        val insertAt = if (introIndex != null) introIndex + 1 else blocks.size
        blocks.add(insertAt, MessageItem.AiReplyBlock(text = "", scenarioCard = card))

        list[aiMsgIndex] = aiMsg.copy(text = mergeAiText(blocks), blocks = blocks)
        _messages.value = list

        shiftIntroTrackingOnInsert(insertAt, renderState)
        return true
    }

    /**
     * 优先使用显式映射；若映射失真，则根据介绍文案与场景关键词做兜底重绑定。
     */
    private fun resolveIntroIndexForScenario(
        aiMsg: MessageItem.AiMsg,
        groupKey: String,
        card: ScenarioCard,
        renderState: StreamRenderState
    ): Int? {
        var fallbackMappedIndex: Int? = null
        val mappedIndex = renderState.introBlockByGroupKey[groupKey]
        if (mappedIndex != null && mappedIndex in aiMsg.blocks.indices) {
            fallbackMappedIndex = mappedIndex
            val mappedText = aiMsg.blocks[mappedIndex].text
            if (introLikelyMatchesCard(mappedText, card)) {
                return mappedIndex
            }
        }

        val allIntroIndices = renderState.categoryIntroBlockIndices
            .distinct()
            .filter { idx -> idx in aiMsg.blocks.indices }
        if (allIntroIndices.isEmpty()) return fallbackMappedIndex

        val boundIntroIndices = renderState.introBlockByGroupKey.values.toSet()
        val prioritizedCandidates = allIntroIndices
            .filterNot { idx -> idx in boundIntroIndices }
            .ifEmpty { allIntroIndices }

        val matchedIndex = prioritizedCandidates.firstOrNull { idx ->
            val introText = aiMsg.blocks[idx].text
            introLikelyMatchesCard(introText, card)
        } ?: fallbackMappedIndex

        if (matchedIndex != null) {
            renderState.introBlockByGroupKey[groupKey] = matchedIndex
            renderState.awaitingIntroBlockIndices.remove(matchedIndex)
        }
        return matchedIndex
    }

    private fun introLikelyMatchesCard(introText: String, card: ScenarioCard): Boolean {
        val text = introText.trim()
        if (text.isBlank()) return false

        val keywords = listOf(
            card.subCategory.trim(),
            card.category.trim(),
            card.firstProductTitle.trim()
        ).filter { it.isNotEmpty() }

        if (keywords.isEmpty()) return true
        return keywords.any { keyword -> text.contains(keyword, ignoreCase = true) }
    }

    /** 在插入新块后，统一修正所有“介绍块索引”跟踪结构。 */
    private fun shiftIntroTrackingOnInsert(insertAt: Int, renderState: StreamRenderState) {
        if (insertAt < 0) return

        for (i in renderState.categoryIntroBlockIndices.indices) {
            if (renderState.categoryIntroBlockIndices[i] >= insertAt) {
                renderState.categoryIntroBlockIndices[i] = renderState.categoryIntroBlockIndices[i] + 1
            }
        }

        val mappedKeys = renderState.introBlockByGroupKey.keys.toList()
        mappedKeys.forEach { key ->
            val idx = renderState.introBlockByGroupKey[key] ?: return@forEach
            if (idx >= insertAt) {
                renderState.introBlockByGroupKey[key] = idx + 1
            }
        }

        if (renderState.awaitingIntroBlockIndices.isNotEmpty()) {
            val updatedQueue = ArrayDeque<Int>()
            renderState.awaitingIntroBlockIndices.forEach { idx ->
                updatedQueue.addLast(if (idx >= insertAt) idx + 1 else idx)
            }
            renderState.awaitingIntroBlockIndices.clear()
            renderState.awaitingIntroBlockIndices.addAll(updatedQueue)
        }
    }

    /** 在移除块后，统一修正所有“介绍块索引”跟踪结构。 */
    private fun shiftIntroTrackingOnRemove(removedIndex: Int, renderState: StreamRenderState) {
        if (removedIndex < 0) return

        val updatedIntroIndices = renderState.categoryIntroBlockIndices
            .distinct()
            .mapNotNull { idx ->
                when {
                    idx == removedIndex -> null
                    idx > removedIndex -> idx - 1
                    else -> idx
                }
            }
        renderState.categoryIntroBlockIndices.clear()
        renderState.categoryIntroBlockIndices.addAll(updatedIntroIndices)

        val updatedMap = mutableMapOf<String, Int>()
        renderState.introBlockByGroupKey.forEach { (key, idx) ->
            when {
                idx == removedIndex -> Unit
                idx > removedIndex -> updatedMap[key] = idx - 1
                else -> updatedMap[key] = idx
            }
        }
        renderState.introBlockByGroupKey.clear()
        renderState.introBlockByGroupKey.putAll(updatedMap)

        if (renderState.awaitingIntroBlockIndices.isNotEmpty()) {
            val updatedQueue = ArrayDeque<Int>()
            renderState.awaitingIntroBlockIndices.forEach { idx ->
                when {
                    idx == removedIndex -> Unit
                    idx > removedIndex -> updatedQueue.addLast(idx - 1)
                    else -> updatedQueue.addLast(idx)
                }
            }
            renderState.awaitingIntroBlockIndices.clear()
            renderState.awaitingIntroBlockIndices.addAll(updatedQueue)
        }
    }

    /** 合并 AI blocks 生成兼容文本字段。 */
    private fun mergeAiText(blocks: List<MessageItem.AiReplyBlock>): String {
        return blocks
            .mapNotNull { block -> block.text.trim().takeIf { it.isNotEmpty() } }
            .joinToString("\n")
            .trim()
    }

    // ─── 商品补全与场景入口组织 ────────────────────────────────────────────────

    /**
     * 根据本轮收集到的商品与推荐理由生成最终展示卡片。
     * - 多品类：使用 ScenarioReply 展示品类入口卡片
     * - 单品类：保持 ProductCards 展示方式
     */
    private fun emitRecommendationCards(
        aiMsgIndex: Int,
        introBlockIndices: List<Int>
    ) {
        val pairs = productReasonPairs.toList()
        productReasonPairs.clear()
        if (pairs.isEmpty()) return

        scope.launch {
            try {
                val resolved = withContext(Dispatchers.IO) {
                    resolveRecommendations(pairs)
                }
                if (resolved.isEmpty()) return@launch

                val grouped = resolved.groupBy { toGroupKey(it.category, it.subCategory) }
                val cardsByGroup = buildScenarioCards(grouped)
                    .associateBy { toGroupKey(it.category, it.subCategory) }

                if (cardsByGroup.isEmpty()) return@launch

                attachScenarioCardsToAiIntro(
                    aiMsgIndex = aiMsgIndex,
                    introBlockIndices = introBlockIndices,
                    cardsByGroup = cardsByGroup
                )
            } catch (e: Exception) {
                _error.value = "获取场景化推荐失败: ${e.message}"
            }
        }
    }

    /** 先按 product_id 去重，再补齐商品详情与图片，和推荐理由拼装。 */
    private fun resolveRecommendations(pairs: List<ProductReasonPair>): List<ResolvedRecommendation> {
        val orderedPairs = mutableListOf<ProductReasonPair>()
        val seenProductIds = mutableSetOf<String>()

        pairs.forEach { pair ->
            val id = pair.productId.trim()
            if (id.isEmpty()) return@forEach
            if (seenProductIds.add(id)) {
                orderedPairs.add(pair.copy(productId = id))
            }
        }

        if (orderedPairs.isEmpty()) return emptyList()

        val products = resolveProductsByIds(orderedPairs.map { it.productId })
        if (products.isEmpty()) return emptyList()

        val productMap = products.associateBy { it.resolvedId }
        return orderedPairs.mapNotNull { pair ->
            val product = productMap[pair.productId] ?: return@mapNotNull null
            ResolvedRecommendation(
                product = product,
                category = pair.category.ifBlank { product.category },
                subCategory = pair.subCategory.ifBlank { product.subCategory },
                reason = pair.reason.trim(),
                placeholderToken = pair.placeholderToken
            )
        }
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

    /** 按品类聚合后构建入口卡片数据。 */
    private fun buildScenarioCards(
        grouped: Map<String, List<ResolvedRecommendation>>
    ): List<ScenarioCard> {
        return grouped.values.mapNotNull { items ->
            val products = items.map { rec ->
                rec.product.copy(reason = rec.reason)
            }
            val first = items.firstOrNull() ?: return@mapNotNull null
            val firstProduct = products.firstOrNull() ?: return@mapNotNull null
            val categoryName = first.category.ifBlank { "猜你喜欢" }
            val subCategoryName = first.subCategory
            val groupKey = toGroupKey(categoryName, subCategoryName)

            ScenarioCard(
                scenarioId = "scenario_${groupKey.hashCode()}",
                scenarioName = firstProduct.resolvedTitle,
                emoji = categoryEmoji(categoryName),
                subtitle = "",
                reason = items.firstOrNull { it.reason.isNotBlank() }?.reason.orEmpty(),
                category = categoryName,
                subCategory = subCategoryName,
                products = products,
                firstProductTitle = firstProduct.resolvedTitle,
                firstProductPrice = firstProduct.resolvedPrice,
                firstProductImage = firstProduct.resolvedImageUrl,
                productCount = products.size,
                shopHint = "${products.size}件类似商品"
            )
        }
    }

    /** 把品类入口卡片插入到对应品类介绍文本块下方。 */
    private fun attachScenarioCardsToAiIntro(
        aiMsgIndex: Int,
        introBlockIndices: List<Int>,
        cardsByGroup: Map<String, ScenarioCard>
    ) {
        if (aiMsgIndex < 0) return

        val list = currentList()
        if (aiMsgIndex !in list.indices) return
        val aiMsg = list[aiMsgIndex] as? MessageItem.AiMsg ?: return

        val blocks = aiMsg.blocks.toMutableList()
        val validIntroIndices = introBlockIndices
            .distinct()
            .filter { it in blocks.indices }

        val remainingCards = cardsByGroup.toMutableMap()

        if (validIntroIndices.isEmpty()) {
            // 无品类介绍段时，保底按顺序附加到气泡末尾。
            remainingCards.values.forEach { card ->
                blocks.add(MessageItem.AiReplyBlock(text = "", scenarioCard = card))
            }
        } else {
            var shift = 0
            validIntroIndices.forEach { introIndex ->
                val actualIndex = introIndex + shift
                val introText = blocks.getOrNull(actualIndex)?.text.orEmpty()
                val introKey = extractGroupKeyFromIntro(introText)

                val card = introKey?.let { remainingCards.remove(it) }
                    ?: findCardByCategoryNameInText(introText, remainingCards)
                        ?.also { match ->
                            val key = toGroupKey(match.category, match.subCategory)
                            remainingCards.remove(key)
                        }
                    ?: return@forEach

                blocks.add(actualIndex + 1, MessageItem.AiReplyBlock(text = "", scenarioCard = card))
                shift += 1
            }

            // 若存在无法匹配到介绍段的入口，追加到气泡末尾兜底展示。
            remainingCards.values.forEach { card ->
                blocks.add(MessageItem.AiReplyBlock(text = "", scenarioCard = card))
            }
        }

        val mergedText = blocks
            .mapNotNull { block -> block.text.trim().takeIf { it.isNotEmpty() } }
            .joinToString("\n")
            .trim()

        list[aiMsgIndex] = aiMsg.copy(text = mergedText, blocks = blocks)
        _messages.value = list
    }

    /** 从“品类介绍”文本中尽量提取 category/subCategory 分组 key。 */
    private fun extractGroupKeyFromIntro(text: String): String? {
        val intro = text.trim()
        if (intro.isBlank()) return null

        val slashMatch = Regex("([\u4e00-\u9fa5A-Za-z0-9]+)\\s*/\\s*([\u4e00-\u9fa5A-Za-z0-9]+)")
            .find(intro)
        if (slashMatch != null) {
            return toGroupKey(slashMatch.groupValues[1], slashMatch.groupValues[2])
        }

        return null
    }

    /** 兜底：根据品类名是否出现在介绍文本中匹配入口卡片。 */
    private fun findCardByCategoryNameInText(
        introText: String,
        cardsByGroup: Map<String, ScenarioCard>
    ): ScenarioCard? {
        if (introText.isBlank()) return null

        return cardsByGroup.values.firstOrNull { card ->
            val categoryHit = card.category.isNotBlank() && introText.contains(card.category)
            val subHit = card.subCategory.isNotBlank() && introText.contains(card.subCategory)
            categoryHit || subHit
        }
    }

    /** 统一分组 key，避免 category/subCategory 空值时冲突。 */
    private fun toGroupKey(category: String, subCategory: String): String {
        return "${category.trim()}::${subCategory.trim()}"
    }

    /** 入口卡片 emoji 根据品类做轻量映射。 */
    private fun categoryEmoji(category: String): String {
        return when {
            category.contains("美妆") || category.contains("护肤") -> "✨"
            category.contains("数码") || category.contains("电子") -> "🎧"
            category.contains("服饰") || category.contains("运动") -> "👟"
            category.contains("食品") || category.contains("生活") -> "🛍️"
            else -> "🧭"
        }
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
        addItem(MessageItem.AiMsg(text = "", isStreaming = true))
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
        productReasonPairs.clear()
        productPairQueue.clear()
        placeholderTokenSeed = 0L

        _messages.value = mutableListOf()
        _isStreaming.value = false
        showWelcome.value = true
    }

    override fun onCleared() {
        super.onCleared()
        activeCall?.cancel()
    }
}
