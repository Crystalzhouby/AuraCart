# 完善会话系统

## 多会话支持
当前系统只支持单一会话，不能把不同会话给分离开，现设计，每个会话创建后，会有一个唯一的conversation_id。需要补充以下功能：
- 添加GET /api/converation/接口，用于前端申请新对话，该接口会返回新对话的conversation_id
- 在现有的/api/search接口的输入参数上再加入conversation_id参数。
- 会话记忆memory需要根据conversation_id存储会话记忆，检索时也需要根据conversation_id检索相应的记忆。
- /api/search结果返回也要添加上conversation_id参数。