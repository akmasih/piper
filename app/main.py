# File: app/main.py - /root/piper/app/main.py
# FastAPI main application for Piper TTS service with centralized logging and monitoring

import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import uvicorn

from app.config import settings
from app.tts_service import PiperTTSService

# Prometheus Metrics
REQUEST_COUNT = Counter(
    'piper_requests_total',
    'Total number of requests',
    ['method', 'endpoint', 'status']
)

REQUEST_DURATION = Histogram(
    'piper_request_duration_seconds',
    'Request duration in seconds',
    ['method', 'endpoint']
)

TTS_GENERATION_COUNT = Counter(
    'piper_tts_generations_total',
    'Total TTS generations',
    ['language', 'status']
)

TTS_GENERATION_DURATION = Histogram(
    'piper_tts_generation_duration_seconds',
    'TTS generation duration in seconds',
    ['language']
)

ACTIVE_REQUESTS = Gauge(
    'piper_active_requests',
    'Number of active requests'
)

MODEL_LOAD_STATUS = Gauge(
    'piper_model_loaded',
    'Model load status (1=loaded, 0=not loaded)',
    ['language', 'model_name']
)

# JSON Structured Logging Setup
class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with additional metadata"""
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        log_record['server_name'] = settings.SERVER_NAME
        log_record['server_ip'] = settings.TAILSCALE_IP
        log_record['service'] = 'piper-tts'
        log_record['environment'] = 'production'
        log_record['timestamp'] = self.formatTime(record, self.datefmt)

# Configure logging
log_handler = logging.StreamHandler(sys.stdout)
formatter = CustomJsonFormatter(
    '%(timestamp)s %(name)s %(levelname)s %(message)s %(server_name)s %(server_ip)s %(service)s'
)
log_handler.setFormatter(formatter)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    handlers=[log_handler]
)
logger = logging.getLogger(__name__)

tts_service = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application
    Handles startup and shutdown events
    """
    global tts_service
    try:
        logger.info("Initializing Piper TTS service", extra={
            'event': 'service_startup',
            'version': '1.1.0'
        })
        
        tts_service = PiperTTSService()
        await tts_service.initialize()
        
        # Update model load status metrics
        for lang, model_name in tts_service.loaded_models.items():
            MODEL_LOAD_STATUS.labels(language=lang, model_name=model_name).set(1)
        
        logger.info("Piper TTS service initialized successfully", extra={
            'event': 'service_ready',
            'models_loaded': len(tts_service.loaded_models),
            'languages': list(tts_service.loaded_models.keys())
        })
        
        # Store start time for uptime calculation
        app.state.start_time = time.time()
        
        yield
    except Exception as e:
        logger.error("Failed to initialize service", extra={
            'event': 'service_startup_failed',
            'error': str(e),
            'error_type': type(e).__name__
        }, exc_info=True)
        raise
    finally:
        if tts_service:
            await tts_service.cleanup()
        logger.info("Piper TTS service shutdown complete", extra={
            'event': 'service_shutdown'
        })

