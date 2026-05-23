# Demo Script

## 3-5 分钟演示

1. 展示项目结构：`client/` 原生 Android、`server/` FastAPI、`data/` 商品库、`docs/` 评审材料。
2. 启动后端：`uvicorn app.main:app --app-dir server --reload --port 8000`。
3. 打开 Android App，输入“推荐一款适合油皮的洗面奶”。
4. 展示 AI 逐字回复和商品卡片，说明商品来自库内结构化数据。
5. 输入“不要含酒精的，再便宜点”，展示多轮条件收敛方向。
6. 输入“把第一款加入购物车”，展示 `cart_update` 和购物车状态。
7. 总结 RAG 反幻觉策略：库内商品、结构化卡片、空召回追问。
