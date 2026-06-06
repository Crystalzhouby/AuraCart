# 修改retrieve节点的实现

1. 修改keyword和semantic检索 
两者的sql语句的返回结果不再包含sku_id，但是为了检索价格信息，sql语句依然需要join sku表。
此外，我希望返回结果中一个product_id最多只有5条数据（这里的5需要写入到config.yaml中，便于后续调整）。