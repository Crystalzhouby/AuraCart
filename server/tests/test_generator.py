"""测试 GENERATOR_SYSTEM 提示词模板。

Generator 类已随非流式模式移除，Agent 工作流使用 option_gen 节点
生成后续选项。此文件保留对 GENERATOR_SYSTEM 模板的验证。
"""

import pytest


# ---------------------------------------------------------------------------
# GENERATOR_SYSTEM prompt 规则验证
# ---------------------------------------------------------------------------


class TestGeneratorPrompt:
    """验证 GENERATOR_SYSTEM 包含预期的行为约束规则。"""

    def test_reasoning_max_chars_placeholder(self):
        """字数限制使用占位符，非硬编码。"""
        from app.agent.prompts.generator_prompt import GENERATOR_SYSTEM
        assert "{reasoning_max_chars}" in GENERATOR_SYSTEM

    def test_requirements_summary_placeholder(self):
        """GENERATOR_SYSTEM 应包含 {requirements_summary} 模板变量。"""
        from app.agent.prompts.generator_prompt import GENERATOR_SYSTEM
        assert "{requirements_summary}" in GENERATOR_SYSTEM

    def test_anti_fabrication_rule(self):
        """GENERATOR_SYSTEM 应包含反编造规则。"""
        from app.agent.prompts.generator_prompt import GENERATOR_SYSTEM
        assert "MUST NOT 编造" in GENERATOR_SYSTEM
        assert "目前商品信息中未提及" in GENERATOR_SYSTEM
