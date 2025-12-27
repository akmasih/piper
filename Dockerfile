# Dockerfile
# /root/piper/Dockerfile
# Piper TTS Server container

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install piper-tts
RUN pip install --no-cache-dir piper-tts

# Create app user
RUN useradd -m -u 1000 piper

# Set working directory
WORKDIR /app

# Copy application code
COPY --chown=piper:piper app/ /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create directories
RUN mkdir -p /app/models /tmp/piper && \
    chown -R piper:piper /app/models /tmp/piper

# Switch to non-root user
USER piper

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    MODELS_DIR=/app/models \
    TEMP_DIR=/tmp/piper \
    HOST=0.0.0.0 \
    PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/piper/health || exit 1

# Expose port
EXPOSE 8000

# Run server
CMD ["python", "main.py"]