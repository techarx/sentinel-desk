# EDGAR ingestion. Build from the REPO ROOT (it needs config/entities.yaml):
#   docker build -f services/ingest-edgar/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY services/ingest-edgar/requirements.txt .
RUN pip install -r requirements.txt

# Bake the embedding model into the image: no downloads at run time.
COPY services/ingest-edgar/download_model.py .
RUN python download_model.py /models && chmod -R a+rX /models

COPY config/entities.yaml /app/config/entities.yaml
COPY services/ingest-edgar/ingest_edgar ./ingest_edgar

ENV MODEL_DIR=/models \
    HF_HUB_OFFLINE=1 \
    HOME=/tmp

USER 10001
ENTRYPOINT ["python", "-m", "ingest_edgar"]
