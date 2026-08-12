from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from dsvire.visual_adapters import RapidOcrAdapter, TextLayoutAdapter
from dsvire.visual_registry import (
    VisualRegistryError,
    bind_prediction_scores,
    load_visual_registry_data,
)


def _identity(mpn: str = "A-1", package: str = "SOIC-8") -> dict[str, str]:
    return {"manufacturer": "Acme", "mpn": mpn, "package": package}


def _case(
    case_id: str,
    label: str,
    region_type: str,
    *,
    identity: dict[str, str] | None = None,
    view: str = "not_applicable",
) -> dict:
    return {
        "id": case_id,
        "label": label,
        "region_type": region_type,
        "page": 3,
        "bbox_norm": [0.1, 0.2, 0.8, 0.7],
        "view": view,
        "claimed_identity": identity or _identity(),
        "rationale": "Synthetic reviewed annotation.",
    }


def _registry(split: str = "calibration", reviewed: bool = True) -> dict:
    return {
        "schema_version": "dsvire.visual-eval-registry.v1",
        "documents": [
            {
                "id": "acme-a1-rev1",
                "document_group": "acme-a-family",
                "split": split,
                "category": "voltage_regulator",
                "source": {"url": "https://example.invalid/a1.pdf", "revision": "Rev. 1"},
                "content_sha256": "a" * 64,
                "redistribution": "redistributable",
                "license_note": "Synthetic fixture.",
                "identity": _identity(),
                "review": {
                    "status": "reviewed" if reviewed else "unreviewed",
                    "reviewers": ["fixture-reviewer"] if reviewed else [],
                    "reviewed_at": "2026-08-12T00:00:00Z" if reviewed else None,
                    "annotation_revision": "annotations@1",
                },
                "cases": [
                    _case("pinout", "positive", "pinout", view="top"),
                    _case("table", "positive", "table"),
                    _case("package", "positive", "package"),
                    _case(
                        "wrong-package",
                        "wrong_package",
                        "package",
                        identity=_identity(package="TSSOP-8"),
                    ),
                    _case(
                        "wrong-variant",
                        "wrong_variant",
                        "package",
                        identity=_identity(mpn="A-2"),
                    ),
                    _case("wrong-view", "wrong_view", "pinout", view="bottom"),
                ],
            }
        ],
    }


def test_reviewed_registry_parses_and_has_deterministic_content_digest() -> None:
    data = _registry()
    first = load_visual_registry_data(data)
    second = load_visual_registry_data(deepcopy(data))

    assert first == second
    assert len(first.content_sha256) == 64
    assert {case.label for case in first.documents[0].cases} >= {
        "positive",
        "wrong_package",
        "wrong_variant",
        "wrong_view",
    }


@pytest.mark.parametrize("split", ["calibration", "evaluation"])
def test_unreviewed_labels_cannot_enter_calibration_or_evaluation(split: str) -> None:
    with pytest.raises(VisualRegistryError, match="annotations must be reviewed"):
        load_visual_registry_data(_registry(split, reviewed=False))


def test_unreviewed_development_labels_are_explicitly_allowed() -> None:
    parsed = load_visual_registry_data(_registry("development", reviewed=False))
    assert parsed.documents[0].review.status == "unreviewed"


def test_document_family_cannot_leak_across_splits() -> None:
    data = _registry()
    duplicate = deepcopy(data["documents"][0])
    duplicate["id"] = "acme-a1-eval"
    duplicate["split"] = "evaluation"
    duplicate["content_sha256"] = "b" * 64
    data["documents"].append(duplicate)
    with pytest.raises(VisualRegistryError, match="leaks across splits"):
        load_visual_registry_data(data)


def test_same_pdf_hash_cannot_cross_document_families() -> None:
    data = _registry()
    duplicate = deepcopy(data["documents"][0])
    duplicate["id"] = "other"
    duplicate["document_group"] = "other-family"
    data["documents"].append(duplicate)
    with pytest.raises(VisualRegistryError, match="assigned to multiple groups"):
        load_visual_registry_data(data)


@pytest.mark.parametrize("region_type", ["pinout", "table", "package"])
def test_every_required_positive_region_is_mandatory(region_type: str) -> None:
    data = _registry()
    data["documents"][0]["cases"] = [
        case
        for case in data["documents"][0]["cases"]
        if not (case["label"] == "positive" and case["region_type"] == region_type)
    ]
    with pytest.raises(VisualRegistryError, match="missing positive regions"):
        load_visual_registry_data(data)


