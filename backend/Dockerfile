FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system zhixing && adduser --system --ingroup zhixing zhixing

COPY backend/pyproject.toml /app/pyproject.toml
COPY backend/requirements.lock.txt /app/requirements.lock.txt
COPY backend/app /app/app
COPY backend/migrations /app/migrations
COPY backend/alembic.ini /app/alembic.ini
COPY backend/config/project_facts.yaml /app/config/project_facts.yaml

RUN python -m pip install -r /app/requirements.lock.txt && python -m pip install --no-deps . \
    && mkdir -p /app/.data/assets && chown -R zhixing:zhixing /app

USER zhixing

ENV ZHIXING_FACT_SOURCE=/app/config/project_facts.yaml

EXPOSE 8000

CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
