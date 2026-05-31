"""MCL-A2: Memory 工具函数测试。

验证 count_tokens 和 truncate_by_tokens 两个纯函数。
"""
import json
from app.agent.memory import count_tokens, truncate_by_tokens


def test_count_tokens_empty_list():
    """空历史的 token 数应为 0。"""
    assert count_tokens([]) == 0


def test_count_tokens_basic():
    """基本 token 计数：char/4 估算。"""
    history = [{"sub_queries": [{"text": "蓝牙耳机", "strategy": "keyword"}]}]
    serialized = json.dumps(history, ensure_ascii=False)
    expected = len(serialized) // 4
    assert count_tokens(history) == expected


def test_count_tokens_returns_int():
    """count_tokens 应返回 int 类型。"""
    assert isinstance(count_tokens([{"sub_queries": [{"text": "test"}]}]), int)


def test_truncate_by_tokens_no_truncation_needed():
    """token 数不超阈值时不截断。"""
    history = [{"sub_queries": [{"text": "短文本", "strategy": "keyword"}]}]
    result = truncate_by_tokens(history, max_tokens=10000)
    assert len(result) == len(history)


def test_truncate_by_tokens_removes_oldest_first():
    """截断时应从最旧的元素开始丢弃（FIFO）。"""
    history = [
        {"sub_queries": [{"text": "A" * 2000}]},  # ~500 tokens
        {"sub_queries": [{"text": "B" * 2000}]},  # ~500 tokens
        {"sub_queries": [{"text": "C" * 2000}]},  # ~500 tokens
    ]
    # 总 token ~1500，阈值 ~600 token → 应保留最后 2 个
    result = truncate_by_tokens(history, max_tokens=600)
    assert len(result) < len(history)
    # 最旧的被丢弃
    assert result[0]["sub_queries"][0]["text"][0] != "A"


def test_truncate_by_tokens_keeps_at_least_one():
    """即使第一个元素就超出阈值，也应保留至少 1 个元素。"""
    history = [{"sub_queries": [{"text": "X" * 10000}]}]
    result = truncate_by_tokens(history, max_tokens=10)
    assert len(result) >= 1


def test_truncate_by_tokens_empty_list():
    """空历史截断后仍为空。"""
    result = truncate_by_tokens([], max_tokens=100)
    assert result == []


def test_truncate_by_tokens_edge_case_exact_threshold():
    """恰好等于阈值时不截断。"""
    history = [{"sub_queries": [{"text": "T" * 40}]}]  # ~10 tokens
    total = count_tokens(history)
    result = truncate_by_tokens(history, max_tokens=total)
    assert len(result) == len(history)
