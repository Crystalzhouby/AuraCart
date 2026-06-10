# AuraCart Client — 设计方案

> 平台：Android (Kotlin) | 更新日期：2026-06-10

## 1. 页面结构

### 1.1 MainActivity — 主容器

```
┌──────────────────────────────────────┐
│  Toolbar                              │
│  [☰] [新对话]              [🛒 3]   │
├──────────────────────────────────────┤
│                                      │
│  ChatFragment (聊天主区域)            │
│  ┌────────────────────────────────┐  │
│  │ 欢迎横幅 (首次进入)             │  │
│  │ AI 消息气泡 (AiMsg)             │  │
│  │ 商品卡片 (横向/场景)            │  │
│  │ 追问标签 (FollowTags)           │  │
│  └────────────────────────────────┘  │
│                                      │
│  [输入框________________] [发送]      │
├──────────────────────────────────────┤
│  DrawerLayout (侧边抽屉)              │
│  ├── 历史对话                         │
│  ├── 我的订单                         │
│  ├── 消息中心                         │
│  ├── 购物车                           │
│  └── 收藏 (即将上线)                  │
└──────────────────────────────────────┘
```

### 1.2 页面清单

| 页面 | 组件 | 说明 |
|------|------|------|
| 主聊天页 | `ChatFragment` | RecyclerView 消息列表 + 输入框，核心交互页 |
| 商品详情 | `ProductDetailActivity` | 全屏商品详情 (标题/品牌/价格/SKU/评价) |
| 半屏详情 | `HalfScreenProductDetailActivity` | 从聊天页商品卡片点击弹出的半屏浮层 |
| 品类落地页 | `CategoryProductsActivity` | 场景入口卡片点击后的品类商品列表 |
| 购物车 | `CartActivity` | 已加入购物车的商品列表 |
| 历史对话 | `ChatHistoryActivity` | 按时间倒序的历史会话列表 |
| 消息中心 | `MessagesActivity` | 系统消息/通知 |
| 我的订单 | `MyOrdersActivity` | 订单列表 (即将上线) |

## 2. SSE 事件协议与消息模型

### 2.1 事件类型映射

| SSE 事件 | ChatStreamEvent 子类 | 处理方式 |
|----------|---------------------|----------|
| `welcome_chat_stream` | `StreamText(WELCOME, ...)` | start→new block, delta→append, end→trim |
| `welcome` | `Welcome(text)` | 追加到 AiMsg blocks |
| `chat_reply` | `ChatReply(text)` | 有 pending→回填理由 / 无→品类介绍段 |
| `products` | `ProductEvent(id, sku, cat, sub)` | 入队 productPairQueue, 记 productReasonPairs |
| `category_intro` | `ChatReply(text)` | 品类介绍块, 记录为 scenario 锚点 |
| `category_intro_stream` | `StreamText(CATEGORY_INTRO, ...)` | 流式追加品类介绍块 |
| `product_reason` | `ChatReply(text)` | 对应最近 products 事件的推荐理由 |
| `ending` | `ChatReply(text)` | 缓存 deferredEndingText |
| `ending_stream` | `StreamText(ENDING, ...)` | 增量追加 deferredEndingText |
| `next_options` | `NextOptions(options)` | 追加 FollowTags |
| `done` | `Done(text, cid)` | 触发卡片渲染 + 追加结束语 |
| `error` | `Error(message)` | 兜底文本或错误提示 |

### 2.2 消息模型 (MessageItem)

```kotlin
sealed class MessageItem {
    class UserMsg(text: String)                          // 用户消息
    class AiMsg(text, isStreaming, blocks)               // AI 消息 (多 block)
    class ProductCards(products: List<ApiProduct>)       // 商品卡片组
    class ScenarioReply(text, scenarioCards, ...)        // 场景回复
    class HorizontalProductCard(product: ApiProduct)     // 横向单品卡片
    class FollowTags(tags: List<String>)                 // 追问标签
    object Typing                                        // 打字动画占位
}
```

## 3. 状态管理

### 3.1 ChatViewModel 核心状态