app = FastAPI(
    title="Piper TTS Service",
    description="Text-to-Speech service using Piper for Lingudesk system - Supports 15 languages",
    version="1.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://{settings.BACKEND_IP}:8000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Language pattern for validation - 15 supported languages
LANGUAGE_PATTERN = "^(en|de|fr|es|it|fa|zh|ar|ru|pt|ja|sw|tr|ko|vi)$"

class TTSRequest(BaseModel):
    """Request model for TTS generation"""
    text: str = Field(..., min_length=1, max_length=5000)
    language: str = Field(..., pattern=LANGUAGE_PATTERN)
    voice: str = Field(None, description="Optional specific voice name")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    
    @validator('text')
    def clean_text(cls, v):
        """Clean and validate text input"""
        v = ' '.join(v.split())
        if not v:
            raise ValueError("Text cannot be empty after cleaning")
        return v

class VoiceInfo(BaseModel):
    """Model for voice information"""
    voice_id: str
    language: str
    name: str
    quality: str
    sample_rate: int

class LanguageInfo(BaseModel):
    """Model for language information"""
    code: str
    name: str
    native_name: str
    region: str
    model: str
    quality: str

class HealthResponse(BaseModel):
    """Model for health check response"""
    status: str
    service: str
    version: str
    models_loaded: int
    available_languages: list
    uptime_seconds: float = None

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """
    Middleware for metrics collection and request tracking
    """
    ACTIVE_REQUESTS.inc()
    start_time = time.time()
    
    try:
        response = await call_next(request)
        duration = time.time() - start_time
        
        # Record metrics
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code
        ).inc()
        
        REQUEST_DURATION.labels(
            method=request.method,
            endpoint=request.url.path
        ).observe(duration)
        
        # Log request
        logger.info("Request completed", extra={
            'event': 'request_completed',
            'method': request.method,
            'path': request.url.path,
            'status_code': response.status_code,
            'duration': round(duration, 3),
            'client_ip': request.client.host
        })
        
        return response
    except Exception as e:
        duration = time.time() - start_time
        logger.error("Request failed", extra={
            'event': 'request_failed',
            'method': request.method,
            'path': request.url.path,
            'duration': round(duration, 3),
            'error': str(e),
            'error_type': type(e).__name__
        }, exc_info=True)
        raise
    finally:
        ACTIVE_REQUESTS.dec()

@app.middleware("http")
async def verify_backend_ip(request: Request, call_next):
    """
    Middleware to verify requests are from authorized backend
    Only allows requests from configured BACKEND_IP
    """
    client_ip = request.client.host
    
    # Allow health checks and metrics from localhost for Docker health check and monitoring
    if request.url.path in ["/piper/health", "/piper/metrics"] and client_ip in ["127.0.0.1", "::1"]:
        return await call_next(request)
    
    # Verify client IP matches backend IP
    if client_ip != settings.BACKEND_IP:
        logger.warning("Unauthorized access attempt", extra={
            'event': 'unauthorized_access',
            'client_ip': client_ip,
            'path': request.url.path,
            'expected_ip': settings.BACKEND_IP
        })
        return Response(content="Forbidden", status_code=403)
    
    return await call_next(request)

