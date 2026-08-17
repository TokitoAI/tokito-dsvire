"""Rebuildable Redis fan-out and Qdrant retrieval acceleration."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient, models
from redis.asyncio import Redis

from .platform_db import PlatformDatabase
from .retrieval_pack import RetrievalPack

logger = logging.getLogger(__name__)
_SAFE_NAME = re.compile(r"[^a-zA-Z0-9_-]")


class RedisEvents:
    def __init__(self, url: str) -> None:
        self.client: Redis = Redis.from_url(
            url,
            decode_responses=False,
            socket_connect_timeout=3,
            socket_timeout=5,
            health_check_interval=30,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def ping(self) -> None:
        await self.client.ping()

    async def publish(self, job_id: str, payload: dict[str, object]) -> None:
        await self.client.publish(
            f"dsvire:job:{job_id}",
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )

    @asynccontextmanager
    async def subscribe(self, job_id: str) -> AsyncIterator[AsyncIterator[None]]:
        pubsub = self.client.pubsub()
        await pubsub.subscribe(f"dsvire:job:{job_id}")

        async def signals() -> AsyncIterator[None]:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5)
                if message is not None:
                    yield None
                else:
                    yield None  # timeout still forces an authoritative PostgreSQL replay

        try:
            yield signals()
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()  # type: ignore[no-untyped-call]


async def dispatch_outbox(
    database: PlatformDatabase, events: RedisEvents, stop: asyncio.Event
) -> None:
    """At-least-once Redis delivery; duplicates are harmless wake-up hints."""
    owner = f"{socket.gethostname()}:{id(asyncio.current_task())}"
    while not stop.is_set():
        try:
            messages = await database.claim_outbox(owner)
            if not messages:
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), 1)
                continue
            for message in messages:
                await events.publish(str(message.aggregate_id), message.payload)
                await database.acknowledge_outbox(owner, message.outbox_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("outbox dispatch failed; PostgreSQL events remain replayable")
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), 2)


class QdrantIndex:
    """Indexes validated immutable packs; collection identity binds exact models."""

    def __init__(self, url: str, api_key: str | None = None) -> None:
        self.client = AsyncQdrantClient(url=url, api_key=api_key, timeout=10)

    @staticmethod
    def collection(pack: RetrievalPack) -> str:
        raw = (
            f"dsvire_{pack.dense_model.sha256[:12]}_{pack.multi_model.sha256[:12]}_"
            f"{pack.dense_dim}_{pack.multi_dim}"
        )
        return _SAFE_NAME.sub("_", raw)[:200]

    async def close(self) -> None:
        await self.client.close()

    async def ping(self) -> None:
        await self.client.get_collections()

    async def ensure_collection(self, pack: RetrievalPack) -> str:
        name = self.collection(pack)
        if not await self.client.collection_exists(name):
            await self.client.create_collection(
                collection_name=name,
                vectors_config={
                    "dense": models.VectorParams(
                        size=pack.dense_dim, distance=models.Distance.COSINE
                    ),
                    "multi": models.VectorParams(
                        size=pack.multi_dim,
                        distance=models.Distance.COSINE,
                        multivector_config=models.MultiVectorConfig(
                            comparator=models.MultiVectorComparator.MAX_SIM
                        ),
                    ),
                },
                on_disk_payload=True,
            )
            await self.client.create_payload_index(
                name, "tenant_id", models.PayloadSchemaType.KEYWORD, wait=True
            )
            await self.client.create_payload_index(
                name, "pack_sha256", models.PayloadSchemaType.KEYWORD, wait=True
            )
        return name

    async def index_pack(self, tenant_id: str, pack: RetrievalPack) -> int:
        name = await self.ensure_collection(pack)
        points = [
            models.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"{tenant_id}:{pack.pack_sha256}:{region.id}")),
                vector={
                    "dense": list(region.dense),
                    "multi": [list(item) for item in region.multi],
                },
                payload={
                    "tenant_id": tenant_id,
                    "pack_sha256": pack.pack_sha256,
                    "source_sha256": pack.source_sha256,
                    "region_id": region.id,
                    "page": region.page,
                    "type": region.region_type,
                    "content_sha256": region.content_sha256,
                    "text_fields": dict(region.text_fields),
                },
            )
            for region in pack.regions
        ]
        for start in range(0, len(points), 128):
            await self.client.upsert(name, points=points[start : start + 128], wait=True)
        return len(points)

    async def search_dense(
        self,
        tenant_id: str,
        pack: RetrievalPack,
        vector: Sequence[float],
        limit: int = 20,
    ) -> list[models.ScoredPoint]:
        if len(vector) != pack.dense_dim:
            raise ValueError("query vector dimension does not match pack")
        response = await self.client.query_points(
            self.collection(pack),
            query=list(vector),
            using="dense",
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="tenant_id", match=models.MatchValue(value=tenant_id)
                    ),
                    models.FieldCondition(
                        key="pack_sha256", match=models.MatchValue(value=pack.pack_sha256)
                    ),
                ]
            ),
            limit=min(max(limit, 1), 100),
            with_payload=True,
        )
        return response.points
