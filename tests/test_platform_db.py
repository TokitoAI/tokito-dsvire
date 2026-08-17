from __future__ import annotations

import asyncio
import json
from typing import Any

from dsvire.platform_db import _configure_connection, _encode_json


class FakeConnection:
    def __init__(self) -> None:
        self.codecs: list[tuple[str, dict[str, Any]]] = []

    async def set_type_codec(self, type_name: str, **options: Any) -> None:
        self.codecs.append((type_name, options))


def test_postgres_json_codecs_decode_structures_and_preserve_canonical_writes() -> None:
    connection = FakeConnection()
    asyncio.run(_configure_connection(connection))  # type: ignore[arg-type]
    assert [name for name, _ in connection.codecs] == ["json", "jsonb"]
    for _, options in connection.codecs:
        assert options["decoder"]('{"stage":"queued"}') == {"stage": "queued"}
        assert options["encoder"]({"stage": "queued"}) == '{"stage":"queued"}'
        assert options["encoder"]('{"already":"encoded"}') == '{"already":"encoded"}'
        assert options["format"] == "text"


def test_json_encoder_is_deterministic() -> None:
    assert json.loads(_encode_json({"b": 2, "a": 1})) == {"a": 1, "b": 2}
    assert _encode_json({"b": 2, "a": 1}) == '{"a":1,"b":2}'
