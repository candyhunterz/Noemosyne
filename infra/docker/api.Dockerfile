FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv
FROM python:3.13-slim@sha256:881d80734ee05dca6f7f42dcb080975652a53c7eda9ba1f03bb8da31aa6a6ec2
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
