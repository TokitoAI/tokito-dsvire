import asyncio
import hashlib
from pathlib import Path

import pytest

from dsvire.object_store import LocalObjectStore, ObjectIntegrityError, ObjectRef, object_key


def test_object_key_is_tenant_scoped_and_content_addressed() -> None:
    digest = "a" * 64
    assert object_key("tenant_1", "pdf", digest, "pdf") == (
        f"tenants/tenant_1/pdf/aa/{digest}.pdf"
    )
    with pytest.raises(ValueError):
        object_key("../escape", "pdf", digest, "pdf")


def test_local_store_is_immutable_and_verifies_reads(tmp_path: Path) -> None:
    async def exercise() -> None:
        store = LocalObjectStore(tmp_path)
        payload = b"%PDF-1.7 test"
        first = await store.put_immutable("tenant", "pdf", payload, "pdf", "application/pdf")
        second = await store.put_immutable("tenant", "pdf", payload, "pdf", "application/pdf")
        assert first == second
        assert await store.read_verified(first) == payload

        path = tmp_path / first.key
        path.write_bytes(b"corrupted")
        with pytest.raises(ObjectIntegrityError):
            await store.read_verified(first)

    asyncio.run(exercise())


def test_verified_read_rejects_wrong_reference(tmp_path: Path) -> None:
    async def exercise() -> None:
        store = LocalObjectStore(tmp_path)
        ref = await store.put_immutable("tenant", "report", b"report", "json", "application/json")
        wrong = ObjectRef(ref.key, hashlib.sha256(b"other").hexdigest(), ref.size, ref.content_type)
        with pytest.raises(ObjectIntegrityError):
            await store.read_verified(wrong)

    asyncio.run(exercise())
