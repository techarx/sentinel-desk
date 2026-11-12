# Trade stream: seed, generator and consumer in one image.
# Build from the REPO ROOT (it needs config/entities.yaml):
#   docker build -f services/trades/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY services/trades/requirements.txt .
RUN pip install -r requirements.txt

COPY config/entities.yaml /app/config/entities.yaml
COPY services/trades/trades ./trades

USER 10001
EXPOSE 9100
ENTRYPOINT ["python", "-m", "trades"]
