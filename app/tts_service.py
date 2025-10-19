# File: app/tts_service.py - /root/piper/app/tts_service.py
# Core TTS service implementation using Piper with structured logging

import asyncio
import io
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, Optional, Any, BinaryIO
from concurrent.futures import ThreadPoolExecutor

from pydub import AudioSegment
import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

class PiperTTSService:
    """
    Piper TTS Service Handler
    Manages voice models and generates speech from text with comprehensive logging
    """
    
    def __init__(self):
        """Initialize TTS service with configuration"""
        self.models_dir = Path("/app/models")
        self.temp_dir = Path(settings.TEMP_DIR)
        self.loaded_models = {}
        self.model_configs = {}
        self.executor = ThreadPoolExecutor(max_workers=settings.WORKER_THREADS)
        self._ready = False
        
        # Language to model name mapping from settings
        self.language_models = {
            'en': settings.MODEL_EN,
            'de': settings.MODEL_DE,
            'fr': settings.MODEL_FR,
            'es': settings.MODEL_ES,
            'it': settings.MODEL_IT,
            'fa': settings.MODEL_FA
        }
        
        logger.info("TTS service instance created", extra={
            'event': 'service_init',
            'models_dir': str(self.models_dir),
            'temp_dir': str(self.temp_dir),
            'worker_threads': settings.WORKER_THREADS
        })
        
    async def initialize(self):
        """
        Initialize the TTS service
        Creates directories and prepares all language models
        """
        try:
            logger.info("Starting TTS service initialization", extra={
                'event': 'initialization_start',
                'languages': list(self.language_models.keys())
            })
            
            # Create required directories
            self.models_dir.mkdir(parents=True, exist_ok=True)
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            
            logger.debug("Directories created", extra={
                'event': 'directories_created',
                'models_dir': str(self.models_dir),
                'temp_dir': str(self.temp_dir)
            })
            
            # Prepare all language models
            initialization_start = time.time()
            for lang, model_name in self.language_models.items():
                await self._prepare_model(lang, model_name)
            
            initialization_duration = time.time() - initialization_start
            
            self._ready = True
            logger.info("TTS service initialization completed", extra={
                'event': 'initialization_complete',
                'models_loaded': len(self.loaded_models),
                'languages': list(self.loaded_models.keys()),
                'duration': round(initialization_duration, 2)
            })
            
        except Exception as e:
            logger.error("Failed to initialize TTS service", extra={
                'event': 'initialization_failed',
                'error': str(e),
                'error_type': type(e).__name__
            }, exc_info=True)
            raise
    
    async def _prepare_model(self, language: str, model_name: str):
        """
        Prepare a voice model for a specific language
        Downloads model if not present and loads configuration
        
        Args:
            language: Language code (en, de, fr, es, it, fa)
            model_name: Name of the Piper voice model
        """
        try:
            logger.debug("Preparing model", extra={
                'event': 'model_preparation_start',
                'language': language,
                'model_name': model_name
            })
            
            model_dir = self.models_dir / language
            model_dir.mkdir(parents=True, exist_ok=True)
            
            model_file = model_dir / f"{model_name}.onnx"
            config_file = model_dir / f"{model_name}.onnx.json"
            
            # Download model if not present
            if not model_file.exists() or not config_file.exists():
                logger.info("Model files not found, downloading", extra={
                    'event': 'model_download_start',
                    'language': language,
                    'model_name': model_name
                })
                await self._download_model(model_name, model_dir)
            else:
                logger.debug("Model files already exist", extra={
                    'event': 'model_files_exist',
                    'language': language,
                    'model_file': str(model_file),
                    'config_file': str(config_file)
                })
            
            # Load model configuration
            if config_file.exists():
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    self.model_configs[language] = {
                        'model_path': str(model_file),
                        'config_path': str(config_file),
                        'model_name': model_name,
                        'config': config
                    }
                    self.loaded_models[language] = model_name
                    
                    logger.info("Model loaded successfully", extra={
                        'event': 'model_loaded',
                        'language': language,
                        'model_name': model_name,
                        'sample_rate': config.get('audio', {}).get('sample_rate', 'unknown')
                    })
            else:
                logger.warning("Config file not found after download", extra={
                    'event': 'config_file_missing',
                    'language': language,
                    'config_file': str(config_file)
                })
            
        except Exception as e:
            logger.error("Failed to prepare model", extra={
                'event': 'model_preparation_failed',
                'language': language,
                'model_name': model_name,
                'error': str(e),
                'error_type': type(e).__name__
            }, exc_info=True)
    
    async def _download_model(self, model_name: str, output_dir: Path):
        """
        Download a Piper voice model using piper CLI
        
        Args:
            model_name: Name of the model to download
            output_dir: Directory to save the model files
        """
        logger.info("Starting model download", extra={
            'event': 'model_download_start',
            'model_name': model_name,
            'output_dir': str(output_dir)
        })
        
        loop = asyncio.get_event_loop()
        download_start = time.time()
        
        def download():
            try:
                cmd = [
                    "piper", "--download-model", model_name,
                    "--download-dir", str(output_dir)
                ]
                
                logger.debug("Executing download command", extra={
                    'event': 'download_command_exec',
                    'command': ' '.join(cmd)
                })
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                if result.returncode != 0:
                    raise Exception(f"Model download failed: {result.stderr}")
                
                download_duration = time.time() - download_start
                logger.info("Model download completed", extra={
                    'event': 'model_download_complete',
                    'model_name': model_name,
                    'duration': round(download_duration, 2)
                })
                    
            except subprocess.TimeoutExpired:
                logger.error("Model download timeout", extra={
                    'event': 'model_download_timeout',
                    'model_name': model_name,
                    'timeout': 300
                })
                raise Exception(f"Model download timeout for {model_name}")
            except Exception as e:
                logger.error("Model download error", extra={
                    'event': 'model_download_error',
                    'model_name': model_name,
                    'error': str(e),
                    'error_type': type(e).__name__
                }, exc_info=True)
                raise Exception(f"Failed to download model {model_name}: {e}")
        
        await loop.run_in_executor(self.executor, download)
    
    def is_ready(self) -> bool:
        """
        Check if service is ready to process requests
        
        Returns:
            True if service is initialized and models are loaded
        """
        return self._ready and len(self.loaded_models) > 0
    
    def get_available_languages(self) -> list:
        """
        Get list of available language codes
        
        Returns:
            List of language codes with loaded models
        """
        return list(self.loaded_models.keys())
    
    def get_model_name(self, language: str) -> str:
        """
        Get the model name for a specific language
        
        Args:
            language: Language code
            
        Returns:
            Model name or "unknown" if not found
        """
        return self.loaded_models.get(language, "unknown")
    
    async def get_voices(self) -> Dict[str, list]:
        """
        Get information about all available voices
        
        Returns:
            Dictionary mapping language codes to list of voice information
        """
        voices = {}
        
        for lang, model_name in self.loaded_models.items():
            config = self.model_configs.get(lang, {}).get('config', {})
            
            voice_info = {
                'voice_id': model_name,
                'language': lang,
                'name': model_name.split('-')[1] if '-' in model_name else model_name,
                'quality': self._extract_quality(model_name),
                'sample_rate': config.get('audio', {}).get('sample_rate', 22050)
            }
            
            voices[lang] = [voice_info]
        
        logger.debug("Voices list generated", extra={
            'event': 'voices_list_generated',
            'languages': list(voices.keys()),
            'total_voices': sum(len(v) for v in voices.values())
        })
        
        return voices
    
    def _extract_quality(self, model_name: str) -> str:
        """
        Extract quality level from model name
        
        Args:
            model_name: Name of the model
            
        Returns:
            Quality level string
        """
        if 'high' in model_name:
            return 'high'
        elif 'medium' in model_name:
            return 'medium'
        elif 'low' in model_name:
            return 'low'
        elif 'x_low' in model_name or 'x-low' in model_name:
            return 'x-low'
        return 'standard'
    
    async def generate_speech(
        self,
        text: str,
        language: str,
        voice: Optional[str] = None,
        speed: float = 1.0
    ) -> BinaryIO:
        """
        Generate speech audio from text
        
        Args:
            text: Text to convert to speech
            language: Language code
            voice: Optional specific voice name (currently unused)
            speed: Speech speed multiplier (0.5 to 2.0)
            
        Returns:
            Binary IO object containing MP3 audio data
            
        Raises:
            ValueError: If language not supported or text is empty
            Exception: If generation fails
        """
        generation_start = time.time()
        
        logger.info("Starting speech generation", extra={
            'event': 'speech_generation_start',
            'language': language,
            'text_length': len(text),
            'speed': speed,
            'voice': voice
        })
        
        # Validate language
        if language not in self.loaded_models:
            logger.warning("Unsupported language requested", extra={
                'event': 'unsupported_language',
                'language': language,
                'available_languages': list(self.loaded_models.keys())
            })
            raise ValueError(f"Language {language} not supported")
        
        # Validate text
        if not text.strip():
            logger.warning("Empty text provided", extra={
                'event': 'empty_text'
            })
            raise ValueError("Text cannot be empty")
        
        # Get model configuration
        model_config = self.model_configs[language]
        model_path = model_config['model_path']
        config_path = model_config['config_path']
        
        try:
            # Generate speech using Piper
            piper_start = time.time()
            audio_data = await self._run_piper(
                text=text,
                model_path=model_path,
                config_path=config_path,
                speed=speed
            )
            piper_duration = time.time() - piper_start
            
            logger.debug("Piper generation completed", extra={
                'event': 'piper_generation_complete',
                'language': language,
                'duration': round(piper_duration, 3),
                'audio_size': len(audio_data)
            })
            
            # Convert to MP3 format
            mp3_start = time.time()
            mp3_data = await self._convert_to_mp3(audio_data)
            mp3_duration = time.time() - mp3_start
            
            total_duration = time.time() - generation_start
            
            logger.info("Speech generation completed", extra={
                'event': 'speech_generation_complete',
                'language': language,
                'text_length': len(text),
                'audio_size': len(mp3_data),
                'piper_duration': round(piper_duration, 3),
                'mp3_duration': round(mp3_duration, 3),
                'total_duration': round(total_duration, 3)
            })
            
            return io.BytesIO(mp3_data)
            
        except Exception as e:
            duration = time.time() - generation_start
            logger.error("Speech generation failed", extra={
                'event': 'speech_generation_failed',
                'language': language,
                'text_length': len(text),
                'error': str(e),
                'error_type': type(e).__name__,
                'duration': round(duration, 3)
            }, exc_info=True)
            raise
    
    async def _run_piper(
        self,
        text: str,
        model_path: str,
        config_path: str,
        speed: float
    ) -> bytes:
        """
        Run Piper TTS engine to generate speech
        
        Args:
            text: Text to synthesize
            model_path: Path to ONNX model file
            config_path: Path to model config file
            speed: Speech speed multiplier
            
        Returns:
            WAV audio data as bytes
            
        Raises:
            Exception: If Piper execution fails or times out
        """
        loop = asyncio.get_event_loop()
        
        def run_tts():
            text_file_path = None
            wav_file_path = None
            
            try:
                # Create temporary text file
                with tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix='.txt',
                    dir=str(self.temp_dir),
                    delete=False
                ) as text_file:
                    text_file.write(text)
                    text_file_path = text_file.name
                
                # Create temporary WAV file
                with tempfile.NamedTemporaryFile(
                    suffix='.wav',
                    dir=str(self.temp_dir),
                    delete=False
                ) as wav_file:
                    wav_file_path = wav_file.name
                
                # Build Piper command
                cmd = [
                    "piper",
                    "--model", model_path,
                    "--config", config_path,
                    "--output_file", wav_file_path
                ]
                
                # Add speed control if needed
                if speed != 1.0:
                    length_scale = 1.0 / speed
                    cmd.extend(["--length-scale", str(length_scale)])
                
                logger.debug("Executing Piper command", extra={
                    'event': 'piper_command_exec',
                    'model_path': model_path,
                    'speed': speed
                })
                
                # Run Piper with text input
                with open(text_file_path, 'r') as f:
                    result = subprocess.run(
                        cmd,
                        stdin=f,
                        capture_output=True,
                        timeout=settings.REQUEST_TIMEOUT
                    )
                
                if result.returncode != 0:
                    error_msg = result.stderr.decode()
                    logger.error("Piper execution failed", extra={
                        'event': 'piper_execution_failed',
                        'return_code': result.returncode,
                        'error': error_msg
                    })
                    raise Exception(f"Piper failed: {error_msg}")
                
                # Read generated WAV file
                with open(wav_file_path, 'rb') as f:
                    wav_data = f.read()
                
                logger.debug("WAV file read", extra={
                    'event': 'wav_file_read',
                    'size': len(wav_data)
                })
                
                return wav_data
                    
            except subprocess.TimeoutExpired:
                logger.error("Piper execution timeout", extra={
                    'event': 'piper_timeout',
                    'timeout': settings.REQUEST_TIMEOUT
                })
                raise Exception("TTS generation timeout")
            except Exception as e:
                logger.error("Piper execution error", extra={
                    'event': 'piper_execution_error',
                    'error': str(e),
                    'error_type': type(e).__name__
                }, exc_info=True)
                raise Exception(f"TTS generation failed: {e}")
            finally:
                # Clean up temporary files
                for path in [text_file_path, wav_file_path]:
                    if path:
                        try:
                            if os.path.exists(path):
                                os.unlink(path)
                        except Exception as e:
                            logger.warning("Failed to cleanup temp file", extra={
                                'event': 'temp_file_cleanup_failed',
                                'file': path,
                                'error': str(e)
                            })
        
        return await loop.run_in_executor(self.executor, run_tts)
    
    async def _convert_to_mp3(self, wav_data: bytes) -> bytes:
        """
        Convert WAV audio data to MP3 format
        
        Args:
            wav_data: WAV audio data as bytes
            
        Returns:
            MP3 audio data as bytes
            
        Raises:
            Exception: If conversion fails
        """
        loop = asyncio.get_event_loop()
        
        def convert():
            try:
                logger.debug("Starting MP3 conversion", extra={
                    'event': 'mp3_conversion_start',
                    'wav_size': len(wav_data),
                    'bitrate': settings.MP3_BITRATE
                })
                
                # Load WAV data
                audio = AudioSegment.from_wav(io.BytesIO(wav_data))
                
                # Export as MP3
                mp3_buffer = io.BytesIO()
                audio.export(
                    mp3_buffer,
                    format='mp3',
                    bitrate=settings.MP3_BITRATE,
                    parameters=["-q:a", "2"]
                )
                
                mp3_buffer.seek(0)
                mp3_data = mp3_buffer.read()
                
                logger.debug("MP3 conversion completed", extra={
                    'event': 'mp3_conversion_complete',
                    'mp3_size': len(mp3_data),
                    'compression_ratio': round(len(wav_data) / len(mp3_data), 2)
                })
                
                return mp3_data
                
            except Exception as e:
                logger.error("MP3 conversion error", extra={
                    'event': 'mp3_conversion_error',
                    'error': str(e),
                    'error_type': type(e).__name__
                }, exc_info=True)
                raise Exception(f"MP3 conversion failed: {e}")
        
        return await loop.run_in_executor(self.executor, convert)
    
    async def cleanup(self):
        """
        Clean up resources and temporary files
        Called during service shutdown
        """
        try:
            logger.info("Starting service cleanup", extra={
                'event': 'cleanup_start'
            })
            
            # Shutdown thread pool executor
            self.executor.shutdown(wait=True, cancel_futures=True)
            
            # Clear model caches
            models_count = len(self.loaded_models)
            self.loaded_models.clear()
            self.model_configs.clear()
            
            # Clean temporary directory
            if self.temp_dir.exists():
                temp_files = list(self.temp_dir.glob("*"))
                for file in temp_files:
                    try:
                        file.unlink()
                    except Exception as e:
                        logger.warning("Failed to delete temp file", extra={
                            'event': 'temp_file_delete_failed',
                            'file': str(file),
                            'error': str(e)
                        })
            
            logger.info("Service cleanup completed", extra={
                'event': 'cleanup_complete',
                'models_cleared': models_count,
                'temp_files_cleaned': len(temp_files) if 'temp_files' in locals() else 0
            })
            
        except Exception as e:
            logger.error("Cleanup error", extra={
                'event': 'cleanup_error',
                'error': str(e),
                'error_type': type(e).__name__
            }, exc_info=True)