# /root/piper/app/tts_service.py
import asyncio
import io
import json
import logging
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Dict, Optional, Any, BinaryIO
from concurrent.futures import ThreadPoolExecutor

from pydub import AudioSegment
import numpy as np

from config import settings

logger = logging.getLogger(__name__)

class PiperTTSService:
    def __init__(self):
        self.models_dir = Path("/app/models")
        self.temp_dir = Path(settings.TEMP_DIR)
        self.loaded_models = {}
        self.model_configs = {}
        self.executor = ThreadPoolExecutor(max_workers=settings.WORKER_THREADS)
        self._ready = False
        
        self.language_models = {
            'en': settings.MODEL_EN,
            'de': settings.MODEL_DE,
            'fr': settings.MODEL_FR,
            'es': settings.MODEL_ES,
            'it': settings.MODEL_IT,
            'fa': settings.MODEL_FA
        }
        
    async def initialize(self):
        try:
            self.models_dir.mkdir(parents=True, exist_ok=True)
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            
            for lang, model_name in self.language_models.items():
                await self._prepare_model(lang, model_name)
            
            self._ready = True
            logger.info(f"Loaded {len(self.loaded_models)} language models")
            
        except Exception as e:
            logger.error(f"Failed to initialize TTS service: {e}")
            raise
    
    async def _prepare_model(self, language: str, model_name: str):
        try:
            model_dir = self.models_dir / language
            model_dir.mkdir(parents=True, exist_ok=True)
            
            model_file = model_dir / f"{model_name}.onnx"
            config_file = model_dir / f"{model_name}.onnx.json"
            
            if not model_file.exists() or not config_file.exists():
                logger.info(f"Downloading model {model_name} for {language}")
                await self._download_model(model_name, model_dir)
            
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
                    logger.info(f"Model {model_name} ready for {language}")
            
        except Exception as e:
            logger.error(f"Failed to prepare model for {language}: {e}")
    
    async def _download_model(self, model_name: str, output_dir: Path):
        loop = asyncio.get_event_loop()
        
        def download():
            try:
                cmd = [
                    "piper", "--download-model", model_name,
                    "--download-dir", str(output_dir)
                ]
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                
                if result.returncode != 0:
                    raise Exception(f"Model download failed: {result.stderr}")
                    
            except subprocess.TimeoutExpired:
                raise Exception(f"Model download timeout for {model_name}")
            except Exception as e:
                raise Exception(f"Failed to download model {model_name}: {e}")
        
        await loop.run_in_executor(self.executor, download)
    
    def is_ready(self) -> bool:
        return self._ready and len(self.loaded_models) > 0
    
    def get_available_languages(self) -> list:
        return list(self.loaded_models.keys())
    
    def get_model_name(self, language: str) -> str:
        return self.loaded_models.get(language, "unknown")
    
    async def get_voices(self) -> Dict[str, list]:
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
        
        return voices
    
    def _extract_quality(self, model_name: str) -> str:
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
        
        if language not in self.loaded_models:
            raise ValueError(f"Language {language} not supported")
        
        if not text.strip():
            raise ValueError("Text cannot be empty")
        
        model_config = self.model_configs[language]
        model_path = model_config['model_path']
        config_path = model_config['config_path']
        
        audio_data = await self._run_piper(
            text=text,
            model_path=model_path,
            config_path=config_path,
            speed=speed
        )
        
        mp3_data = await self._convert_to_mp3(audio_data)
        
        return io.BytesIO(mp3_data)
    
    async def _run_piper(
        self,
        text: str,
        model_path: str,
        config_path: str,
        speed: float
    ) -> bytes:
        loop = asyncio.get_event_loop()
        
        def run_tts():
            try:
                with tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix='.txt',
                    dir=str(self.temp_dir),
                    delete=False
                ) as text_file:
                    text_file.write(text)
                    text_file_path = text_file.name
                
                with tempfile.NamedTemporaryFile(
                    suffix='.wav',
                    dir=str(self.temp_dir),
                    delete=False
                ) as wav_file:
                    wav_file_path = wav_file.name
                
                try:
                    cmd = [
                        "piper",
                        "--model", model_path,
                        "--config", config_path,
                        "--output_file", wav_file_path
                    ]
                    
                    if speed != 1.0:
                        length_scale = 1.0 / speed
                        cmd.extend(["--length-scale", str(length_scale)])
                    
                    with open(text_file_path, 'r') as f:
                        result = subprocess.run(
                            cmd,
                            stdin=f,
                            capture_output=True,
                            timeout=settings.REQUEST_TIMEOUT
                        )
                    
                    if result.returncode != 0:
                        raise Exception(f"Piper failed: {result.stderr.decode()}")
                    
                    with open(wav_file_path, 'rb') as f:
                        wav_data = f.read()
                    
                    return wav_data
                    
                finally:
                    for path in [text_file_path, wav_file_path]:
                        try:
                            if os.path.exists(path):
                                os.unlink(path)
                        except:
                            pass
                            
            except subprocess.TimeoutExpired:
                raise Exception("TTS generation timeout")
            except Exception as e:
                raise Exception(f"TTS generation failed: {e}")
        
        return await loop.run_in_executor(self.executor, run_tts)
    
    async def _convert_to_mp3(self, wav_data: bytes) -> bytes:
        loop = asyncio.get_event_loop()
        
        def convert():
            try:
                audio = AudioSegment.from_wav(io.BytesIO(wav_data))
                
                mp3_buffer = io.BytesIO()
                audio.export(
                    mp3_buffer,
                    format='mp3',
                    bitrate=settings.MP3_BITRATE,
                    parameters=["-q:a", "2"]
                )
                
                mp3_buffer.seek(0)
                return mp3_buffer.read()
                
            except Exception as e:
                raise Exception(f"MP3 conversion failed: {e}")
        
        return await loop.run_in_executor(self.executor, convert)
    
    async def cleanup(self):
        try:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.loaded_models.clear()
            self.model_configs.clear()
            
            if self.temp_dir.exists():
                for file in self.temp_dir.glob("*"):
                    try:
                        file.unlink()
                    except:
                        pass
            
            logger.info("TTS service cleanup completed")
            
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
