# TaxScraper backend.
#
# Build context is `backend/`, deliberately: `Files/` (the real client corpus)
# and `data/` (the raw zone, the vault, the audit chain) sit at the repository
# root and are therefore outside the context entirely. A .dockerignore that
# someone edits cannot put them back.
#
#   docker build -t taxscraper-api ./backend
#   docker run -p 8000:8000 --env-file backend/.env taxscraper-api
#
# Tesseract is installed here rather than assumed: without it every scanned
# page is marked OCR_UNAVAILABLE and routed to human review, which on this
# corpus means the pipeline reads nothing at all.

FROM python:3.11-slim-bookworm

# --- System packages -------------------------------------------------------
# tesseract-ocr        the OCR engine; osd is required for the rotated-page
#                      retry, which five pages of the sample corpus need
# libglib2.0-0         opencv-python-headless still links against it
# libgomp1             OpenMP runtime used by opencv and numpy
# curl                 container healthcheck only
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-osd \
        libglib2.0-0 \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Requirements first so the layer caches across source edits. This layer is
# slow: PyMuPDF, opencv, spaCy and the en_core_web_sm wheel are all large.
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app

# --- Runtime configuration -------------------------------------------------
# Paths are set explicitly rather than left to the "./data" defaults, so the
# zones do not depend on which directory the process happens to start in.
ENV TESSERACT_CMD=/usr/bin/tesseract \
    DATA_DIR=/app/data \
    RAW_ZONE_DIR=/app/data/raw \
    MASKED_ZONE_DIR=/app/data/masked \
    OUTPUT_ZONE_DIR=/app/data/output \
    TMP_ZONE_DIR=/app/data/tmp \
    VECTOR_STORE_DIR=/app/data/vector \
    DATABASE_URL=sqlite:////app/data/taxscraper.db \
    APP_HOST=0.0.0.0 \
    PORT=8000

# SECURITY: no shell, no home, no write access outside the data zones. A
# process that cannot write to /app/app cannot be made to persist anything
# through the code it runs.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin taxscraper \
    && mkdir -p /app/data \
    && chown -R taxscraper:taxscraper /app/data
USER taxscraper

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

# One worker on purpose. The audit log is a hash chain that concurrent writers
# would corrupt, and both the burst limiter and the daily quota assume a single
# instance. Scaling out means moving those three things first.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
