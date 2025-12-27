# tts_service.py
# /root/piper/app/tts_service.py
# TTS service with hierarchical voice selection: Language → Locale → Gender → Voice

import logging
import subprocess
import tempfile
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List, BinaryIO
from io import BytesIO
from dataclasses import dataclass

from config import settings, Gender, Quality, QUALITY_PRIORITY

logger = logging.getLogger(__name__)


# =============================================================================
# Custom Exceptions with Helpful Messages
# =============================================================================

@dataclass
class ErrorContext:
    """Context information for error messages"""
    requested: str
    available: List[str]
    hint: str = ""


class TTSError(Exception):
    """Base TTS error"""
    def __init__(self, message: str, context: Optional[ErrorContext] = None):
        self.message = message
        self.context = context
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        result = {"error": self.message}
        if self.context:
            result["requested"] = self.context.requested
            result["available"] = self.context.available
            if self.context.hint:
                result["hint"] = self.context.hint
        return result


class LanguageNotFoundError(TTSError):
    """Requested language not found"""
    pass


class LocaleNotFoundError(TTSError):
    """Requested locale not found for language"""
    pass


class GenderNotFoundError(TTSError):
    """No voices found for requested gender"""
    pass


class VoiceNotFoundError(TTSError):
    """Requested voice not found"""
    pass


class QualityNotFoundError(TTSError):
    """Requested quality not available for voice"""
    pass


class TextValidationError(TTSError):
    """Text validation failed"""
    pass


class SynthesisError(TTSError):
    """Speech synthesis failed"""
    pass


# =============================================================================
# TTS Service
# =============================================================================

