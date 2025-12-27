# main.py
# /root/piper/app/main.py
# FastAPI application with hierarchical TTS API

import logging
import time
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from config import settings
from tts_service import (
    tts_service,
    TTSError,
    LanguageNotFoundError,
    LocaleNotFoundError,
    GenderNotFoundError,
    VoiceNotFoundError,
    QualityNotFoundError,
    TextValidationError,
    SynthesisError,
)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Lifespan Management
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Piper TTS Server...")

    # Load voice catalog
    if not settings.load_voices():
        logger.error("Failed to load voice catalog!")
    else:
        logger.info(
            f"Loaded {len(settings.catalog.languages)} languages, "
            f"{settings.catalog.total_voices} voices"
        )

    yield

    logger.info("Shutting down Piper TTS Server...")


# =============================================================================
# FastAPI App
# =============================================================================

app = FastAPI(
    title="Piper TTS Server",
    description="Multi-language Text-to-Speech with hierarchical voice selection",
    version="2.0.0",
    lifespan=lifespan,
)


# =============================================================================
# Request/Response Models
# =============================================================================

class TTSRequest(BaseModel):
    """TTS generation request"""
    text: str = Field(..., min_length=1, max_length=5000, description="Text to synthesize")
    language: str = Field(..., min_length=2, max_length=3, description="Language code (e.g., 'en', 'de', 'fa')")
    locale: Optional[str] = Field(None, description="Locale/region code (e.g., 'US', 'GB', 'IR')")
    gender: Optional[str] = Field(None, description="Voice gender filter: 'male', 'female', 'neutral'")
    voice: Optional[str] = Field(None, description="Specific voice name (e.g., 'lessac', 'ryan')")
    quality: Optional[str] = Field(None, description="Quality level: 'high', 'medium', 'low', 'x_low'")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech rate (0.5-2.0)")
    speaker_id: int = Field(0, ge=0, description="Speaker ID for multi-speaker models")

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "text": "Hello, how are you today?",
                    "language": "en",
                    "locale": "US",
                    "gender": "female",
                    "voice": "lessac",
                    "quality": "high",
                    "speed": 1.0,
                },
                {
                    "text": "Guten Tag, wie geht es Ihnen?",
                    "language": "de",
                },
                {
                    "text": "سلام، حالت چطوره؟",
                    "language": "fa",
                    "voice": "gyro",
                },
            ]
        }


class ErrorResponse(BaseModel):
    """Error response with helpful context"""
    error: str
    requested: Optional[str] = None
    available: Optional[list] = None
    hint: Optional[str] = None


# =============================================================================
# Exception Handlers
# =============================================================================

@app.exception_handler(LanguageNotFoundError)
async def language_not_found_handler(request, exc: LanguageNotFoundError):
    return JSONResponse(status_code=404, content=exc.to_dict())


@app.exception_handler(LocaleNotFoundError)
async def locale_not_found_handler(request, exc: LocaleNotFoundError):
    return JSONResponse(status_code=404, content=exc.to_dict())


@app.exception_handler(GenderNotFoundError)
async def gender_not_found_handler(request, exc: GenderNotFoundError):
    return JSONResponse(status_code=400, content=exc.to_dict())


@app.exception_handler(VoiceNotFoundError)
async def voice_not_found_handler(request, exc: VoiceNotFoundError):
    return JSONResponse(status_code=404, content=exc.to_dict())


@app.exception_handler(QualityNotFoundError)
async def quality_not_found_handler(request, exc: QualityNotFoundError):
    return JSONResponse(status_code=400, content=exc.to_dict())


@app.exception_handler(TextValidationError)
async def text_validation_handler(request, exc: TextValidationError):
    return JSONResponse(status_code=400, content=exc.to_dict())


@app.exception_handler(SynthesisError)
async def synthesis_error_handler(request, exc: SynthesisError):
    return JSONResponse(status_code=500, content=exc.to_dict())


@app.exception_handler(TTSError)
async def tts_error_handler(request, exc: TTSError):
    return JSONResponse(status_code=500, content=exc.to_dict())


# =============================================================================
# Health & Info Endpoints
# =============================================================================

@app.get("/piper/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "piper-tts",
        "version": "2.0.0",
        "languages": len(settings.catalog.languages),
        "voices": settings.catalog.total_voices,
    }


@app.get("/piper/info")
async def server_info():
    """Server information"""
    return {
        "service": "Piper TTS",
        "version": "2.0.0",
        "api_version": "v2",
        "hierarchy": "Language → Locale → Gender → Voice → Quality",
        "stats": tts_service.get_stats(),
        "defaults": {
            "language": settings.default_language,
            "locale": settings.default_locale,
            "quality": settings.default_quality,
            "speed": settings.default_speed,
        },
        "limits": {
            "max_text_length": settings.max_text_length,
            "min_speed": settings.min_speed,
            "max_speed": settings.max_speed,
        },
    }


# =============================================================================
# Language Endpoints
# =============================================================================

@app.get("/piper/tts/languages")
async def list_languages():
    """
    List all supported languages.
    
    Returns languages with their available locales and voice counts.
    """
    languages = tts_service.get_languages()
    return {
        "count": len(languages),
        "languages": languages,
    }


@app.get("/piper/tts/languages/{language}")
async def get_language_details(language: str):
    """
    Get details for a specific language.
    
    Returns language info with all available locales.
    """
    lang = settings.catalog.get_language(language)
    if not lang:
        raise LanguageNotFoundError(
            f"Language '{language}' not found",
            context=None,
        )

    return {
        "code": lang.code,
        "name": lang.name,
        "native_name": lang.native_name,
        "default_locale": lang.default_locale,
        "locales": tts_service.get_locales(language),
        "total_voices": lang.total_voices,
    }


