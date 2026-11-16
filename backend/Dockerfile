# API and worker image (BUILD_PLAN §3 Hosting, Step 28). Build from the repo root:
#   docker build -f backend/Dockerfile -t orrfin-api .
# The same image runs the API (default command), the job worker (python -m app.worker),
# migrations (alembic upgrade head) and the demo seed (python -m app.seed_demo).
# Paths mirror the repo, because the app finds seed/ and storage/ next to backend/ (config.REPO_ROOT).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/backend
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
RUN pip install .

# Simulated ERP fixtures and sample invoices the demo reads.
COPY seed /srv/seed

# Run as a plain user; uploaded files and the simulated ERPs' state live in /srv/storage (a volume).
RUN useradd --system --uid 10001 --home /srv orrfin \
    && mkdir -p /srv/storage && chown orrfin /srv/storage
USER orrfin

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
