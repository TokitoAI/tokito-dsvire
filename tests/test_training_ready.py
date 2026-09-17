from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

from dsvire.ablation_gates import GATE_VERSION, AblationGateError, evaluate_ablation_gates
from dsvire.accelerators import IndexIdentityError, index_telemetry, pack_point_payload
from dsvire.cppt import extract_side_channel
from dsvire.cycle_execution import (
    CYCLE_V4_PACKET_SHA256,
    CYCLE_V4_PLAN_ID,
    CYCLE_V5_PACKET_SHA256,
    CYCLE_V5_PLAN_ID,
    CycleExecutionError,
    assert_score_access_authorized,
    inspect_cycle_v4,
    inspect_cycle_v5,
)
from dsvire.dhpr import probe_pdf
from dsvire.dsff import LayoutBox, extract_xobjects, iou
from dsvire.eftri import REGION_TYPES, EftriError, route
from dsvire.egvv_campaign import calibrate
from dsvire.layout_detect import LayoutDetectError, OnnxLayoutDetector
from dsvire.pdf_fixtures import add_rgb_image_page, text_pdf, write_pdf
from dsvire.region_corpus import build_region_records
from dsvire.retrieval_pack import build_retrieval_pack, load_retrieval_pack
from dsvire.retrieval_train import light_merge, mrl_loss, type_gate
from dsvire.sealed_holdout import leakage_hits, load_sealed_holdout
from dsvire.training_corpus import (
    TrainingCorpusError,
    audit_corpus,
    fingerprint_pdf,
    parse_corpus_record,
    refuse_hash_split,
)
from dsvire.training_runtime import TrainingRunError, bind_run
from dsvire.visual_metrics import Prediction


def _record(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "content_sha256": "a" * 64,
        "bytes": 1024,
        "page_count": 4,
        "source_url": "https://www.ti.com/lit/ds/symlink/example.pdf",
        "final_url": "https://www.ti.com/lit/ds/symlink/example.pdf",
        "retrieved_at": "2026-08-17T10:21:26Z",
        "manufacturer": "Texas Instruments",
        "category": "sensor",
        "symbols": ["TMP999"],
        "label_tier": "layout_only_weak_identity",
        "permitted_use": "local research training candidate after terms review",
        "terms_url": "https://www.ti.com/legal",
        "split": "training_candidate",
    }
    base.update(overrides)
    return base


def test_sealed_holdout_includes_cycle_v4_and_rejects_overlap() -> None:
    holdout = load_sealed_holdout()
    assert CYCLE_V4_PLAN_ID in holdout.plan_ids
    assert leakage_hits(holdout, url="https://www.ti.com/lit/ds/symlink/tmp102.pdf") == (
        "sealed_url",
    )
    assert not leakage_hits(
        holdout,
        url="https://www.ti.com/lit/ds/symlink/not-a-cycle-part.pdf",
        content_sha256="b" * 64,
        identity_text=("TMP999AIDRLR",),
    )


def test_cycle_v4_status_is_retired_without_mma8451q() -> None:
    status = inspect_cycle_v4()
    assert status.plan_id == CYCLE_V4_PLAN_ID
    assert status.packet_sha256 == CYCLE_V4_PACKET_SHA256
    assert status.score_access_authorized is False
    assert status.sources_complete is False
    assert status.stage == "sources_incomplete"
    assert "nxp-mma8451q-rev-10-3" in status.invalidations
    with pytest.raises(CycleExecutionError, match="score access is forbidden"):
        assert_score_access_authorized(status)


def test_cycle_v5_status_is_sealed_without_mma8451q() -> None:
    status = inspect_cycle_v5()
    assert status.plan_id == CYCLE_V5_PLAN_ID
    assert status.packet_sha256 == CYCLE_V5_PACKET_SHA256
    assert status.sources_complete is True
    assert status.stage == "scores_authorized"
    assert status.score_access_authorized is True


def test_cycle_v4_live_invalidation_is_incomplete() -> None:
    manifest = json.loads(
        Path("evaluation/retrieval_cycle_v4_source_manifest.json").read_text(encoding="utf-8")
    )
    manifest["complete"] = False
    manifest["invalidations"] = [{"id": "nxp-mma8451q-rev-10-3", "status": "invalidated"}]
    manifest["sources"] = [
        item for item in manifest["sources"] if item["id"] != "nxp-mma8451q-rev-10-3"
    ]
    status = inspect_cycle_v4(source_manifest=manifest)
    assert status.stage == "sources_incomplete"
    assert "nxp-mma8451q-rev-10-3" in status.invalidations


