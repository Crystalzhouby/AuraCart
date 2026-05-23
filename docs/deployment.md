# Deployment

## 后端本地启动

```bash
cp .env.example .env
cd server
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

调试流式接口：

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"200 元以下的蓝牙耳机有哪些？"}'
```

## 数据处理

```bash
python3 data/scripts/import_products.py --raw-dir data/ecommerce_agent_dataset --output data/processed/products.jsonl
python3 data/scripts/build_index.py --products data/processed/products.jsonl --output data/processed/text_index.json
```

以上命令从仓库根目录执行。数据目录约定与字段说明见 `data/README.md`。

## Docker Compose

```bash
cp .env.example .env
docker compose up server
```

## Android

使用 Android Studio 打开 `client/`，模拟器访问后端地址为 `http://10.0.2.2:8000/`。
