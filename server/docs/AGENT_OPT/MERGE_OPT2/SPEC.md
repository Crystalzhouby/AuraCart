# 合并Agent节点

合并输出闲聊对话CHITCHAT_SYSTEM、ROUTER_SYSTEM和WELCOME_SYSTEM为统一的提示词，只进行一次LLM调用。
保留之前各个提示词生成内容的逻辑，在新的提示词里面额外添加一些关联性的逻辑：
首先同ROUTER_SYSTEM，判断用户的意图是chat、explicit和scenario中的哪一个，如果意图是chat，那么进行闲聊，引导用户购物，逻辑同CHITCHAT_SYSTEM，如果是explicit或scenario，那么输出一些商品相关的闲聊，可以参考WELCOME_SYSTEM。

对于该提示词的输出：包含两部分：
```
{
    "welcome_chat": 闲聊内容
    "intent": 查询意图"chat"|"explicit"|"scenario"
}
```
流式输出时，先逐token输出"welcome_chat"，然后再按语义单元输出"intent"。