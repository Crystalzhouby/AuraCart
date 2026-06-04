"""MCL-I5/I6: 提示词扩展 + _parse_response 适配测试。

验证：
1. QUERY_PARSE_SYSTEM 包含 category/sub_category 字段指引
2. GENERATOR_SYSTEM 包含 requirements_summary 模板变量
3. _parse_response 兼容新旧两种 LLM 响应格式
"""
import json
from app.services.query_parser_service import QUERY_PARSE_SYSTEM
from app.agent.prompts.generator_prompt import GENERATOR_SYSTEM
from app.services.query_parser_service import QueryParser


class TestQueryParseSystemPrompt:
    """验证扩展后的 QUERY_PARSE_SYSTEM 提示词。"""

    def test_prompt_includes_category_fields(self):
        """QUERY_PARSE_SYSTEM 应包含 category 和 sub_category 字段说明。"""
        assert "category" in QUERY_PARSE_SYSTEM
        assert "sub_category" in QUERY_PARSE_SYSTEM

    def test_prompt_includes_category_marking_guidance(self):
        """QUERY_PARSE_SYSTEM 应包含品类标记指引。"""
        assert "品类" in QUERY_PARSE_SYSTEM


class TestGeneratorSystemPrompt:
    """验证扩展后的 GENERATOR_SYSTEM 提示词。"""

    def test_prompt_includes_requirements_summary(self):
        """GENERATOR_SYSTEM 应包含 {requirements_summary} 模板变量。"""
        assert "{requirements_summary}" in GENERATOR_SYSTEM


class TestParseResponseAdaptation:
    """验证 _parse_response 对新旧 LLM 响应格式的兼容性。"""

    def test_old_format_without_category(self):
        """旧格式（无 category/sub_category）——解析成功，新字段为 None。"""
        old_response = json.dumps([
            {"text": "蓝牙耳机", "strategy": "keyword",
             "field": None, "operator": None, "value": None, "expanded_values": None}
        ])
        parser = QueryParser(llm=None)
        result = parser._parse_response(old_response)
        assert len(result) == 1
        assert result[0].category is None
        assert result[0].sub_category is None
        assert result[0].text == "蓝牙耳机"

    def test_new_format_with_category(self):
        """新格式（含 category/sub_category）——解析成功，字段正确。"""
        new_response = json.dumps([
            {"text": "防晒霜", "strategy": "keyword",
             "field": None, "operator": None, "value": None, "expanded_values": None,
             "category": "面部护肤", "sub_category": "防晒霜"}
        ])
        parser = QueryParser(llm=None)
        result = parser._parse_response(new_response)
        assert len(result) == 1
        assert result[0].category == "面部护肤"
        assert result[0].sub_category == "防晒霜"

    def test_new_format_with_category_only(self):
        """新格式只含 category 不含 sub_category。"""
        new_response = json.dumps([
            {"text": "跑鞋", "strategy": "keyword",
             "field": None, "operator": None, "value": None, "expanded_values": None,
             "category": "运动户外"}
        ])
        parser = QueryParser(llm=None)
        result = parser._parse_response(new_response)
        assert result[0].category == "运动户外"
        assert result[0].sub_category is None

    def test_mixed_format_some_have_category(self):
        """混合格式：部分有 category，部分无。"""
        response = json.dumps([
            {"text": "防晒霜", "strategy": "keyword",
             "field": None, "operator": None, "value": None, "expanded_values": None,
             "category": "面部护肤", "sub_category": "防晒霜"},
            {"text": "", "strategy": "structured_filter",
             "field": "price", "operator": "lt", "value": 200, "expanded_values": None}
        ])
        parser = QueryParser(llm=None)
        result = parser._parse_response(response)
        assert len(result) == 2
        assert result[0].category == "面部护肤"
        assert result[1].category is None

    def test_unknown_fields_no_error(self):
        """LLM 返回未知字段时不应报错。"""
        response = json.dumps([
            {"text": "test", "strategy": "semantic",
             "field": None, "operator": None, "value": None, "expanded_values": None,
             "unknown_field": "should_not_crash"}
        ])
        parser = QueryParser(llm=None)
        result = parser._parse_response(response)
        assert len(result) == 1
        assert result[0].text == "test"
