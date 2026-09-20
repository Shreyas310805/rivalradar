# syntax=docker/dockerfile:1

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# lxml needs a compiler toolchain only if no wheel is available; curl is used
# by the compose healthcheck fallback.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN pip install --no-deps -e .

# Writable location for snapshots, reports and the SQLite file.
RUN mkdir -p /app/data/snapshots /app/data/reports

# Drop privileges: the crawler should never run as root.
RUN useradd --create-home --shell /bin/bash rivalradar \
    && chown -R rivalradar:rivalradar /app
USER rivalradar

ENV DATA_DIR=/app/data \
    DATABASE_URL=sqlite:////app/data/rivalradar.db

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# ---------------------------------------------------------------------------
# Optional JavaScript-rendering image.
#   docker build --target playwright -t rivalradar-backend:playwright ./backend
# The Playwright base image ships Chromium and its system libraries.
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy AS playwright

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt requirements-playwright.txt ./
RUN pip install -r requirements.txt -r requirements-playwright.txt \
    && playwright install chromium

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN pip install --no-deps -e . && mkdir -p /app/data/snapshots /app/data/reports

ENV DATA_DIR=/app/data \
    DATABASE_URL=sqlite:////app/data/rivalradar.db \
    PLAYWRIGHT_ENABLED=true

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
