# 完善会话记忆Memory机制

## 问题
在现有实现中，当Intent Extraction或Scenario Gen提取完成用户当前查询的意图{requirements}后，就会把意图{requirements}存入到memory中，但是后续需要把{requirements}和memory都发送给Product Retrieval节点，这会导致当前用户意图{requirements}发生重复。
例如某次服务输出日志的Intent Extraction的输出为：
result='requirements={"sub_queries": [{"text": "防晒霜", "strategy": "keyword", "field": null, "operator": null, "value": null, "expanded_values": null, "category": "面部护肤", "sub_category": "防晒霜"}, {"text": "", "strategy": "structured_filter", "field": "price", "operator": "lt", "value": 200, "expanded_values": null, "category": null, "sub_category": null}]} | conversation_history=[{"sub_queries": [{"text": "防晒霜", "strategy": "keyword", "field": null, "operator": null, "value": null, "expanded_values": null, "category": "面部护肤", "sub_category": "防晒霜"}, {"text": "", "strategy": "structured_filter", "field": "price", "operator": "lt", "value": 200, "expanded_values": null, "category": null, "sub_category": null}]}]'

## 解决方案
在Intent Extraction或Scenario Gen节点中不把当前{requirements}放入memory中，而是在Product Retrieval节点完成检索后再把{requirements}放入memory中