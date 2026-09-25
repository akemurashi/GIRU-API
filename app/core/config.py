from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    APP_ENV: str = "development"
    SECRET_KEY: str = ""
    ALLOWED_ORIGINS: List[str] = []

    DATABASE_URL: str = ""

    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""
    AZURE_TENANT_ID: str = ""

    AWS_REGION: str = ""
    COGNITO_USER_POOL_ID: str = ""
    COGNITO_CLIENT_ID: str = ""
    COGNITO_DOMAIN: str = ""
    COGNITO_REDIRECT_URI: str = ""

    GEMMA_BASE_URL: str = ""
    GEMMA_MODEL: str = "gemma4:latest"
    GEMMA_MAX_TOKENS: int = 2048
    GEMMA_TEMPERATURE: float = 0.1

    EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIM: int = 768

    CHUNK_STRATEGY: str = "paragraph"
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 50

    RETRIEVAL_TOP_K: int = 5
    MIN_SIMILARITY_SCORE: float = 0.7

    class Config:
        env_file = ".env"

settings = Settings()
