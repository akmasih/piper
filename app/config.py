# config.py
# Path: /root/piper/app/config.py
# Pinned catalog of every speech pack component (engine runtime, voices, recognisers) and the builder's settings.
#
# This file is the contract between the pack builder and the two clients (web and
# Flutter). Everything a client downloads is listed here, pinned to one upstream
# release, so the same build input always produces the same pack.
#
# Why one engine version for everything: the clients load every model with the
# same sherpa-onnx build (the Flutter plugin on phones, the WebAssembly module in
# the browser). A model exported for one sherpa-onnx release is only guaranteed to
# load in that release, so SHERPA_ONNX_VERSION is written into the manifest and a
# client whose engine differs refuses the manifest instead of guessing.

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple


# =============================================================================
# Engine
# =============================================================================

SHERPA_ONNX_VERSION = "1.13.8"
"""The sherpa-onnx release every client runs and every model is built for."""

SHERPA_ONNX_GIT_URL = "https://github.com/k2-fsa/sherpa-onnx"
"""Source checkout used only to run the Whisper export script at the pinned tag."""

SHERPA_RELEASES_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
"""Upstream release assets: pre-converted Piper voices, espeak-ng data, Parakeet."""

SHERPA_WEB_ARCHIVE_URL = (
    f"https://pub.dev/api/archives/sherpa_onnx_web-{SHERPA_ONNX_VERSION}.tar.gz"
)
"""The browser build of the engine, published inside the sherpa_onnx_web package."""

MANIFEST_SCHEMA = 1
"""Bumped only when the manifest's shape changes; clients refuse other values."""


# =============================================================================
# Licences
# =============================================================================

ALLOWED_LICENSES = frozenset(
    {
        "cc0",
        "cc010",
        "publicdomain",
        "ccby40",
        "ccby30",
        "mit",
        "apache20",
    }
)
"""
Licences a voice or model may carry to be shipped in a commercial app.

Compared after normalisation (lower case, only letters and digits), so
"CC BY 4.0", "CC-BY-4.0" and "cc-by-4.0" are the same entry. A voice whose model
card names anything else stops the build with its name and licence: shipping a
non-commercial voice is a legal decision, never something to find out later.
"""


