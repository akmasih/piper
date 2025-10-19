# /root/piper/app/config.py
import os
from typing import Optional
from pathlib import Path

class Settings:
    def __init__(self):
        self.SERVER_NAME = os.getenv("SERVER_NAME", "piper")
        self.TAILSCALE_IP = os.getenv("TAILSCALE_IP", "100.109.226.109")
        self.PORT = int(os.getenv("PORT", "8000"))
        self.BACKEND_IP = os.getenv("BACKEND_IP", "100.116.174.15")
        self.DEFAULT_SAMPLE_RATE = int(os.getenv("DEFAULT_SAMPLE_RATE", "22050"))
        self.MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", "5000"))
        self.OUTPUT_FORMAT = os.getenv("OUTPUT_FORMAT", "mp3")
        self.MP3_BITRATE = os.getenv("MP3_BITRATE", "128k")
        self.MODEL_QUALITY_PREFERENCE = os.getenv("MODEL_QUALITY_PREFERENCE", "high,medium,low,x-low").split(',')
        self.MODEL_EN = os.getenv("MODEL_EN", "en_US-lessac-high")
        self.MODEL_DE = os.getenv("MODEL_DE", "de_DE-thorsten-high")
        self.MODEL_FR = os.getenv("MODEL_FR", "fr_FR-siwis-medium")
        self.MODEL_ES = os.getenv("MODEL_ES", "es_ES-carlfm-x_low")
        self.MODEL_IT = os.getenv("MODEL_IT", "it_IT-riccardo-x_low")
        self.MODEL_FA = os.getenv("MODEL_FA", "fa_IR-gyro-medium")
        self.MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "10"))
        self.REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
        self.WORKER_THREADS = int(os.getenv("WORKER_THREADS", "4"))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.LOG_FORMAT = os.getenv("LOG_FORMAT", "json")
        self.TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/piper")
        self.RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
        self.RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "100"))
    
    def get_model_for_language(self, language: str) -> Optional[str]:
        model_mapping = {
            'en': self.MODEL_EN,
            'de': self.MODEL_DE,
            'fr': self.MODEL_FR,
            'es': self.MODEL_ES,
            'it': self.MODEL_IT,
            'fa': self.MODEL_FA
        }
        return model_mapping.get(language)
    
    def validate(self):
        errors = []
        if not self.BACKEND_IP:
            errors.append("BACKEND_IP is required")
        for lang in ['en', 'de', 'fr', 'es', 'it', 'fa']:
            model = self.get_model_for_language(lang)
            if not model:
                errors.append(f"Model for language {lang} is not configured")
        temp_path = Path(self.TEMP_DIR)
        if not temp_path.exists():
            try:
                temp_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Cannot create temp directory: {e}")
        if errors:
            raise ValueError(f"Configuration errors: {'; '.join(errors)}")
        return True

settings = Settings()

try:
    settings.validate()
except ValueError as e:
    import logging
    logging.warning(f"Configuration warning: {e}")
