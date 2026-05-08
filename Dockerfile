# MY-IA V2 — Dockerfile (FastAPI + Jinja2 sert HTML & API)
FROM python:3.12-slim

WORKDIR /code

# Dépendances système (parsing docs, OCR, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    netcat-openbsd \
    tesseract-ocr \
    tesseract-ocr-fra \
    tesseract-ocr-eng \
    poppler-utils \
    libmagic1 \
    libgl1 \
    libglib2.0-0 \
    pandoc \
    libjpeg-dev \
    libpng-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Requirements (cache Docker)
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

RUN rm -rf /root/.cache/pip && \
    find /usr/local/lib/python3.12 -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true

# NLTK datasets pré-téléchargés (utilisés par unstructured pour chunker xlsx/docx/pptx).
# Sans ça, partition_xlsx() tente un download au runtime → HTTP 403/échec offline.
ENV NLTK_DATA=/usr/local/share/nltk_data
RUN python -m nltk.downloader -d "$NLTK_DATA" punkt punkt_tab averaged_perceptron_tagger averaged_perceptron_tagger_eng stopwords

# Utilisateur non-root
RUN addgroup --system appuser && adduser --system --ingroup appuser appuser

# Code applicatif
COPY ./app /code/app/

# Scripts d'init
COPY ./scripts/docker/entrypoint.sh /code/scripts/docker/entrypoint.sh
COPY ./scripts/docker/seed.py /code/scripts/docker/seed.py
RUN chmod +x /code/scripts/docker/entrypoint.sh

RUN chown -R appuser:appuser /code

ENV PYTHONPATH=/code

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

USER appuser

ENTRYPOINT ["/code/scripts/docker/entrypoint.sh"]
