# Agent Tool优化

## 添加Tool工具
主要添加一些查询数据库的tool工具。
（1）查询有哪些数据表，连接的postgresql中的ecommerce数据库下有哪些表，返回有哪些表信息，然后给出每个表存储了哪些数据的描述信息；
（2）查询某个数据表有哪些字段，并给出每个字段的含义；
（3）查询某个数据表的某个字段有哪些取值，允许多字段联合查询；
注意每个tool的输出格式你需要预先生成一个版本，然后需要向我核对一下。

## 优化目录结构
将rag/prompt.py也放到/agent/prompt下，便于提示词统一管理。

## 优化Agent
调整以下几个Agent的实现。

### 重构router节点
该节点负责对用户意图进行识别，首先划分为"闲聊"和"商品查询"两类，如果是"商品查询"，进一步地分为"明确商品查询"和"场景化查询"两类。
现在需要做的改进是，在识别到用户查询为"商品查询"是，在划分完成"明确商品查询"和"场景化查询"后，利用历史对话记录改写当前用户查询，如补充查询主体等，
例如用户的三轮查询为，"帮我推荐跑鞋" → "要轻量的" → "预算 500 以内"，后两个查询"要轻量的"和"预算 500 以内"的主体应能够根据历史对话识别出为跑鞋，并补充进用户查询，"要轻量的跑鞋"，"预算 500 以内的跑鞋"。
将改写后的查询交给extraction节点和scenario_gen节点。

### 重构extraction节点
该节点负责电商查询意图拆解。
第一步，首先应该生成用户查询中对brand,category和sub_category这几个字段的意图信息，category和sub_category取值参考category_lookup中有哪些(category,sub_category)对，brand的取值参考product表中在(category,sub_category)取值下brand字段有哪些取值。这些取值的查询借助上述提到的Tool工具。
第二步，extraction节点从memory中检索品类为(category,sub_category)的历史查询数据，然后将历史查询数据与当前查询数据做拼接。
第三步，按照(category,sub_category)对分组提取拼接后的用户查询对于该子品类的商品的需求，该需要包含两个查询条件，分别是结构化查询条件structured_filter和语义查询条件semantic；
- 用户的子需求关于价格区间或者库存数量：为structured_filter，field的取值可以在{"price","stock"}中取值，value的取值根据用户需求来确定，可以保留当前{"operator": "lt", "value": 200}的形式；
- 将用户的期望的主观感受（"好用""舒服""效果好""性价比高"）或客观属性要求（含酒精，不含香精和不粘腻）等转换为semantic查询条件中的text字段，text应综合，凝练且不丢失语义地表述该部分用户的查询意图；
- 拼接后的用户查询可能包含了前后矛盾的查询意图，例如用户刚才提到价格不高于200元，后续有提到价格不高于300元，此时以后续的用户查询意图为准；
- 去除"提取关键字查询keyword"的分支。

输出形式（数组，每个元素对应一个品类）：
```json
[
    {
        "category": "str | null",
        "sub_category": "str | null",
        "text": "str",
        "min_price": 0,
        "max_price": 4294967295,
        "order_num": 1,
        "brand": ["str"] | null
    },
    ...
]
```
字段说明：
- `category`: 用户想要商品的品类
- `sub_category`: 用户想要商品的子品类
- `text`: 语义查询条件文本，综合凝练地表述用户主观感受和客观属性需求
- `min_price`: 用户需求的最低价格，没有则为 0
- `max_price`: 用户需求的最高价格，没有则为 2^32-1（4294967295）
- `order_num`: 用户需要的下单数量，未明确提出时默认为 1
- `brand`: 用户想要的品牌列表，可能需要世界知识展开（如"日系品牌"→["SK-II","资生堂",...]），无品牌偏好则为 null

### 重构retrieval节点
extraction节点按照(category,sub_category)提取出了用户意图信息，单个(category,sub_category)对应的意图信息为：
```
{
"category": str | null,         // 用户想要商品的品类1
"sub_category": str | null      // 用户想要商品的子品类1
"text": str,                    // 语义查询条件的文本
"min_price": int,               // 用户需求给出的最低价格，没有为0
"max_price": int,               // 用户需求给出的最高价格，没有为2^32-1
"order_num": int,               // 用户商品需要下单的数量，用户没明确提出时，默认为1
"brand": [str] | null,          // 用户想要的品牌，可能需要世界知识，多值展开，如"日系品牌"→["SK-II","资生堂",...]，还有非日系品牌等。
}
```
接下来，检索时，也按照(category,sub_category)分组做检索，检索分为双路混合检索，一路语义检索，一路关键词检索，之后用RRF综合两路检索结果，最后再采用精排模型做重排序，按照相关性排序，取top-k作为最终结果。

首先，将意图信息中的category,sub_category,min_price,max_price,order_num转换为SQL查询条件，其中order_num是要求所需销售单品sku的库存量stock需要大于等于order_num，category和sub_category限定了销售单品所属的品类，min_price和max_price限定了所需销售单品sku的价格，brand限定了销售单品sku所属的品牌范围。
语义检索：在以上SQL条件的基础上，用text进行语义相似度匹配，最终SQL检索结果按照语义相似度排序，结果返回top-25；
关键词检索：采用 PostgreSQL 内置 `plainto_tsquery('chinese', ...)` 对用户查询进行分词，然后同样在以上 SQL 条件的基础上，基于 tsvector 进行检索，结果返回 top-25；
排名综合：采用RRF将语义检索和关键词检索的结果进行综合排名，取top-25。语义检索和关键词检索权重分别为0.7和0.3;
最后，采用精排模型bge-ranker-v2-m3进行检索结果进行精排，取出top-5作为检索的最终结果。

此外，需要注意：
1. 在单路检索阶段，如果有同一product_id多不同的sku_id的sku都满足，那么取sku_id最小的那个sku，其他的淘汰掉。
2. 对于一个product_id，检索得到的product_review最多为5条。
3. 以上单product_id的product_review最大数量的和检索返回数量等都需要能够在config.yaml中配置，之前的方案也要类似的配置参数，注意不要重复配置。

## 改进会话记忆系统

### 会话记忆存储
记忆系统不再存储extraction节点给出的意图信息，而是存储用户发送的原始的查询数据，注意：这里的查询数据既不是提取出的意图，也不是改写后的对话，而是用户发送的原有的查询。原始的查询数据按照(category,sub_category)进行分组存储。

### 会话记忆检索
1. router节点检索memory用于改写当前用户查询，memory返回原始的查询数据即可；
2. intent extraction和scenario gen节点检索memory用户查找商品，按照(category,sub_category)分组检索memory，memory返回原始的历史查询数据即可，intent extraction节点和scenario gen节点将历史查询数据与当前查询合并起来，再做意图提取。

### 会话记忆更新
当检索完成后，retieval节点会将查询数据更新到memory中；
对于查询数据，继续累加即可；