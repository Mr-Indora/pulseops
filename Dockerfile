FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/srv
WORKDIR /srv
RUN useradd --system --uid 10001 --no-create-home pulseops

# Runtime deps only: read [project].dependencies, skip dev/tools extras. Copied alone so the
# layer is cached until pyproject.toml changes.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/req.txt \
 && pip install -r /tmp/req.txt && rm /tmp/req.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
USER pulseops
EXPOSE 8000

# Migrate on the direct DB URL (alembic env.py reads MIGRATION_DATABASE_URL), then serve.
# exec makes uvicorn PID 1 so SIGTERM reaches it and graceful shutdown works.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --timeout-graceful-shutdown 20"]
