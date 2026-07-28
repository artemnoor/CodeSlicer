FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY support_packs ./support_packs
COPY frontend ./frontend
COPY docker-entrypoint.sh /usr/local/bin/codeslicer-entrypoint

RUN pip install --no-cache-dir . && chmod +x /usr/local/bin/codeslicer-entrypoint

ENV PYTHONUNBUFFERED=1 \
    IMPACT_REGISTRY_LOCAL_DB=/app/.impact_engine/impact_registry.sqlite \
    IMPACT_REGISTRY_CACHE_ROOT=/app/.impact_engine/registry_cache

EXPOSE 8001 8787

ENTRYPOINT ["/usr/local/bin/codeslicer-entrypoint"]
CMD ["impact-engine-local-api", "--host", "127.0.0.1", "--port", "8001"]
