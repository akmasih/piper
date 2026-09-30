# whisper_export.py
# Path: /Users/eleheim/projects/piper/app/whisper_export.py
# Exports Whisper turbo to ONNX with cross-attention outputs using sherpa-onnx's script at the pinned tag, then quantizes it to int8 in separate processes.
#
# Word timings from Whisper come from dynamic time warping over the decoder's
# cross-attention (sherpa-onnx `enable_token_timestamps`). The models sherpa-onnx
# publishes are exported without that output, so they decode text but cannot say
# when a word was spoken. export-onnx-with-attention.py, from the same release the
# clients run, adds the fourth decoder output that the engine's DTW reads.
#
# That script quantizes to int8 in the same process that still holds the
# PyTorch model and the traced graph, which is what drove the memory peak past
# what Docker Desktop gives a container. Here the work is split into three child
# processes, each starting with empty memory:
#
#   1. export   the script itself, with its int8 step deferred: float32 ONNX + tokens
#   2. quantize the float32 encoder to int8, with the script's exact settings
#   3. quantize the float32 decoder to int8, likewise
#
# Each stage is cached in the work directory: the float32 export takes minutes
# and a 1.5 GB checkpoint, and only the int8 files are kept once they exist.
#
# Children are started as `python whisper_export.py <stage> ...`.

import logging
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

from config import SHERPA_ONNX_GIT_URL, SHERPA_ONNX_VERSION, WHISPER_TURBO, Settings
from fetch import git_checkout

logger = logging.getLogger(__name__)

_MODEL_NAME = "turbo"
_EXPORT_SCRIPT = "export-onnx-with-attention.py"

# The quantization the export script applies (v1.13.8, main()); the export
# stage refuses to run if the script asks for anything else.
_QUANTIZE_OP_TYPES: List[str] = ["MatMul"]
_QUANTIZE_WEIGHT_TYPE = "QInt8"

# Float32 files the export script writes into its working directory.
_FLOAT_FILES: Dict[str, str] = {
    "encoder": f"{_MODEL_NAME}-encoder.onnx",
    "decoder": f"{_MODEL_NAME}-decoder.onnx",
    "tokens": f"{_MODEL_NAME}-tokens.txt",
}


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

    float_dir = _export_float(settings)

    staging = output_dir.with_name(output_dir.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for part in ("encoder", "decoder"):
        source = float_dir / _FLOAT_FILES[part]
        target = staging / WHISPER_TURBO.files[part]
        logger.info("Quantizing Whisper %s %s to int8", _MODEL_NAME, part)
        _run_child(["quantize", str(source), str(target)], cwd=staging, what=f"int8 quantization of the {part}")
        if not target.is_file():
            raise RuntimeError(f"Quantization did not produce {target}")
    shutil.copy2(float_dir / _FLOAT_FILES["tokens"], staging / WHISPER_TURBO.files["tokens"])

    if output_dir.exists():
        shutil.rmtree(output_dir)
    staging.rename(output_dir)
    stamp.write_text(SHERPA_ONNX_VERSION, encoding="utf-8")

    # The float32 export is several gigabytes and is not shipped.
    shutil.rmtree(float_dir)
    return output_dir


def _export_float(settings: Settings) -> Path:
    """Run the export script (without its int8 step) into its own directory."""
    float_dir = settings.export_dir / f"whisper-{_MODEL_NAME}-{SHERPA_ONNX_VERSION}.float32"
    stamp = float_dir / ".exported"
    if stamp.is_file():
        logger.info("Using cached float32 Whisper export in %s", float_dir)
        return float_dir

    checkout = git_checkout(
        SHERPA_ONNX_GIT_URL, f"v{SHERPA_ONNX_VERSION}", settings.work_dir / "src"
    )
    script = (checkout / "scripts" / "whisper" / _EXPORT_SCRIPT).resolve()
    if not script.is_file():
        raise RuntimeError(f"Export script is missing from the checkout: {script}")

    # A fresh directory: the float32 encoder is over 2 GB, so its weights land
    # in external data files beside it, all of which go away with the directory.
    if float_dir.exists():
        shutil.rmtree(float_dir)
    float_dir.mkdir(parents=True)

    logger.info("Exporting Whisper %s with cross-attention outputs (float32)", _MODEL_NAME)
    _run_child(["export", str(script)], cwd=float_dir, what="float32 export")
    for name in _FLOAT_FILES.values():
        if not (float_dir / name).is_file():
            raise RuntimeError(f"Whisper export did not produce {name} in {float_dir}")

    stamp.write_text(SHERPA_ONNX_VERSION, encoding="utf-8")
    return float_dir


def _run_child(args: List[str], cwd: Path, what: str) -> None:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *args],
        cwd=cwd,
    )
    if completed.returncode == -signal.SIGKILL:
        raise RuntimeError(
            f"Whisper {what} was killed (SIGKILL), which is the kernel's out-of-memory "
            "killer: give Docker more memory (Docker Desktop: Settings > Resources > "
            "Memory, at least 12 GB, plus swap) and run ./setup.sh again."
        )
    if completed.returncode != 0:
        raise RuntimeError(f"Whisper {what} failed with exit code {completed.returncode}")


# =============================================================================
# Child processes
# =============================================================================


def _child_export(script_path: str) -> None:
    """
    Run export-onnx-with-attention.py as its own `__main__` block does, with
    its quantize_dynamic calls deferred to the quantize stage.
    """
    import importlib.util

    script = Path(script_path)
    # The script imports its sibling export_onnx.py.
    sys.path.insert(0, str(script.parent))
    spec = importlib.util.spec_from_file_location("export_onnx_with_attention", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def defer_quantization(model_input: str, model_output: str, op_types_to_quantize, weight_type) -> None:
        if list(op_types_to_quantize) != _QUANTIZE_OP_TYPES or weight_type.name != _QUANTIZE_WEIGHT_TYPE:
            raise RuntimeError(
                f"{script.name} quantizes {model_input} with op types {op_types_to_quantize} "
                f"and weight type {weight_type.name}; whisper_export.py applies "
                f"{_QUANTIZE_OP_TYPES} and {_QUANTIZE_WEIGHT_TYPE}. Update it to match the script."
            )
        logger.info("Deferred int8 quantization of %s to its own process", model_input)

    module.quantize_dynamic = defer_quantization
    sys.argv = [script.name, "--model", _MODEL_NAME]

    # The script's `if __name__ == "__main__":` block at the pinned tag.
    import torch
    from whisper.model import disable_sdpa

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    with disable_sdpa():
        module.main()


def _child_quantize(model_input: str, model_output: str) -> None:
    """Dynamic int8 quantization with the export script's settings."""
    from onnxruntime.quantization import QuantType, quantize_dynamic

    quantize_dynamic(
        model_input=model_input,
        model_output=model_output,
        op_types_to_quantize=_QUANTIZE_OP_TYPES,
        weight_type=QuantType[_QUANTIZE_WEIGHT_TYPE],
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stage = sys.argv[1]
    if stage == "export":
        _child_export(sys.argv[2])
    elif stage == "quantize":
        _child_quantize(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(f"Unknown stage: {stage}")
