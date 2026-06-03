# 修改QUERY_PARSE_SYSTEM提示词

## 问题
当前提示词在提取category/sub_category时，生成了一些在当前数据表中不存在的字段取值，如category为"面部护肤"，sub_category为"防晒霜"。

## 解决思路
应该参考category_lookup表中的数据，生成的字段取值必须出现在category_lookup表中。