def test_corpus_refuses_sealed_url_and_hash_splits() -> None:
    holdout = load_sealed_holdout()
    records = [
        parse_corpus_record(_record(category=category, symbols=[f"PART{index}"]))
        for index, category in enumerate(
            [
                "analog_mixed_signal",
                "connector",
                "discrete",
                "interface_logic",
                "memory",
                "microcontroller_fpga",
                "other",
                "power_management",
                "rf",
                "sensor",
            ]
        )
    ]
    audit_corpus(records, holdout=holdout)
    with pytest.raises(TrainingCorpusError, match="family clusters"):
        refuse_hash_split(records)
    leaked = parse_corpus_record(
        _record(final_url="https://www.ti.com/lit/ds/symlink/tmp102.pdf", symbols=["TMP102"])
    )
    with pytest.raises(TrainingCorpusError, match="leaks"):
        audit_corpus([*records[1:], leaked], holdout=holdout)


def test_fingerprint_and_dhpr_routes() -> None:
    digital = text_pdf(["PIN CONFIGURATION\nVDD GND SCL SDA"] * 3)
    info = fingerprint_pdf(digital)
    assert info["page_count"] == 3
    assert probe_pdf(digital).route == "born_digital"
    writer = PdfWriter()
    add_rgb_image_page(writer, bytes([255, 0, 0]) * 8 * 8, width=8, height=8)
    scan = write_pdf(writer)
    assert probe_pdf(scan).route in {"scan", "image_heavy", "mixed"}
    figures = extract_xobjects(scan)
    assert figures
    assert figures[0].name == "Im0"
    assert iou(figures[0].bbox_norm, figures[0].bbox_norm) == 1.0


class _FixedDetector:
    detector_id = "test-layout"
    model_sha256 = "0" * 64

    def detect(self, png: bytes, *, page: int) -> tuple[LayoutBox, ...]:
        del png
        return (
            LayoutBox(
                page=page,
                bbox_norm=(0.1, 0.1, 0.9, 0.9),
                label="figure",
                score=0.91,
                source="doclayout_yolo",
            ),
        )


def test_region_corpus_binds_renderer_and_rejects_sealed_bytes() -> None:
    payload = text_pdf(["PIN CONFIGURATION\nVDD GND SCL SDA"])
    digest = hashlib.sha256(payload).hexdigest()
    record = parse_corpus_record(
        _record(content_sha256=digest, bytes=len(payload), page_count=1, symbols=["TMP999"])
    )
    holdout = load_sealed_holdout()
    probe, regions = build_region_records(
        payload, record, detector=_FixedDetector(), holdout=holdout
    )
    assert probe.route == "born_digital"
    assert regions[0].renderer.startswith("pdfium-")
    assert regions[0].document_sha256 == digest
    sealed = parse_corpus_record(
        _record(
            content_sha256=digest,
            bytes=len(payload),
            page_count=1,
            final_url="https://www.ti.com/lit/ds/symlink/tmp102.pdf",
            symbols=["TMP102"],
        )
    )
    with pytest.raises(Exception, match="sealed"):
        build_region_records(payload, sealed, detector=_FixedDetector(), holdout=holdout)


def test_eftri_cppt_and_layout_fail_closed() -> None:
    logits = [0.0] * len(REGION_TYPES)
    logits[0] = 4.0
    decision = route(logits, layout_label="figure")
    assert decision.primary == "pinout"
    assert decision.abstained is False
    weak = route([0.0] * len(REGION_TYPES), layout_label="figure")
    assert weak.abstained is True
    with pytest.raises(EftriError):
        route([0.0], layout_label="figure")
    payload = text_pdf(["Figure 1. Pin configuration\nVDD GND SCL SDA RESET"])
    channel = extract_side_channel(
        payload, page=1, bbox_norm=(0.0, 0.0, 1.0, 1.0), region_type="pinout"
    )
    assert "VDD" in channel.pin_names
    assert channel.caption.lower().startswith("figure 1")
    with pytest.raises(LayoutDetectError, match="missing"):
        OnnxLayoutDetector(Path("missing.onnx"), "a" * 64, expected_bytes=12)


