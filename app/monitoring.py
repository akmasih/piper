# /root/piper/app/monitoring.py
# Optional monitoring and metrics for Piper TTS service

import time
import psutil
import logging
from typing import Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict, deque
from threading import Lock

logger = logging.getLogger(__name__)


class TTSMetrics:
    """Simple metrics collector for TTS service"""
    
    def __init__(self, window_size: int = 100):
        """Initialize metrics collector"""
        self.window_size = window_size
        self.lock = Lock()
        
        # Request metrics
        self.request_count = 0
        self.success_count = 0
        self.error_count = 0
        
        # Language statistics
        self.language_stats = defaultdict(int)
        
        # Performance metrics (sliding window)
        self.generation_times = deque(maxlen=window_size)
        self.request_sizes = deque(maxlen=window_size)
        
        # Error tracking
        self.recent_errors = deque(maxlen=10)
        
        # Start time
        self.start_time = time.time()
        
    def record_request(
        self,
        language: str,
        text_length: int,
        generation_time: float,
        success: bool,
        error: str = None
    ):
        """Record metrics for a TTS request"""
        with self.lock:
            self.request_count += 1
            
            if success:
                self.success_count += 1
                self.generation_times.append(generation_time)
                self.request_sizes.append(text_length)
            else:
                self.error_count += 1
                if error:
                    self.recent_errors.append({
                        'timestamp': datetime.utcnow().isoformat(),
                        'language': language,
                        'error': error
                    })
            
            self.language_stats[language] += 1
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        with self.lock:
            uptime = time.time() - self.start_time
            
            # Calculate averages
            avg_generation_time = (
                sum(self.generation_times) / len(self.generation_times)
                if self.generation_times else 0
            )
            
            avg_text_length = (
                sum(self.request_sizes) / len(self.request_sizes)
                if self.request_sizes else 0
            )
            
            # Success rate
            success_rate = (
                (self.success_count / self.request_count * 100)
                if self.request_count > 0 else 0
            )
            
            # System metrics
            process = psutil.Process()
            
            return {
                'service': 'piper-tts',
                'uptime_seconds': round(uptime, 2),
                'uptime_human': str(timedelta(seconds=int(uptime))),
                
                'requests': {
                    'total': self.request_count,
                    'successful': self.success_count,
                    'failed': self.error_count,
                    'success_rate': round(success_rate, 2)
                },
                
                'performance': {
                    'avg_generation_time_ms': round(avg_generation_time * 1000, 2),
                    'avg_text_length': round(avg_text_length),
                    'requests_per_minute': round(
                        self.request_count / (uptime / 60), 2
                    ) if uptime > 0 else 0
                },
                
                'languages': dict(self.language_stats),
                
                'system': {
                    'cpu_percent': process.cpu_percent(),
                    'memory_mb': round(process.memory_info().rss / 1024 / 1024, 2),
                    'threads': process.num_threads()
                },
                
                'recent_errors': list(self.recent_errors)[-5:]  # Last 5 errors
            }
    
    def reset(self):
        """Reset all metrics"""
        with self.lock:
            self.request_count = 0
            self.success_count = 0
            self.error_count = 0
            self.language_stats.clear()
            self.generation_times.clear()
            self.request_sizes.clear()
            self.recent_errors.clear()
            self.start_time = time.time()


# Global metrics instance
metrics = TTSMetrics()


# Decorator for timing functions
def measure_time(func):
    """Decorator to measure function execution time"""
    async def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = await func(*args, **kwargs)
            elapsed = time.time() - start
            logger.debug(f"{func.__name__} took {elapsed:.3f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"{func.__name__} failed after {elapsed:.3f}s: {e}")
            raise
    return wrapper