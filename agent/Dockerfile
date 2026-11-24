FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1

WORKDIR /app

COPY agent/pyproject.toml ./
RUN uv pip install --system -r pyproject.toml

COPY shared/whitz_rag ./whitz_rag
COPY agent/app ./app
COPY agent/evals ./evals
COPY agent/entrypoint.sh ./
RUN chmod +x entrypoint.sh \
    && groupadd -g 1000 whitz \
    && useradd -u 1000 -g 1000 -m -s /bin/sh whitz \
    && chown -R 1000:1000 /app

USER 1000:1000

EXPOSE 8642

ENTRYPOINT ["./entrypoint.sh"]