def test_identity_negative_relationships_are_strict() -> None:
    data = _registry()
    wrong_package = next(
        case for case in data["documents"][0]["cases"] if case["label"] == "wrong_package"
    )
    wrong_package["claimed_identity"] = _identity(mpn="A-2", package="TSSOP-8")
    with pytest.raises(VisualRegistryError, match="differ only by package"):
        load_visual_registry_data(data)

    data = _registry()
    wrong_variant = next(
        case for case in data["documents"][0]["cases"] if case["label"] == "wrong_variant"
    )
    wrong_variant["region_type"] = "pinout"
    with pytest.raises(VisualRegistryError, match="must use a package region"):
        load_visual_registry_data(data)


def test_wrong_view_must_oppose_a_positive_oriented_view() -> None:
    data = _registry()
    wrong_view = next(
        case for case in data["documents"][0]["cases"] if case["label"] == "wrong_view"
    )
    wrong_view["view"] = "top"
    with pytest.raises(VisualRegistryError, match="must oppose"):
        load_visual_registry_data(data)


@pytest.mark.parametrize(
    "bbox",
    [[0.8, 0.2, 0.1, 0.7], [-0.1, 0.2, 0.8, 0.7], [0.1, 0.2, float("nan"), 0.7]],
)
def test_bounding_boxes_are_finite_normalized_and_ordered(bbox: list[float]) -> None:
    data = _registry()
    data["documents"][0]["cases"][0]["bbox_norm"] = bbox
    with pytest.raises(VisualRegistryError, match="bbox_norm"):
        load_visual_registry_data(data)


def test_unknown_fields_and_insecure_sources_fail_closed() -> None:
    data = _registry()
    data["documents"][0]["surprise"] = True
    with pytest.raises(VisualRegistryError, match="unknown"):
        load_visual_registry_data(data)

    data = _registry()
    data["documents"][0]["source"]["url"] = "http://example.invalid/a1.pdf"
    with pytest.raises(VisualRegistryError, match="HTTPS"):
        load_visual_registry_data(data)


def test_adapter_scores_are_bound_to_registry_owned_labels_and_splits() -> None:
    registry = load_visual_registry_data(_registry())
    scores = {
        f"{registry.documents[0].document_id}/{case.case_id}": 0.9
        for case in registry.documents[0].cases
    }
    predictions = bind_prediction_scores(registry, scores)

    assert {prediction.split for prediction in predictions} == {"calibration"}
    assert {prediction.label for prediction in predictions} == {
        case.label for case in registry.documents[0].cases
    }
    assert [prediction.case_id for prediction in predictions] == sorted(scores)


def test_adapter_score_set_must_match_registry_exactly() -> None:
    registry = load_visual_registry_data(_registry())
    expected = {
        f"{registry.documents[0].document_id}/{case.case_id}": 0.5
        for case in registry.documents[0].cases
    }
    missing = dict(expected)
    missing.pop(next(iter(missing)))
    with pytest.raises(VisualRegistryError, match="missing"):
        bind_prediction_scores(registry, missing)

    unknown = {**expected, "unreviewed/injected-label": 1.0}
    with pytest.raises(VisualRegistryError, match="unknown"):
        bind_prediction_scores(registry, unknown)

    invalid = {**expected, next(iter(expected)): float("nan")}
    with pytest.raises(VisualRegistryError, match="finite"):
        bind_prediction_scores(registry, invalid)