class TTSService:
    """
    Text-to-Speech service with hierarchical voice selection.
    
    Hierarchy: Language → Locale → Gender → Voice → Quality
    
    Selection logic:
    1. Language (required) - must exist
    2. Locale (optional) - defaults to language's default locale
    3. Gender (optional) - filters available voices
    4. Voice (optional) - defaults to first matching voice
    5. Quality (optional) - defaults to best available
    """

    def __init__(self):
        self.models_dir = settings.models_dir
        self.catalog = settings.catalog
        self.temp_dir = settings.temp_dir
        self.mp3_bitrate = settings.mp3_bitrate
        self.default_sample_rate = settings.default_sample_rate

    async def generate_speech(
        self,
        text: str,
        language: str,
        locale: Optional[str] = None,
        gender: Optional[str] = None,
        voice: Optional[str] = None,
        quality: Optional[str] = None,
        speed: float = 1.0,
        speaker_id: int = 0,
    ) -> BinaryIO:
        """
        Generate speech audio from text.
        
        Args:
            text: Text to synthesize (required)
            language: Language code, e.g., "en", "de", "fa" (required)
            locale: Locale/region code, e.g., "US", "GB", "IR" (optional)
            gender: Voice gender filter: "male", "female", "neutral" (optional)
            voice: Specific voice name, e.g., "lessac", "ryan" (optional)
            quality: Quality level: "high", "medium", "low", "x_low" (optional)
            speed: Speech rate 0.5-2.0 (default: 1.0)
            speaker_id: Speaker ID for multi-speaker models (default: 0)
            
        Returns:
            BytesIO containing MP3 audio data
            
        Raises:
            LanguageNotFoundError: Language not supported
            LocaleNotFoundError: Locale not found for language
            GenderNotFoundError: No voices for requested gender
            VoiceNotFoundError: Voice not found
            QualityNotFoundError: Quality not available
            TextValidationError: Text validation failed
            SynthesisError: Synthesis failed
        """
        # Validate text
        self._validate_text(text)

        # Validate speed
        speed = max(settings.min_speed, min(settings.max_speed, speed))

        # Resolve voice through hierarchy
        resolved = self._resolve_voice_hierarchy(
            language=language,
            locale=locale,
            gender=gender,
            voice=voice,
            quality=quality,
        )

        lang, loc, v, variant = resolved

        logger.info(
            f"Generating speech: lang={lang.code}, locale={loc.code}, "
            f"voice={v.name}, quality={variant.quality.value}, "
            f"speed={speed}, text_len={len(text)}"
        )

        # Generate audio
        audio_data = await self._synthesize(
            text=text,
            model_path=str(self.models_dir / variant.model_file),
            sample_rate=variant.sample_rate,
            speed=speed,
            speaker_id=speaker_id,
            num_speakers=variant.num_speakers,
        )

        return audio_data

    def _validate_text(self, text: str) -> None:
        """Validate input text"""
        if not text or not text.strip():
            raise TextValidationError(
                "Text is required and cannot be empty",
                ErrorContext(
                    requested="(empty)",
                    available=[],
                    hint="Provide non-empty text to synthesize",
                )
            )

        if len(text) > settings.max_text_length:
            raise TextValidationError(
                f"Text exceeds maximum length of {settings.max_text_length} characters",
                ErrorContext(
                    requested=f"{len(text)} characters",
                    available=[f"max {settings.max_text_length}"],
                    hint="Split long text into smaller chunks",
                )
            )

    def _resolve_voice_hierarchy(
        self,
        language: str,
        locale: Optional[str],
        gender: Optional[str],
        voice: Optional[str],
        quality: Optional[str],
    ) -> tuple:
        """
        Resolve voice through hierarchy with detailed errors.
        
        Returns: (Language, Locale, Voice, VoiceVariant)
        """
        # Step 1: Get Language
        lang = self.catalog.get_language(language)
        if not lang:
            available_langs = list(self.catalog.languages.keys())
            raise LanguageNotFoundError(
                f"Language '{language}' not found",
                ErrorContext(
                    requested=language,
                    available=sorted(available_langs),
                    hint=f"Use one of: {', '.join(sorted(available_langs)[:10])}{'...' if len(available_langs) > 10 else ''}",
                )
            )

        # Step 2: Get Locale
        if locale:
            loc = lang.get_locale(locale)
            if not loc:
                available_locales = list(lang.locales.keys())
                raise LocaleNotFoundError(
                    f"Locale '{locale}' not found for language '{language}'",
                    ErrorContext(
                        requested=locale,
                        available=available_locales,
                        hint=f"For {lang.name}, use one of: {', '.join(available_locales)}",
                    )
                )
        else:
            loc = lang.get_default_locale()
            if not loc:
                raise LocaleNotFoundError(
                    f"No locales available for language '{language}'",
                    ErrorContext(
                        requested="(default)",
                        available=[],
                        hint=f"Language {lang.name} has no voice models installed",
                    )
                )

        # Step 3: Filter by Gender (if specified)
        gender_enum = None
        if gender:
            try:
                gender_enum = Gender(gender.lower())
            except ValueError:
                raise GenderNotFoundError(
                    f"Invalid gender '{gender}'",
                    ErrorContext(
                        requested=gender,
                        available=[g.value for g in Gender],
                        hint="Use 'male', 'female', or 'neutral'",
                    )
                )

            # Check if any voices match gender
            gender_voices = loc.get_voices(gender_enum)
            if not gender_voices:
                available_genders = list(loc.voices_by_gender.keys())
                raise GenderNotFoundError(
                    f"No {gender} voices available for {language}-{loc.code}",
                    ErrorContext(
                        requested=gender,
                        available=[g.value for g in available_genders],
                        hint=f"Available genders for {lang.name} ({loc.name}): {', '.join(g.value for g in available_genders)}",
                    )
                )

        # Step 4: Get Voice
        if voice:
            v = loc.get_voice(voice)
            if not v:
                available_voices = [vv.name for vv in loc.get_voices(gender_enum)]
                raise VoiceNotFoundError(
                    f"Voice '{voice}' not found for {language}-{loc.code}",
                    ErrorContext(
                        requested=voice,
                        available=available_voices,
                        hint=f"Available voices: {', '.join(available_voices)}",
                    )
                )
            # Check gender compatibility if both specified
            if gender_enum and v.gender != gender_enum:
                raise VoiceNotFoundError(
                    f"Voice '{voice}' is {v.gender.value}, not {gender}",
                    ErrorContext(
                        requested=f"{voice} ({gender})",
                        available=[vv.name for vv in loc.get_voices(gender_enum)],
                        hint=f"Either change gender filter or choose a {gender} voice",
                    )
                )
        else:
            v = loc.get_default_voice(gender_enum)
            if not v:
                raise VoiceNotFoundError(
                    f"No voices available for {language}-{loc.code}",
                    ErrorContext(
                        requested="(default)",
                        available=[],
                        hint=f"No voice models installed for {lang.name} ({loc.name})",
                    )
                )

        # Step 5: Get Quality Variant
        if quality:
            try:
                quality_enum = Quality(quality.lower())
            except ValueError:
                raise QualityNotFoundError(
                    f"Invalid quality '{quality}'",
                    ErrorContext(
                        requested=quality,
                        available=[q.value for q in Quality],
                        hint="Use 'high', 'medium', 'low', or 'x_low'",
                    )
                )

            variant = v.get_variant(quality_enum)
            if not variant:
                available_qualities = [q.value for q in v.available_qualities]
                raise QualityNotFoundError(
                    f"Quality '{quality}' not available for voice '{v.name}'",
                    ErrorContext(
                        requested=quality,
                        available=available_qualities,
                        hint=f"Voice '{v.name}' available in: {', '.join(available_qualities)}",
                    )
                )
        else:
            variant = v.get_variant()  # Best available
            if not variant:
                raise QualityNotFoundError(
                    f"No quality variants available for voice '{v.name}'",
                    ErrorContext(
                        requested="(best)",
                        available=[],
                        hint=f"Voice '{v.name}' has no model files",
                    )
                )

        return (lang, loc, v, variant)

    async def _synthesize(
        self,
        text: str,
        model_path: str,
        sample_rate: int,
        speed: float,
        speaker_id: int,
        num_speakers: int,
    ) -> BinaryIO:
        """
        Run Piper TTS synthesis and return MP3 audio.
        
        Piper automatically finds the .onnx.json config file next to the model.
        Uses: echo "text" | piper --model X --output_file Y
        """
        try:
            # Ensure temp directory exists
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            
            # Create temp files for audio pipeline
            wav_path = self.temp_dir / f"tts_{id(text)}_{hash(text) % 10000}.wav"
            mp3_path = self.temp_dir / f"tts_{id(text)}_{hash(text) % 10000}.mp3"

            try:
                # Build piper command
                # Note: Piper automatically loads .onnx.json config from same directory
                piper_cmd = [
                    "piper",
                    "--model", model_path,
                    "--output_file", str(wav_path),
                    "--length_scale", str(1.0 / speed),  # Piper uses length_scale (inverse of speed)
                ]

                # Add speaker ID for multi-speaker models
                if num_speakers > 1 and speaker_id > 0:
                    piper_cmd.extend(["--speaker", str(speaker_id)])

                logger.debug(f"Running piper command: {' '.join(piper_cmd)}")

                # Run piper with text as stdin
                process = await asyncio.create_subprocess_exec(
                    *piper_cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await process.communicate(input=text.encode("utf-8"))

                if process.returncode != 0:
                    error_msg = stderr.decode("utf-8", errors="replace")
                    logger.error(f"Piper error: {error_msg}")
                    raise SynthesisError(
                        f"Speech synthesis failed: {error_msg[:200]}",
                        ErrorContext(
                            requested=f"model={Path(model_path).name}",
                            available=[],
                            hint="Check if model file exists and is valid",
                        )
                    )

                # Check if WAV file was created
                if not wav_path.exists():
                    raise SynthesisError(
                        "Piper did not produce output audio",
                        ErrorContext(
                            requested=f"model={Path(model_path).name}",
                            available=[],
                            hint="Model may be corrupted or incompatible",
                        )
                    )

                # Convert WAV to MP3 with ffmpeg using configured bitrate
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-y",  # Overwrite output
                    "-i", str(wav_path),
                    "-codec:a", "libmp3lame",
                    "-b:a", self.mp3_bitrate,  # Use configured bitrate
                    "-ar", str(sample_rate),  # Use model's sample rate
                    "-ac", "1",  # Mono audio
                    "-loglevel", "error",
                    str(mp3_path),
                ]

                logger.debug(f"Running ffmpeg command: {' '.join(ffmpeg_cmd)}")

                process = await asyncio.create_subprocess_exec(
                    *ffmpeg_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    error_msg = stderr.decode("utf-8", errors="replace")
                    logger.error(f"FFmpeg error: {error_msg}")
                    raise SynthesisError(
                        "Audio encoding failed",
                        ErrorContext(
                            requested="MP3 encoding",
                            available=[],
                            hint=f"FFmpeg error: {error_msg[:100]}",
                        )
                    )

                # Read MP3 data into memory
                with open(mp3_path, "rb") as f:
                    audio_data = BytesIO(f.read())

                audio_data.seek(0)
                return audio_data

            finally:
                # Cleanup temp files
                if wav_path.exists():
                    wav_path.unlink(missing_ok=True)
                if mp3_path.exists():
                    mp3_path.unlink(missing_ok=True)

        except SynthesisError:
            raise
        except Exception as e:
            logger.exception("Synthesis error")
            raise SynthesisError(
                f"Unexpected synthesis error: {str(e)}",
                ErrorContext(
                    requested=text[:50] + "..." if len(text) > 50 else text,
                    available=[],
                    hint="Check server logs for details",
                )
            )

    # =========================================================================
    # Catalog Query Methods
    # =========================================================================

    def get_languages(self) -> List[Dict[str, Any]]:
        """Get all supported languages"""
        return self.catalog.list_languages()

    def get_locales(self, language: str) -> List[Dict[str, Any]]:
        """Get locales for a language"""
        lang = self.catalog.get_language(language)
        if not lang:
            raise LanguageNotFoundError(
                f"Language '{language}' not found",
                ErrorContext(
                    requested=language,
                    available=list(self.catalog.languages.keys()),
                )
            )
        return self.catalog.list_locales(language)

    def get_voices(
        self,
        language: str,
        locale: str,
        gender: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get voices for a locale"""
        # Validate language
        lang = self.catalog.get_language(language)
        if not lang:
            raise LanguageNotFoundError(
                f"Language '{language}' not found",
                ErrorContext(
                    requested=language,
                    available=list(self.catalog.languages.keys()),
                )
            )

        # Validate locale
        loc = lang.get_locale(locale)
        if not loc:
            raise LocaleNotFoundError(
                f"Locale '{locale}' not found for language '{language}'",
                ErrorContext(
                    requested=locale,
                    available=list(lang.locales.keys()),
                )
            )

        return self.catalog.list_voices(language, locale, gender)

    def get_voice_details(
        self,
        language: str,
        locale: str,
        voice_name: str,
    ) -> Dict[str, Any]:
        """Get detailed info about a specific voice"""
        voice = self.catalog.get_voice(language, locale, voice_name)
        if not voice:
            # Determine what's missing
            lang = self.catalog.get_language(language)
            if not lang:
                raise LanguageNotFoundError(
                    f"Language '{language}' not found",
                    ErrorContext(requested=language, available=list(self.catalog.languages.keys())),
                )
            loc = lang.get_locale(locale)
            if not loc:
                raise LocaleNotFoundError(
                    f"Locale '{locale}' not found",
                    ErrorContext(requested=locale, available=list(lang.locales.keys())),
                )
            raise VoiceNotFoundError(
                f"Voice '{voice_name}' not found",
                ErrorContext(requested=voice_name, available=[v.name for v in loc.voices.values()]),
            )

        return {
            "name": voice.name,
            "display_name": voice.display_name,
            "gender": voice.gender.value,
            "description": voice.description,
            "qualities": [
                {
                    "level": q.value,
                    "sample_rate": voice.variants[q].sample_rate,
                    "num_speakers": voice.variants[q].num_speakers,
                }
                for q in voice.available_qualities
            ],
            "best_quality": voice.best_quality.value if voice.best_quality else None,
        }

    def get_full_catalog(self) -> Dict[str, Any]:
        """Get complete voice catalog"""
        return self.catalog.get_full_catalog()

    def get_stats(self) -> Dict[str, Any]:
        """Get catalog statistics"""
        return {
            "languages": len(self.catalog.languages),
            "locales": self.catalog.total_locales,
            "voices": self.catalog.total_voices,
            "qualities": [q.value for q in Quality],
        }


# Global service instance
tts_service = TTSService()