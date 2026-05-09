# syntax=docker/dockerfile:1.6

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --upgrade pip && \
    pip wheel --wheel-dir /wheels .


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/prices.db

RUN groupadd --system --gid 1000 am4bot && \
    useradd --system --uid 1000 --gid am4bot \
            --home /app --shell /usr/sbin/nologin am4bot && \
    mkdir -p /data /app && \
    chown am4bot:am4bot /data /app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links /wheels am4bot && \
    rm -rf /wheels /root/.cache

USER am4bot
WORKDIR /app
VOLUME ["/data"]

ENTRYPOINT ["am4bot"]
