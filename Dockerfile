FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY support_packs ./support_packs
COPY frontend ./frontend

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1 \
    IMPACT_REGISTRY_LOCAL_DB=/app/.impact_engine/impact_registry.sqlite \
    IMPACT_REGISTRY_CACHE_ROOT=/app/.impact_engine/registry_cache

EXPOSE 8001 8787

CMD ["impact-engine-local-api", "--host", "0.0.0.0", "--port", "8001"]
