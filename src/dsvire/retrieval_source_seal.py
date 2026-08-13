"""Acquire and seal the immutable source set for a retrieval benchmark cycle."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from pypdf import PdfReader

from .retrieval_preregistration import load_retrieval_preregistration

SOURCE_MANIFEST_VERSION = "dsvire.retrieval-cycle-source-manifest.v1"
FROZEN_CYCLE_V2_SHA256 = "6acc99d5621fcd3f73efdc801b7fc7754ac244d600e94b106e6c62712116698d"
_TOKEN = re.compile(r"[a-z0-9]+")


class SourceSealError(ValueError):
    """An official source cannot be acquired without violating the sealed plan."""


class Response(Protocol):
    headers: Mapping[str, str]

    def read(self, size: int = -1) -> bytes: ...
    def geturl(self) -> str: ...
    def __enter__(self) -> Response: ...
    def __exit__(self, *args: object) -> None: ...


OpenUrl = Callable[[urllib.request.Request, float], Response]


class _BoundedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        redirect_dict = getattr(req, "redirect_dict", {})
        if sum(redirect_dict.values()) >= self.maximum:
            raise SourceSealError("official source exceeded the registered redirect limit")
        if urlparse(newurl).scheme != "https":
            raise SourceSealError("official source redirected away from HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_open(maximum_redirects: int) -> OpenUrl:
    opener = urllib.request.build_opener(_BoundedRedirectHandler(maximum_redirects))

    def open_url(request: urllib.request.Request, timeout: float) -> Response:
        return opener.open(request, timeout=timeout)  # type: ignore[no-any-return]

    return open_url


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def manifest_sha256(value: Mapping[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("manifest_sha256", None)
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _identity_markers(family: Mapping[str, str]) -> tuple[str, ...]:
    candidates = _TOKEN.findall(
        f"{family['datasheet_identity']} {family['selected_mpn']} {family['id']}".lower()
    )
    ignored = {"datasheet", "revision", "selected", "calibration", "evaluation"}
    markers = sorted({token for token in candidates if len(token) >= 6 and token not in ignored})
    if not markers:
        raise SourceSealError(f"{family['id']}: no bounded identity marker can be derived")
    return tuple(markers)


def _verify_pdf_identity(
    payload: bytes, family: Mapping[str, str], *, page_limit: int = 32
) -> list[str]:
    if not payload.startswith(b"%PDF-"):
        raise SourceSealError(f"{family['id']}: official response is not a PDF")
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
        if not reader.pages:
            raise SourceSealError(f"{family['id']}: PDF contains no pages")
        pages = list(range(min(len(reader.pages), page_limit)))
        if len(reader.pages) > page_limit:
            pages.extend(range(max(page_limit, len(reader.pages) - 4), len(reader.pages)))
        metadata: Mapping[str, Any] = reader.metadata or {}
        metadata_text = " ".join(str(value) for value in metadata.values() if value)
        text = (
            metadata_text
            + " "
            + " ".join(reader.pages[index].extract_text() or "" for index in pages)
        )
    except SourceSealError:
        raise
    except Exception as exc:
        raise SourceSealError(f"{family['id']}: PDF parsing failed") from exc
    normalized = "".join(_TOKEN.findall(text.lower()))
    matched = [marker for marker in _identity_markers(family) if marker in normalized]
    if not matched:
        raise SourceSealError(f"{family['id']}: declared datasheet identity was not found")
    return matched


def _download_one(
    family: Mapping[str, str],
    *,
    cache_dir: Path,
    max_bytes: int,
    open_url: OpenUrl,
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        family["official_source_url"],
        headers={"User-Agent": "Tokito-DSViRe-Evaluation/1.0", "Accept": "application/pdf"},
    )
    temporary: Path | None = None
    try:
        with open_url(request, timeout_seconds) as response:
            final_url = response.geturl()
            if urlparse(final_url).scheme != "https":
                raise SourceSealError(f"{family['id']}: final source URL is not HTTPS")
            declared = response.headers.get("content-length")
            declared_bytes: int | None = None
            if declared is not None:
                try:
                    declared_bytes = int(declared)
                except ValueError as exc:
                    raise SourceSealError(f"{family['id']}: invalid content-length") from exc
                if declared_bytes < 8 or declared_bytes > max_bytes:
                    raise SourceSealError(f"{family['id']}: declared source size is outside bounds")
            cache_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{family['id']}.", suffix=".tmp", dir=cache_dir, delete=False
            ) as target:
                temporary = Path(target.name)
                digest = hashlib.sha256()
                prefix = b""
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise SourceSealError(f"{family['id']}: source exceeds registered byte cap")
                    if len(prefix) < 8:
                        prefix += chunk[: 8 - len(prefix)]
                    digest.update(chunk)
                    target.write(chunk)
        if declared_bytes is not None and total != declared_bytes:
            raise SourceSealError(
                f"{family['id']}: source was truncated; declared {declared_bytes}, got {total}"
            )
        if total < 8 or not prefix.startswith(b"%PDF-"):
            raise SourceSealError(f"{family['id']}: official response is not a PDF")
        assert temporary is not None
        payload = temporary.read_bytes()
        matched = _verify_pdf_identity(payload, family)
        content_sha256 = digest.hexdigest()
        destination = cache_dir / f"{content_sha256}.pdf"
        if destination.exists():
            if destination.read_bytes() != payload:
                raise SourceSealError(f"{family['id']}: digest collision in local cache")
            temporary.unlink()
        else:
            temporary.replace(destination)
        temporary = None
        return {
            "id": family["id"],
            "split": family["split"],
            "requested_url": family["official_source_url"],
            "final_url": final_url,
            "bytes": total,
            "content_sha256": content_sha256,
            "identity_markers": matched,
            "redistribution": "download_only",
            "status": "sealed",
        }
    except (OSError, urllib.error.URLError) as exc:
        raise SourceSealError(f"{family['id']}: official source request failed") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def acquire_source_manifest(
    plan_value: Any,
    *,
    cache_dir: Path,
    consumed_family_ids: set[str],
    open_url: OpenUrl | None = None,
    timeout_seconds: float = 60,
    attempts: int = 3,
    retry_delay_seconds: float = 1,
) -> dict[str, Any]:
    plan = load_retrieval_preregistration(plan_value, consumed_family_ids=consumed_family_ids)
    if plan.content_sha256 != FROZEN_CYCLE_V2_SHA256:
        raise SourceSealError("refusing an altered or unrecognized retrieval cycle plan")
    acquisition = plan_value["acquisition"]
    opener = open_url or _default_open(acquisition["allowed_redirects"])
    if not 1 <= attempts <= 5:
        raise SourceSealError("source attempts must be within 1..=5")
    if not 0 <= retry_delay_seconds <= 60:
        raise SourceSealError("source retry delay must be within 0..=60 seconds")
    sources: list[dict[str, Any]] = []
    invalidations: list[dict[str, str]] = []
    for family in plan_value["families"]:
        last_error: SourceSealError | None = None
        for attempt in range(1, attempts + 1):
            try:
                sources.append(
                    _download_one(
                        family,
                        cache_dir=cache_dir,
                        max_bytes=acquisition["maximum_pdf_bytes"],
                        open_url=opener,
                        timeout_seconds=timeout_seconds,
                    )
                )
                last_error = None
                break
            except SourceSealError as exc:
                last_error = exc
                if attempt < attempts:
                    time.sleep(retry_delay_seconds * attempt)
        if last_error is not None:
            invalidations.append(
                {"id": family["id"], "reason": str(last_error), "status": "invalidated"}
            )
    manifest: dict[str, Any] = {
        "schema_version": SOURCE_MANIFEST_VERSION,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.content_sha256,
        "sources": sources,
        "invalidations": invalidations,
        "complete": len(sources) == len(plan.family_ids) and not invalidations,
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    validate_source_manifest(manifest, expected_family_ids=set(plan.family_ids))
    return manifest


def validate_source_manifest(value: Any, *, expected_family_ids: set[str]) -> None:
    if not isinstance(value, Mapping):
        raise SourceSealError("source manifest must be an object")
    required = {
        "schema_version",
        "plan_id",
        "plan_sha256",
        "sources",
        "invalidations",
        "complete",
        "manifest_sha256",
    }
    if set(value) != required or value["schema_version"] != SOURCE_MANIFEST_VERSION:
        raise SourceSealError("source manifest keys or version are invalid")
    sources, invalidations = value["sources"], value["invalidations"]
    if not isinstance(sources, list) or not isinstance(invalidations, list):
        raise SourceSealError("source manifest accounting is invalid")
    source_ids = {item.get("id") for item in sources if isinstance(item, Mapping)}
    invalid_ids = {item.get("id") for item in invalidations if isinstance(item, Mapping)}
    if source_ids & invalid_ids or source_ids | invalid_ids != expected_family_ids:
        raise SourceSealError(
            "source manifest does not account for each registered family exactly once"
        )
    if len(source_ids) != len(sources) or len(invalid_ids) != len(invalidations):
        raise SourceSealError("source manifest contains duplicate family records")
    source_keys = {
        "id",
        "split",
        "requested_url",
        "final_url",
        "bytes",
        "content_sha256",
        "identity_markers",
        "redistribution",
        "status",
    }
    final_urls: set[str] = set()
    digests: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping) or set(source) != source_keys:
            raise SourceSealError("sealed source record keys are invalid")
        if (
            not str(source["requested_url"]).startswith("https://")
            or not str(source["final_url"]).startswith("https://")
            or not isinstance(source["bytes"], int)
            or not 8 <= source["bytes"] <= 67_108_864
            or not re.fullmatch(r"[0-9a-f]{64}", str(source["content_sha256"]))
            or source["redistribution"] != "download_only"
            or source["status"] != "sealed"
        ):
            raise SourceSealError("sealed source record is invalid")
        if source["final_url"] in final_urls or source["content_sha256"] in digests:
            raise SourceSealError(
                "distinct families resolved to duplicate official source bytes or URL"
            )
        final_urls.add(source["final_url"])
        digests.add(source["content_sha256"])
    expected_complete = source_ids == expected_family_ids and not invalidations
    if value["complete"] is not expected_complete:
        raise SourceSealError("source manifest completion flag is inconsistent")
    if manifest_sha256(value) != value["manifest_sha256"]:
        raise SourceSealError("source manifest digest is invalid")


def write_manifest_atomic(manifest: Mapping[str, Any], destination: Path) -> None:
    if manifest_sha256(manifest) != manifest.get("manifest_sha256"):
        raise SourceSealError("source manifest digest is invalid")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    ) as target:
        temporary = Path(target.name)
        json.dump(manifest, target, indent=2, sort_keys=True)
        target.write("\n")
    temporary.replace(destination)