def test_training_runtime_and_retrieval_math(tmp_path: Path) -> None:
    holdout = load_sealed_holdout()
    with pytest.raises(TrainingRunError, match="24GB"):
        bind_run(
            run_id="prod",
            scale="production",
            accelerator_profile="index.gpu.standard",
            corpus_sha256="c" * 64,
            model_sha256="d" * 64,
            runtime_sha256="e" * 64,
            holdout=holdout,
            max_steps=1,
            detected_vram_mb=4096,
        )
    run = bind_run(
        run_id="smoke",
        scale="smoke",
        accelerator_profile="index.gpu.smoke",
        corpus_sha256="c" * 64,
        model_sha256="d" * 64,
        runtime_sha256="e" * 64,
        holdout=holdout,
        max_steps=2,
        detected_vram_mb=4096,
    )
    assert run.accelerator_profile == "index.gpu.smoke"
    query = [1.0] * 512
    positive = [0.9] * 512
    negative = [-0.2] * 512
    loss = mrl_loss(query, positive, [negative])
    assert loss > 0
    merged = light_merge([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [0.1, 0.9]], keep=2)
    assert len(merged) == 2
    assert type_gate("pinout", ("pinout", "table")) is True
    assert type_gate("curve", ("pinout", "table")) is False


def test_egvv_refuses_evaluation_during_calibration() -> None:
    status = inspect_cycle_v4()
    predictions = (
        Prediction("c1", "g", "calibration", "positive", 0.9),
        Prediction("c2", "g", "evaluation", "positive", 0.8),
    )
    with pytest.raises(CycleExecutionError):
        calibrate(
            predictions,
            status=status,
            model_id="egvv@test",
            model_sha256="f" * 64,
            preprocessing_id="prep",
            dataset_sha256="a" * 64,
            calibration_id="cal",
        )


def test_ablation_gates_and_qdrant_payload_contracts() -> None:
    baselines = {
        name: {"r_at_5": 0.5}
        for name in (
            "bm25_structured_text",
            "dense_text_rag",
            "siglip_pages",
            "dse_page_vector",
            "colqwen2_full_page",
            "colqwen2_light_merge",
            "layout_crop_siglip",
            "lgpc",
            "lgpc_eftri",
        )
    }
    baselines["colqwen2_full_page"] = {"r_at_5": 0.7}
    baselines["dense_text_rag"] = {"r_at_5": 0.4}
    evidence = {
        "schema_version": GATE_VERSION,
        "baselines": baselines,
        "candidate": {
            "r_at_5": 0.72,
            "query_p95_hot_ms": 400,
            "index_pages_per_second_per_gpu": 3.0,
            "pack_vs_full_page_ratio": 0.1,
            "verified_wrong_figure_rate": 0.01,
            "ndcg_delta_vs_previous": 0.0,
        },
    }
    result = evaluate_ablation_gates(evidence)
    assert result["passed"] is True
    with pytest.raises(AblationGateError, match="waiver"):
        evaluate_ablation_gates({**evidence, "waiver": "ship anyway"})
    envelope = build_retrieval_pack(
        {
            "source_sha256": "1" * 64,
            "models": {
                "dense": {"id": "dense@test", "sha256": "2" * 64},
                "multi": {"id": "multi@test", "sha256": "3" * 64},
            },
            "dense_dim": 2,
            "multi_dim": 2,
            "vector_dtype": "float32",
            "regions": [
                {
                    "id": "doc/a",
                    "page": 1,
                    "bbox_norm": [0.1, 0.2, 0.5, 0.8],
                    "type": "pinout",
                    "content_sha256": "4" * 64,
                    "text_fields": {"caption": "pins"},
                    "dense": [1.0, 0.0],
                    "multi": [[1.0, 0.0]],
                }
            ],
        }
    )
    pack = load_retrieval_pack(envelope)
    payload = pack_point_payload(
        "tenant",
        pack,
        pack.regions[0],
        project_id="proj",
        renderer_id="pdfium-x",
        preprocess_id="prep",
        policy_id="unpublished",
    )
    assert payload["renderer_id"] == "pdfium-x"
    assert payload["dense_model_sha256"] == "2" * 64
    with pytest.raises(IndexIdentityError):
        index_telemetry("query_text", {"hits": 1})
    assert index_telemetry("index_rebuild", {"points": 3})["points"] == 3
