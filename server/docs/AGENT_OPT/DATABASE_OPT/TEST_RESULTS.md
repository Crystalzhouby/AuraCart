# DATABASE_OPT 测试结果

> 测试环境: conda AuraCart (Python 3.12.13)
> 测试日期: 2026-06-09

## F1: ChatMessage 持久化单元测试

| 用例 | 结果 |
|---|---|
| `test_router_chat_stream_returns_chat_reply` | PASSED |
| `test_router_chat_nonstream_returns_chat_reply` | PASSED |
| `test_router_explicit_does_not_overwrite_chat_reply` | PASSED |
| `test_option_gen_returns_chat_reply` | PASSED |
| `test_option_gen_empty_ending` | PASSED |

## F2: 实时数据感知集成测试

| 用例 | 结果 |
|---|---|
| `test_data_awareness_insert_and_delete` | PASSED |

### 测试详情

- **Phase 1 (插入前)**: 搜索 "DATABASE_OPT_TEST_MARKER 精华液推荐" → RRF 融合 7 个商品 → rerank 后 5 个 → 不含测试商品
- **Phase 2 (插入后)**: 插入 3 个测试商品 → 相同搜索 → RRF 融合 8 个商品 → rerank 后 5 个 → 找到 `p_test_aware_001`
- **Phase 3 (删除后)**: 删除测试商品 → 相同搜索 → RRF 融合 7 个商品 → 不含测试商品

## 回归测试

所有离线测试 125 passed (不含网络依赖测试)，0 回归。
