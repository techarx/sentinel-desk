# Database migrations image: `alembic upgrade head` by default.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations

# Non-root, numeric UID so Kubernetes can verify runAsNonRoot.
USER 10001

ENTRYPOINT ["alembic"]
CMD ["upgrade", "head"]
