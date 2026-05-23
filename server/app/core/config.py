from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI电商导购后端API"
    app_env: str = "local"
    api_prefix: str = "/api"
    ark_api_key: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3/"
    ark_model: str = "ep-20260514111645-lmgt2"
    sqlite_url: str = "sqlite:///./storage/ecom_guide.db"
    chroma_persist_dir: str = "./.chroma"
    product_data_path: str = "data/processed/products.jsonl"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
