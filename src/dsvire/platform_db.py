"""PostgreSQL authority for DS-ViRe jobs, leases, replay, and outbox delivery."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import asyncpg

from .object_store import ObjectRef


class JobConflict(RuntimeError):
    """An idempotency key was reused for a different request."""


class JobNotFound(LookupError):
    """No job exists for the tenant-scoped identifier."""


@dataclass(frozen=True)
class Lease:
    job_id: UUID
    tenant_id: UUID
    document: ObjectRef
    request: dict[str, Any]
    attempt: int
    cancel_requested: bool


@dataclass(frozen=True)
class OutboxMessage:
    outbox_id: int
    topic: str
    aggregate_id: UUID
    payload: dict[str, Any]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class PlatformDatabase:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, url: str, *, minimum: int = 1, maximum: int = 10) -> PlatformDatabase:
        pool = await asyncpg.create_pool(
            url,
            min_size=minimum,
            max_size=maximum,
            command_timeout=30,
            server_settings={"application_name": "tokito-dsvire"},
        )
        if pool is None:  # pragma: no cover - asyncpg only permits this for custom setup callbacks
            raise RuntimeError("asyncpg did not create a connection pool")
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def migrate(self) -> None:
        migration = (Path(__file__).parent / "sql" / "001_platform.sql").read_text("utf-8")
        async with self.pool.acquire() as connection, connection.transaction():
            # A transaction-scoped advisory lock makes concurrent deploy migrations safe.
            await connection.execute("SELECT pg_advisory_xact_lock($1)", 0x445356495245)
            await connection.execute(migration)

    async def ping(self) -> None:
        async with self.pool.acquire() as connection:
            await connection.fetchval("SELECT 1")

    async def ensure_tenant(self, slug: str) -> UUID:
        async with self.pool.acquire() as connection:
            return cast(
                UUID,
                await connection.fetchval(
                    """
                INSERT INTO dsvire_tenant(slug) VALUES($1)
                ON CONFLICT (slug) DO UPDATE SET slug = EXCLUDED.slug
                RETURNING tenant_id
                """,
                    slug,
                ),
            )

    async def issue_api_key(self, tenant_id: UUID, label: str) -> str:
        """Issue a bearer once; only its SHA-256 digest is persisted."""
        token = f"dsv_live_{secrets.token_urlsafe(32)}"
        digest = hashlib.sha256(token.encode()).hexdigest()
        async with self.pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO dsvire_api_key(tenant_id,label,token_sha256) VALUES($1,$2,$3)",
                tenant_id,
                label,
                digest,
            )
        return token

    async def authenticate(self, token: str) -> UUID | None:
        if not token.startswith("dsv_live_") or len(token) > 128:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        async with self.pool.acquire() as connection:
            return cast(
                UUID | None,
                await connection.fetchval(
                    """
                UPDATE dsvire_api_key SET last_used_at=clock_timestamp()
                WHERE token_sha256=$1 AND revoked_at IS NULL
                RETURNING tenant_id
                """,
                    digest,
                ),
            )

    async def submit(
        self,
        *,
        tenant_id: UUID,
        document: ObjectRef,
        idempotency_key: str,
        request: Mapping[str, object],
        max_attempts: int,
    ) -> tuple[UUID, bool]:
        """Submit exactly once. Returns ``(job_id, created)``."""
        request_json = _json(dict(request))
        async with self.pool.acquire() as connection, connection.transaction():
            document_id = await connection.fetchval(
                """
                INSERT INTO dsvire_document
                    (tenant_id, sha256, byte_size, object_key, content_type)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (tenant_id, sha256) DO UPDATE SET sha256 = EXCLUDED.sha256
                RETURNING document_id
                """,
                tenant_id,
                document.sha256,
                document.size,
                document.key,
                document.content_type,
            )
            row = await connection.fetchrow(
                """
                INSERT INTO dsvire_job
                    (tenant_id, document_id, idempotency_key, request, max_attempts)
                VALUES ($1, $2, $3, $4::jsonb, $5)
                ON CONFLICT (tenant_id, idempotency_key) DO NOTHING
                RETURNING job_id
                """,
                tenant_id,
                document_id,
                idempotency_key,
                request_json,
                max_attempts,
            )
            if row:
                job_id = row["job_id"]
                await self._event(connection, tenant_id, job_id, "queued", {"stage": "queued"})
                return job_id, True
            existing = await connection.fetchrow(
                """
                SELECT job_id, document_id, request FROM dsvire_job
                WHERE tenant_id = $1 AND idempotency_key = $2
                """,
                tenant_id,
                idempotency_key,
            )
            if existing is None:
                raise RuntimeError("idempotent submission disappeared")
            if existing["document_id"] != document_id or dict(existing["request"]) != dict(request):
                raise JobConflict("idempotency key is bound to a different request")
            return existing["job_id"], False

    async def lease_next(self, owner: str, lease_seconds: int) -> Lease | None:
        async with self.pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """
                WITH candidate AS (
                    SELECT job_id FROM dsvire_job
                    WHERE (state = 'queued' OR
                           (state = 'running' AND lease_expires_at < clock_timestamp()))
                      AND attempt < max_attempts AND cancel_requested = false
                    ORDER BY created_at, job_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE dsvire_job j
                SET state = 'running', stage = 'starting', attempt = attempt + 1,
                    lease_owner = $1,
                    lease_expires_at = clock_timestamp() + make_interval(secs => $2)
                FROM candidate c, dsvire_document d
                WHERE j.job_id = c.job_id AND d.document_id = j.document_id
                RETURNING j.job_id, j.tenant_id, j.request, j.attempt, j.cancel_requested,
                          d.object_key, d.sha256, d.byte_size, d.content_type
                """,
                owner,
                lease_seconds,
            )
            if row is None:
                return None
            await self._event(
                connection,
                row["tenant_id"],
                row["job_id"],
                "leased",
                {"attempt": row["attempt"]},
            )
            return Lease(
                row["job_id"],
                row["tenant_id"],
                ObjectRef(row["object_key"], row["sha256"], row["byte_size"], row["content_type"]),
                dict(row["request"]),
                row["attempt"],
                row["cancel_requested"],
            )

    async def heartbeat(self, job_id: UUID, owner: str, stage: str, lease_seconds: int) -> bool:
        async with self.pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """
                UPDATE dsvire_job SET stage = $3,
                    lease_expires_at = clock_timestamp() + make_interval(secs => $4)
                WHERE job_id = $1 AND lease_owner = $2 AND state = 'running'
                  AND lease_expires_at >= clock_timestamp()
                RETURNING tenant_id, cancel_requested
                """,
                job_id,
                owner,
                stage,
                lease_seconds,
            )
            if row is None:
                return False
            await self._event(connection, row["tenant_id"], job_id, "progress", {"stage": stage})
            return not row["cancel_requested"]

    async def finish(
        self,
        job_id: UUID,
        owner: str,
        *,
        result: Mapping[str, object] | None = None,
        error_code: str | None = None,
        retryable: bool = False,
    ) -> None:
        async with self.pool.acquire() as connection, connection.transaction():
            current = await connection.fetchrow(
                "SELECT tenant_id, attempt, max_attempts, cancel_requested FROM dsvire_job "
                "WHERE job_id=$1 AND lease_owner=$2 AND state='running' FOR UPDATE",
                job_id,
                owner,
            )
            if current is None:
                raise JobNotFound("active lease not found")
            if current["cancel_requested"]:
                state, stage, kind = "cancelled", "cancelled", "cancelled"
            elif result is not None:
                state, stage, kind = "succeeded", "complete", "succeeded"
            elif retryable and current["attempt"] < current["max_attempts"]:
                state, stage, kind = "queued", "retrying", "retrying"
            else:
                state, stage, kind = "failed", "failed", "failed"
            terminal = state in {"succeeded", "failed", "cancelled"}
            await connection.execute(
                """
                UPDATE dsvire_job SET state=$3::dsvire_job_state, stage=$4,
                    result=$5::jsonb, error_code=$6, lease_owner=NULL, lease_expires_at=NULL,
                    completed_at=CASE WHEN $7 THEN clock_timestamp() ELSE NULL END
                WHERE job_id=$1 AND lease_owner=$2
                """,
                job_id,
                owner,
                state,
                stage,
                _json(dict(result)) if result is not None else None,
                error_code,
                terminal,
            )
            await self._event(
                connection,
                current["tenant_id"],
                job_id,
                kind,
                {"error_code": error_code} if error_code else {},
            )

    async def request_cancel(self, tenant_id: UUID, job_id: UUID) -> bool:
        async with self.pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                """
                UPDATE dsvire_job SET cancel_requested=true,
                    state=CASE WHEN state='queued' THEN 'cancelled'::dsvire_job_state ELSE state END,
                    stage=CASE WHEN state='queued' THEN 'cancelled' ELSE stage END,
                    completed_at=CASE WHEN state='queued' THEN clock_timestamp() ELSE completed_at END
                WHERE tenant_id=$1 AND job_id=$2
                  AND state IN ('queued', 'running')
                RETURNING state
                """,
                tenant_id,
                job_id,
            )
            if row is None:
                return False
            await self._event(connection, tenant_id, job_id, "cancel_requested", {})
            return True

    async def get_job(self, tenant_id: UUID, job_id: UUID) -> dict[str, Any]:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT job_id, state::text, stage, attempt, max_attempts, cancel_requested,
                       result, error_code, created_at, updated_at, completed_at
                FROM dsvire_job WHERE tenant_id=$1 AND job_id=$2
                """,
                tenant_id,
                job_id,
            )
        if row is None:
            raise JobNotFound("job not found")
        return {key: value for key, value in dict(row).items()}

    async def events(
        self, tenant_id: UUID, job_id: UUID, after: int = 0, limit: int = 500
    ) -> list[dict[str, Any]]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT event_id, kind, payload, created_at FROM dsvire_job_event
                WHERE tenant_id=$1 AND job_id=$2 AND event_id>$3
                ORDER BY event_id LIMIT $4
                """,
                tenant_id,
                job_id,
                after,
                min(max(limit, 1), 500),
            )
        return [dict(row) for row in rows]

    async def claim_outbox(self, owner: str, limit: int = 100) -> list[OutboxMessage]:
        async with self.pool.acquire() as connection, connection.transaction():
            rows = await connection.fetch(
                """
                WITH candidate AS (
                    SELECT outbox_id FROM dsvire_outbox
                    WHERE published_at IS NULL
                      AND (lock_expires_at IS NULL OR lock_expires_at < clock_timestamp())
                    ORDER BY outbox_id FOR UPDATE SKIP LOCKED LIMIT $2
                )
                UPDATE dsvire_outbox o SET lock_owner=$1,
                    lock_expires_at=clock_timestamp() + interval '30 seconds',
                    attempts=attempts+1
                FROM candidate c WHERE o.outbox_id=c.outbox_id
                RETURNING o.outbox_id,o.topic,o.aggregate_id,o.payload
                """,
                owner,
                min(max(limit, 1), 500),
            )
        return [
            OutboxMessage(row["outbox_id"], row["topic"], row["aggregate_id"], dict(row["payload"]))
            for row in rows
        ]

    async def acknowledge_outbox(self, owner: str, outbox_id: int) -> bool:
        async with self.pool.acquire() as connection:
            status = str(
                await connection.execute(
                    """
                UPDATE dsvire_outbox SET published_at=clock_timestamp(),
                    lock_owner=NULL,lock_expires_at=NULL
                WHERE outbox_id=$1 AND lock_owner=$2 AND published_at IS NULL
                """,
                    outbox_id,
                    owner,
                )
            )
        return status == "UPDATE 1"

    @staticmethod
    async def _event(
        connection: asyncpg.Connection,
        tenant_id: UUID,
        job_id: UUID,
        kind: str,
        payload: Mapping[str, object],
    ) -> None:
        event_id = await connection.fetchval(
            "INSERT INTO dsvire_job_event(job_id, tenant_id, kind, payload) "
            "VALUES($1,$2,$3,$4::jsonb) RETURNING event_id",
            job_id,
            tenant_id,
            kind,
            _json(dict(payload)),
        )
        await connection.execute(
            "INSERT INTO dsvire_outbox(topic, aggregate_id, payload) "
            "VALUES('dsvire.job.event',$1,$2::jsonb)",
            job_id,
            _json({"event_id": event_id, "tenant_id": str(tenant_id), "kind": kind}),
        )


@asynccontextmanager
async def database(url: str) -> AsyncIterator[PlatformDatabase]:
    store = await PlatformDatabase.connect(url)
    try:
        yield store
    finally:
        await store.close()
