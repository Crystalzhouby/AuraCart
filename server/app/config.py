"""
应用配置模块。

从 YAML 配置文件（默认：``config.yaml``）加载并验证配置项，
支持通过环境变量覆盖。配置项按领域分组到各个子配置类中，
并通过一个 ``settings`` 单例统一暴露。

核心功能：
- 数据库连接参数（异步与同步）
- Embedding 服务的凭证与模型
- LLM 服务的凭证与模型
- 搜索权重与检索限制
- 后台同步调度
- 请求超时阈值
"""

import os
from pathlib import Path
import yaml
from pydantic_settings import BaseSettings


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并两个字典，override 中的值覆盖 base 中的值。"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class DatabaseSettings(BaseSettings):
    """PostgreSQL 连接参数与向量维度配置。"""

    host: str = "localhost"
    """数据库主机地址。"""

    port: int = 5432
    """数据库端口号。"""

    user: str = "postgres"
    """数据库用户名。"""

    password: str = "123456"
    """数据库密码。"""

    dbname: str = "ecommerce"
    """目标数据库名称。"""

    vector_dim: int = 1024
    """pgvector 向量维度（必须与 embedding 模型输出维度一致）。"""

    @property
    def url(self) -> str:
        """
        基于 asyncpg 驱动的异步数据库连接 URL。

        返回值:
            str: 用于异步操作的 PostgreSQL 连接字符串。
        """
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"

    @property
    def sync_url(self) -> str:
        """
        基于 psycopg2 驱动的同步数据库连接 URL。

        返回值:
            str: 用于同步操作（如 Alembic 迁移）的 PostgreSQL 连接字符串。
        """
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.dbname}"


class EmbeddingSettings(BaseSettings):
    """文本 Embedding 服务的配置。"""

    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    """Embedding API 端点的基础 URL。"""

    api_key: str = ""
    """Embedding 服务的 API 密钥。建议通过环境变量设置。"""

    model: str = "doubao-embedding"
    """Embedding 请求使用的模型标识。"""

    batch_size: int = 20
    """单次 API 调用中嵌入的文本数量。"""


class LLMSettings(BaseSettings):
    """大语言模型服务的配置。"""

    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    """LLM API 端点的基础 URL。"""

    api_key: str = ""
    """LLM 服务的 API 密钥。建议通过环境变量设置。"""

    model: str = "doubao-seed-2.0-lite"
    """聊天/补全请求使用的模型标识。"""

    temperature: float = 0.3
    """采样温度，控制回复的随机性（0.0 表示确定性输出）。"""


class SearchSettings(BaseSettings):
    """多源搜索与检索的配置。"""

    rrf_k: int = 60
    """RRF 融合平滑参数，调节排名差异的权重。"""

    top_k_per_query: int = 20
    """单次查询从每条路径检索的最大候选数量。"""

    final_sku_limit: int = 10
    """RRF 融合后返回给用户的最大 SKU 数量。"""


class SyncSettings(BaseSettings):
    """后台数据同步循环的配置。"""

    interval_s: int = 2
    """同步周期间的轮询间隔（秒）。"""

    enabled: bool = True
    """启动时是否启用后台同步。"""


class LogSettings(BaseSettings):
    """日志配置。"""

    level: str = "INFO"
    """日志级别：DEBUG / INFO / WARNING / ERROR。默认 INFO。"""

    dir: str = "log"
    """日志文件输出目录。相对于 server/ 目录。"""


class DatasetSettings(BaseSettings):
    """商品数据集路径配置。"""

    dir: str = "data/ecommerce_agent_dataset_"
    """数据集根目录路径，相对于项目根目录。"""


class TimeoutSettings(BaseSettings):
    """搜索管道各阶段的超时阈值。"""

    query_parse: float = 3.0
    """自然语言查询解析的超时时间（秒）。"""

    retrieval: float = 1.0
    """跨源向量检索的超时时间（秒）。"""

    generation: float = 15.0
    """LLM 答案生成的超时时间（秒）。"""

    total_request: float = 30.0
    """整个搜索请求生命周期的总超时时间（秒）。"""


class Settings(BaseSettings):
    """
    根配置类，聚合所有子配置组。

    实例化时使用默认子配置；调用 ``from_yaml()`` 方法从文件加载。
    """

    database: DatabaseSettings = DatabaseSettings()
    dataset: DatasetSettings = DatasetSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    llm: LLMSettings = LLMSettings()
    log: LogSettings = LogSettings()
    search: SearchSettings = SearchSettings()
    sync: SyncSettings = SyncSettings()
    timeout: TimeoutSettings = TimeoutSettings()

    @classmethod
    def from_yaml(cls, path: str = "config.yaml") -> "Settings":
        """
        从 YAML 配置文件加载配置。

        配置文件的查找顺序：
        1. ``AURACART_CONFIG`` 环境变量（如已设置）。
        2. 传入的 ``path`` 参数。
        3. 回退搜索：当前工作目录，然后是 server 根目录。

        API 密钥会从环境变量（``EMBEDDING_API_KEY``、
        ``LLM_API_KEY``）合并，以避免在 YAML 中存储敏感信息。

        参数:
            path: YAML 配置文件的相对或绝对路径。
                默认为 ``config.yaml``。

        返回值:
            Settings: 完全初始化后的配置实例。

        异常:
            FileNotFoundError: 找不到配置文件时抛出。
        """
        # 允许通过环境变量覆盖配置文件的位置
        env_path = os.environ.get("AURACART_CONFIG")
        if env_path:
            path = env_path

        config_path = Path(path)
        # 相对路径先按当前工作目录解析，再按 server 模块根目录解析
        if not config_path.is_absolute():
            cwd_candidate = Path.cwd() / config_path
            module_root_candidate = Path(__file__).resolve().parents[1] / config_path
            if cwd_candidate.exists():
                config_path = cwd_candidate
            elif module_root_candidate.exists():
                config_path = module_root_candidate

        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # --- 合并 .secrets.yaml（API 密钥等敏感信息） ---
        if not env_path:
            secrets_path = config_path.parent / ".secrets.yaml"
            if secrets_path.exists():
                with secrets_path.open("r", encoding="utf-8") as sf:
                    secrets_data = yaml.safe_load(sf) or {}
                _deep_merge(data, secrets_data)

        # --- 从 YAML 各节构建独立的配置组 ---
        db_data = data.get("database", {})
        db = DatabaseSettings(**db_data)

        emb_data = data.get("embedding", {})
        emb_data["api_key"] = os.environ.get(
            "EMBEDDING_API_KEY", emb_data.get("api_key", "")
        )
        emb = EmbeddingSettings(**emb_data)

        llm_data = data.get("llm", {})
        llm_data["api_key"] = os.environ.get(
            "LLM_API_KEY", llm_data.get("api_key", "")
        )
        llm = LLMSettings(**llm_data)

        search_data = data.get("search", {})
        search = SearchSettings(**search_data)

        sync_data = data.get("sync", {})
        sync = SyncSettings(**sync_data)

        timeout_data = data.get("timeout", {})
        timeout = TimeoutSettings(**timeout_data)

        dataset_data = data.get("dataset", {})
        dataset = DatasetSettings(**dataset_data)

        log_data = data.get("log", {})
        log_data["level"] = os.environ.get("AURACART_LOG_LEVEL", log_data.get("level", "INFO"))
        log = LogSettings(**log_data)

        return cls(database=db, dataset=dataset, embedding=emb, llm=llm, search=search, sync=sync, timeout=timeout, log=log)


# 模块级配置单例 —— 在导入时一次性初始化
settings = Settings.from_yaml()
