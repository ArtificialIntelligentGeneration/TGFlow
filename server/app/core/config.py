import os
from pathlib import Path
from functools import lru_cache
from typing import Optional
from dotenv import load_dotenv


# Load env from default locations
load_dotenv()
load_dotenv("server/.env")


BASE_DIR = Path(__file__).resolve().parents[2]  # points to server/


class Settings:
    """Application settings loaded from environment variables.

    Keep this intentionally simple to avoid heavy deps; works in Docker and local.
    """

    # Environment
    ENV: str = os.getenv("ENV", "dev")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        # Local default: peer auth, unix socket
        "postgresql+psycopg2:///slava_licensing",
    )

    # Redis (rate limiting)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # JWT / Auth
    JWT_PRIVATE_KEY_PATH: Optional[str] = os.getenv(
        "JWT_PRIVATE_KEY_PATH", str(BASE_DIR / "keys" / "jwtRS256.key")
    )
    JWT_PUBLIC_KEY_PATH: Optional[str] = os.getenv(
        "JWT_PUBLIC_KEY_PATH", str(BASE_DIR / "keys" / "jwtRS256.key.pub")
    )
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))  # 7 days
    JWT_ISSUER: str = os.getenv("JWT_ISSUER", "slava-licensing")

    # Business params
    RESERVATION_TTL_MINUTES: int = int(os.getenv("RESERVATION_TTL_MINUTES", "15"))

    # Rate limits
    RATE_LIMIT_PER_TOKEN_RPS: int = int(os.getenv("RATE_LIMIT_PER_TOKEN_RPS", "20"))
    RATE_LIMIT_PER_IP_RPS: int = int(os.getenv("RATE_LIMIT_PER_IP_RPS", "60"))

    # Metrics
    METRICS_ENABLED: bool = os.getenv("METRICS_ENABLED", "true").lower() == "true"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


