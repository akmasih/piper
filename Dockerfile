# Dockerfile
# Path: /root/piper/Dockerfile
# Image of the speech pack builder: downloads pinned models, exports Whisper with attention outputs, writes the manifest.

FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        bzip2 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch: the export traces the model once, no GPU is involved.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.4.1

WORKDIR /app

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app/__init__.py app/config.py app/fetch.py app/manifest.py app/validate.py app/whisper_export.py app/main.py /app/

# No USER here: docker-compose.yml runs the container as the invoking host
# user, so the packs and the work cache it writes belong to that user.

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "main.py"]
