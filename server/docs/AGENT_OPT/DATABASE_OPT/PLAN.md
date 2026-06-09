# PLAN.md — DATABASE_OPT 实现方案

> 输入: `server/docs/AGENT_OPT/DATABASE_OPT/DEFINE.md`

## 1. 整体实现架构

```mermaid
flowchart LR
    subgraph F1[F1: ChatMessage 修复]
        R[intent_route_agent.py] -->|chat_reply: welcome_chat| S[AgentState]
        O[option_generate_agent.py] -->|chat_reply: ending| S
        S --> P[search.py 持久化]
    end

    subgraph F2[F2: 数据感知测试]
        GEN[生成 3 条新商品 JSON] --> INS[插入 product/sku/marketing/faq/reviews]
        INS --> SRCH1[/api/search 检索]
        SRCH1 --> ASSERT[断言新商品可见]
        ASSERT --> DEL[删除商品]
        DEL --> SRCH2[/api/search 检索]
        SRCH2 --> ASSERT2[断言新商品消失]
    end
```

## 2. 核心功能接口

| 接口 | 满足需求 | 说明 |
|---|---|---|
| `intent_route_node` return 补 `chat_reply` | F1-Chat | 聊天流程回复持久化 |
| `option_generate_node` return 补 `chat_reply` | F1-推荐 | 推荐流程回复持久化 |
| `test_chat_message_persistence.py` | F1-验证 | 单元测试验证 chat_reply 写入 |
| `test_data_awareness.py` | F2 | 集成测试验证检索感知变更 |

## 3. 模块变更

### 3.1 `app/agent/nodes/intent_route_agent.py`

- **输入**: AgentState + LLMService
- **输出**: dict（新增 `chat_reply` 字段）
- **变更**: 两处 chat 路径 return 中加 `"chat_reply": welcome_chat`

### 3.2 `app/agent/nodes/option_generate_agent.py`

- **输入**: AgentState + LLMService
- **输出**: dict（新增 `chat_reply` 字段）
- **变更**: return 中加 `"chat_reply": ending`

### 3.3 `tests/test_chat_message_persistence.py`（新建）

- **功能**: 验证 intent_route_node 和 option_generate_node 返回 dict 含 `chat_reply`
- **类型**: 单元测试，无需网络

### 3.4 `tests/test_data_awareness.py`（新建）

- **功能**: 插入/删除前后检索验证
- **类型**: 集成测试，需 LLM + Embedding

## 4. 方案优点

- **最小改动**: 仅两处 return 加一个字段，改动面积极小
- **复用现有逻辑**: `search.py` 持久化代码无需修改，条件 `if user_query and chat_reply` 保持不变
- **异常安全**: ending 为空时自动跳过（现有条件保护）

## 5. 主要风险

| 风险 | 概率 | 缓解 |
|---|---|---|
| F2 测试 LLM 不稳定导致偶发失败 | 中 | 宽松断言（出现/消失趋势判断），标记 skip |
| 测试数据未清理干净 | 低 | finally 块强制清理 |

## 6. 实现复杂度评估

**极低**。F1 为两处一行代码追加；F2 为按模式编写测试用例。总计影响 4-5 个文件。

## 7. 可测试性评估

- **F1**: 纯单元测试，Mock LLM，断言返回字典含 `chat_reply` key
- **F2**: 端到端集成测试，依赖真实环境

## 8. 可交付性评估

可独立交付，不依赖其他模块变更。修复后 ChatMessage 表即开始产生数据，测试可验证。
