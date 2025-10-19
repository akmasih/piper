# File: Dockerfile - /root/piper/Dockerfile
# Docker image for Piper TTS service with updated dependencies

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    ffmpeg \
    libsndfile1 \
    espeak-ng \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Piper TTS latest version
RUN pip install --no-cache-dir piper-tts==1.3.0

# Copy and install Python requirements
COPY app/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ /app/app/

# Create necessary directories
RUN mkdir -p /app/models \
    && mkdir -p /tmp/piper \
    && chmod 777 /tmp/piper

# Create non-root user for security
RUN useradd -m -u 1000 piper && \
    chown -R piper:piper /app /tmp/piper

USER piper

# Expose service port
EXPOSE 8000

# Health check configuration
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start the service with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]