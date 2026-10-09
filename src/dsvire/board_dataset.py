"""Source-bound inventory of the app dataset; visual labels never become part IDs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .pipeline import RetrievalError

PLAN_SCHEMA = "dsvire.board-symbol-plan.v1"
MAX_METADATA_BYTES = 16 * 1024 * 1024


def dataset_file(root: Path, relative: str) -> Path:
    """Resolve a regular, bounded input without escaping the dataset root."""
    base = root.resolve()
    candidate = (base / relative).resolve()
    if not candidate.is_relative_to(base) or not candidate.is_file():
        raise RetrievalError("dataset input is missing or escapes its root")
    return candidate


def metadata(root: Path, relative: str) -> tuple[Any, dict[str, str]]:
    path = dataset_file(root, relative)
    with path.open("rb") as handle:
        payload = handle.read(MAX_METADATA_BYTES + 1)
    if len(payload) > MAX_METADATA_BYTES:
        raise RetrievalError("dataset metadata exceeds its byte limit")
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise RetrievalError("invalid dataset metadata") from exc
    return value, {"path": relative, "sha256": hashlib.sha256(payload).hexdigest()}


def _identity_value(value: object) -> str | None:
    if not isinstance(value, str) or value.strip() in {"", "-", "?", "unknown"}:
        return None
    return value.strip()


def plan_board_symbols(dataset_root: Path, board_family: str) -> dict[str, Any]:
    """Inventory source candidates, preserving specimen/source mismatch and unknowns.

    The source-bundles registry owns board selection. There is deliberately no
    fuzzy family match and no fallback to another board's richer BOM.
    """
    bundles, registry_source = metadata(dataset_root, "data/photo-model/source-bundles.json")
    if not isinstance(bundles, dict) or board_family not in bundles:
        raise RetrievalError("unknown dataset board family")
    bundle = bundles[board_family]
    if not isinstance(bundle, dict) or not isinstance(bundle.get("path"), str):
        raise RetrievalError("invalid board source bundle")
    source_dir = bundle["path"]
    # Resolve even when no machine-readable inventory exists.
    resolved_dir = (dataset_root.resolve() / source_dir).resolve()
    if not resolved_dir.is_relative_to(dataset_root.resolve()) or not resolved_dir.is_dir():
        raise RetrievalError("board source directory is missing or escapes its root")
    sources = [registry_source]
    components: list[dict[str, Any]] = []
    inventory_path = f"{source_dir}/structured-source/schematic-component-inventory.json"
    if (resolved_dir / "structured-source/schematic-component-inventory.json").is_file():
        inventory, source = metadata(dataset_root, inventory_path)
        if not isinstance(inventory, list):
            raise RetrievalError("invalid schematic component inventory")
        sources.append(source)
        for row_index, row in enumerate(inventory):
            if not isinstance(row, dict) or not isinstance(row.get("parameters"), dict):
                raise RetrievalError("invalid component inventory row")
            parameters = row["parameters"]
            components.append(
                {
                    "candidate_id": f"inventory:{row_index}",
                    "reference": _identity_value(row.get("designator")),
                    "manufacturer": _identity_value(parameters.get("Mfg")),
                    "mpn": _identity_value(parameters.get("Mfg code")),
                    "package": None,
                    "library_reference": row.get("library_reference"),
                    "source": source,
                    "source_record_index": row.get("record_index"),
                    "status": "needs_identity_package_datasheet_and_specimen_review",
                }
            )
    # These annotations are partial visual seeds. Even a class score near 1
    # cannot assert manufacturer, MPN, package, refdes or board registration.
    for annotation_path in (
        "data/photo-model/component-seed-annotations.json",
        "data/photo-model/large-board-component-seeds.json",
        "data/photo-model/nxp-component-seeds.json",
    ):
        annotation, source = metadata(dataset_root, annotation_path)
        if not isinstance(annotation, dict):
            raise RetrievalError("invalid visual annotation metadata")
        sources.append(source)
        images = annotation.get("images", [])
        if not isinstance(images, list):
            raise RetrievalError("invalid visual annotation images")
        # The NXP file uses one top-level image and annotations array.
        if annotation_path.endswith("/nxp-component-seeds.json"):
            images = [
                {
                    "board_family": "nxp_frdm_mcxn236_board",
                    "objects": annotation.get("annotations", []),
                }
            ]
        for image_index, image in enumerate(images):
            if not isinstance(image, dict) or not isinstance(image.get("objects", []), list):
                raise RetrievalError("invalid visual annotation image")
            family = image.get("board_family")
            # The visual seed file's explicit spelling differs from the registry.
            if family == "ultimainboard_2_1_4":
                family = "ultimainboard"
            if family != board_family:
                continue
            for object_index, obj in enumerate(image.get("objects", [])):
                if not isinstance(obj, dict):
                    raise RetrievalError("invalid visual annotation object")
                components.append(
                    {
                        "candidate_id": f"{Path(annotation_path).stem}:{image_index}:{object_index}",
                        "reference": None,
                        "manufacturer": None,
                        "mpn": None,
                        "package": None,
                        "component_class": obj.get("class", obj.get("class_name")),
                        "source": source,
                        "status": "unidentified_visual_seed",
                    }
                )
    return {
        "schema_version": PLAN_SCHEMA,
        "board_family": board_family,
        "source_relation": bundle.get("relation"),
        "exact_component_mapping": bundle.get("exact_component_mapping") is True,
        "mapping_requirement": bundle.get("exact_component_mapping"),
        "incompatible_bundle": bundle.get("incompatible_bundle"),
        "sources": sources,
        "components": components,
        "generation_ready_count": 0,
        "publication_allowed": False,
    }
