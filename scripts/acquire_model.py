#!/usr/bin/env python3
"""Acquire a manifest-pinned model without importing its ML runtime."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dsvire.model_acquire import acquire_model
from dsvire.model_manifest import ModelManifestError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        adapter = acquire_model(args.manifest, args.destination)
    except (OSError, json.JSONDecodeError, ModelManifestError) as exc:
        parser.error(str(exc))
    print(os.fspath(adapter))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