| 状态 | 类型 | 说明 |
|------|------|------|
| `messages` | `LiveData<MutableList<MessageItem>>` | 消息列表 (UI 观察) |
| `isStreaming` | `LiveData<Boolean>` | SSE 流进行中 (控制发送按钮) |
| `showWelcome` | `LiveData<Boolean>` | 首页欢迎横幅显隐 |
| `error` | `LiveData<String?>` | 错误提示 |
| `conversationId` | `String?` | 当前会话 ID |

### 3.2 会话生命周期

```
App 启动 → resetChat() → createConversation()
  → sendMessage("query") → SSE 流
    → sendMessage("follow-up") (同一 conversationId)
      → ... 
        → resetChat() → 新 conversationId
```

- 会话 ID 防抖：`isCreatingConversation` 标记防止并发创建
- 待发队列：会话未就绪时缓存消息到 `pendingMessageAfterConversationReady`

## 4. 网络层

### 4.1 ChatStreamClient (SSE)

- 实现：OkHttp 手动解析 SSE 文本流
- 端点：`GET /api/search/{conversation_id}?q=...`
- 解析：按行读取，`event:` / `data:` 行配对，产出 `ChatStreamEvent`
- 取消：`Call.cancel()` 支持中途中断

### 4.2 RetrofitClient (REST)

同步接口 (用于批量补全)：

| 方法 | 端点 | 用途 |
|------|------|------|
| `sendMessage()` | `POST /api/chat` | (兼容旧协议) |
| `getProduct()` | `GET /api/products/{id}` | 单商品详情 |
| `getProducts()` | `GET /api/products` | 商品列表 |
| `getProductReview()` | `GET /api/review/{id}` | 商品评价 |
| `getAllSkus()` | `GET /api/all_skus/{id}` | SKU 全量 |

实际批量补全使用 `java.net.URL` 直接读取 (绕过 Retrofit 异步限制)：
- `GET /api/products/batch?ids=...`
- `GET /api/products/image/batch?ids=...`

### 4.3 图片路径解析

```kotlin
// RetrofitClient.resolveImageUrl(path)
// 相对路径 → Base URL 拼接
// 绝对 URL → 原样返回
// null → 占位图
```

## 5. 商品展示模式

### 5.1 横向商品卡片 (单品类)

适用场景：搜索结果为同一 sub_category 的商品

```
┌─────────────────────────────────────┐
│ 欢迎语 / 品类介绍                    │
├─────────────────────────────────────┤
│ ┌────────┐  商品标题                 │
│ │ 商品图  │  品牌 · ¥199            │
│ │ 100dp  │  ★ 4.5                  │
│ └────────┘              [🛒 加购]   │
│ ─────────────────────────────────── │
│ ┌────────┐  商品标题                 │
│ │ 商品图  │  ...                     │
│ └────────┘                           │
├─────────────────────────────────────┤
│ 结束语                               │
│ [追问标签1] [追问标签2] [追问标签3]    │
└─────────────────────────────────────┘
```

### 5.2 场景入口卡片 (多品类)

适用场景：搜索跨多个 sub_category (如"度假需要准备什么")

```
┌─────────────────────────────────────┐
│ 品类介绍: 美妆护肤 (防晒)             │
│ ┌─────────────────────────────────┐ │
│ │ 🌸 海边防晒                        │ │
│ │ [图] 安热沙小金瓶                  │ │
│ │ ¥198 · 3件类似商品 >              │ │
│ └─────────────────────────────────┘ │
│                                      │
│ 品类介绍: 服装 (连衣裙)               │
│ ┌─────────────────────────────────┐ │
│ │ 👗 夏日连衣裙                      │ │
│ │ ...                               │ │
│ └─────────────────────────────────┘ │
├─────────────────────────────────────┤
│ 结束语 + 追问标签                     │
└─────────────────────────────────────┘
```

## 6. 异常处理

| 场景 | 处理 |
|------|------|
| 会话创建失败 | postValue error，UI 展示 Toast |
| SSE 流中断 | handleStreamError → 检查可见文本 → 无则追加兜底文案 |
| 商品批量接口失败 | runCatching 返回空集合，不阻塞消息流 |
| 图片加载失败 | 占位图兜底 |
| conversation not found | 自动重建会话并重试当前查询 |
| 快速重复发送 | isStreaming 标记防止并发请求 |
