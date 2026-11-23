# Retrieval service: vector, BM25 and hybrid search; CLI and HTTP API.
#   docker build -t sentinel-retrieval services/retrieval
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# The same embedding model the chunks were embedded with, baked in (no downloads at run time).
COPY download_model.py .
RUN python download_model.py /models && chmod -R a+rX /models

COPY retrieval ./retrieval

ENV MODEL_DIR=/models \
    HF_HUB_OFFLINE=1 \
    HOME=/tmp

USER 10001
EXPOSE 8000
ENTRYPOINT ["python", "-m", "retrieval"]
CMD ["serve"]
