"""Container entrypoint with parent-process configuration preflight."""

from __future__ import annotations

import uvicorn

from .config import ServiceConfig


def main() -> None:
    # Uvicorn's multiprocess supervisor may exit successfully when every child
    # rejects application startup. Validate in the container's PID 1 process so
    # unsafe configuration and unusable storage always produce a nonzero exit.
    ServiceConfig.from_env().prepare()
    uvicorn.run(
        "dsvire.api:app",
        host="0.0.0.0",
        port=8081,
        workers=2,
        limit_concurrency=32,
        timeout_keep_alive=5,
        access_log=False,
    )


if __name__ == "__main__":
    main()
