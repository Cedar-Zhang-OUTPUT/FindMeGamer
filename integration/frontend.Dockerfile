FROM python:3.13-slim
WORKDIR /app
COPY backend/pyproject.toml ./
RUN pip install --no-cache-dir ".[dev]"
# Only explicitly selected source files; never COPY dotenv or credential files.
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY integration/runtime/frontend_runtime.py /harness/frontend_runtime.py
