from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FARMHAND_", env_file=".env")

    database_url: str = "postgresql+psycopg://farmhand:farmhand@localhost:2727/farmhand"
    storage_root: str = "./storage"
    # The Storage settings page may only pick folders under here (where network
    # shares get mounted for the container). Empty = the parent of storage_root.
    storage_browse_root: str = ""
    host: str = "0.0.0.0"
    port: int = 4545

    # Rolling-window versioning, per spec
    full_file_version_window: int = 5


settings = Settings()
