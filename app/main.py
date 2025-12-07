# File: app/main.py - /root/piper/app/main.py
# FastAPI main application for Piper TTS service with centralized logging and monitoring

import logging
import re
import sys
import time
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, validator
from pythonjsonlogger import jsonlogger
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import uvicorn

from app.config import settings
from app.tts_service import PiperTTSService


class ErrorResponse(BaseModel):
    """Standard error response model"""
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None
    hint: Optional[str] = None

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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Custom handler for validation errors
    Provides user-friendly error messages especially for language validation
    """
    errors = exc.errors()
    
    # Check if this is a language validation error
    for error in errors:
        if 'language' in error.get('loc', []):
            invalid_value = error.get('input', 'unknown')
            
            logger.warning("Invalid language requested", extra={
                'event': 'invalid_language_request',
                'requested_language': invalid_value,
                'available_languages': settings.SUPPORTED_LANGUAGES
            })
            
            return JSONResponse(
                status_code=400,
                content={
                    "error": "unsupported_language",
                    "message": f"Language '{invalid_value}' is not supported",
                    "details": {
                        "requested_language": invalid_value,
                        "available_languages": settings.SUPPORTED_LANGUAGES,
                        "total_supported": len(settings.SUPPORTED_LANGUAGES)
                    },
                    "hint": "Use GET /piper/tts/languages for detailed information about supported languages"
                }
            )
    
    # Check if this is a text validation error
    for error in errors:
        if 'text' in error.get('loc', []):
            error_type = error.get('type', '')
            
            if 'too_short' in error_type or 'min_length' in error_type:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "text_too_short",
                        "message": "Text cannot be empty",
                        "details": {
                            "min_length": 1,
                            "max_length": settings.MAX_TEXT_LENGTH
                        },
                        "hint": "Provide at least 1 character of text"
                    }
                )
            
            if 'too_long' in error_type or 'max_length' in error_type:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": "text_too_long",
                        "message": f"Text exceeds maximum length of {settings.MAX_TEXT_LENGTH} characters",
                        "details": {
                            "max_length": settings.MAX_TEXT_LENGTH,
                            "provided_length": len(error.get('input', ''))
                        },
                        "hint": f"Reduce text to {settings.MAX_TEXT_LENGTH} characters or less"
                    }
                )
    
    # Check if this is a speed validation error
    for error in errors:
        if 'speed' in error.get('loc', []):
            invalid_value = error.get('input', 'unknown')
            
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_speed",
                    "message": f"Speed value '{invalid_value}' is out of range",
                    "details": {
                        "provided_speed": invalid_value,
                        "min_speed": 0.5,
                        "max_speed": 2.0,
                        "default_speed": 1.0
                    },
                    "hint": "Speed must be between 0.5 and 2.0"
                }
            )
    
    # Generic validation error for other cases
    formatted_errors = []
    for error in errors:
        formatted_errors.append({
            "field": ".".join(str(loc) for loc in error.get('loc', [])),
            "message": error.get('msg', 'Validation error'),
            "type": error.get('type', 'unknown')
        })
    
    return JSONResponse(
        status_code=400,
        content={
            "error": "validation_error",
            "message": "Request validation failed",
            "details": {
                "errors": formatted_errors
            },
            "hint": "Check the request parameters and try again"
        }
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Custom handler for HTTP exceptions
    Provides consistent error response format
    """
    error_mapping = {
        400: "bad_request",
        403: "forbidden",
        404: "not_found",
        500: "internal_error",
        503: "service_unavailable"
    }
    
    error_code = error_mapping.get(exc.status_code, "error")
    
    response_content = {
        "error": error_code,
        "message": exc.detail
    }
    
    # Add helpful hints based on error type
    if exc.status_code == 403:
        response_content["hint"] = "This endpoint only accepts requests from authorized backend servers"
    elif exc.status_code == 503:
        response_content["hint"] = "The service is starting up or temporarily unavailable. Please try again shortly"
        response_content["details"] = {
            "health_check": "/piper/health"
        }
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response_content
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
        models_loaded = len(tts_service.loaded_models) if tts_service else 0
        is_ready = tts_service.is_ready() if tts_service else False
        
        logger.warning("Health check failed - service not ready", extra={
            'event': 'health_check_failed',
            'service_ready': is_ready,
            'models_loaded': models_loaded
        })
        
        return JSONResponse(
            status_code=503,
            content={
                "error": "service_not_ready",
                "message": "The TTS service is not ready to accept requests",
                "details": {
                    "service_initialized": tts_service is not None,
                    "models_loaded": models_loaded,
                    "is_ready": is_ready
                },
                "hint": "The service may still be starting up. Please wait and try again"
            }
        )
    
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
        return JSONResponse(
            status_code=503,
            content={
                "error": "service_not_initialized",
                "message": "The TTS service is not initialized",
                "hint": "Check /piper/health for service status"
            }
        )
    
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
        return JSONResponse(
            status_code=500,
            content={
                "error": "voices_retrieval_failed",
                "message": "Failed to retrieve available voices",
                "hint": "Please try again or check /piper/health for service status"
            }
        )

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
        return JSONResponse(
            status_code=503,
            content={
                "error": "service_not_initialized",
                "message": "The TTS service is not initialized",
                "hint": "Check /piper/health for service status"
            }
        )
    
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
        return JSONResponse(
            status_code=500,
            content={
                "error": "languages_retrieval_failed",
                "message": "Failed to retrieve language information",
                "hint": "Please try again or check /piper/health for service status"
            }
        )

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
        return JSONResponse(
            status_code=503,
            content={
                "error": "service_not_initialized",
                "message": "The TTS service is not initialized",
                "details": {
                    "requested_language": request.language,
                    "text_length": len(request.text)
                },
                "hint": "The service may still be starting up. Check /piper/health for status"
            }
        )
    
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
            return JSONResponse(
                status_code=500,
                content={
                    "error": "no_audio_generated",
                    "message": "The TTS engine did not produce any audio output",
                    "details": {
                        "language": request.language,
                        "text_length": len(request.text),
                        "model": tts_service.get_model_name(request.language)
                    },
                    "hint": "This may be due to unsupported characters in the text. Try simplifying the input"
                }
            )
        
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
        error_message = str(e)
        
        logger.warning("Invalid TTS request", extra={
            'event': 'tts_generation_invalid',
            'language': request.language,
            'error': error_message,
            'duration': round(duration, 3)
        })
        TTS_GENERATION_COUNT.labels(language=request.language, status='invalid').inc()
        
        # Check if this is a language-related error
        if "not available" in error_message or "not supported" in error_message:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "unsupported_language",
                    "message": error_message,
                    "details": {
                        "requested_language": request.language,
                        "available_languages": tts_service.get_available_languages() if tts_service else [],
                        "generation_time": round(duration, 3)
                    },
                    "hint": "Use GET /piper/tts/languages for detailed information about supported languages"
                }
            )
        
        # Check if this is a text-related error
        if "empty" in error_message.lower():
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_text",
                    "message": error_message,
                    "details": {
                        "text_length": len(request.text) if request.text else 0
                    },
                    "hint": "Provide non-empty text for speech generation"
                }
            )
        
        # Generic value error
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_request",
                "message": error_message,
                "hint": "Check your request parameters"
            }
        )
    except Exception as e:
        duration = time.time() - start_time
        error_message = str(e)
        
        logger.error("TTS generation error", extra={
            'event': 'tts_generation_error',
            'language': request.language,
            'error': error_message,
            'error_type': type(e).__name__,
            'duration': round(duration, 3)
        }, exc_info=True)
        TTS_GENERATION_COUNT.labels(language=request.language, status='error').inc()
        
        return JSONResponse(
            status_code=500,
            content={
                "error": "generation_failed",
                "message": "Speech generation failed due to an internal error",
                "details": {
                    "language": request.language,
                    "text_length": len(request.text),
                    "generation_time": round(duration, 3)
                },
                "hint": "Please try again. If the problem persists, check /piper/health for service status"
            }
        )

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