def test_committed_visual_seed_is_agent_audited_development_data_only() -> None:
    root = Path(__file__).parents[1]
    path = root / "evaluation/visual_registry.v1.json"
    registry = load_visual_registry_data(json.loads(path.read_text(encoding="utf-8")))

    assert len(registry.documents) == 17
    assert {document.split for document in registry.documents} == {"development"}
    reviews = {document.document_id: document.review.status for document in registry.documents}
    assert set(reviews.values()) == {"reviewed"}
    assert all(
        document.review.reviewers == ("agent:codex-gpt5",)
        for document in registry.documents
        if document.review.status == "reviewed"
    )
    assert {document.category for document in registry.documents} == {
        "analog_to_digital_converter",
        "microcontroller",
        "voltage_regulator",
        "operational_amplifier",
        "timer",
        "wireless_microcontroller",
        "led_driver",
        "environmental_sensor",
        "gpio_expander",
        "real_time_clock",
        "serial_eeprom",
        "can_transceiver",
        "can_controller",
    }
    assert len({document.identity.manufacturer for document in registry.documents}) >= 10
    assert all(document.redistribution == "download_only" for document in registry.documents)
    assert all(len(document.cases) >= 6 for document in registry.documents)
    assert not list((root / "evaluation").glob("*.pdf"))

    documents = {document.document_id: document for document in registry.documents}
    expected_expansion = {
        "nxp-pca9685-rev-4-2015-04": (
            "237d47f339cac4c3a0d56a5f0b4d3c93df71e3eb43f36ac57ea4ff38e6b2e585",
            "PCA9685PW",
        ),
        "bosch-bme280-rev-1-23-2022-01": (
            "a2ccdb449fec94380742fe8eec851a11d9bd4142252d332b34682b4deecd7d89",
            "BME280",
        ),
        "onsemi-ncp1117-rev-31-2021-08": (
            "72a1aeb60abf0acae2f5c9cfecd9a9ff34fd1bbb903624625666609fde20526c",
            "NCP1117ST33T3G",
        ),
        "nxp-pcf8574-rev-5-2013-05": (
            "15873fa13e8b9e3baeb924cc5ce845eabf0e1d2671a441feaaa3c4bb56e77013",
            "PCF8574T/3",
        ),
        "renesas-isl1208-rev-9-01-2022-07": (
            "73335397f3926212bcb1d64a0aa6b301af400b3adab1f67953751db49772921c",
            "ISL1208IB8Z",
        ),
        "onsemi-cat24c32-rev-28-2025-07": (
            "460c65458075bad2a8eebb59ce40831020b246145e95d7529cc12647d266a7f3",
            "CAT24C32WI-GT3",
        ),
        "microchip-mcp2561-2-ds20005167c-2014-07": (
            "c36b24e45446d8a1b7d90c0618a924cac0f117994390e60169287e6ba488c53e",
            "MCP2562-E/SN",
        ),
        "microchip-mcp23017-23s17-ds20001952d-2022-06": (
            "63cb5f2bec44434cdeeada1790d0316c9dc06b33febb489ad87bb0e2d540496a",
            "MCP23017-E/SO",
        ),
    }
    for document_id, (content_sha256, mpn) in expected_expansion.items():
        document = documents[document_id]
        assert document.content_sha256 == content_sha256
        assert document.identity.mpn == mpn
        assert {case.label for case in document.cases} == {
            "positive",
            "wrong_package",
            "wrong_variant",
            "wrong_view",
            "wrong_figure",
        }
        assert {case.region_type for case in document.cases if case.label == "positive"} == {
            "pinout",
            "table",
            "package",
        }


def test_multivendor_evidence_export_is_bound_to_exact_registry_subset() -> None:
    root = Path(__file__).parents[1]
    registry_data = json.loads(
        (root / "evaluation/visual_registry.v1.json").read_text(encoding="utf-8")
    )
    evidence = json.loads(
        (root / "evaluation/results/multivendor-development-2026-08-12.json").read_text(
            encoding="utf-8"
        )
    )
    scope = evidence["scope"]
    selected = set(scope["document_ids"])
    subset_data = {
        "schema_version": registry_data["schema_version"],
        "documents": [
            document for document in registry_data["documents"] if document["id"] in selected
        ],
    }
    subset = load_visual_registry_data(subset_data)

    assert {document.document_id for document in subset.documents} == selected
    assert subset.content_sha256 == scope["registry_sha256"]
    assert len(subset.documents) == scope["documents"]
    assert sum(len(document.cases) for document in subset.documents) == scope["cases"]
    assert {document.identity.manufacturer for document in subset.documents} == set(
        scope["manufacturers"]
    )
    assert scope["eligible_for_policy_fitting"] is False
    assert all(len(comparator["score_sha256"]) == 64 for comparator in evidence["comparators"])

    adapters = [TextLayoutAdapter(), RapidOcrAdapter(engine=lambda _image: None)]
    implementations = {
        adapter.metadata.adapter_id: adapter.metadata.implementation_sha256 for adapter in adapters
    }
    assert {
        comparator["adapter_id"]: comparator["implementation_sha256"]
        for comparator in evidence["comparators"]
    } == implementations
