# File: app/main.py - /root/piper/app/main.py
# FastAPI main application for Piper TTS service

import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator
import uvicorn

from app.config import settings
from app.tts_service import PiperTTSService

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
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
        logger.info("Initializing Piper TTS service...")
        tts_service = PiperTTSService()
        await tts_service.initialize()
        logger.info("Piper TTS service initialized successfully")
        yield
    finally:
        if tts_service:
            await tts_service.cleanup()
        logger.info("Piper TTS service shutdown complete")

app = FastAPI(
    title="Piper TTS Service",
    description="Text-to-Speech service using Piper for Lingudesk system",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://{settings.BACKEND_IP}:8000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

class TTSRequest(BaseModel):
    """Request model for TTS generation"""
    text: str = Field(..., min_length=1, max_length=5000)
    language: str = Field(..., pattern="^(en|de|fr|es|it|fa)$")
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

class HealthResponse(BaseModel):
    """Model for health check response"""
    status: str
    service: str
    models_loaded: int
    available_languages: list

@app.middleware("http")
async def verify_backend_ip(request: Request, call_next):
    """
    Middleware to verify requests are from authorized backend
    Only allows requests from configured BACKEND_IP
    """
    client_ip = request.client.host
    
    # Allow health checks from localhost for Docker health check
    if request.url.path == "/health" and client_ip in ["127.0.0.1", "::1"]:
        return await call_next(request)
    
    # Verify client IP matches backend IP
    if client_ip != settings.BACKEND_IP:
        logger.warning(f"Unauthorized access attempt from {client_ip}")
        return Response(content="Forbidden", status_code=403)
    
    return await call_next(request)

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint
    Returns service status and available models
    """
    if not tts_service or not tts_service.is_ready():
        raise HTTPException(status_code=503, detail="Service not ready")
    
    return HealthResponse(
        status="healthy",
        service="piper-tts",
        models_loaded=len(tts_service.loaded_models),
        available_languages=tts_service.get_available_languages()
    )

@app.get("/tts/voices", response_model=Dict[str, list[VoiceInfo]])
async def get_voices():
    """
    Get available voices for all languages
    Returns dictionary mapping languages to voice info
    """
    if not tts_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        voices = await tts_service.get_voices()
        return voices
    except Exception as e:
        logger.error(f"Error getting voices: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve voices")

@app.post("/tts/generate")
async def generate_speech(request: TTSRequest):
    """
    Generate speech from text
    Returns audio stream in MP3 format
    """
    if not tts_service:
        raise HTTPException(status_code=503, detail="Service not initialized")
    
    try:
        logger.info(f"TTS request: language={request.language}, text_length={len(request.text)}")
        
        audio_data = await tts_service.generate_speech(
            text=request.text,
            language=request.language,
            voice=request.voice,
            speed=request.speed
        )
        
        if not audio_data:
            raise HTTPException(status_code=500, detail="Failed to generate audio")
        
        return StreamingResponse(
            audio_data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": f"inline; filename=speech_{request.language}.mp3",
                "Cache-Control": "no-cache",
                "X-TTS-Language": request.language,
                "X-TTS-Model": tts_service.get_model_name(request.language)
            }
        )
        
    except ValueError as e:
        logger.error(f"Invalid request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating speech: {e}")
        raise HTTPException(status_code=500, detail="Speech generation failed")

@app.get("/")
async def root():
    """
    Root endpoint
    Returns basic service information
    """
    return {
        "service": "Piper TTS",
        "version": "1.0.0",
        "status": "running"
    }

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        workers=2,
        log_level=settings.LOG_LEVEL.lower()
    )