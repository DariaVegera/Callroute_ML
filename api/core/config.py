from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_env: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = "postgresql+asyncpg://callroute:callroute_secret@postgres:5432/callroute_db"

    # Redis / Celery
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # JWT
    secret_key: str = "supersecretkey_change_in_production_32chars"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # ML / Billing
    low_confidence_threshold: float = 0.55
    default_signup_bonus: int = 100

    # Model paths
    fast_model_path: str = "/app/models/catboost_model.cbm"
    fast_tfidf_path: str = "/app/models/tfidf.pkl"
    smart_model_path: str = "/app/models/smart_model"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
