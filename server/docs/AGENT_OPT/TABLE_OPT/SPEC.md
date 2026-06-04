# product_review表更新

## 提取各个product的properties字段信息
将数据集中的每个product中包含的多个sku的properties字段的信息汇总为一句话。
例如对于如下的id为p_beauty_001的产品，可以总结为"本精华产品包含30ml经典装，50ml加大装和75ml家用装"。
```
{
  "product_id": "p_beauty_001",
  "title": "雅诗兰黛特润修护肌活精华露淡纹紧致保湿夜间修护抗初老精华30ml",
  "brand": "雅诗兰黛",
  "category": "美妆护肤",
  "sub_category": "精华",
  "base_price": 720.0,
  "image_path": "ecommerce_agent_dataset/images/p_beauty_001_live.jpg",
  "skus": [
    {
      "sku_id": "s_p_beauty_001_1",
      "properties": {
        "容量": "30ml 经典装"
      },
      "price": 720.0,
      "stock": 15
    },
    {
      "sku_id": "s_p_beauty_001_2",
      "properties": {
        "容量": "50ml 加大装"
      },
      "price": 980.0,
      "stock": 10
    },
    {
      "sku_id": "s_p_beauty_001_3",
      "properties": {
        "容量": "75ml 家用装"
      },
      "price": 1260.0,
      "stock": 81
    }
  ],
  "rag_knowledge": {
        ...
    ]
  }
}
```

## 更新product_review表
将上述的properties字段信息汇总，进行向量化处理，放入到product_review表中。其source设置为"property"，其source_weights为1.0。

## 日志打印更新
DEBUG级别日志需要打印keyword_search SQL和semantic_search SQL的查询结果。