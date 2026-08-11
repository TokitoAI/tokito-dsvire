from __future__ import annotations

from pathlib import Path

import pytest

from dsvire.config import ConfigurationError, ServiceConfig


def test_environment_configuration_is_strict(tmp_path: Path) -> None:
    config = ServiceConfig.from_env(
        {
            "DSVIRE_DATA_DIR": str(tmp_path),
            "DSVIRE_SERVICE_TOKEN": "x" * 32,
            "DSVIRE_MAX_CONCURRENT_JOBS": "3",
            "DSVIRE_JOB_TIMEOUT_SECONDS": "90",
            "DSVIRE_WORKER_CPU_SECONDS": "80",
        }
    )
    config.validate()
    assert config.max_concurrent_jobs == 3
    assert config.job_timeout_seconds == 90


def test_insecure_mode_requires_explicit_nonproduction_environment(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="SERVICE_TOKEN is required"):
        ServiceConfig(
            data_dir=tmp_path,
            service_token="",
            environment="production",
            allow_insecure_dev=True,
        ).validate()

    ServiceConfig(
        data_dir=tmp_path,
        service_token="",
        environment="development",
        allow_insecure_dev=True,
    ).validate()


def test_short_service_token_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="at least 32"):
        ServiceConfig(data_dir=tmp_path, service_token="too-short").validate()


def test_inconsistent_time_and_size_limits_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="must exceed"):
        ServiceConfig(
            data_dir=tmp_path,
            service_token="x" * 32,
            admission_timeout_seconds=10,
            job_timeout_seconds=5,
            worker_cpu_seconds=4,
        ).validate()
    with pytest.raises(ConfigurationError, match="MAX_PDF_BYTES"):
        ServiceConfig(
            data_dir=tmp_path,
            service_token="x" * 32,
            max_pdf_bytes=65 * 1024 * 1024,
        ).validate()
    with pytest.raises(ConfigurationError, match="MAX_CONCURRENT_JOBS"):
        ServiceConfig(
            data_dir=tmp_path,
            service_token="x" * 32,
            max_concurrent_jobs=0,
        ).validate()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DSVIRE_ALLOW_INSECURE_DEV", "maybe"),
        ("DSVIRE_MAX_CONCURRENT_JOBS", "0"),
        ("DSVIRE_JOB_TIMEOUT_SECONDS", "nan"),
    ],
)
def test_invalid_environment_values_are_rejected(name: str, value: str) -> None:
    with pytest.raises(ConfigurationError):
        ServiceConfig.from_env({name: value})
