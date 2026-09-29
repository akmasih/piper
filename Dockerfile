# Dockerfile
# Path: /Users/eleheim/projects/piper/Dockerfile
# Image of the speech pack builder: downloads pinned models, exports Whisper with attention outputs, writes the manifest.

FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        bzip2 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch: the export traces the model once, no GPU is involved.
# Only the torch wheel comes from PyTorch's index (x86_64 and aarch64, so the
# image builds on the servers and on Apple silicon alike); its dependencies are
# pinned in requirements.txt and come from PyPI, because the index's mirrored
# copies of them are rejected by this image's pip.
RUN pip install --no-cache-dir --no-deps \
        --index-url https://download.pytorch.org/whl/cpu \
        torch==2.4.1

WORKDIR /app

COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip check

# No user is baked in: docker-compose.yml runs the builder as the host user
# who starts it, so everything it writes on the host belongs to that user.
COPY app/__init__.py app/config.py app/fetch.py app/manifest.py app/validate.py app/whisper_export.py app/main.py /app/

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "main.py"]