def normalize_license(value: str) -> str:
    """Reduce a licence name to letters and digits so spellings compare equal."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


# =============================================================================
# Catalog entries
# =============================================================================


@dataclass(frozen=True)
class TtsVoice:
    """
    One Piper voice, as sherpa-onnx republishes it (vits-piper-<id>.tar.bz2).

    `id` is Piper's own voice key (<lang>_<REGION>-<name>-<quality>), so it can
    be traced back to the upstream model card without a lookup table.
    """

    id: str
    language: str
    locale: str
    gender: str
    display_name: str

    @property
    def component_id(self) -> str:
        return f"tts-{self.id}"

    @property
    def archive_url(self) -> str:
        return f"{SHERPA_RELEASES_URL}/tts-models/vits-piper-{self.id}.tar.bz2"

    @property
    def archive_root(self) -> str:
        return f"vits-piper-{self.id}"


@dataclass(frozen=True)
class SttModel:
    """
    One offline recogniser that returns per-token timestamps.

    `max_input_sec` is the longest stretch of audio the client may hand the model
    in one call. The client cuts longer audio at quiet points before decoding, so
    the model never sees more than it was built for (Whisper's encoder is fixed
    at thirty seconds; Parakeet is kept to a minute so a phone's memory holds).
    """

    component_id: str
    model_type: str
    languages: Tuple[str, ...]
    max_input_sec: int
    license: str
    attribution: str
    files: Dict[str, str]


@dataclass(frozen=True)
class Pack:
    """
    What a learner installs: one feature, one language.

    A pack is a list of components. Components are shared — the English and the
    German subtitle packs point at the same Parakeet model — so a client that
    installs both downloads it once.
    """

    id: str
    feature: str
    language: str
    components: Tuple[str, ...]
    default_voice: str = ""


# Voices: one pack per language, each voice its own component. The genders are
# stated here, not guessed from the name; the clients show them as written.
TTS_VOICES: List[TtsVoice] = [
    TtsVoice("en_US-kristin-medium", "en", "US", "female", "Kristin"),
    TtsVoice("en_US-norman-medium", "en", "US", "male", "Norman"),
    TtsVoice("de_DE-kerstin-low", "de", "DE", "female", "Kerstin"),
    TtsVoice("de_DE-thorsten-medium", "de", "DE", "male", "Thorsten"),
    TtsVoice("fa_IR-amir-medium", "fa", "IR", "male", "Amir"),
    TtsVoice("fa_IR-gyro-medium", "fa", "IR", "male", "Gyro"),
]

PARAKEET_V3 = SttModel(
    component_id="stt-parakeet-tdt-0.6b-v3-int8",
    model_type="nemo_transducer",
    languages=("en", "de"),
    max_input_sec=60,
    license="CC-BY-4.0",
    attribution="NVIDIA Parakeet TDT 0.6B v3, CC BY 4.0",
    files={
        "encoder": "encoder.int8.onnx",
        "decoder": "decoder.int8.onnx",
        "joiner": "joiner.int8.onnx",
        "tokens": "tokens.txt",
    },
)
PARAKEET_V3_ARCHIVE_URL = (
    f"{SHERPA_RELEASES_URL}/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"
)
PARAKEET_V3_ARCHIVE_ROOT = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"

WHISPER_TURBO = SttModel(
    component_id="stt-whisper-turbo-timestamps-int8",
    model_type="whisper",
    languages=("fa",),
    max_input_sec=28,
    license="MIT",
    attribution="OpenAI Whisper large-v3-turbo, MIT",
    files={
        "encoder": "turbo-encoder.int8.onnx",
        "decoder": "turbo-decoder.int8.onnx",
        "tokens": "turbo-tokens.txt",
    },
)
"""
Exported here, not downloaded: the released sherpa-onnx Whisper models carry no
cross-attention output, and without it there are no word timings — which is the
one thing a subtitle needs. export-onnx-with-attention.py adds that output.
"""

ESPEAK_COMPONENT_ID = "espeak-ng-data"
ESPEAK_ARCHIVE_URL = f"{SHERPA_RELEASES_URL}/tts-models/espeak-ng-data.tar.bz2"

RUNTIME_WEB_COMPONENT_ID = "runtime-web"
RUNTIME_WEB_FILES = (
    "sherpa-onnx-wasm-web.js",
    "sherpa-onnx-wasm-web.wasm",
    "sherpa-onnx-tts.js",
    "sherpa-onnx-asr.js",
)
"""Taken from the sherpa_onnx_web package's assets/ directory, byte for byte."""


def _tts_pack(language: str, default_voice: str) -> Pack:
    voices = tuple(v.component_id for v in TTS_VOICES if v.language == language)
    return Pack(
        id=f"tts-{language}",
        feature="tts",
        language=language,
        components=voices,
        default_voice=f"tts-{default_voice}",
    )


def _stt_pack(language: str, model: SttModel) -> Pack:
    return Pack(
        id=f"video-stt-{language}",
        feature="video_stt",
        language=language,
        components=(model.component_id,),
    )


PACKS: List[Pack] = [
    _tts_pack("en", "en_US-kristin-medium"),
    _tts_pack("de", "de_DE-thorsten-medium"),
    _tts_pack("fa", "fa_IR-amir-medium"),
    _stt_pack("en", PARAKEET_V3),
    _stt_pack("de", PARAKEET_V3),
    _stt_pack("fa", WHISPER_TURBO),
]


# =============================================================================
# Builder settings
# =============================================================================


@dataclass
class Settings:
    """Paths the builder reads and writes, from the environment."""

    packs_dir: Path = field(default_factory=lambda: Path(os.environ["PACKS_DIR"]))
    work_dir: Path = field(default_factory=lambda: Path(os.environ["WORK_DIR"]))
    log_level: str = field(default_factory=lambda: os.environ["LOG_LEVEL"])

    @property
    def downloads_dir(self) -> Path:
        return self.work_dir / "downloads"

    @property
    def extract_dir(self) -> Path:
        return self.work_dir / "extracted"

    @property
    def export_dir(self) -> Path:
        return self.work_dir / "export"

    @property
    def components_dir(self) -> Path:
        return self.packs_dir / "components"

    @property
    def manifest_path(self) -> Path:
        return self.packs_dir / "manifest.json"
