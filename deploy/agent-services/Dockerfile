FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FMG_AGENT_CATALOG_DIR=/srv/api-catalog
WORKDIR /srv/agent-service
COPY agent-service/constraints.txt agent-service/pyproject.toml ./
COPY agent-service/src ./src
RUN pip install --no-cache-dir -c constraints.txt . && useradd --uid 10001 --create-home agent
COPY agent-service/alembic.ini ./
COPY agent-service/migrations ./migrations
COPY api-catalog /srv/api-catalog
USER agent
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "fmg_agent.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
