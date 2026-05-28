# tests/test_config.py
"""测试应用配置系统。

验证 Settings 对象能否正确从 YAML 配置文件加载，
数据库 URL 属性是否正确构造，以及环境变量覆盖是否优先于 YAML 值。
"""

import os
from unittest.mock import patch


def test_settings_from_yaml(tmp_path):
    """验证 Settings 从 config.yaml 加载所有字段，并遵循环境变量覆盖。

    创建一个包含数据库与 embedding 配置节的临时 YAML 配置文件，
    然后断言每个字段均被解析到正确的 Settings 属性中。
    同时验证 EMBEDDING_API_KEY 环境变量覆盖 YAML 文件中的 api_key 值。

    参数:
        tmp_path: pytest 临时目录 fixture，用于写入 config.yaml。
    """
    import yaml

    # 构造一份典型的配置结构
    config_data = {
        "database": {
            "host": "localhost",
            "port": 5432,
            "user": "testuser",
            "password": "testpass",
            "dbname": "testdb",
            "vector_dim": 768,
        },
        "embedding": {
            "base_url": "https://test.api.com",
            "api_key": "test-key-123",
            "model": "test-embedding",
        },
    }

    config_path = tmp_path / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)

    # 通过 patch EMBEDDING_API_KEY 来验证环境变量优先级高于配置文件
    with patch.dict(os.environ, {"EMBEDDING_API_KEY": "env-key-override"}):
        from app.config import Settings
        settings = Settings.from_yaml(str(config_path))

    # --- 数据库字段断言 ---
    assert settings.database.host == "localhost"
    assert settings.database.port == 5432
    assert settings.database.user == "testuser"
    assert settings.database.dbname == "testdb"
    assert settings.database.vector_dim == 768

    # --- URL 构造断言 ---
    assert "testuser:testpass@localhost:5432/testdb" in settings.database.url
    assert "psycopg2" in settings.database.sync_url

    # --- Embedding 字段断言 ---
    assert settings.embedding.api_key == "env-key-override"
    assert settings.embedding.model == "test-embedding"
    assert settings.embedding.base_url == "https://test.api.com"


def test_database_url_construction():
    """验证 DatabaseSettings.url 和 DatabaseSettings.sync_url 的连接字符串是否正确拼接。

    使用已知值构造 DatabaseSettings 实例，然后确认异步（asyncpg）
    与同步（psycopg2）URL 属性生成预期的连接字符串。
    """
    from app.config import DatabaseSettings

    db = DatabaseSettings(
        host="db.example.com",
        port=5433,
        user="admin",
        password="secret",
        dbname="mydb",
    )

    assert db.url == "postgresql+asyncpg://admin:secret@db.example.com:5433/mydb"
    assert db.sync_url == "postgresql+psycopg2://admin:secret@db.example.com:5433/mydb"
