# whisper_export.py
# Path: /root/piper/app/whisper_export.py
# Exports Whisper turbo to ONNX with cross-attention outputs, using sherpa-onnx's own script at the pinned tag.
#
# Word timings from Whisper come from dynamic time warping over the decoder's
# cross-attention (sherpa-onnx `enable_token_timestamps`). The models sherpa-onnx
# publishes are exported without that output, so they decode text but cannot say
# when a word was spoken. export-onnx-with-attention.py, from the same release the
# clients run, adds the fourth decoder output that the engine's DTW reads.
#
# The export needs PyTorch and downloads the turbo checkpoint through the
# `openai-whisper` package; it runs once and its result is cached in the work
# directory, because it takes several minutes and several gigabytes of memory.

import logging
import shutil
import subprocess
import sys
from pathlib import Path

from config import SHERPA_ONNX_GIT_URL, SHERPA_ONNX_VERSION, WHISPER_TURBO, Settings
from fetch import git_checkout

logger = logging.getLogger(__name__)

_MODEL_NAME = "turbo"


def export_whisper_turbo(settings: Settings) -> Path:
    """
    Return a directory holding the int8 encoder, int8 decoder and tokens of
    Whisper turbo exported with cross-attention weights.
    """
    output_dir = settings.export_dir / f"whisper-{_MODEL_NAME}-{SHERPA_ONNX_VERSION}"
    stamp = output_dir / ".exported"
    if stamp.is_file():
        logger.info("Using cached Whisper export in %s", output_dir)
        return output_dir

    checkout = git_checkout(
        SHERPA_ONNX_GIT_URL, f"v{SHERPA_ONNX_VERSION}", settings.work_dir / "src"
    )
    script_dir = checkout / "scripts" / "whisper"

    logger.info("Exporting Whisper %s with cross-attention outputs", _MODEL_NAME)
    subprocess.run(
        [sys.executable, "export-onnx-with-attention.py", "--model", _MODEL_NAME],
        cwd=script_dir,
        check=True,
    )

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    for name in WHISPER_TURBO.files.values():
        produced = script_dir / name
        if not produced.is_file():
            raise RuntimeError(f"Whisper export did not produce {name} in {script_dir}")
        shutil.move(str(produced), output_dir / name)

    # The float32 exports and their external weight files are several gigabytes
    # and are not shipped; remove them so the checkout does not keep them.
    for leftover in script_dir.glob(f"{_MODEL_NAME}-*"):
        if leftover.is_file():
            leftover.unlink()

    stamp.write_text(SHERPA_ONNX_VERSION, encoding="utf-8")
    return output_dir
