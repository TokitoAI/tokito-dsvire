"""Content-addressed object storage with verified reads and atomic local writes."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KINDS = frozenset({"pdf", "crop", "evidence", "pack", "symbol", "report", "bundle"})


class ObjectIntegrityError(RuntimeError):
    """Stored bytes do not match their immutable reference."""


@dataclass(frozen=True)
class ObjectRef:
    key: str
    sha256: str
    size: int
    content_type: str


def object_key(tenant_id: str, kind: str, digest: str, suffix: str) -> str:
    if kind not in _KINDS or not _SHA256.fullmatch(digest):
        raise ValueError("invalid object kind or digest")
    safe_tenant = re.sub(r"[^a-zA-Z0-9_-]", "", tenant_id)
    safe_suffix = re.sub(r"[^a-zA-Z0-9.]", "", suffix).lstrip(".")
    if not safe_tenant or safe_tenant != tenant_id or not safe_suffix:
        raise ValueError("invalid tenant or suffix")
    return f"tenants/{safe_tenant}/{kind}/{digest[:2]}/{digest}.{safe_suffix}"


class ObjectStore(Protocol):
    async def put_immutable(
        self, tenant_id: str, kind: str, payload: bytes, suffix: str, content_type: str
    ) -> ObjectRef: ...

    async def read_verified(self, ref: ObjectRef) -> bytes: ...

    async def presign_get(self, ref: ObjectRef, expires_seconds: int) -> str: ...


class LocalObjectStore:
    """Filesystem backend for single-node self-hosting and deterministic tests."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if self.root not in candidate.parents:
            raise ValueError("object key escapes storage root")
        return candidate

    async def put_immutable(
        self, tenant_id: str, kind: str, payload: bytes, suffix: str, content_type: str
    ) -> ObjectRef:
        digest = hashlib.sha256(payload).hexdigest()
        ref = ObjectRef(
            object_key(tenant_id, kind, digest, suffix), digest, len(payload), content_type
        )
        path = self._path(ref.key)
        await asyncio.to_thread(self._write_atomic, path, payload)
        return ref

    @staticmethod
    def _write_atomic(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.exists():
            existing = path.read_bytes()
            if existing != payload:
                raise ObjectIntegrityError("immutable object collision")
            return
        descriptor, temporary = tempfile.mkstemp(prefix=".upload-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    async def read_verified(self, ref: ObjectRef) -> bytes:
        payload = await asyncio.to_thread(self._path(ref.key).read_bytes)
        if len(payload) != ref.size or hashlib.sha256(payload).hexdigest() != ref.sha256:
            raise ObjectIntegrityError("object size or SHA-256 mismatch")
        return payload

    async def presign_get(self, ref: ObjectRef, expires_seconds: int) -> str:
        raise RuntimeError("local object storage does not issue public download URLs")


class S3ObjectStore:
    """S3-compatible backend. Blocking SDK calls are isolated from the event loop."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        access_key: str,
        secret_key: str,
        endpoint: str = "",
    ) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    async def put_immutable(
        self, tenant_id: str, kind: str, payload: bytes, suffix: str, content_type: str
    ) -> ObjectRef:
        digest = hashlib.sha256(payload).hexdigest()
        ref = ObjectRef(
            object_key(tenant_id, kind, digest, suffix), digest, len(payload), content_type
        )

        def upload() -> None:
            self.client.put_object(
                Bucket=self.bucket,
                Key=ref.key,
                Body=payload,
                ContentType=content_type,
                Metadata={"sha256": digest},
                IfNoneMatch="*",
            )

        from botocore.exceptions import ClientError

        try:
            await asyncio.to_thread(upload)
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status not in {409, 412}:
                raise
            existing = await self.read_verified(ref)
            if existing != payload:
                raise ObjectIntegrityError("immutable object collision") from exc
        return ref

    async def read_verified(self, ref: ObjectRef) -> bytes:
        response = await asyncio.to_thread(
            self.client.get_object, Bucket=self.bucket, Key=ref.key, ChecksumMode="ENABLED"
        )
        payload = cast(bytes, await asyncio.to_thread(response["Body"].read))
        if len(payload) != ref.size or hashlib.sha256(payload).hexdigest() != ref.sha256:
            raise ObjectIntegrityError("object size or SHA-256 mismatch")
        return payload

    async def presign_get(self, ref: ObjectRef, expires_seconds: int) -> str:
        if expires_seconds < 1 or expires_seconds > 3600:
            raise ValueError("download expiry must be in 1..=3600 seconds")
        head = await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=ref.key)
        metadata = head.get("Metadata", {})
        if head.get("ContentLength") != ref.size or metadata.get("sha256") != ref.sha256:
            raise ObjectIntegrityError("object metadata does not match immutable reference")
        return await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": ref.key},
            ExpiresIn=expires_seconds,
        )
