# config.py
# /root/piper/app/config.py
# Configuration and data models for Piper TTS with hierarchical voice structure

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class Gender(str, Enum):
    """Voice gender enumeration"""
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


class Quality(str, Enum):
    """Voice quality levels (ordered from best to lowest)"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    X_LOW = "x_low"


# Quality priority for auto-selection (best first)
QUALITY_PRIORITY = [Quality.HIGH, Quality.MEDIUM, Quality.LOW, Quality.X_LOW]


@dataclass
class VoiceVariant:
    """
    A specific voice variant (quality level).
    Example: en_US-lessac-high
    """
    quality: Quality
    model_file: str  # Path to .onnx file
    config_file: str  # Path to .onnx.json file
    sample_rate: int = 22050
    num_speakers: int = 1
    speaker_id_map: Dict[str, int] = field(default_factory=dict)

    @property
    def full_key(self) -> str:
        """Get the full voice key from model file name"""
        return Path(self.model_file).stem


@dataclass
class Voice:
    """
    A voice identity (e.g., lessac, ryan, thorsten).
    Can have multiple quality variants.
    """
    name: str  # Voice name (e.g., "lessac", "ryan")
    display_name: str  # Human-readable name
    gender: Gender
    variants: Dict[Quality, VoiceVariant] = field(default_factory=dict)
    description: str = ""

    @property
    def available_qualities(self) -> List[Quality]:
        """Get available qualities sorted by priority"""
        return [q for q in QUALITY_PRIORITY if q in self.variants]

    @property
    def best_quality(self) -> Optional[Quality]:
        """Get best available quality"""
        qualities = self.available_qualities
        return qualities[0] if qualities else None

    def get_variant(self, quality: Optional[Quality] = None) -> Optional[VoiceVariant]:
        """Get variant by quality or best available"""
        if quality and quality in self.variants:
            return self.variants[quality]
        # Return best available
        best = self.best_quality
        return self.variants.get(best) if best else None


@dataclass
class Locale:
    """
    A locale/accent (e.g., US, GB for English).
    Contains voices grouped by gender.
    """
    code: str  # Locale code (e.g., "US", "GB", "DE")
    name: str  # Display name (e.g., "United States", "United Kingdom")
    voices: Dict[str, Voice] = field(default_factory=dict)  # voice_name -> Voice

    @property
    def voices_by_gender(self) -> Dict[Gender, List[Voice]]:
        """Get voices grouped by gender"""
        result: Dict[Gender, List[Voice]] = {g: [] for g in Gender}
        for voice in self.voices.values():
            result[voice.gender].append(voice)
        return {g: v for g, v in result.items() if v}  # Only non-empty

    def get_voices(self, gender: Optional[Gender] = None) -> List[Voice]:
        """Get voices, optionally filtered by gender"""
        if gender:
            return [v for v in self.voices.values() if v.gender == gender]
        return list(self.voices.values())

    def get_voice(self, name: str) -> Optional[Voice]:
        """Get voice by name"""
        return self.voices.get(name)

    def get_default_voice(self, gender: Optional[Gender] = None) -> Optional[Voice]:
        """Get default voice for this locale"""
        voices = self.get_voices(gender)
        return voices[0] if voices else None


@dataclass
class Language:
    """
    A language (e.g., English, German, Persian).
    Contains locales/accents.
    """
    code: str  # ISO 639-1 code (e.g., "en", "de", "fa")
    name: str  # Display name (e.g., "English", "German", "Persian")
    native_name: str  # Native name (e.g., "English", "Deutsch", "فارسی")
    locales: Dict[str, Locale] = field(default_factory=dict)  # locale_code -> Locale
    default_locale: Optional[str] = None

    def get_locale(self, code: str) -> Optional[Locale]:
        """Get locale by code"""
        return self.locales.get(code)

    def get_default_locale(self) -> Optional[Locale]:
        """Get default locale for this language"""
        if self.default_locale and self.default_locale in self.locales:
            return self.locales[self.default_locale]
        # Return first available
        return next(iter(self.locales.values()), None) if self.locales else None

    @property
    def total_voices(self) -> int:
        """Count total voices across all locales"""
        return sum(len(loc.voices) for loc in self.locales.values())


# Language metadata with native names
LANGUAGE_METADATA = {
    "ar": {"name": "Arabic", "native": "العربية"},
    "bg": {"name": "Bulgarian", "native": "Български"},
    "ca": {"name": "Catalan", "native": "Català"},
    "cs": {"name": "Czech", "native": "Čeština"},
    "cy": {"name": "Welsh", "native": "Cymraeg"},
    "da": {"name": "Danish", "native": "Dansk"},
    "de": {"name": "German", "native": "Deutsch"},
    "el": {"name": "Greek", "native": "Ελληνικά"},
    "en": {"name": "English", "native": "English"},
    "es": {"name": "Spanish", "native": "Español"},
    "fa": {"name": "Persian", "native": "فارسی"},
    "fi": {"name": "Finnish", "native": "Suomi"},
    "fr": {"name": "French", "native": "Français"},
    "he": {"name": "Hebrew", "native": "עברית"},
    "hi": {"name": "Hindi", "native": "हिन्दी"},
    "hu": {"name": "Hungarian", "native": "Magyar"},
    "id": {"name": "Indonesian", "native": "Bahasa Indonesia"},
    "is": {"name": "Icelandic", "native": "Íslenska"},
    "it": {"name": "Italian", "native": "Italiano"},
    "ka": {"name": "Georgian", "native": "ქართული"},
    "kk": {"name": "Kazakh", "native": "Қазақша"},
    "lb": {"name": "Luxembourgish", "native": "Lëtzebuergesch"},
    "lv": {"name": "Latvian", "native": "Latviešu"},
    "ml": {"name": "Malayalam", "native": "മലയാളം"},
    "ne": {"name": "Nepali", "native": "नेपाली"},
    "nl": {"name": "Dutch", "native": "Nederlands"},
    "no": {"name": "Norwegian", "native": "Norsk"},
    "pl": {"name": "Polish", "native": "Polski"},
    "pt": {"name": "Portuguese", "native": "Português"},
    "ro": {"name": "Romanian", "native": "Română"},
    "ru": {"name": "Russian", "native": "Русский"},
    "sk": {"name": "Slovak", "native": "Slovenčina"},
    "sl": {"name": "Slovenian", "native": "Slovenščina"},
    "sr": {"name": "Serbian", "native": "Српски"},
    "sv": {"name": "Swedish", "native": "Svenska"},
    "sw": {"name": "Swahili", "native": "Kiswahili"},
    "te": {"name": "Telugu", "native": "తెలుగు"},
    "tr": {"name": "Turkish", "native": "Türkçe"},
    "uk": {"name": "Ukrainian", "native": "Українська"},
    "vi": {"name": "Vietnamese", "native": "Tiếng Việt"},
    "zh": {"name": "Chinese", "native": "中文"},
}

# Locale/Region metadata
LOCALE_METADATA = {
    "AR": {"name": "Argentina"},
    "BE": {"name": "Belgium"},
    "BG": {"name": "Bulgaria"},
    "BR": {"name": "Brazil"},
    "CD": {"name": "Congo"},
    "CN": {"name": "China"},
    "CZ": {"name": "Czech Republic"},
    "DE": {"name": "Germany"},
    "DK": {"name": "Denmark"},
    "ES": {"name": "Spain"},
    "FI": {"name": "Finland"},
    "FR": {"name": "France"},
    "GB": {"name": "United Kingdom"},
    "GE": {"name": "Georgia"},
    "GR": {"name": "Greece"},
    "HU": {"name": "Hungary"},
    "ID": {"name": "Indonesia"},
    "IL": {"name": "Israel"},
    "IN": {"name": "India"},
    "IR": {"name": "Iran"},
    "IS": {"name": "Iceland"},
    "IT": {"name": "Italy"},
    "JO": {"name": "Jordan"},
    "KE": {"name": "Kenya"},
    "KZ": {"name": "Kazakhstan"},
    "LU": {"name": "Luxembourg"},
    "LV": {"name": "Latvia"},
    "MX": {"name": "Mexico"},
    "NL": {"name": "Netherlands"},
    "NO": {"name": "Norway"},
    "NP": {"name": "Nepal"},
    "PL": {"name": "Poland"},
    "PT": {"name": "Portugal"},
    "RO": {"name": "Romania"},
    "RS": {"name": "Serbia"},
    "RU": {"name": "Russia"},
    "SE": {"name": "Sweden"},
    "SI": {"name": "Slovenia"},
    "SK": {"name": "Slovakia"},
    "TR": {"name": "Turkey"},
    "UA": {"name": "Ukraine"},
    "US": {"name": "United States"},
    "VN": {"name": "Vietnam"},
}


class VoiceCatalog:
    """
    Central catalog managing all voices with hierarchical structure:
    Language → Locale → Gender → Voice → Quality
    """

    def __init__(self):
        self.languages: Dict[str, Language] = {}
        self._voice_key_map: Dict[str, tuple] = {}  # full_key -> (lang, locale, voice, quality)

    def load_from_index(self, index_path: str) -> bool:
        """
        Load voice catalog from voice_index.json generated by setup.sh.
        
        Expected format:
        {
            "languages": {
                "en": {
                    "locales": {
                        "US": {
                            "voices": {
                                "lessac": {
                                    "qualities": {
                                        "high": {"model": "...", "config": "...", ...},
                                        "medium": {...}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        """
        try:
            with open(index_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Clear existing
            self.languages.clear()
            self._voice_key_map.clear()

            languages_data = data.get("languages", {})

            for lang_code, lang_data in languages_data.items():
                # Get language metadata
                lang_meta = LANGUAGE_METADATA.get(lang_code, {})
                language = Language(
                    code=lang_code,
                    name=lang_meta.get("name", lang_code.upper()),
                    native_name=lang_meta.get("native", lang_code.upper()),
                )

                locales_data = lang_data.get("locales", {})
                first_locale = None

                for locale_code, locale_data in locales_data.items():
                    if first_locale is None:
                        first_locale = locale_code

                    # Get locale metadata
                    locale_meta = LOCALE_METADATA.get(locale_code, {})
                    locale = Locale(
                        code=locale_code,
                        name=locale_meta.get("name", locale_code),
                    )

                    voices_data = locale_data.get("voices", {})

                    for voice_name, voice_data in voices_data.items():
                        # Determine gender from voice data or name heuristics
                        gender_str = voice_data.get("gender", "neutral").lower()
                        gender = Gender(gender_str) if gender_str in [g.value for g in Gender] else Gender.NEUTRAL

                        voice = Voice(
                            name=voice_name,
                            display_name=voice_data.get("display_name", voice_name.replace("_", " ").title()),
                            gender=gender,
                            description=voice_data.get("description", ""),
                        )

                        qualities_data = voice_data.get("qualities", {})

                        for quality_str, variant_data in qualities_data.items():
                            try:
                                quality = Quality(quality_str)
                            except ValueError:
                                logger.warning(f"Unknown quality: {quality_str}")
                                continue

                            variant = VoiceVariant(
                                quality=quality,
                                model_file=variant_data.get("model", ""),
                                config_file=variant_data.get("config", ""),
                                sample_rate=variant_data.get("sample_rate", 22050),
                                num_speakers=variant_data.get("num_speakers", 1),
                                speaker_id_map=variant_data.get("speaker_id_map", {}),
                            )

                            voice.variants[quality] = variant

                            # Build reverse lookup
                            full_key = f"{lang_code}_{locale_code}-{voice_name}-{quality_str}"
                            self._voice_key_map[full_key] = (lang_code, locale_code, voice_name, quality)

                        if voice.variants:
                            locale.voices[voice_name] = voice

                    if locale.voices:
                        language.locales[locale_code] = locale

                if language.locales:
                    language.default_locale = first_locale
                    self.languages[lang_code] = language

            logger.info(f"Loaded {len(self.languages)} languages, {self.total_voices} voices")
            return True

        except Exception as e:
            logger.error(f"Failed to load voice index: {e}")
            return False

    @property
    def total_voices(self) -> int:
        """Get total number of unique voices"""
        return sum(lang.total_voices for lang in self.languages.values())

    @property
    def total_locales(self) -> int:
        """Get total number of locales"""
        return sum(len(lang.locales) for lang in self.languages.values())

    def get_language(self, code: str) -> Optional[Language]:
        """Get language by code"""
        return self.languages.get(code)

    def get_locale(self, lang_code: str, locale_code: str) -> Optional[Locale]:
        """Get locale by language and locale codes"""
        lang = self.get_language(lang_code)
        return lang.get_locale(locale_code) if lang else None

    def get_voice(self, lang_code: str, locale_code: str, voice_name: str) -> Optional[Voice]:
        """Get voice by full path"""
        locale = self.get_locale(lang_code, locale_code)
        return locale.get_voice(voice_name) if locale else None

    def resolve_voice(
        self,
        language: str,
        locale: Optional[str] = None,
        gender: Optional[str] = None,
        voice: Optional[str] = None,
        quality: Optional[str] = None,
    ) -> Optional[tuple]:
        """
        Resolve voice parameters to actual voice variant.
        
        Returns: (Language, Locale, Voice, VoiceVariant) or None
        """
        # Get language
        lang = self.get_language(language)
        if not lang:
            return None

        # Get locale (or default)
        if locale:
            loc = lang.get_locale(locale)
        else:
            loc = lang.get_default_locale()
        if not loc:
            return None

        # Parse gender
        gender_enum = None
        if gender:
            try:
                gender_enum = Gender(gender.lower())
            except ValueError:
                pass

        # Get voice (or default for gender)
        if voice:
            v = loc.get_voice(voice)
        else:
            v = loc.get_default_voice(gender_enum)
        if not v:
            return None

        # Get quality variant
        quality_enum = None
        if quality:
            try:
                quality_enum = Quality(quality.lower())
            except ValueError:
                pass

        variant = v.get_variant(quality_enum)
        if not variant:
            return None

        return (lang, loc, v, variant)

    def find_by_voice_key(self, voice_key: str) -> Optional[tuple]:
        """
        Find voice by full key (e.g., en_US-lessac-high).
        
        Returns: (Language, Locale, Voice, VoiceVariant) or None
        """
        if voice_key in self._voice_key_map:
            lang_code, locale_code, voice_name, quality = self._voice_key_map[voice_key]
            return self.resolve_voice(lang_code, locale_code, None, voice_name, quality.value)
        return None

    def list_languages(self) -> List[Dict[str, Any]]:
        """Get list of all languages with summary info"""
        result = []
        for lang in sorted(self.languages.values(), key=lambda x: x.name):
            result.append({
                "code": lang.code,
                "name": lang.name,
                "native_name": lang.native_name,
                "locales": list(lang.locales.keys()),
                "default_locale": lang.default_locale,
                "total_voices": lang.total_voices,
            })
        return result

    def list_locales(self, language: str) -> List[Dict[str, Any]]:
        """Get list of locales for a language"""
        lang = self.get_language(language)
        if not lang:
            return []

        result = []
        for loc in lang.locales.values():
            voices_by_gender = loc.voices_by_gender
            result.append({
                "code": loc.code,
                "name": loc.name,
                "full_code": f"{language}-{loc.code}",
                "voice_count": len(loc.voices),
                "genders": {
                    g.value: len(voices)
                    for g, voices in voices_by_gender.items()
                },
            })
        return result

    def list_voices(
        self,
        language: str,
        locale: str,
        gender: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get list of voices for a locale, optionally filtered by gender"""
        loc = self.get_locale(language, locale)
        if not loc:
            return []

        gender_enum = None
        if gender:
            try:
                gender_enum = Gender(gender.lower())
            except ValueError:
                pass

        result = []
        for v in loc.get_voices(gender_enum):
            result.append({
                "name": v.name,
                "display_name": v.display_name,
                "gender": v.gender.value,
                "description": v.description,
                "qualities": [q.value for q in v.available_qualities],
                "best_quality": v.best_quality.value if v.best_quality else None,
            })
        return result

    def get_full_catalog(self) -> Dict[str, Any]:
        """Get complete voice catalog"""
        result = {}
        for lang_code, lang in self.languages.items():
            lang_data = {
                "name": lang.name,
                "native_name": lang.native_name,
                "default_locale": lang.default_locale,
                "locales": {},
            }
            for locale_code, locale in lang.locales.items():
                locale_data = {
                    "name": locale.name,
                    "voices": {},
                }
                for voice_name, voice in locale.voices.items():
                    locale_data["voices"][voice_name] = {
                        "display_name": voice.display_name,
                        "gender": voice.gender.value,
                        "qualities": [q.value for q in voice.available_qualities],
                    }
                lang_data["locales"][locale_code] = locale_data
            result[lang_code] = lang_data
        return result


class Settings:
    """Application settings loaded from environment variables"""

    def __init__(self):
        # Server Configuration
        self.server_name = os.getenv("SERVER_NAME", "piper")
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "8000"))
        self.tailscale_ip = os.getenv("TAILSCALE_IP", "")
        
        # Security - Allowed backend IP
        self.backend_ip = os.getenv("BACKEND_IP", "")
        
        # Models Directory
        self.models_dir = Path(os.getenv("MODELS_DIR", "/app/models"))
        self.voice_index_path = self.models_dir / "voice_index.json"

        # TTS defaults
        self.default_language = os.getenv("DEFAULT_LANGUAGE", "en")
        self.default_locale = os.getenv("DEFAULT_REGION", "US")
        self.default_voice = os.getenv("DEFAULT_VOICE", "lessac")
        self.default_quality = os.getenv("DEFAULT_QUALITY", "high")
        self.default_speed = float(os.getenv("DEFAULT_SPEED", "1.0"))

        # Audio Configuration
        self.default_sample_rate = int(os.getenv("DEFAULT_SAMPLE_RATE", "22050"))
        self.output_format = os.getenv("OUTPUT_FORMAT", "mp3")
        self.mp3_bitrate = os.getenv("MP3_BITRATE", "128k")
        
        # Limits
        self.max_text_length = int(os.getenv("MAX_TEXT_LENGTH", "5000"))
        self.min_speed = 0.5
        self.max_speed = 2.0
        
        # Performance Settings
        self.max_concurrent_requests = int(os.getenv("MAX_CONCURRENT_REQUESTS", "10"))
        self.request_timeout = int(os.getenv("REQUEST_TIMEOUT", "30"))
        self.worker_threads = int(os.getenv("WORKER_THREADS", "4"))
        
        # Temporary Directory
        self.temp_dir = Path(os.getenv("TEMP_DIR", "/tmp/piper"))
        
        # Rate Limiting
        self.rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
        self.rate_limit_per_minute = int(os.getenv("RATE_LIMIT_PER_MINUTE", "100"))
        
        # Monitoring Configuration
        self.monitoring_enabled = os.getenv("MONITORING_ENABLED", "false").lower() == "true"
        self.log_server_ip = os.getenv("LOG_SERVER_IP", "")
        self.loki_url = os.getenv("LOKI_URL", "")
        self.prometheus_url = os.getenv("PROMETHEUS_URL", "")
        
        # Logging
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.log_format = os.getenv("LOG_FORMAT", "json")

        # Voice catalog
        self.catalog = VoiceCatalog()
        
    def ensure_temp_dir(self) -> None:
        """Create temp directory if it doesn't exist"""
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def load_voices(self) -> bool:
        """Load voice catalog from index file"""
        if not self.voice_index_path.exists():
            logger.error(f"Voice index not found: {self.voice_index_path}")
            return False
        return self.catalog.load_from_index(str(self.voice_index_path))
    
    def is_allowed_ip(self, client_ip: str) -> bool:
        """Check if client IP is allowed to connect"""
        # If no backend IP configured, allow all (for development)
        if not self.backend_ip:
            return True
        
        # Allow localhost for health checks
        if client_ip in ("127.0.0.1", "::1", "localhost"):
            return True
            
        # Allow configured backend IP
        return client_ip == self.backend_ip


# Global settings instance
settings = Settings()