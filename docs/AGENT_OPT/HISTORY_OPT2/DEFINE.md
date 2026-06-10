# DEFINE.md — HISTORY_OPT2 需求分析

> 输入: `server/docs/AGENT_OPT/HISTORY_OPT2/SPEC.md`

## 1. 功能需求

### F1: 数据库表结构变更

| 变更 | 说明 |
|---|---|
| `chat_message` → `chat_history` | 表重命名，字段不变 (id, conversation_id, role, content, created_at) |
| `conversation` 表精简 | 只保留 conversation_id (PK) + created_at + updated_at，删除 memory (JSONB) 列 |
| 删除 `session_memory` 机制 | 移除 `app/agent/memory.py`，AgentState 移除 `session_memory` 字段 |

### F2: 滑动窗口对话历史

- **数据来源**: ChatHistory 表，按 conversation_id 过滤，按 created_at 倒序取最近 `memory_recent_rounds` (10) 轮对话
- **注入节点**: Router, Extract STEP1, Extract STEP2, Retrieve 2b, Scene Retrieve, Option Gen
- **格式化**: 最近 N 轮 user/assistant 文本，按时间排序
- **超出窗口**: 直接丢弃，不做摘要/压缩

### F3: 各节点历史注入要求

| 节点 | 要求 |
|---|---|
| Router | 注入完整窗口历史，帮助意图判断 |
| Extract STEP1 | 注入完整窗口历史，帮助品类推断 |
| Extract STEP2 | 注入窗口历史 + 提示词强调"重点关注与 STEP1 提取品类相关的部分" |
| Retrieve 2b | 注入窗口历史 + 提示词强调"重点关注与检索品类相关的部分" |
| Scene Retrieve | 注入窗口历史 + 提示词强调"重点关注与各品类相关的部分" |
| Option Gen | 注入完整窗口历史 |

### F4: 删除 Retrieve 节点 3.Memory 更新阶段

### F5: config.yaml 参数化

- `scene_generate_agent.py:114` 硬编码 `[:6]` → 新配置项 `max_scene_categories`，默认值 3
- 确认 `memory_recent_rounds` 已在 config.yaml 中

### F6: Conversation 表语义变更

- `GET /api/conversation` — 只 INSERT conversation_id（不再插入 memory）
- `search.py` — 校验 conversation 存在性后从 ChatHistory 加载历史

## 2. 性能需求

无特殊性能要求。ChatHistory 查询按 conversation_id + created_at 索引，10 轮查询开销极低。

## 3. 最终交付物

1. 数据库迁移脚本（alembic）
2. 修改后的 model 文件：`chat_message.py` → `chat_history.py`，精简 `conversation.py`
3. 新增 `app/agent/history.py` — 滑动窗口查询公共函数
4. 删除 `app/agent/memory.py`
5. 修改各 agent 节点注入滑动窗口历史
6. 修改 `search.py` — 移除 session_memory 读写
7. 修改 `get_conversation.py` — 精简 INSERT
8. 修改 `get_product_info.py` — ChatHistory 表名适配
9. `config.yaml` / `config.py` — 新增 `max_scene_categories`
10. 更新测试文件
11. 清理 `models/__init__.py`

## 4. 硬约束

- 不能破坏现有 125+ 测试
- 数据库迁移需通过 alembic 管理，自动处理表重命名
- ChatHistory 表保持与 ChatMessage 完全相同的字段结构（仅改名）
- `memory_recent_rounds` 已在 config.yaml 中，值为 10，不做修改
- 删除的 session_memory 相关代码需完全清理，不留死代码

## 5. 隐含要求

- 滑动窗口历史查询函数需可复用（各节点共用同一函数）
- 历史文本格式化需统一（时间戳 + role + content）
- ChatHistory 表需在 conversation_id 和 created_at 上有合适索引
- 各节点对"与品类相关的部分"的提示词指令需差异化

## 6. 任务完成边界

- ChatHistory 表正常工作，ChatMessage 不再存在
- Conversation 表精简为 3 字段
- 各节点注入滑动窗口历史，prompt 含差异化关注指令
- 现有 125+ 测试 0 回归
- 新增测试覆盖滑动窗口查询和 prompt 注入
- `memory.py` 完整移除

## 7. 风险点

| 风险 | 影响 | 缓解 |
|---|---|---|
| ChatMessage→ChatHistory 改名影响面大 | 编译错误、测试失败 | grep 全量搜索 ChatMessage 引用，逐一更新 |
| 删除 session_memory 影响现有测试 | 大量测试依赖 session_memory 字段 | 先更新 model → 逐一改测试 |
| 滑动窗口历史文本过长 | prompt token 超限 | 每轮截断单条消息长度（如限制 200 字），窗口大小可控 |
| 历史查询引入 DB 依赖 | 此前 session_memory 为纯内存操作 | 各节点接受 db_session_factory 参数 |