# =============================================================================
# Locale Endpoints
# =============================================================================

@app.get("/piper/tts/languages/{language}/locales")
async def list_locales(language: str):
    """
    List available locales for a language.
    
    Returns locales with voice counts by gender.
    """
    locales = tts_service.get_locales(language)
    return {
        "language": language,
        "count": len(locales),
        "locales": locales,
    }


@app.get("/piper/tts/languages/{language}/locales/{locale}")
async def get_locale_details(language: str, locale: str):
    """
    Get details for a specific locale.
    
    Returns locale info with all available voices.
    """
    loc = settings.catalog.get_locale(language, locale)
    if not loc:
        # Determine specific error
        lang = settings.catalog.get_language(language)
        if not lang:
            raise LanguageNotFoundError(f"Language '{language}' not found")
        raise LocaleNotFoundError(f"Locale '{locale}' not found for '{language}'")

    voices_by_gender = loc.voices_by_gender
    return {
        "code": loc.code,
        "name": loc.name,
        "full_code": f"{language}-{locale}",
        "voices": tts_service.get_voices(language, locale),
        "by_gender": {
            g.value: [v.name for v in voices]
            for g, voices in voices_by_gender.items()
        },
    }


# =============================================================================
# Voice Endpoints
# =============================================================================

@app.get("/piper/tts/languages/{language}/locales/{locale}/voices")
async def list_voices(
    language: str,
    locale: str,
    gender: Optional[str] = Query(None, description="Filter by gender"),
):
    """
    List available voices for a locale.
    
    Optionally filter by gender (male/female/neutral).
    """
    voices = tts_service.get_voices(language, locale, gender)
    return {
        "language": language,
        "locale": locale,
        "gender_filter": gender,
        "count": len(voices),
        "voices": voices,
    }


@app.get("/piper/tts/languages/{language}/locales/{locale}/voices/{voice}")
async def get_voice_details(language: str, locale: str, voice: str):
    """
    Get detailed information about a specific voice.
    
    Returns voice properties and available quality variants.
    """
    details = tts_service.get_voice_details(language, locale, voice)
    return {
        "language": language,
        "locale": locale,
        **details,
    }


# =============================================================================
# Catalog Endpoints
# =============================================================================

@app.get("/piper/tts/catalog")
async def get_full_catalog():
    """
    Get complete voice catalog.
    
    Returns all languages, locales, and voices in hierarchical structure.
    """
    catalog = tts_service.get_full_catalog()
    stats = tts_service.get_stats()
    return {
        "stats": stats,
        "catalog": catalog,
    }


@app.get("/piper/tts/voices")
async def list_all_voices():
    """
    List all voices across all languages (flat list).
    
    Useful for searching or building UI.
    """
    all_voices = []
    for lang_code, lang in settings.catalog.languages.items():
        for locale_code, locale in lang.locales.items():
            for voice_name, voice in locale.voices.items():
                all_voices.append({
                    "language": lang_code,
                    "language_name": lang.name,
                    "locale": locale_code,
                    "locale_name": locale.name,
                    "voice": voice_name,
                    "display_name": voice.display_name,
                    "gender": voice.gender.value,
                    "qualities": [q.value for q in voice.available_qualities],
                    "key": f"{lang_code}_{locale_code}-{voice_name}",
                })

    return {
        "count": len(all_voices),
        "voices": all_voices,
    }


# =============================================================================
# TTS Generation Endpoint
# =============================================================================

@app.post("/piper/tts/generate")
async def generate_speech(request: TTSRequest):
    """
    Generate speech audio from text.
    
    ## Selection Hierarchy
    
    1. **language** (required): Language code like "en", "de", "fa"
    2. **locale** (optional): Region code like "US", "GB", "IR" - defaults to language's default
    3. **gender** (optional): Filter voices by "male", "female", or "neutral"
    4. **voice** (optional): Specific voice name like "lessac", "ryan" - defaults to first available
    5. **quality** (optional): "high", "medium", "low", "x_low" - defaults to best available
    
    ## Examples
    
    **Simple (auto-select everything):**
    ```json
    {"text": "Hello world", "language": "en"}
    ```
    
    **With locale:**
    ```json
    {"text": "Hello world", "language": "en", "locale": "GB"}
    ```
    
    **With gender preference:**
    ```json
    {"text": "Hello world", "language": "en", "gender": "male"}
    ```
    
    **Full control:**
    ```json
    {
        "text": "Hello world",
        "language": "en",
        "locale": "US",
        "gender": "female",
        "voice": "lessac",
        "quality": "high",
        "speed": 1.2
    }
    ```
    
    Returns MP3 audio stream.
    """
    start_time = time.time()

    audio_data = await tts_service.generate_speech(
        text=request.text,
        language=request.language,
        locale=request.locale,
        gender=request.gender,
        voice=request.voice,
        quality=request.quality,
        speed=request.speed,
        speaker_id=request.speaker_id,
    )

    duration = time.time() - start_time
    logger.info(f"Generated speech in {duration:.2f}s")

    return StreamingResponse(
        audio_data,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline; filename=speech.mp3",
            "X-Generation-Time": f"{duration:.3f}",
        },
    )


# =============================================================================
# Legacy Compatibility Endpoint
# =============================================================================

@app.post("/synthesize")
async def legacy_synthesize(request: TTSRequest):
    """
    Legacy endpoint for backward compatibility.
    
    Redirects to /piper/tts/generate
    """
    return await generate_speech(request)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )