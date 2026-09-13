import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

    # Database
    DATABASE_URL: str = Field(
        default="postgresql://localhost:5432/terralens",
        description="Sync PostgreSQL connection string for migrations/scripts",
    )
    DATABASE_ASYNC_URL: str = Field(
        default="postgresql+asyncpg://localhost:5432/terralens",
        description="Async PostgreSQL connection string for FastAPI endpoints",
    )

    # AI Agent Provider (gemini or openai)
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gemini-2.0-flash"

    # Geospatial Thresholds & Parameters
    DEFAULT_CLOUD_COVER_THRESHOLD: float = 20.0
    DEFAULT_NDVI_CHANGE_THRESHOLD: float = -0.20
    MIN_CHANGE_AREA_M2: float = 500.0
    SPATIAL_SEARCH_RADIUS_METERS: float = 1000.0

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
