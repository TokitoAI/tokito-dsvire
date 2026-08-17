from pathlib import Path

import pytest

from dsvire.config import ConfigurationError
from dsvire.platform_config import PlatformConfig


def _env() -> dict[str, str]:
    return {
        "DSVIRE_DATABASE_URL": "postgresql://dsvire:secret@postgres/dsvire",
        "DSVIRE_OBJECT_BUCKET": "dsvire",
        "DSVIRE_LOCAL_OBJECT_DIR": "objects",
        "DSVIRE_REDIS_URL": "redis://valkey:6379/0",
        "DSVIRE_QDRANT_URL": "http://qdrant:6333",
        "DSVIRE_PUBLIC_BASE_URL": "https://dsvire.tokito.dev",
    }


def test_platform_config_accepts_self_hosted_local_objects() -> None:
    config = PlatformConfig.from_env(_env())
    assert config.local_object_dir == Path("objects")
    assert config.max_attempts == 5


def test_platform_config_requires_https_public_origin() -> None:
    env = _env() | {"DSVIRE_PUBLIC_BASE_URL": "http://public.example"}
    with pytest.raises(ConfigurationError, match="must use HTTPS"):
        PlatformConfig.from_env(env)


def test_s3_mode_requires_credentials() -> None:
    env = _env()
    del env["DSVIRE_LOCAL_OBJECT_DIR"]
    with pytest.raises(ConfigurationError, match="credentials"):
        PlatformConfig.from_env(env)


def test_secrets_can_be_loaded_from_compose_secret_files(tmp_path: Path) -> None:
    secret = tmp_path / "database-url"
    secret.write_text("postgresql://dsvire:secret@postgres/dsvire\n", encoding="utf-8")
    env = _env()
    del env["DSVIRE_DATABASE_URL"]
    env["DSVIRE_DATABASE_URL_FILE"] = str(secret)
    assert PlatformConfig.from_env(env).database_url.endswith("@postgres/dsvire")
