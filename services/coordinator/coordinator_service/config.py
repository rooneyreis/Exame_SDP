"""Configuration from environment variables (set in docker-compose.yml)."""
import os
from dataclasses import dataclass


def _bool(name: str) -> bool:
    return os.environ.get(name, "").lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    ca_file: str = os.environ.get("CA_FILE", "/certs/ca.crt")
    db_user: str = os.environ.get("COORD_DB_USER", "coord_svc")
    db_password: str = os.environ.get("COORD_DB_PASSWORD", "coord-pass")
    public_keys_dir: str = os.environ.get("PUBLIC_KEYS_DIR", "/keys/public")
    trusted_signers: tuple = tuple(os.environ.get("TRUSTED_SIGNERS", "api-1,api-2").split(","))
    max_concurrent_tx: int = int(os.environ.get("MAX_CONCURRENT_TX", "20"))
    participant_timeout: float = float(os.environ.get("PARTICIPANT_TIMEOUT_SECONDS", "10"))
    recovery_interval: float = float(os.environ.get("RECOVERY_INTERVAL_SECONDS", "5"))

    # Settlement with the partner bank (legacy, Java/XML)
    legacy_url: str = os.environ.get("LEGACY_URL", "https://legacy-bank.global.local:9443")
    signing_key: str = os.environ.get("SIGNING_KEY", "/keys/private/coordinator-ed25519.pem")
    legacy_public_key: str = os.environ.get("LEGACY_PUBLIC_KEY", "/keys/public/legacy-bank-ed25519.pub.pem")

    # Fault injection defaults (also settable at runtime with POST /admin/chaos)
    chaos_pause_after_prepare: int = int(os.environ.get("CHAOS_PAUSE_AFTER_PREPARE", "0"))
    chaos_crash_after_prepare: bool = _bool("CHAOS_CRASH_AFTER_PREPARE")
    chaos_crash_after_decision: bool = _bool("CHAOS_CRASH_AFTER_DECISION")
    chaos_fail_participant: str | None = os.environ.get("CHAOS_FAIL_PARTICIPANT") or None


settings = Settings()
