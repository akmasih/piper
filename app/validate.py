# validate.py
# Path: /Users/eleheim/projects/piper/app/validate.py
# Loads and runs every staged voice and recogniser with the pinned sherpa-onnx engine before the manifest is published.
#
# A pack the engine cannot load must never reach a learner. On the web a load
# failure is an error message; in the mobile app it is an uncaught C++ exception
# that ends the whole app. Hashes prove the files are the files the builder made;
# only loading them in the same engine release the clients run proves they work.
#
# Each check runs in a child process (`python validate.py <json>`): a model that
# the engine rejects can abort the process outright, and that must fail the one
# check with its reason, not kill the build without one.

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

_CHECK_TIMEOUT_SEC = 600


def _check_voice(spec: Dict[str, str]) -> Dict[str, object]:
    import sherpa_onnx

    tts = sherpa_onnx.OfflineTts(
        sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=spec["model"],
                    tokens=spec["tokens"],
                    data_dir=spec["data_dir"],
                ),
                num_threads=1,
            ),
        )
    )
    audio = tts.generate(spec["sample_text"], sid=0, speed=1.0)
    if len(audio.samples) == 0:
        raise RuntimeError("the voice produced no audio")
    if audio.sample_rate != int(spec["sample_rate"]):
        raise RuntimeError(f"the voice speaks at {audio.sample_rate} Hz, the manifest says {spec['sample_rate']}")
    return {"samples": len(audio.samples), "sample_rate": audio.sample_rate}


def _check_recogniser(spec: Dict[str, str]) -> Dict[str, object]:
    import numpy as np
    import sherpa_onnx

    if spec["model_type"] == "nemo_transducer":
        recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=spec["encoder"],
            decoder=spec["decoder"],
            joiner=spec["joiner"],
            tokens=spec["tokens"],
            model_type="nemo_transducer",
        )
    else:
        recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
            encoder=spec["encoder"],
            decoder=spec["decoder"],
            tokens=spec["tokens"],
            language=spec["language"],
            enable_token_timestamps=True,
        )
    # Two seconds of faint noise: enough for every stage of the model to run.
    rng = np.random.default_rng(0)
    samples = (rng.standard_normal(32000) * 0.01).astype(np.float32)
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, samples)
    recognizer.decode_stream(stream)
    result = stream.result
    if len(result.tokens) != len(result.timestamps):
        raise RuntimeError(
            f"{len(result.tokens)} tokens came back with {len(result.timestamps)} timestamps: "
            "word timings would be missing"
        )
    return {"tokens": len(result.tokens)}


def run_check(spec: Dict[str, str], label: str) -> None:
    """Run one check in a child process; raise with its output when it fails."""
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), json.dumps(spec)],
        capture_output=True,
        text=True,
        timeout=_CHECK_TIMEOUT_SEC,
    )
    if completed.returncode != 0:
        output = (completed.stdout + completed.stderr).strip().splitlines()[-15:]
        raise RuntimeError(
            f"{label} does not load in the pinned sherpa-onnx engine "
            f"(exit {completed.returncode}):\n" + "\n".join(output)
        )
    logger.info("Validated %s: %s", label, completed.stdout.strip().splitlines()[-1])


def validation_specs(components: List[object], components_dir: Path) -> List[Dict[str, str]]:
    """The checks for every voice and recogniser among the staged components."""
    by_id = {c.id: c for c in components}
    specs: List[Dict[str, str]] = []
    for component in components:
        root = components_dir / component.id / component.version
        if component.kind == "tts_voice":
            data = by_id[component.requires[0]]
            specs.append(
                {
                    "check": "voice",
                    "label": component.id,
                    "model": str(root / component.tts["model"]),
                    "tokens": str(root / component.tts["tokens"]),
                    "data_dir": str(components_dir / data.id / data.version / component.tts["data_dir"]),
                    "sample_rate": str(component.tts["sample_rate"]),
                    "sample_text": "Hello.",
                }
            )
        elif component.kind == "stt_model":
            files = component.stt["files"]
            spec = {
                "check": "recogniser",
                "label": component.id,
                "model_type": component.stt["model_type"],
                "tokens": str(root / files["tokens"]),
                "encoder": str(root / files["encoder"]),
                "decoder": str(root / files["decoder"]),
                "language": component.stt["languages"][0],
            }
            if "joiner" in files:
                spec["joiner"] = str(root / files["joiner"])
            specs.append(spec)
    return specs


def _child(spec_json: str) -> None:
    spec = json.loads(spec_json)
    if spec["check"] == "voice":
        summary = _check_voice(spec)
    else:
        summary = _check_recogniser(spec)
    print(json.dumps(summary))


if __name__ == "__main__":
    _child(sys.argv[1])
