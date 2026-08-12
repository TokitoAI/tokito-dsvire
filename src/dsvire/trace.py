"""Minimal, dependency-free W3C trace-context handling for the HTTP boundary."""

from __future__ import annotations

import secrets
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    parent_id: str
    flags: str

    @classmethod
    def parse(cls, value: str | None) -> TraceContext | None:
        if value is None or len(value) != 55:
            return None
        parts = value.split("-")
        if len(parts) != 4 or parts[0] != "00":
            return None
        trace_id, parent_id, flags = parts[1:]
        if not (_lower_hex(trace_id, 32) and _lower_hex(parent_id, 16) and _lower_hex(flags, 2)):
            return None
        if int(trace_id, 16) == 0 or int(parent_id, 16) == 0:
            return None
        return cls(trace_id, parent_id, flags)

    @classmethod
    def generate(cls) -> TraceContext:
        return cls(_nonzero_hex(16), _nonzero_hex(8), "01")

    def child(self) -> TraceContext:
        return TraceContext(self.trace_id, _nonzero_hex(8), self.flags)

    def header(self) -> str:
        return f"00-{self.trace_id}-{self.parent_id}-{self.flags}"


def _lower_hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)


def _nonzero_hex(byte_count: int) -> str:
    while True:
        value = secrets.token_hex(byte_count)
        if int(value, 16) != 0:
            return value
