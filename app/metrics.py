# metrics.py
# Path: /root/piper/app/metrics.py
# Prometheus metrics module for Lingudesk Piper TTS Server

import time
from typing import Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    Info,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)

from log_config import get_logger

logger = get_logger(__name__)

# ============================================
# CONFIGURATION
# ============================================

SERVER_NAME = "piper"
SERVER_TYPE = "tts"
SERVER_VERSION = "2.2.0"

# ============================================
# HTTP METRICS
# ============================================

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status", "server"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint", "server"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0),
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Number of HTTP requests currently being processed",
    ["method", "server"],
)

# ============================================
# SERVER INFO
# ============================================

SERVER_INFO = Info(
    "fastapi_server",
    "FastAPI server information",
)

# ============================================
# TTS SPECIFIC METRICS
# ============================================

# TTS generation operations
TTS_REQUESTS_TOTAL = Counter(
    "tts_requests_total",
    "Total TTS generation requests",
    ["language", "locale", "status", "server"],
)

TTS_GENERATION_DURATION_SECONDS = Histogram(
    "tts_generation_duration_seconds",
    "TTS generation duration in seconds",
    ["language", "locale", "server"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

TTS_TEXT_LENGTH = Histogram(
    "tts_text_length_chars",
    "Length of text sent for TTS generation",
    ["language", "server"],
    buckets=(10, 50, 100, 250, 500, 1000, 2000, 5000),
)

TTS_AUDIO_SIZE_BYTES = Histogram(
    "tts_audio_size_bytes",
    "Size of generated audio in bytes",
    ["language", "locale", "server"],
    buckets=(1000, 10000, 50000, 100000, 500000, 1000000, 5000000),
)

# Voice usage
TTS_VOICE_USAGE_TOTAL = Counter(
    "tts_voice_usage_total",
    "Voice usage count",
    ["language", "locale", "voice", "gender", "quality", "server"],
)

# Active generations
TTS_ACTIVE_GENERATIONS = Gauge(
    "tts_active_generations",
    "Number of TTS generations currently in progress",
    ["server"],
)

# Catalog info
TTS_LANGUAGES_TOTAL = Gauge(
    "tts_languages_total",
    "Total number of supported languages",
    ["server"],
)

TTS_VOICES_TOTAL = Gauge(
    "tts_voices_total",
    "Total number of available voices",
    ["server"],
)

# Errors
TTS_ERRORS_TOTAL = Counter(
    "tts_errors_total",
    "Total TTS errors",
    ["error_type", "server"],
)

# IP filtering
TTS_BLOCKED_REQUESTS_TOTAL = Counter(
    "tts_blocked_requests_total",
    "Total requests blocked by IP filter",
    ["server"],
)

# ============================================
# HELPER FUNCTIONS
# ============================================

def increment_counter(metric: Counter, labels: dict, value: float = 1):
    """Increment a counter metric safely."""
    try:
        metric.labels(**labels).inc(value)
    except Exception as e:
        logger.debug(f"Failed to increment counter: {e}")


def observe_histogram(metric: Histogram, labels: dict, value: float):
    """Observe a histogram metric safely."""
    try:
        metric.labels(**labels).observe(value)
    except Exception as e:
        logger.debug(f"Failed to observe histogram: {e}")


def set_gauge(metric: Gauge, labels: dict, value: float):
    """Set a gauge metric safely."""
    try:
        metric.labels(**labels).set(value)
    except Exception as e:
        logger.debug(f"Failed to set gauge: {e}")


# ============================================
# CONVENIENCE FUNCTIONS FOR TTS METRICS
# ============================================

def track_tts_request(language: str, locale: str, status: str, duration: float = None):
    """Track a TTS generation request."""
    increment_counter(TTS_REQUESTS_TOTAL, {
        "language": language,
        "locale": locale or "default",
        "status": status,
        "server": SERVER_NAME,
    })
    if duration is not None:
        observe_histogram(TTS_GENERATION_DURATION_SECONDS, {
            "language": language,
            "locale": locale or "default",
            "server": SERVER_NAME,
        }, duration)


def track_text_length(language: str, length: int):
    """Track text length for TTS request."""
    observe_histogram(TTS_TEXT_LENGTH, {
        "language": language,
        "server": SERVER_NAME,
    }, length)


def track_audio_size(language: str, locale: str, size_bytes: int):
    """Track generated audio size."""
    observe_histogram(TTS_AUDIO_SIZE_BYTES, {
        "language": language,
        "locale": locale or "default",
        "server": SERVER_NAME,
    }, size_bytes)


def track_voice_usage(language: str, locale: str, voice: str, gender: str, quality: str):
    """Track voice usage."""
    increment_counter(TTS_VOICE_USAGE_TOTAL, {
        "language": language,
        "locale": locale or "default",
        "voice": voice,
        "gender": gender,
        "quality": quality,
        "server": SERVER_NAME,
    })


def set_active_generations(count: int):
    """Set current active generations count."""
    set_gauge(TTS_ACTIVE_GENERATIONS, {
        "server": SERVER_NAME,
    }, count)


def increment_active_generations():
    """Increment active generations."""
    TTS_ACTIVE_GENERATIONS.labels(server=SERVER_NAME).inc()


def decrement_active_generations():
    """Decrement active generations."""
    TTS_ACTIVE_GENERATIONS.labels(server=SERVER_NAME).dec()


def set_catalog_stats(languages: int, voices: int):
    """Set catalog statistics."""
    set_gauge(TTS_LANGUAGES_TOTAL, {"server": SERVER_NAME}, languages)
    set_gauge(TTS_VOICES_TOTAL, {"server": SERVER_NAME}, voices)


def track_tts_error(error_type: str):
    """Track TTS error."""
    increment_counter(TTS_ERRORS_TOTAL, {
        "error_type": error_type,
        "server": SERVER_NAME,
    })


def track_blocked_request():
    """Track blocked request by IP filter."""
    increment_counter(TTS_BLOCKED_REQUESTS_TOTAL, {
        "server": SERVER_NAME,
    })


# ============================================
# PATH NORMALIZATION
# ============================================

def normalize_path(path: str) -> str:
    """Normalize path to avoid high cardinality."""
    parts = path.split("/")
    normalized = []
    
    for part in parts:
        if not part:
            continue
        # Replace language codes (2-3 chars) after specific paths
        # Keep them as-is for TTS paths since they're meaningful labels
        normalized.append(part)
    
    return "/" + "/".join(normalized) if normalized else "/"


def get_status_class(status_code: int) -> str:
    """Get status class for grouping."""
    if 200 <= status_code < 300:
        return "2xx"
    elif 300 <= status_code < 400:
        return "3xx"
    elif 400 <= status_code < 500:
        return "4xx"
    else:
        return "5xx"


# ============================================
# SETUP FUNCTION
# ============================================

def setup_metrics(app: FastAPI, server_version: str = "2.2.0") -> None:
    """
    Setup Prometheus metrics for the Piper TTS FastAPI application.
    
    Usage:
        from metrics import setup_metrics
        setup_metrics(app, server_version="2.2.0")
    """
    global SERVER_VERSION
    SERVER_VERSION = server_version
    
    SERVER_INFO.info({
        "server_name": SERVER_NAME,
        "server_type": SERVER_TYPE,
        "version": SERVER_VERSION,
    })
    
    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next: Callable):
        method = request.method
        path = normalize_path(request.url.path)
        
        # Skip metrics endpoint to avoid recursion
        if path == "/metrics":
            return await call_next(request)
        
        HTTP_REQUESTS_IN_PROGRESS.labels(
            method=method,
            server=SERVER_NAME,
        ).inc()
        
        start_time = time.perf_counter()
        status_code = 500
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = time.perf_counter() - start_time
            
            increment_counter(HTTP_REQUESTS_TOTAL, {
                "method": method,
                "endpoint": path,
                "status": get_status_class(status_code),
                "server": SERVER_NAME,
            })
            
            observe_histogram(HTTP_REQUEST_DURATION_SECONDS, {
                "method": method,
                "endpoint": path,
                "server": SERVER_NAME,
            }, duration)
            
            HTTP_REQUESTS_IN_PROGRESS.labels(
                method=method,
                server=SERVER_NAME,
            ).dec()
    
    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint():
        """Prometheus metrics endpoint."""
        return Response(
            content=generate_latest(REGISTRY),
            media_type=CONTENT_TYPE_LATEST,
        )
    
    logger.info(
        "Prometheus metrics enabled",
        extra={
            "server_name": SERVER_NAME,
            "server_version": SERVER_VERSION,
        },
    )
