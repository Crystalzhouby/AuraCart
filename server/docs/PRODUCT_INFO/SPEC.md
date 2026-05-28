# 接口修改

1. 修改GET /api/products/{product_id}接口
仅返回单个产品的信息product_id，title，brand，category，sub_category和base_price。以json格式返回。

2. 添加GET /api/products/image/{product_id}
返回product_id对应商品的图片。

3. 添加GET /api/sku/{sku_id}
返回sku_id对应sku的信息，如sku_id、properties、price和stock。以json格式返回。