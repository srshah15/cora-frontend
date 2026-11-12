# Backend image for Render (or any Docker host).
# Why Docker: OCR needs the Tesseract system package, which a plain Python
# runtime can't install. Debian's apt has it.
FROM python:3.13-slim

# tesseract-ocr-eng is the English language data PyMuPDF's OCR reads.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Where the language data lives on Debian 12/13 (Tesseract 5).
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Render sets PORT. Secrets (LLM_API_KEY, DATABASE_URL) are set in the
# host's dashboard, never baked into the image.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
