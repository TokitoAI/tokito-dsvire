"""Fail-closed configuration for the durable DS-ViRe platform services."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .config import ConfigurationError


def _required(env: Mapping[str, str], name: str) -> str:
    value = _secret(env, name)
    if not value:
        raise ConfigurationError(f"{name} is required when DSVIRE_PLATFORM_ENABLED=true")
    return value


def _secret(env: Mapping[str, str], name: str) -> str:
    direct = env.get(name, "").strip()
    file_name = env.get(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ConfigurationError(f"set only one of {name} and {name}_FILE")
    if file_name:
        try:
            return Path(file_name).read_text("utf-8").strip()
        except OSError as exc:
            raise ConfigurationError(f"cannot read {name}_FILE") from exc
    return direct


def _positive_int(env: Mapping[str, str], name: str, default: int, maximum: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < 1 or value > maximum:
        raise ConfigurationError(f"{name} must be in 1..={maximum}")
    return value


@dataclass(frozen=True)
class PlatformConfig:
    """Connections and limits for the distributed runtime.

    Secrets are read from the environment at process start and never serialized.  Object
    keys are opaque and tenant scoped; the public API never accepts a caller supplied key.
    """

    database_url: str
    object_endpoint: str
    object_region: str
    object_bucket: str
    object_access_key: str
    object_secret_key: str
    redis_url: str
    qdrant_url: str
    qdrant_api_key: str | None
    public_base_url: str
    upload_ttl_seconds: int = 900
    lease_seconds: int = 90
    event_retention_days: int = 30
    max_attempts: int = 5
    local_object_dir: Path | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> PlatformConfig:
        values = os.environ if env is None else env
        local_dir = values.get("DSVIRE_LOCAL_OBJECT_DIR", "").strip()
        config = cls(
            database_url=_required(values, "DSVIRE_DATABASE_URL"),
            object_endpoint=values.get("DSVIRE_OBJECT_ENDPOINT", "").strip(),
            object_region=values.get("DSVIRE_OBJECT_REGION", "us-east-1").strip(),
            object_bucket=_required(values, "DSVIRE_OBJECT_BUCKET"),
            object_access_key=_secret(values, "DSVIRE_OBJECT_ACCESS_KEY"),
            object_secret_key=_secret(values, "DSVIRE_OBJECT_SECRET_KEY"),
            redis_url=_required(values, "DSVIRE_REDIS_URL"),
            qdrant_url=_required(values, "DSVIRE_QDRANT_URL"),
            qdrant_api_key=_secret(values, "DSVIRE_QDRANT_API_KEY") or None,
            public_base_url=_required(values, "DSVIRE_PUBLIC_BASE_URL").rstrip("/"),
            upload_ttl_seconds=_positive_int(values, "DSVIRE_UPLOAD_TTL_SECONDS", 900, 86_400),
            lease_seconds=_positive_int(values, "DSVIRE_LEASE_SECONDS", 90, 3_600),
            event_retention_days=_positive_int(values, "DSVIRE_EVENT_RETENTION_DAYS", 30, 3650),
            max_attempts=_positive_int(values, "DSVIRE_MAX_ATTEMPTS", 5, 20),
            local_object_dir=Path(local_dir) if local_dir else None,
        )
        config.validate()
        return config

    def validate(self) -> None:
        database = urlparse(self.database_url)
        if database.scheme not in {"postgres", "postgresql"} or not database.hostname:
            raise ConfigurationError("DSVIRE_DATABASE_URL must be a PostgreSQL URL")
        if urlparse(self.redis_url).scheme not in {"redis", "rediss"}:
            raise ConfigurationError("DSVIRE_REDIS_URL must use redis:// or rediss://")
        if urlparse(self.qdrant_url).scheme not in {"http", "https"}:
            raise ConfigurationError("DSVIRE_QDRANT_URL must be an HTTP(S) URL")
        if urlparse(self.public_base_url).scheme != "https":
            raise ConfigurationError("DSVIRE_PUBLIC_BASE_URL must use HTTPS")
        if self.local_object_dir is None:
            if not self.object_access_key or not self.object_secret_key:
                raise ConfigurationError(
                    "object-store credentials are required unless DSVIRE_LOCAL_OBJECT_DIR is set"
                )
            if self.object_endpoint and urlparse(self.object_endpoint).scheme not in {
                "http",
                "https",
            }:
                raise ConfigurationError("DSVIRE_OBJECT_ENDPOINT must be an HTTP(S) URL")
