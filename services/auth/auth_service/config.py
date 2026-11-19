"""Configuration from environment variables (set in docker-compose.yml)."""
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_dsn: str = os.environ.get("AUTH_DB_DSN", "")
    jwt_private_key: Path = Path(os.environ.get("JWT_PRIVATE_KEY", "/keys/private/auth-rs256.pem"))
    data_key: Path = Path(os.environ.get("DATA_KEY", "/keys/private/auth-data.key"))
    ca_file: str = os.environ.get("CA_FILE", "/certs/ca.crt")
    # api instances that create accounts after KYC (tried in order: if one is down, the next)
    api_urls: list[str] = field(default_factory=lambda: [
        u.strip() for u in os.environ.get(
            "API_URLS", "https://api-1.global.local:8000,https://api-2.global.local:8000"
        ).split(",") if u.strip()
    ])
    access_ttl_seconds: int = 15 * 60
    refresh_ttl_days: int = 7
    service_token_ttl_seconds: int = 60


settings = Settings()
