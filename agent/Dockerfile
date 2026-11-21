FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1

WORKDIR /app

COPY pyproject.toml ./
RUN uv pip install --system -r pyproject.toml

COPY app ./app
COPY evals ./evals
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh \
    && groupadd -g 1000 whitz \
    && useradd -u 1000 -g 1000 -m -s /bin/sh whitz \
    && chown -R 1000:1000 /app

USER 1000:1000

EXPOSE 8642

ENTRYPOINT ["./entrypoint.sh"]
