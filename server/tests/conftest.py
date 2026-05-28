# tests/conftest.py
"""AuraCart 测试套件的共享 pytest fixture 与配置。

提供会话级配置，例如所有异步测试使用的 async 后端
（anyio/pytest-asyncio 集成）。
"""

import pytest


@pytest.fixture(scope="session")
def anyio_backend():
    """返回本会话中所有异步测试使用的 async 后端。

    返回值:
        str: anyio 后端名称（"asyncio"）。
    """
    return "asyncio"
