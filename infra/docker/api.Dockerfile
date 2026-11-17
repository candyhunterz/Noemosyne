FROM ghcr.io/astral-sh/uv:0.12.8@sha256:d1cbaeadc234fe19c0d93daabcf5e98738cd93c6d1dd4918ef6aa30735feb23a AS uv
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY apps/api apps/api
COPY apps/worker apps/worker
COPY packages packages
COPY migrations migrations
COPY examples examples
COPY alembic.ini ./
RUN uv sync --frozen --no-dev \
    && rm -rf /root/.cache/uv \
        /usr/local/lib/python3.13/site-packages/pip \
        /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
        /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13 \
        /bin/uv /bin/uvx
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/apps/api:/app/packages/domain:/app/packages/db:/app/packages/retrieval"
CMD ["sh", "-c", "alembic upgrade head && uvicorn noemosyne_api.main:app --host 0.0.0.0 --port 8000"]
