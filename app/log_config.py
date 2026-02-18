# log_config.py
# Path: /root/piper/app/log_config.py
# Centralized logging configuration for Piper TTS server
#
# Logging strategy:
#   1. stdout  → Docker json-file driver → Fluent Bit (docker.* input) → Loki
#   2. file    → /var/log/fastapi/piper.log (local backup on host via volume mount)
#
# Fluent Bit does NOT read the file directly. It reads Docker container logs.
# The file is only a local safety net / backup for debugging on the server itself.

import os
import sys
import json
import logging
import glob
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional


# ============================================
# CONFIGURATION (from environment)
# ============================================

LOG_DIR = os.environ.get("LOG_DIR", "/var/log/fastapi")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
SERVER_NAME = os.environ.get("SERVER_NAME", "piper")

# Rotation: max 500MB per file, 10 backups = ~5GB total
LOG_MAX_BYTES = int(os.environ.get("LOG_MAX_BYTES", 500 * 1024 * 1024))
LOG_BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", 10))

# Retention: delete files older than 14 days
LOG_RETENTION_DAYS = int(os.environ.get("LOG_RETENTION_DAYS", 14))


# ============================================
# JSON FORMATTER
# ============================================

class JSONFormatter(logging.Formatter):
    """
    Structured JSON log formatter.

    Every line is a valid JSON object:
    {
        "ts": "2025-02-15T12:00:00.123Z",
        "level": "INFO",
        "logger": "main",
        "msg": "Request processed",
        "server": "piper",
        "language": "en",
        "locale": "US",
        "voice": "lessac",
        "duration_ms": 123.4,
        "error": "traceback..."
    }
    """

    _SKIP_FIELDS = frozenset({
        "name", "msg", "args", "created", "relativeCreated", "exc_info",
        "exc_text", "stack_info", "lineno", "funcName", "filename",
        "module", "pathname", "thread", "threadName", "process",
        "processName", "levelname", "levelno", "msecs", "message",
        "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.utcfromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S.")
                  + f"{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "server": SERVER_NAME,
        }

        # Extract extra fields (language, locale, voice, duration_ms, etc.)
        for key, value in record.__dict__.items():
            if key not in self._SKIP_FIELDS and not key.startswith("_"):
                if isinstance(value, (str, int, float, bool, type(None))):
                    entry[key] = value

        if record.exc_info and record.exc_info[0] is not None:
            entry["error"] = self.formatException(record.exc_info)

        return json.dumps(entry, ensure_ascii=False, default=str)


# ============================================
# SETUP
# ============================================

_initialized = False


def setup_logging(
    server_name: Optional[str] = None,
    log_level: Optional[str] = None,
    log_dir: Optional[str] = None,
) -> None:
    """
    Initialize logging for the application.
    Call once at startup.

    Dual output:
      1. stdout   → picked up by Docker → Fluent Bit → Loki  (primary)
      2. file     → local backup on host volume mount         (secondary)

    Args:
        server_name: Override SERVER_NAME env var
        log_level:   Override LOG_LEVEL env var
        log_dir:     Override LOG_DIR env var
    """
    global _initialized, SERVER_NAME

    if _initialized:
        return

    if server_name:
        SERVER_NAME = server_name
    level = (log_level or LOG_LEVEL).upper()
    directory = log_dir or LOG_DIR
    numeric_level = getattr(logging, level, logging.INFO)

    # Root logger
    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers.clear()

    json_formatter = JSONFormatter()

    # --- Handler 1: stdout (primary - Docker → Fluent Bit → Loki) ---
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(numeric_level)
    stdout_handler.setFormatter(json_formatter)
    root.addHandler(stdout_handler)

    # --- Handler 2: file (secondary - local backup on host) ---
    log_file = None
    try:
        os.makedirs(directory, exist_ok=True)
        log_file = os.path.join(directory, f"{SERVER_NAME}.log")

        file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(json_formatter)
        root.addHandler(file_handler)
    except (OSError, PermissionError) as e:
        # File logging is optional - if it fails, stdout still works
        root.warning(
            f"File logging unavailable ({e}), using stdout only",
            extra={"log_dir": directory},
        )
        log_file = None

    # Suppress noisy third-party loggers
    for name in ("uvicorn.access", "httpcore", "httpx", "urllib3", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(numeric_level)

    _initialized = True

    logger = logging.getLogger("log_config")
    logger.info(
        "Logging initialized",
        extra={
            "log_level": level,
            "log_file": log_file or "disabled",
            "stdout": True,
            "max_bytes": LOG_MAX_BYTES,
            "backup_count": LOG_BACKUP_COUNT,
            "retention_days": LOG_RETENTION_DAYS,
        },
    )


# ============================================
# LOGGER FACTORY
# ============================================

def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger.

    Usage in any module:
        from log_config import get_logger
        logger = get_logger(__name__)
        logger.info("Something happened", extra={"language": "en", "voice": "lessac"})
    """
    return logging.getLogger(name)


# ============================================
# LOG CLEANUP
# ============================================

async def cleanup_old_logs(
    log_dir: Optional[str] = None,
    retention_days: Optional[int] = None,
) -> int:
    """
    Delete log files older than retention period.
    Call from your background cleanup loop.
    Returns number of files deleted.
    """
    directory = log_dir or LOG_DIR
    days = retention_days or LOG_RETENTION_DAYS
    cutoff = time.time() - (days * 86400)
    deleted = 0

    try:
        pattern = os.path.join(directory, "*.log*")
        for filepath in glob.glob(pattern):
            if os.path.getmtime(filepath) < cutoff:
                os.remove(filepath)
                deleted += 1

        if deleted > 0:
            logger = get_logger("log_config")
            logger.info(f"Cleaned {deleted} log files older than {days} days")
    except Exception as e:
        logger = get_logger("log_config")
        logger.error(f"Log cleanup failed: {e}")

    return deleted
