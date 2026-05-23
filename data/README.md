# Data

本目录存放电商导购 RAG 的原始商品数据、数据处理脚本与处理结果。和数据清洗、归一化、索引构建相关的内容都统一放在这里，避免散落到后端服务代码里。

## 目录约定

- `ecommerce_agent_dataset/`：导师数据集，包含原始商品 JSON 与商品图片。
- `scripts/`：数据处理脚本。
- `processed/`：清洗后的 `products.jsonl` 和检索索引文件。

## 使用说明

以下命令都从仓库根目录执行。

### 1. 生成标准商品 JSONL

```bash
python3 data/scripts/import_products.py \
  --raw-dir data/ecommerce_agent_dataset \
  --output data/processed/products.jsonl
```

该脚本会递归读取 `ecommerce_agent_dataset/` 下的原始商品 JSON，归一化为后端可直接读取的 JSONL 文件。

### 2. 构建本地检索索引

```bash
python3 data/scripts/build_index.py \
  --products data/processed/products.jsonl \
  --output data/processed/text_index.json
```

当前索引是 Chroma 接入前的轻量文本索引，占位并服务本地检索流程。

### 3. 后端读取数据

后端默认读取 `data/processed/products.jsonl`。如需替换路径，可在 `.env` 中设置：

```bash
PRODUCT_DATA_PATH=data/processed/products.jsonl
```

如果没有生成正式数据，后端会使用内置 demo 商品，保证 API 能先跑通。

## 推荐字段

```json
{
  "id": "p001",
  "name": "商品名",
  "category": "类目",
  "price": 129,
  "stock": 42,
  "image_url": "https://example.com/image.jpg",
  "description": "商品详情、规格、材质、适用场景",
  "tags": ["油皮", "控油", "500以内"],
  "reason": ""
}
```

`price`、`stock`、`image_url` 等关键字段必须来自商品库，不能让大模型自由生成。
