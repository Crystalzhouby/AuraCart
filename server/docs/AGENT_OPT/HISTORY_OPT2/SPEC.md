# 数据库表表更
将ChatMessage表改为ChatHistory表，同时删除Conversation表。
只使用ChatHistory表来存储记忆。

# 原Conversation检索与存储变更
存储方面，在原有逻辑中，在ChitChat节点和Retrieve节点的最后，将该轮对话加入到ChatMessage和Conversation中，现在删除Conversation表即可。
在检索方面，
近几轮的对话历史放在一个滑动窗口中，滑动窗口的阈值为6000token。
router节点引入滑动窗口中的对话历史；
extract节点在STEP1提取品类时，依然引入滑动窗口中的对话历史，在STEP2检索历史时，也引入滑动窗口中的对话历史，但提示词重点关注对话历史中与STEP1提取的品类较为相关的部分。
retrieve节点在2b阶段为单个商品生成推荐理由时，也引入滑动窗口中的对话历史，但提示词重点关注对话历史中与STEP1提取的品类较为相关的部分；将3.Memory更新阶段去除。
scene_retrieve节点在提取完可能相关的品类，也会查询对话历史中与每个品类相关的部分，现在把其实现机制也改为引入滑动窗口中的对话历史，但提示词重点关注对话历史中与STEP1提取的品类较为相关的部分。
option_generate节点也引入滑动窗口中的对话历史。

# 对话历史超出滑动窗口后的压缩机制
滑动窗口大小为10，即存储最近的10轮对话，和config.yaml中的memory_recent_rounds保持一致
请给出压缩机制的设计策略，直接丢弃。

# 检查项目中的一些参数是否放在了config.yaml中
如在server\app\agent\nodes\scene_generate_agent.py中的代码
```
for cat, sub in list(lookup)[:6]:  # 最多 6 个品类
```
其中的6应该被放到config.yaml中，现在改为最多 3 个品类