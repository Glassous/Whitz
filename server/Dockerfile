FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1

WORKDIR /app

COPY server/pyproject.toml ./
RUN uv pip install --system -r pyproject.toml

COPY shared/whitz_rag ./whitz_rag
COPY server/app ./app
COPY server/alembic ./alembic
COPY server/resources ./resources
COPY server/alembic.ini server/entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 8000

CMD ["./entrypoint.sh"]
