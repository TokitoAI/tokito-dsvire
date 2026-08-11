FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DSVIRE_DATA_DIR=/data/dsvire

RUN useradd --create-home --uid 10001 dsvire
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.2,<27" "setuptools>=83,<84" \
    && python -m pip install --no-cache-dir . \
    && python -m pip check

RUN mkdir -p /data/dsvire && chown -R dsvire:dsvire /data/dsvire
USER dsvire
EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8081/v1/health", timeout=2)' || exit 1
CMD ["python", "-m", "dsvire.server"]
