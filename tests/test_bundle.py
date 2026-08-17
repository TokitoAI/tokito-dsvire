import io
import zipfile

import pytest

from dsvire.bundle import build_bundle


def test_bundle_is_reproducible_and_self_describing() -> None:
    files = {"crops/pinout.webp": b"crop", "evidence.json": b"{}\n"}
    first = build_bundle(files, {"job_id": "job-1"})
    second = build_bundle(dict(reversed(list(files.items()))), {"job_id": "job-1"})
    assert first.payload == second.payload
    assert first.sha256 == second.sha256
    with zipfile.ZipFile(io.BytesIO(first.payload)) as archive:
        assert archive.namelist() == ["crops/pinout.webp", "evidence.json", "manifest.json"]
        assert archive.getinfo("manifest.json").date_time == (1980, 1, 1, 0, 0, 0)


def test_bundle_rejects_traversal_and_reserved_manifest() -> None:
    with pytest.raises(ValueError, match="unsafe"):
        build_bundle({"../secret": b"x"}, {})
    with pytest.raises(ValueError, match="reserved"):
        build_bundle({"manifest.json": b"x"}, {})
