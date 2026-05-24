# Android 客户端架构设计方案

## TODO（待完善）

| # | 功能 | 位置 | 说明 |
|---|------|------|------|
| 1 | `cart_update` SSE 事件处理 | `ChatViewModel.streamFromBackend()` | 后端推送 `cart_update` 时，客户端应解析商品并调用 `CartRepository.add()` 自动入购物车，目前只有注释占位 `/* CartRepository handles this */` |
| 2 | 多轮对话 history 传参 | `ChatStreamClient.send()` | `history` 字段目前固定传空数组 `JSONArray()`，应改为从 `ChatViewModel.history` 取近 N 条记录传给后端，实现真正的多轮上下文 |

---

## 1. 整体架构

采用 **Single Activity + MVVM + Navigation Component** 架构：

```
MainActivity（宿主）
├── DrawerLayout 侧边栏（历史对话 / 我的订单 / 消息 / 购物车）
└── NavHostFragment（Fragment 容器）
    └── ChatFragment（主对话页）
        ├── ChatViewModel（状态管理 + 业务逻辑）
        └── RecyclerView（多类型消息列表）

独立 Activity（Intent 跳转）：
  ProductDetailActivity  — 商品详情
  CartActivity           — 购物车
  ChatHistoryActivity    — 历史对话
  MyOrdersActivity       — 我的订单
  MessagesActivity       — 消息通知
```

---

## 2. 模块分层

```
com.ecomguide/
├── model/              数据模型层（纯 Kotlin data class，无 Android 依赖）
│   ├── ApiProduct      商品数据（适配后端新旧字段，含 rag_knowledge）
│   ├── MessageItem     聊天消息（sealed class，5 种类型）
│   ├── CartItem        购物车条目
│   └── ChatStreamEvent SSE 事件类型（sealed class）
│
├── network/            网络层（只负责 HTTP 通信）
│   ├── RetrofitClient  Retrofit 单例 + BASE_URL 常量
│   ├── ApiService      REST 接口定义（商品详情、列表）
│   └── ChatStreamClient OkHttp SSE 流式客户端
│
├── repository/         仓库层（数据访问和状态管理）
│   ├── CartRepository  购物车全局单例（LiveData 驱动角标更新）
│   └── DemoProducts    离线演示商品数据（真实数据集，无需后端）
│
└── ui/                 UI 层（Activity / Fragment / Adapter）
    ├── MainActivity    DrawerLayout 宿主，购物车角标
    ├── chat/           对话页（ChatFragment + ChatViewModel + Adapter）
    ├── detail/         商品详情（ProductDetailActivity）
    ├── cart/           购物车（CartActivity + CartAdapter）
    └── sidebar/        侧边栏页面（历史/订单/消息）
```

---

## 3. 聊天页核心设计

### 3.1 消息列表（RecyclerView 多 ViewType）

| ViewType | 布局文件 | 说明 |
|----------|---------|------|
| `TYPE_WELCOME` | item_welcome.xml | 首页欢迎横幅 + 快捷标签 |
| `TYPE_USER` | item_msg_user.xml | 用户气泡（右对齐） |
| `TYPE_AI` | item_msg_ai.xml | AI 气泡（左对齐，支持流式追加） |
| `TYPE_TYPING` | item_msg_typing.xml | 三点跳动等待动效 |
| `TYPE_PRODUCT_CARDS` | item_msg_products.xml | 商品卡片横向滑动列表 |
| `TYPE_FOLLOW_TAGS` | item_msg_follow_tags.xml | 追问快捷标签（Chip） |

### 3.2 ChatViewModel 状态机

```
初始状态: showWelcome=true, isStreaming=false

用户发送消息
  ↓
isStreaming = true
showWelcome = false
addItem(UserMsg)
addItem(Typing)
  ↓
┌─────────────────────────────────┐
│  本地关键词匹配（buildLocalReply）  │  命中 → deliverLocalReply（离线 Demo）
│  未命中 → streamFromBackend       │  → 调后端 SSE
└─────────────────────────────────┘
  ↓ SSE 事件
delta       → 更新最后一条 AiMsg.text（不重建列表）
product_cards → 追加 ProductCards 项
done        → 保存 session_id，isStreaming=false
error       → 降级显示本地 Demo 商品
```

### 3.3 流式文字渲染策略

- **后端 SSE**：每个 `delta` 事件通过 `notifyItemChanged(position)` 更新单条消息，避免整列刷新
- **本地 Demo**：将回复文本按 6 字符分块，`mainHandler.postDelayed(60ms)` 模拟打字效果
- **线程切换**：OkHttp 回调在子线程 → `mainHandler.post {}` → 主线程更新 LiveData

---

## 4. 商品详情页设计

### 数据来源

```
点击商品卡片
  ↓
Intent 传入 ApiProduct（Parcelable）
  ↓
ProductDetailActivity
  ├── 立即渲染已有数据（价格/标题/SKU/基本信息）
  └── 后台调 GET /api/products/{id} 补全 rag_knowledge
       ├── 官方问答（FAQ 列表）
       └── 用户评价（星级 + 评分）
```

### 图片加载策略

```kotlin
// 优先本地 API 真实图片，失败自动 fallback 到 picsum 占位图
Glide.with(context)
    .load("http://10.0.2.2:8000/images/...")   // 本地 API
    .error(Glide.with(context).load("https://picsum.photos/seed/.../400/400"))
    .centerCrop()
    .into(imageView)
```

---

## 5. 购物车设计

### DiffUtil 关键约束

`CartRepository.updateQty()` **必须**使用 `copy(qty = newQty)` 创建新对象，而非就地修改：

```kotlin
// ❌ 错误：就地修改，DiffUtil 无法检测变化，UI 不刷新
item.qty += 1

// ✅ 正确：创建新对象，DiffUtil 检测到差异，触发 UI 更新
current[idx] = current[idx].copy(qty = newQty)
```

### 购物车角标

`CartRepository.badgeCount` 是 `LiveData<Int>`，`MainActivity` 观察并更新 Toolbar 上的红色圆形角标。

---

## 6. 网络层设计

### 后端地址配置

| 场景 | 地址 |
|------|------|
| Android 模拟器 | `http://10.0.2.2:8000`（映射到宿主机 localhost） |
| 真机（同 WiFi） | `http://{Mac局域网IP}:8000` |

修改位置：`client/app/src/main/java/com/ecomguide/network/RetrofitClient.kt`

### 接口清单

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/stream` | SSE 流式对话（主接口） |
| POST | `/api/chat` | 同步对话（调试用） |
| GET  | `/api/products/{id}` | 商品详情（含 rag_knowledge） |
| GET  | `/api/products` | 商品列表（支持分页和关键词筛选） |
| GET  | `/images/{path}` | 商品图片静态文件 |
