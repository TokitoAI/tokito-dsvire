"""Fail-closed execution order for retrieval cycles. Agents cannot author queries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from .retrieval_authoring import RetrievalAuthoringError, load_authoring_packet, load_authoring_seal
from .retrieval_preregistration import (
    RetrievalPreregistrationError,
    load_retrieval_preregistration,
)
from .retrieval_source_seal import FROZEN_PLAN_DIGESTS, SourceSealError, validate_source_manifest

ROOT = Path(__file__).resolve().parents[2]
CYCLE_V4_PLAN_ID = "dsvire-colsmol-egvv-cycle-v4@2026-08-13"
CYCLE_V4_SOURCE_MANIFEST_SHA256 = "90d4b2019d284627ef50dded91159b9d4639187d4a39e9346280345292a9fefc"
CYCLE_V4_PACKET_SHA256 = "021118687daf969490ee0f5b6289de4549e42bb76fe63d0038fe96c28ba5cb68"
CYCLE_V5_PLAN_ID = "dsvire-colsmol-egvv-cycle-v5@2026-09-17"
CYCLE_V5_SOURCE_MANIFEST_SHA256 = "aa8d7e1fa855df0014f0731b24e5f4ea2f6bebef5c4d78fb1685ad3f816fc74c"
CYCLE_V5_PACKET_SHA256 = "adc10af069a817fdfb06f0b8c5bfb1bf1c32ca71fe995c421fc848adda4b9f65"
Stage = Literal[
    "preregistered",
    "sources_incomplete",
    "sources_complete",
    "packet_ready",
    "awaiting_human_authoring",
    "awaiting_independent_review",
    "scores_authorized",
]


class CycleExecutionError(ValueError):
    """Cycle v4 cannot advance without violating the frozen execution order."""


@dataclass(frozen=True)
class CycleStatus:
    plan_id: str
    stage: Stage
    sources_complete: bool
    invalidations: tuple[str, ...]
    source_manifest_sha256: str | None
    packet_sha256: str | None
    score_access_authorized: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "dsvire.cycle-execution.v1",
            "plan_id": self.plan_id,
            "stage": self.stage,
            "sources_complete": self.sources_complete,
            "invalidations": list(self.invalidations),
            "source_manifest_sha256": self.source_manifest_sha256,
            "packet_sha256": self.packet_sha256,
            "score_access_authorized": self.score_access_authorized,
            "blockers": list(self.blockers),
        }


def _consumed_family_ids(root: Path, *, excluding_plan_id: str) -> set[str]:
    consumed: set[str] = set()
    evaluation = root / "evaluation"
    for path in sorted(evaluation.glob("retrieval_cycle_v*_preregistration.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise CycleExecutionError(f"{path.name} is not an object")
        if str(payload.get("plan_id", "")) == excluding_plan_id:
            continue
        families = payload.get("families")
        if not isinstance(families, list):
            raise CycleExecutionError(f"{path.name} has no families")
        for family in families:
            if isinstance(family, dict) and isinstance(family.get("id"), str):
                consumed.add(family["id"])
    return consumed


def load_cycle_v4_plan(root: Path = ROOT) -> dict[str, Any]:
    path = root / "evaluation" / "retrieval_cycle_v4_preregistration.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise CycleExecutionError("cycle v4 plan is not an object")
    try:
        loaded = load_retrieval_preregistration(
            plan, consumed_family_ids=_consumed_family_ids(root, excluding_plan_id=CYCLE_V4_PLAN_ID)
        )
    except RetrievalPreregistrationError as exc:
        raise CycleExecutionError(str(exc)) from exc
    expected = FROZEN_PLAN_DIGESTS.get(loaded.plan_id)
    if loaded.plan_id != CYCLE_V4_PLAN_ID or expected != loaded.content_sha256:
        raise CycleExecutionError("refusing an altered or unrecognized cycle v4 plan")
    return cast(dict[str, Any], plan)


def inspect_cycle_v4(
    *,
    root: Path = ROOT,
    source_manifest: Mapping[str, Any] | None = None,
    packet: Mapping[str, Any] | None = None,
    submission: Mapping[str, Any] | None = None,
    seal: Mapping[str, Any] | None = None,
) -> CycleStatus:
    plan = load_cycle_v4_plan(root)
    family_ids = {item["id"] for item in plan["families"]}
    blockers: list[str] = []
    invalidations: tuple[str, ...] = ()
    sources_complete = False
    manifest_sha: str | None = None
    if source_manifest is None:
        committed = json.loads(
            (root / "evaluation" / "retrieval_cycle_v4_source_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        source_manifest = committed
    try:
        validate_source_manifest(source_manifest, expected_family_ids=family_ids)
        sources_complete = bool(source_manifest.get("complete")) and not source_manifest.get(
            "invalidations"
        )
        manifest_sha = str(source_manifest["manifest_sha256"])
        if sources_complete:
            raise CycleExecutionError(
                "cycle v4 is retired; official MMA8451Q source was invalidated without replacement"
            )
        if manifest_sha != CYCLE_V4_SOURCE_MANIFEST_SHA256:
            raise CycleExecutionError("live source manifest digest drifted from the retired cycle")
    except (SourceSealError, CycleExecutionError, KeyError, TypeError) as exc:
        blockers.append(str(exc))
        sources_complete = False
    raw_invalid = (
        source_manifest.get("invalidations") if isinstance(source_manifest, Mapping) else []
    )
    if isinstance(raw_invalid, list):
        invalidations = tuple(
            str(item.get("id"))
            for item in raw_invalid
            if isinstance(item, Mapping) and item.get("id")
        )
        if invalidations:
            blockers.append(
                "official source invalidated without replacement: " + ", ".join(invalidations)
            )

    packet_sha: str | None = None
    if packet is None:
        packet = json.loads(
            (root / "evaluation" / "retrieval_cycle_v4_authoring_packet.json").read_text(
                encoding="utf-8"
            )
        )
    try:
        loaded_packet = load_authoring_packet(packet)
        packet_sha = str(loaded_packet["packet_sha256"])
        if packet_sha != CYCLE_V4_PACKET_SHA256:
            raise CycleExecutionError("authoring packet digest drifted from the frozen cycle")
    except (RetrievalAuthoringError, CycleExecutionError) as exc:
        blockers.append(str(exc))

    score_access = False
    stage: Stage
    if not sources_complete:
        stage = "sources_incomplete"
        blockers.append("cycle v4 is retired; the live visual gate is cycle v5")
    elif submission is None and seal is None:
        stage = "awaiting_human_authoring"
        blockers.append("Human A must author regions and natural queries; agents must not")
    elif seal is None:
        stage = "awaiting_independent_review"
        blockers.append("Human B must independently review and seal before score access")
    else:
        if packet is None or submission is None:
            raise CycleExecutionError("seal validation requires packet and submission")
        try:
            loaded_seal = load_authoring_seal(seal, packet, submission)
        except RetrievalAuthoringError as exc:
            raise CycleExecutionError(str(exc)) from exc
        if not loaded_seal.get("score_access_authorized"):
            raise CycleExecutionError("seal does not authorize score access")
        score_access = True
        stage = "scores_authorized"
        if score_access:
            blockers.clear()
    return CycleStatus(
        plan_id=CYCLE_V4_PLAN_ID,
        stage=stage,
        sources_complete=sources_complete,
        invalidations=invalidations,
        source_manifest_sha256=manifest_sha,
        packet_sha256=packet_sha,
        score_access_authorized=score_access,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def load_cycle_v5_plan(root: Path = ROOT) -> dict[str, Any]:
    path = root / "evaluation" / "retrieval_cycle_v5_preregistration.json"
    plan = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise CycleExecutionError("cycle v5 plan is not an object")
    try:
        loaded = load_retrieval_preregistration(
            plan, consumed_family_ids=_consumed_family_ids(root, excluding_plan_id=CYCLE_V5_PLAN_ID)
        )
    except RetrievalPreregistrationError as exc:
        raise CycleExecutionError(str(exc)) from exc
    expected = FROZEN_PLAN_DIGESTS.get(loaded.plan_id)
    if loaded.plan_id != CYCLE_V5_PLAN_ID or expected != loaded.content_sha256:
        raise CycleExecutionError("refusing an altered or unrecognized cycle v5 plan")
    return cast(dict[str, Any], plan)


def inspect_cycle_v5(
    *,
    root: Path = ROOT,
    source_manifest: Mapping[str, Any] | None = None,
    packet: Mapping[str, Any] | None = None,
    submission: Mapping[str, Any] | None = None,
    seal: Mapping[str, Any] | None = None,
) -> CycleStatus:
    plan = load_cycle_v5_plan(root)
    family_ids = {item["id"] for item in plan["families"]}
    blockers: list[str] = []
    invalidations: tuple[str, ...] = ()
    sources_complete = False
    manifest_sha: str | None = None
    if source_manifest is None:
        source_manifest = json.loads(
            (root / "evaluation" / "retrieval_cycle_v5_source_manifest.json").read_text(
                encoding="utf-8"
            )
        )
    try:
        validate_source_manifest(source_manifest, expected_family_ids=family_ids)
        sources_complete = bool(source_manifest.get("complete")) and not source_manifest.get(
            "invalidations"
        )
        manifest_sha = str(source_manifest["manifest_sha256"])
        if sources_complete and manifest_sha != CYCLE_V5_SOURCE_MANIFEST_SHA256:
            raise CycleExecutionError("live source manifest digest drifted from the frozen cycle")
    except (SourceSealError, CycleExecutionError, KeyError, TypeError) as exc:
        blockers.append(str(exc))
        sources_complete = False
    raw_invalid = (
        source_manifest.get("invalidations") if isinstance(source_manifest, Mapping) else []
    )
    if isinstance(raw_invalid, list):
        invalidations = tuple(
            str(item.get("id"))
            for item in raw_invalid
            if isinstance(item, Mapping) and item.get("id")
        )
        if invalidations:
            blockers.append(
                "official source invalidated without replacement: " + ", ".join(invalidations)
            )

    packet_sha: str | None = None
    if packet is None:
        packet = json.loads(
            (root / "evaluation" / "retrieval_cycle_v5_authoring_packet.json").read_text(
                encoding="utf-8"
            )
        )
    try:
        loaded_packet = load_authoring_packet(packet)
        packet_sha = str(loaded_packet["packet_sha256"])
        if packet_sha != CYCLE_V5_PACKET_SHA256:
            raise CycleExecutionError("authoring packet digest drifted from the frozen cycle")
    except (RetrievalAuthoringError, CycleExecutionError) as exc:
        blockers.append(str(exc))

    score_access = False
    stage: Stage
    if not sources_complete:
        stage = "sources_incomplete"
        blockers.append("acquire the exact official PDFs before authoring or scoring")
    elif submission is None and seal is None:
        stage = "awaiting_human_authoring"
        blockers.append("Human A must author regions and natural queries; agents must not")
    elif seal is None:
        stage = "awaiting_independent_review"
        blockers.append("Human B must independently review and seal before score access")
    else:
        if packet is None or submission is None:
            raise CycleExecutionError("seal validation requires packet and submission")
        try:
            loaded_seal = load_authoring_seal(seal, packet, submission)
        except RetrievalAuthoringError as exc:
            raise CycleExecutionError(str(exc)) from exc
        if not loaded_seal.get("score_access_authorized"):
            raise CycleExecutionError("seal does not authorize score access")
        score_access = True
        stage = "scores_authorized"
        blockers.clear()
    return CycleStatus(
        plan_id=CYCLE_V5_PLAN_ID,
        stage=stage,
        sources_complete=sources_complete,
        invalidations=invalidations,
        source_manifest_sha256=manifest_sha,
        packet_sha256=packet_sha,
        score_access_authorized=score_access,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def assert_score_access_authorized(status: CycleStatus) -> None:
    if not status.score_access_authorized:
        raise CycleExecutionError(
            "score access is forbidden until sources, human authoring, and independent review are sealed"
        )
