FROM python:3.12-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DSVIRE_DATA_DIR=/data/dsvire \
    PYTHONPATH=/app/src

RUN useradd --create-home --uid 10001 dsvire
WORKDIR /app
COPY requirements/runtime.lock ./requirements/runtime.lock
RUN python -m pip install --no-cache-dir --no-compile --require-hashes -r requirements/runtime.lock \
    && python -m pip check
COPY src ./src
COPY fixtures/robustness ./fixtures/robustness
COPY scripts/evaluate_robustness.py ./scripts/evaluate_robustness.py
COPY policy ./policy
COPY THIRD_PARTY_NOTICES.md ./THIRD_PARTY_NOTICES.md
COPY scripts/audit_runtime_licenses.py ./scripts/audit_runtime_licenses.py

# Source checkout umasks differ across builders, and earlier host-side checks
# may have created bytecode. Neither is part of the production payload contract.
RUN find /app -type d -name __pycache__ -prune -exec rm -rf '{}' + \
    && find /app -type d -exec chmod 0755 '{}' + \
    && find /app -type f -exec chmod 0644 '{}' +

RUN mkdir -p /data/dsvire && chown -R dsvire:dsvire /data/dsvire
USER dsvire
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8081/v1/health", timeout=2)' || exit 1
CMD ["python", "-m", "dsvire.server"]
