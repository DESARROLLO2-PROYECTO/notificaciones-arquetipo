from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración 12-factor: solo variables de entorno (R6)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str  # p. ej. postgresql+psycopg://usuario:clave@host:5432/base
    log_level: str = "INFO"
    # amqp://... en local o amqps://... (CloudAMQP). Sin valor, la cola queda deshabilitada.
    amqp_url: str | None = None
    amqp_timeout_s: float = 5.0  # conexión y confirmación de cada publicación


@lru_cache
def get_settings() -> Settings:
    return Settings()
