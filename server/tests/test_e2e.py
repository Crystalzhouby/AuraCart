# tests/test_e2e.py
"""端到端测试：样本数据校验、解析、分块与导入流水线。

验证 ecommerce_agent_dataset_sample 目录下的样本 JSON 文件格式正确、
覆盖多个品类，并且生成的 RAG 分块数量和结构符合预期。
这些测试作为完整数据导入流水线的冒烟测试。
"""

import json
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.import_data_service import chunk_product, DataImporter


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "ecommerce_agent_dataset_sample")


def test_all_sample_files_exist():
    """验证预期的三个样本数据文件均存在于数据集目录中。

    测试套件依赖 sample_001.json 至 sample_003.json 以进行流水线
    和覆盖率校验。
    """
    files = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".json"))
    assert len(files) == 3
    assert "sample_001.json" in files
    assert "sample_002.json" in files
    assert "sample_003.json" in files


def test_all_sample_files_valid_json():
    """验证每个样本 JSON 文件均为合法 JSON 且包含必需的顶层键。

    每个文件必须包含 product_id、title、skus（非空列表）
    以及 rag_knowledge 节。
    """
    for f in os.listdir(DATA_DIR):
        if f.endswith(".json"):
            with open(os.path.join(DATA_DIR, f), "r", encoding="utf-8") as fp:
                data = json.load(fp)

            assert "product_id" in data
            assert "title" in data

            # skus 必须是非空列表
            assert "skus" in data
            assert isinstance(data["skus"], list)
            assert len(data["skus"]) > 0

            assert "rag_knowledge" in data


def test_sample_data_chunk_counts():
    """验证每个样本商品至少生成一个结构正确的 RAG 分块。

    每个分块必须满足：
      - source 为 "marketing"、"faq"、"user_review" 之一。
      - content 为非空字符串。
      - metadata 为字典。
    """
    for f in sorted(os.listdir(DATA_DIR)):
        if not f.endswith(".json"):
            continue
        with open(os.path.join(DATA_DIR, f), "r", encoding="utf-8") as fp:
            data = json.load(fp)

        chunks = chunk_product(data)

        # 每个样本必须产生至少一个分块
        assert len(chunks) > 0, f"{f} should produce at least 1 chunk"

        # 验证每个分块的结构
        for source, content, metadata in chunks:
            assert source in ("marketing", "faq", "user_review")
            assert isinstance(content, str)
            assert len(content) > 0
            assert isinstance(metadata, dict)


def test_cross_category_coverage():
    """验证样本数据集至少覆盖两个不同的商品品类。

    确保测试数据涵盖多个品类（如美妆护肤和数码电子），
    以便进行有意义的跨品类搜索和生成测试。
    """
    categories = set()
    for f in os.listdir(DATA_DIR):
        if f.endswith(".json"):
            with open(os.path.join(DATA_DIR, f), "r", encoding="utf-8") as fp:
                data = json.load(fp)
            categories.add(data.get("category", ""))

    assert len(categories) >= 2, f"Expected >=2 categories, got {len(categories)}: {categories}"
