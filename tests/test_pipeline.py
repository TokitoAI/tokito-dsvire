from __future__ import annotations

from pathlib import Path

import pytest

from dsvire.pipeline import DatasheetIdentity, RetrievalError, score_candidate


def test_pinout_verifier_accepts_real_pin_signals() -> None:
    score, verified = score_candidate(
        "pinout",
        "Figure 4-1. 8-pin package top view. VIN 1 BOOT 2 PH 3 GND 4 VSENSE 5 ENA 6 COMP 7 PWRPAD 8",
    )
    assert verified
    assert score >= 0.70


def test_pin_table_verifier_rejects_heading_without_rows() -> None:
    score, verified = score_candidate("table", "Table 4-1. Pin Functions Name Description")
    assert not verified
    assert score < 0.72


def test_verifier_does_not_count_arbitrary_uppercase_words_as_pins() -> None:
    _score, verified = score_candidate(
        "pinout",
        "PIN CONFIGURATION IMPORTANT INFORMATION PACKAGE DEVICE FEATURES",
    )
    assert not verified


def test_identity_is_never_guessed() -> None:
    with pytest.raises(RetrievalError, match="mpn is required"):
        DatasheetIdentity("Texas Instruments", "", "SOIC-8").validate()


def test_non_pdf_fails_before_parser(tmp_path: Path) -> None:
    from dsvire.pipeline import retrieve_symbol_evidence

    with pytest.raises(RetrievalError, match="not a PDF"):
        retrieve_symbol_evidence(
            b"not-pdf-data",
            DatasheetIdentity("Acme", "A-1", "SOIC-8"),
            tmp_path,
        )
