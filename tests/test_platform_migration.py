from __future__ import annotations

from pathlib import Path


def test_platform_migration_handles_existing_enum() -> None:
    migration = (
        Path(__file__).resolve().parents[1] / "src" / "dsvire" / "sql" / "001_platform.sql"
    ).read_text("utf-8")
    assert "WHEN duplicate_object THEN NULL" in migration
    assert "labels IS DISTINCT FROM" in migration
    assert "CREATE TABLE IF NOT EXISTS dsvire_job" in migration