@app.get("/piper/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint
    Returns service status and available models
    """
    if not tts_service or not tts_service.is_ready():
        logger.warning("Health check failed - service not ready", extra={
            'event': 'health_check_failed',
            'service_ready': tts_service.is_ready() if tts_service else False
        })
        raise HTTPException(status_code=503, detail="Service not ready")
    
    uptime = time.time() - app.state.start_time if hasattr(app.state, 'start_time') else 0
    
    return HealthResponse(
        status="healthy",
        service="piper-tts",
        version="1.1.0",
        models_loaded=len(tts_service.loaded_models),
        available_languages=tts_service.get_available_languages(),
        uptime_seconds=round(uptime, 2)
    )

@app.get("/piper/metrics")
async def metrics():
    """
    Prometheus metrics endpoint
    Returns metrics in Prometheus format
    """
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )

@app.get("/piper/tts/voices", response_model=Dict[str, list[VoiceInfo]])
async def get_voices():
    """
    Get available voices for all languages
    Returns dictionary mapping languages to voice info
    """
    if not tts_service:
        logger.error("Voices request failed - service not initialized", extra={
            'event': 'voices_request_failed'
        })
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        voices = await tts_service.get_voices()
        logger.debug("Voices list retrieved", extra={
            'event': 'voices_retrieved',
            'languages_count': len(voices)
        })
        return voices
    except Exception as e:
        logger.error("Error getting voices", extra={
            'event': 'voices_error',
            'error': str(e),
            'error_type': type(e).__name__
        }, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve voices")

@app.get("/piper/tts/languages", response_model=Dict[str, LanguageInfo])
async def get_languages():
    """
    Get information about all supported languages
    Returns dictionary with language details
    """
    if not tts_service:
        logger.error("Languages request failed - service not initialized", extra={
            'event': 'languages_request_failed'
        })
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        language_info = settings.get_language_info()
        result = {}
        
        for code, info in language_info.items():
            if code in tts_service.loaded_models:
                model_name = tts_service.loaded_models[code]
                result[code] = LanguageInfo(
                    code=code,
                    name=info['name'],
                    native_name=info['native'],
                    region=info['region'],
                    model=model_name,
                    quality=tts_service._extract_quality(model_name)
                )
        
        logger.debug("Languages list retrieved", extra={
            'event': 'languages_retrieved',
            'languages_count': len(result)
        })
        return result
    except Exception as e:
        logger.error("Error getting languages", extra={
            'event': 'languages_error',
            'error': str(e),
            'error_type': type(e).__name__
        }, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve languages")

@app.post("/piper/tts/generate")
async def generate_speech(request: TTSRequest):
    """
    Generate speech from text
    Returns audio stream in MP3 format
    """
    if not tts_service:
        logger.error("TTS generation failed - service not initialized", extra={
            'event': 'tts_generation_failed',
            'reason': 'service_not_initialized'
        })
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    start_time = time.time()
    
    try:
        logger.info("TTS generation started", extra={
            'event': 'tts_generation_started',
            'language': request.language,
            'text_length': len(request.text),
            'speed': request.speed,
            'voice': request.voice
        })
        
        audio_data = await tts_service.generate_speech(
            text=request.text,
            language=request.language,
            voice=request.voice,
            speed=request.speed
        )
        
        if not audio_data:
            logger.error("TTS generation produced no audio", extra={
                'event': 'tts_generation_no_audio',
                'language': request.language
            })
            TTS_GENERATION_COUNT.labels(language=request.language, status='failed').inc()
            raise HTTPException(status_code=500, detail="Failed to generate audio")
        
        duration = time.time() - start_time
        
        # Update metrics
        TTS_GENERATION_COUNT.labels(language=request.language, status='success').inc()
        TTS_GENERATION_DURATION.labels(language=request.language).observe(duration)
        
        logger.info("TTS generation completed", extra={
            'event': 'tts_generation_completed',
            'language': request.language,
            'duration': round(duration, 3),
            'text_length': len(request.text),
            'model': tts_service.get_model_name(request.language)
        })
        
        return StreamingResponse(
            audio_data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f"inline; filename=speech_{request.language}.mp3",
                "Cache-Control": "no-cache",
                "X-TTS-Language": request.language,
                "X-TTS-Model": tts_service.get_model_name(request.language),
                "X-Generation-Duration": str(round(duration, 3))
            }
        )
        
    except ValueError as e:
        duration = time.time() - start_time
        logger.warning("Invalid TTS request", extra={
            'event': 'tts_generation_invalid',
            'language': request.language,
            'error': str(e),
            'duration': round(duration, 3)
        })
        TTS_GENERATION_COUNT.labels(language=request.language, status='invalid').inc()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        duration = time.time() - start_time
        logger.error("TTS generation error", extra={
            'event': 'tts_generation_error',
            'language': request.language,
            'error': str(e),
            'error_type': type(e).__name__,
            'duration': round(duration, 3)
        }, exc_info=True)
        TTS_GENERATION_COUNT.labels(language=request.language, status='error').inc()
        raise HTTPException(status_code=500, detail="Speech generation failed")

@app.get("/piper/")
async def root():
    """
    Root endpoint
    Returns basic service information
    """
    return {
        "service": "Piper TTS",
        "version": "1.1.0",
        "status": "running",
        "server": settings.SERVER_NAME,
        "prefix": "/piper/",
        "supported_languages": settings.SUPPORTED_LANGUAGES,
        "total_languages": len(settings.SUPPORTED_LANGUAGES)
    }

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        workers=2,
        log_level=settings.LOG_LEVEL.lower()
    )