# Client Design

## 页面

Android 端先做一个原生对话页：

- 顶部：会话标题和购物车入口。
- 中间：消息列表，支持用户气泡、AI 流式气泡、商品卡片。
- 底部：文本输入框、发送按钮，后续扩展图片/语音入口。

## 状态

- `Idle`：可输入。
- `Streaming`：正在接收 `delta`，发送按钮进入 loading。
- `ProductsReady`：收到 `product_cards` 后插入卡片。
- `CartUpdated`：收到 `cart_update` 后刷新购物车角标。
- `Error`：网络或解析失败，展示重试。

## 流式渲染

客户端用 OkHttp 发起 `/api/chat/stream`，按 SSE 事件类型分发。`delta` 追加到当前 AI 气泡，`product_cards` 渲染为卡片列表，`done` 收尾并保存 `session_id`。
