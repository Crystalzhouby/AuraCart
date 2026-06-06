"""MCL-A2: Memory 工具函数测试。

验证 session_memory 相关的纯函数。
"""
from app.agent.memory import (
    get_recent_queries,
    get_queries_by_category,
    append_query,
)


class TestGetRecentQueries:
    """验证 get_recent_queries 跨品类按时间排序取最近 N 条。"""

    def test_empty_memory(self):
        assert get_recent_queries([], 5) == []

    def test_n_zero(self):
        memory = [{"category": "c1", "sub_category": "s1",
                    "queries": [{"query": "q1", "timestamp": "2026-01-01T00:00:00"}]}]
        assert get_recent_queries(memory, 0) == []

    def test_orders_by_timestamp_desc(self):
        memory = [
            {"category": "a", "sub_category": "a1",
             "queries": [
                 {"query": "old", "timestamp": "2026-01-01T00:00:00"},
                 {"query": "new", "timestamp": "2026-06-01T00:00:00"},
             ]},
        ]
        result = get_recent_queries(memory, 2)
        assert result[0]["query"] == "new"
        assert result[1]["query"] == "old"

    def test_limits_to_n(self):
        memory = [
            {"category": "a", "sub_category": "a1",
             "queries": [
                 {"query": "q1", "timestamp": "2026-01-01T00:00:00"},
                 {"query": "q2", "timestamp": "2026-02-01T00:00:00"},
                 {"query": "q3", "timestamp": "2026-03-01T00:00:00"},
             ]},
        ]
        result = get_recent_queries(memory, 2)
        assert len(result) == 2


class TestGetQueriesByCategory:
    """验证 get_queries_by_category 按品类精确检索。"""

    def test_exact_match(self):
        memory = [
            {"category": "面部护肤", "sub_category": "防晒霜",
             "queries": [{"query": "防晒", "timestamp": "2026-01-01T00:00:00"}]},
        ]
        result = get_queries_by_category(memory, "面部护肤", "防晒霜")
        assert len(result) == 1
        assert result[0]["query"] == "防晒"

    def test_no_match(self):
        memory = [
            {"category": "面部护肤", "sub_category": "防晒霜",
             "queries": [{"query": "防晒", "timestamp": "2026-01-01T00:00:00"}]},
        ]
        result = get_queries_by_category(memory, "服饰运动", "跑步鞋")
        assert result == []

    def test_empty_memory(self):
        assert get_queries_by_category([], "a", "b") == []


class TestAppendQuery:
    """验证 append_query 纯函数行为。"""

    def test_adds_to_existing_group(self):
        memory = [
            {"category": "面部护肤", "sub_category": "防晒霜",
             "queries": [{"query": "防晒", "timestamp": "2026-01-01T00:00:00"}]},
        ]
        result = append_query(
            memory, "轻薄的",
            [{"category": "面部护肤", "sub_category": "防晒霜"}],
            "2026-06-01T00:00:00",
        )
        assert len(result) == 1
        assert len(result[0]["queries"]) == 2

    def test_creates_new_group(self):
        result = append_query(
            [], "跑鞋",
            [{"category": "服饰运动", "sub_category": "跑步鞋"}],
            "2026-06-01T00:00:00",
        )
        assert len(result) == 1
        assert result[0]["category"] == "服饰运动"

    def test_does_not_mutate_original(self):
        memory = [
            {"category": "a", "sub_category": "b",
             "queries": [{"query": "q1", "timestamp": "2026-01-01T00:00:00"}]},
        ]
        result = append_query(
            memory, "q2",
            [{"category": "a", "sub_category": "b"}],
            "2026-06-01T00:00:00",
        )
        assert len(memory[0]["queries"]) == 1
        assert len(result[0]["queries"]) == 2

    def test_unknown_category(self):
        result = append_query(
            [], "闲聊",
            [],
            "2026-06-01T00:00:00",
        )
        assert len(result) == 1
        assert result[0]["category"] is None
