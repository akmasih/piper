# File: app/config.py - /root/piper/app/config.py
# Configuration settings for Piper TTS service with monitoring support

import os
from typing import Optional
from pathlib import Path

class Settings:
    """Configuration settings loaded from environment variables"""
    
    def __init__(self):
        # Server Configuration
        self.SERVER_NAME = os.getenv("SERVER_NAME", "piper")
        self.TAILSCALE_IP = os.getenv("TAILSCALE_IP", "100.109.226.109")
        self.PORT = int(os.getenv("PORT", "8000"))
        self.BACKEND_IP = os.getenv("BACKEND_IP", "100.116.174.15")
        
        # Audio Configuration
        self.DEFAULT_SAMPLE_RATE = int(os.getenv("DEFAULT_SAMPLE_RATE", "22050"))
        self.MAX_TEXT_LENGTH = int(os.getenv("MAX_TEXT_LENGTH", "5000"))
        self.OUTPUT_FORMAT = os.getenv("OUTPUT_FORMAT", "mp3")
        self.MP3_BITRATE = os.getenv("MP3_BITRATE", "128k")
        
        # Model Configuration
        self.MODEL_QUALITY_PREFERENCE = os.getenv("MODEL_QUALITY_PREFERENCE", "high,medium,low,x-low").split(',')
        
        # Language Model Mappings - Original Languages
        self.MODEL_EN = os.getenv("MODEL_EN", "en_US-lessac-high")
        self.MODEL_DE = os.getenv("MODEL_DE", "de_DE-thorsten-high")
        self.MODEL_FR = os.getenv("MODEL_FR", "fr_FR-siwis-medium")
        self.MODEL_ES = os.getenv("MODEL_ES", "es_ES-carlfm-x_low")
        self.MODEL_IT = os.getenv("MODEL_IT", "it_IT-riccardo-x_low")
        self.MODEL_FA = os.getenv("MODEL_FA", "fa_IR-gyro-medium")
        
        # Language Model Mappings - Extended Languages
        self.MODEL_ZH = os.getenv("MODEL_ZH", "zh_CN-huayan-medium")
        self.MODEL_AR = os.getenv("MODEL_AR", "ar_JO-kareem-medium")
        self.MODEL_RU = os.getenv("MODEL_RU", "ru_RU-dmitri-medium")
        self.MODEL_PT = os.getenv("MODEL_PT", "pt_BR-faber-medium")
        self.MODEL_JA = os.getenv("MODEL_JA", "ja_JP-kokoro-medium")
        self.MODEL_SW = os.getenv("MODEL_SW", "sw_CD-lanfrica-medium")
        self.MODEL_TR = os.getenv("MODEL_TR", "tr_TR-dfki-medium")
        self.MODEL_KO = os.getenv("MODEL_KO", "ko_KR-kss-x_low")
        self.MODEL_VI = os.getenv("MODEL_VI", "vi_VN-vais1000-medium")
        
        # Performance Settings
        self.MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "10"))
        self.REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
        self.WORKER_THREADS = int(os.getenv("WORKER_THREADS", "4"))
        
        # Logging Configuration
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.LOG_FORMAT = os.getenv("LOG_FORMAT", "json")
        
        # Monitoring Configuration
        self.LOG_SERVER_IP = os.getenv("LOG_SERVER_IP", "100.122.6.31")
        self.LOKI_URL = os.getenv("LOKI_URL", f"http://{self.LOG_SERVER_IP}:3100")
        self.PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", f"http://{self.LOG_SERVER_IP}:9090")
        self.MONITORING_ENABLED = os.getenv("MONITORING_ENABLED", "true").lower() == "true"
        
        # Temporary Directory
        self.TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/piper")
        
        # Rate Limiting (requests per minute from backend)
        self.RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
        self.RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "100"))
        
        # Supported languages list for validation
        self.SUPPORTED_LANGUAGES = [
            'en', 'de', 'fr', 'es', 'it', 'fa',  # Original
            'zh', 'ar', 'ru', 'pt', 'ja', 'sw', 'tr', 'ko', 'vi'  # Extended
        ]
    
    def get_model_for_language(self, language: str) -> Optional[str]:
        """
        Get model name for a specific language
        
        Args:
            language: Language code (en, de, fr, es, it, fa, zh, ar, ru, pt, ja, sw, tr, ko, vi)
            
        Returns:
            Model name or None if language not supported
        """
        model_mapping = {
            # Original languages
            'en': self.MODEL_EN,
            'de': self.MODEL_DE,
            'fr': self.MODEL_FR,
            'es': self.MODEL_ES,
            'it': self.MODEL_IT,
            'fa': self.MODEL_FA,
            # Extended languages
            'zh': self.MODEL_ZH,
            'ar': self.MODEL_AR,
            'ru': self.MODEL_RU,
            'pt': self.MODEL_PT,
            'ja': self.MODEL_JA,
            'sw': self.MODEL_SW,
            'tr': self.MODEL_TR,
            'ko': self.MODEL_KO,
            'vi': self.MODEL_VI
        }
        return model_mapping.get(language)
    
    def validate(self):
        """
        Validate configuration settings
        
        Returns:
            True if configuration is valid
            
        Raises:
            ValueError: If configuration is invalid
        """
        errors = []
        
        # Validate required settings
        if not self.BACKEND_IP:
            errors.append("BACKEND_IP is required")
        
        if not self.LOG_SERVER_IP and self.MONITORING_ENABLED:
            errors.append("LOG_SERVER_IP is required when monitoring is enabled")
        
        # Validate model configurations for all supported languages
        for lang in self.SUPPORTED_LANGUAGES:
            model = self.get_model_for_language(lang)
            if not model:
                errors.append(f"Model for language {lang} is not configured")
        
        # Validate and create temp directory
        temp_path = Path(self.TEMP_DIR)
        if not temp_path.exists():
            try:
                temp_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                errors.append(f"Cannot create temp directory: {e}")
        
        # Validate numeric settings
        if self.PORT < 1 or self.PORT > 65535:
            errors.append(f"Invalid port number: {self.PORT}")
        
        if self.MAX_CONCURRENT_REQUESTS < 1:
            errors.append("MAX_CONCURRENT_REQUESTS must be at least 1")
        
        if self.REQUEST_TIMEOUT < 1:
            errors.append("REQUEST_TIMEOUT must be at least 1 second")
        
        if errors:
            raise ValueError(f"Configuration errors: {'; '.join(errors)}")
        
        return True
    
    def get_monitoring_config(self) -> dict:
        """
        Get monitoring configuration as dictionary
        
        Returns:
            Dictionary with monitoring settings
        """
        return {
            'enabled': self.MONITORING_ENABLED,
            'log_server_ip': self.LOG_SERVER_IP,
            'loki_url': self.LOKI_URL,
            'prometheus_url': self.PROMETHEUS_URL,
            'log_level': self.LOG_LEVEL,
            'log_format': self.LOG_FORMAT
        }
    
    def get_server_info(self) -> dict:
        """
        Get server information as dictionary
        
        Returns:
            Dictionary with server information
        """
        return {
            'server_name': self.SERVER_NAME,
            'server_ip': self.TAILSCALE_IP,
            'port': self.PORT,
            'backend_ip': self.BACKEND_IP,
            'service': 'piper-tts'
        }
    
    def get_language_info(self) -> dict:
        """
        Get language information with human-readable names
        
        Returns:
            Dictionary mapping language codes to info
        """
        return {
            'en': {'name': 'English', 'native': 'English', 'region': 'US'},
            'de': {'name': 'German', 'native': 'Deutsch', 'region': 'DE'},
            'fr': {'name': 'French', 'native': 'Français', 'region': 'FR'},
            'es': {'name': 'Spanish', 'native': 'Español', 'region': 'ES'},
            'it': {'name': 'Italian', 'native': 'Italiano', 'region': 'IT'},
            'fa': {'name': 'Persian', 'native': 'فارسی', 'region': 'IR'},
            'zh': {'name': 'Chinese', 'native': '中文', 'region': 'CN'},
            'ar': {'name': 'Arabic', 'native': 'العربية', 'region': 'JO'},
            'ru': {'name': 'Russian', 'native': 'Русский', 'region': 'RU'},
            'pt': {'name': 'Portuguese', 'native': 'Português', 'region': 'BR'},
            'ja': {'name': 'Japanese', 'native': '日本語', 'region': 'JP'},
            'sw': {'name': 'Swahili', 'native': 'Kiswahili', 'region': 'CD'},
            'tr': {'name': 'Turkish', 'native': 'Türkçe', 'region': 'TR'},
            'ko': {'name': 'Korean', 'native': '한국어', 'region': 'KR'},
            'vi': {'name': 'Vietnamese', 'native': 'Tiếng Việt', 'region': 'VN'}
        }

# Global settings instance
settings = Settings()

# Validate configuration on module import
try:
    settings.validate()
except ValueError as e:
    import logging
    logging.warning(f"Configuration warning: {e}")