FROM python:3.13-slim
WORKDIR /app
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir ".[dev]"
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
