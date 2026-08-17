"""Validated runtime configuration for the hosted DS-ViRe service."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .pipeline import MAX_PDF_BYTES as PIPELINE_MAX_PDF_BYTES


class ConfigurationError(RuntimeError):
    """The service configuration is unsafe or internally inconsistent."""


def _secret(env: Mapping[str, str], name: str) -> str:
    direct = env.get(name, "").strip()
    file_name = env.get(f"{name}_FILE", "").strip()
    if direct and file_name:
        raise ConfigurationError(f"set only one of {name} and {name}_FILE")
    if not file_name:
        return direct
    try:
        return Path(file_name).read_text("utf-8").strip()
    except OSError as exc:
        raise ConfigurationError(f"cannot read {name}_FILE") from exc


def _bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean")


def _int(env: Mapping[str, str], name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = env.get(name)
    try:
        value = default if raw is None else int(raw.strip())
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise ConfigurationError(f"{name} must be in {minimum}..={maximum}")
    return value


def _float(
    env: Mapping[str, str], name: str, default: float, *, minimum: float, maximum: float
) -> float:
    raw = env.get(name)
    try:
        value = default if raw is None else float(raw.strip())
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise ConfigurationError(f"{name} must be in {minimum}..={maximum}")
    return value


@dataclass(frozen=True)
class ServiceConfig:
    """All limits are per API process unless stated otherwise."""

    data_dir: Path
    service_token: str
    environment: str = "production"
    allow_insecure_dev: bool = False
    max_pdf_bytes: int = 64 * 1024 * 1024
    max_concurrent_jobs: int = 1
    admission_timeout_seconds: float = 2.0
    job_timeout_seconds: float = 75.0
    worker_cpu_seconds: int = 60
    worker_memory_bytes: int = 1536 * 1024 * 1024
    worker_file_bytes: int = 512 * 1024 * 1024
    max_query_bytes: int = 8 * 1024 * 1024
    max_concurrent_queries: int = 2
    query_timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ServiceConfig:
        values = os.environ if env is None else env
        return cls(
            data_dir=Path(values.get("DSVIRE_DATA_DIR", "/data/dsvire")),
            service_token=_secret(values, "DSVIRE_SERVICE_TOKEN"),
            environment=values.get("DSVIRE_ENVIRONMENT", "production").strip().casefold(),
            allow_insecure_dev=_bool(values, "DSVIRE_ALLOW_INSECURE_DEV"),
            max_pdf_bytes=_int(
                values,
                "DSVIRE_MAX_PDF_BYTES",
                PIPELINE_MAX_PDF_BYTES,
                minimum=1024,
                maximum=PIPELINE_MAX_PDF_BYTES,
            ),
            max_concurrent_jobs=_int(
                values, "DSVIRE_MAX_CONCURRENT_JOBS", 1, minimum=1, maximum=32
            ),
            admission_timeout_seconds=_float(
                values,
                "DSVIRE_ADMISSION_TIMEOUT_SECONDS",
                2.0,
                minimum=0.1,
                maximum=60.0,
            ),
            job_timeout_seconds=_float(
                values,
                "DSVIRE_JOB_TIMEOUT_SECONDS",
                75.0,
                minimum=1.0,
                maximum=3600.0,
            ),
            worker_cpu_seconds=_int(
                values, "DSVIRE_WORKER_CPU_SECONDS", 60, minimum=1, maximum=3600
            ),
            worker_memory_bytes=_int(
                values,
                "DSVIRE_WORKER_MEMORY_BYTES",
                1536 * 1024 * 1024,
                minimum=256 * 1024 * 1024,
                maximum=64 * 1024 * 1024 * 1024,
            ),
            worker_file_bytes=_int(
                values,
                "DSVIRE_WORKER_FILE_BYTES",
                512 * 1024 * 1024,
                minimum=64 * 1024 * 1024,
                maximum=8 * 1024 * 1024 * 1024,
            ),
            max_query_bytes=_int(
                values,
                "DSVIRE_MAX_QUERY_BYTES",
                8 * 1024 * 1024,
                minimum=1024,
                maximum=64 * 1024 * 1024,
            ),
            max_concurrent_queries=_int(
                values, "DSVIRE_MAX_CONCURRENT_QUERIES", 2, minimum=1, maximum=32
            ),
            query_timeout_seconds=_float(
                values, "DSVIRE_QUERY_TIMEOUT_SECONDS", 10.0, minimum=0.1, maximum=300.0
            ),
        )

    def validate(self) -> None:
        ranges = (
            ("DSVIRE_MAX_PDF_BYTES", self.max_pdf_bytes, 1024, PIPELINE_MAX_PDF_BYTES, True),
            ("DSVIRE_MAX_CONCURRENT_JOBS", self.max_concurrent_jobs, 1, 32, True),
            (
                "DSVIRE_ADMISSION_TIMEOUT_SECONDS",
                self.admission_timeout_seconds,
                0.1,
                60,
                False,
            ),
            ("DSVIRE_JOB_TIMEOUT_SECONDS", self.job_timeout_seconds, 1, 3600, False),
            ("DSVIRE_WORKER_CPU_SECONDS", self.worker_cpu_seconds, 1, 3600, True),
            (
                "DSVIRE_WORKER_MEMORY_BYTES",
                self.worker_memory_bytes,
                256 * 1024 * 1024,
                64 * 1024 * 1024 * 1024,
                True,
            ),
            (
                "DSVIRE_WORKER_FILE_BYTES",
                self.worker_file_bytes,
                64 * 1024 * 1024,
                8 * 1024 * 1024 * 1024,
                True,
            ),
            ("DSVIRE_MAX_QUERY_BYTES", self.max_query_bytes, 1024, 64 * 1024 * 1024, True),
            ("DSVIRE_MAX_CONCURRENT_QUERIES", self.max_concurrent_queries, 1, 32, True),
            ("DSVIRE_QUERY_TIMEOUT_SECONDS", self.query_timeout_seconds, 0.1, 300, False),
        )
        for name, value, minimum, maximum, integer_only in ranges:
            expected = int if integer_only else int | float
            if not isinstance(value, expected) or isinstance(value, bool):
                raise ConfigurationError(f"{name} must be numeric")
            if not math.isfinite(value) or value < minimum or value > maximum:
                raise ConfigurationError(f"{name} must be in {minimum}..={maximum}")
        if self.environment not in {"production", "staging", "development", "test"}:
            raise ConfigurationError(
                "DSVIRE_ENVIRONMENT must be production, staging, development, or test"
            )
        if self.service_token:
            if len(self.service_token.encode("utf-8")) < 32:
                raise ConfigurationError("DSVIRE_SERVICE_TOKEN must be at least 32 UTF-8 bytes")
        elif not (self.environment in {"development", "test"} and self.allow_insecure_dev):
            raise ConfigurationError(
                "DSVIRE_SERVICE_TOKEN is required; unauthenticated mode is only available "
                "with DSVIRE_ENVIRONMENT=development|test and DSVIRE_ALLOW_INSECURE_DEV=true"
            )
        if self.job_timeout_seconds <= self.admission_timeout_seconds:
            raise ConfigurationError(
                "DSVIRE_JOB_TIMEOUT_SECONDS must exceed DSVIRE_ADMISSION_TIMEOUT_SECONDS"
            )
        if self.worker_cpu_seconds > int(self.job_timeout_seconds) + 1:
            raise ConfigurationError(
                "DSVIRE_WORKER_CPU_SECONDS must not exceed DSVIRE_JOB_TIMEOUT_SECONDS"
            )

    def prepare(self) -> None:
        """Validate configuration and prove the persistent data path is writable."""
        self.validate()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            self.data_dir.chmod(0o700)
        probe = self.data_dir / f".write-probe-{os.getpid()}"
        try:
            with probe.open("xb") as handle:
                handle.write(b"ready")
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            probe.unlink(missing_ok=True)
