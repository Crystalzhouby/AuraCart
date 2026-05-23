# API

## `POST /api/chat/stream`

请求：

```json
{
  "message": "推荐一款适合油皮的洗面奶",
  "session_id": "optional-session-id",
  "history": []
}
```

响应是 `text/event-stream`，事件类型分离：

```text
event: delta
data: {"text":"我从商品库里找到"}

event: product_cards
data: {"products":[{"id":"p001","name":"xxx","price":129,"image_url":"...","reason":"控油清爽"}]}

event: cart_update
data: {"action":"add","items":[...],"message":"已加入购物车"}

event: done
data: {"session_id":"..."}
```

客户端只根据事件类型渲染，不从大模型自然语言里解析商品卡片。

## `POST /api/chat`

非流式调试接口，返回完整文本和商品数组，方便后端测试。
