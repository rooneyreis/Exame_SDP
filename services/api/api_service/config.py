"""Configuration from environment variables (set in docker-compose.yml)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    instance_id: str = os.environ.get("INSTANCE_ID", "api-?")
    ca_file: str = os.environ.get("CA_FILE", "/certs/ca.crt")
    jwks_url: str = os.environ.get("JWKS_URL", "https://auth.global.local:8010/.well-known/jwks.json")
    jwks_refresh_seconds: int = int(os.environ.get("JWKS_REFRESH_SECONDS", "600"))
    db_user: str = os.environ.get("API_DB_USER", "api_svc")
    db_password: str = os.environ.get("API_DB_PASSWORD", "api-pass")
    audit_dir: str = os.environ.get("AUDIT_DIR", "/audit")


settings = Settings()
