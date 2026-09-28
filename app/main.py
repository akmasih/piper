# main.py
# Path: /root/piper/app/main.py
# Builds every speech pack component from pinned upstream sources and publishes the manifest.
#
# Run inside the builder container (see ../docker-compose.yml and ../setup.sh):
#
#   python main.py            build or refresh everything, write manifest.json
#   python main.py --prune    the same, then delete component versions no longer listed
#
# Nothing here chooses between alternatives at run time. Every source is pinned in
# config.py; a missing file, an unexpected archive layout, a licence outside the
# allowlist or a model the engine cannot load stops the build with the reason, and
# the previous manifest stays live.

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Dict, List

from config import (
    ALLOWED_LICENSES,
    ESPEAK_ARCHIVE_URL,
    ESPEAK_COMPONENT_ID,
    PARAKEET_V3,
    PARAKEET_V3_ARCHIVE_ROOT,
    PARAKEET_V3_ARCHIVE_URL,
    RUNTIME_WEB_COMPONENT_ID,
    RUNTIME_WEB_FILES,
    SHERPA_ONNX_GIT_URL,
    SHERPA_ONNX_VERSION,
    SHERPA_WEB_ARCHIVE_URL,
    TTS_VOICES,
    WHISPER_TURBO,
    Settings,
    SttModel,
    TtsVoice,
    normalize_license,
)
from fetch import download, extract, sha256_of
from manifest import Component, prune_unreferenced, stage_component, write_manifest
from validate import run_check, validation_specs
from whisper_export import export_whisper_turbo

logger = logging.getLogger("speech-packs")

_LICENSE_LINE = re.compile(r"^\*\s*License:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _require_file(path: Path) -> Path:
    if not path.is_file():
        raise RuntimeError(f"Expected file is missing: {path}")
    return path


def _require_dir(path: Path) -> Path:
    if not path.is_dir():
        raise RuntimeError(f"Expected directory is missing: {path}")
    return path


def _source(url: str, archive: Path) -> Dict[str, str]:
    return {"url": url, "sha256": sha256_of(archive)}


def build_runtime_web(settings: Settings) -> Component:
    """The engine's WebAssembly build and its JavaScript wrappers, for the browser."""
    archive = download(SHERPA_WEB_ARCHIVE_URL, settings.downloads_dir)
    assets = _require_dir(extract(archive, settings.extract_dir) / "assets")
    sources = {name: _require_file(assets / name) for name in RUNTIME_WEB_FILES}
    version, files = stage_component(settings, RUNTIME_WEB_COMPONENT_ID, sources)
    return Component(
        id=RUNTIME_WEB_COMPONENT_ID,
        kind="runtime",
        version=version,
        license="Apache-2.0",
        attribution=f"sherpa-onnx {SHERPA_ONNX_VERSION}, Apache License 2.0",
        files=files,
        source=_source(SHERPA_WEB_ARCHIVE_URL, archive),
    )


def build_espeak_data(settings: Settings) -> Component:
    """espeak-ng's phoneme data, shared by every Piper voice."""
    archive = download(ESPEAK_ARCHIVE_URL, settings.downloads_dir)
    data_dir = _require_dir(extract(archive, settings.extract_dir) / "espeak-ng-data")
    sources = {
        f"espeak-ng-data/{path.relative_to(data_dir).as_posix()}": path
        for path in sorted(data_dir.rglob("*"))
        if path.is_file()
    }
    version, files = stage_component(settings, ESPEAK_COMPONENT_ID, sources)
    return Component(
        id=ESPEAK_COMPONENT_ID,
        kind="tts_data",
        version=version,
        license="GPL-3.0",
        attribution="espeak-ng data, GNU GPL v3",
        files=files,
        source=_source(ESPEAK_ARCHIVE_URL, archive),
    )


def _voice_license(model_card: Path, voice: TtsVoice) -> str:
    """The dataset licence stated on the voice's model card, checked against the allowlist."""
    text = model_card.read_text(encoding="utf-8")
    match = _LICENSE_LINE.search(text)
    if not match:
        raise RuntimeError(f"Voice {voice.id}: MODEL_CARD states no licence ({model_card})")
    license_name = match.group(1)
    if normalize_license(license_name) not in ALLOWED_LICENSES:
        raise RuntimeError(
            f"Voice {voice.id}: licence '{license_name}' is not in ALLOWED_LICENSES. "
            "Replace the voice in config.TTS_VOICES or, after a legal review, allow the licence."
        )
    return license_name


def build_voice(settings: Settings, voice: TtsVoice) -> Component:
    """One Piper voice: the VITS model, its phoneme token table, and its audio settings."""
    archive = download(voice.archive_url, settings.downloads_dir)
    root = _require_dir(extract(archive, settings.extract_dir) / voice.archive_root)
    model = _require_file(root / f"{voice.id}.onnx")
    tokens = _require_file(root / "tokens.txt")
    config = json.loads(_require_file(root / f"{voice.id}.onnx.json").read_text(encoding="utf-8"))
    license_name = _voice_license(_require_file(root / "MODEL_CARD"), voice)

    sample_rate = int(config["audio"]["sample_rate"])
    num_speakers = int(config["num_speakers"])
    if num_speakers != 1:
        raise RuntimeError(f"Voice {voice.id} has {num_speakers} speakers; the catalog lists single-speaker voices only")

    version, files = stage_component(
        settings,
        voice.component_id,
        {model.name: model, "tokens.txt": tokens},
    )
    return Component(
        id=voice.component_id,
        kind="tts_voice",
        version=version,
        license=license_name,
        attribution=f"Piper voice {voice.id}, {license_name}",
        files=files,
        requires=[ESPEAK_COMPONENT_ID],
        tts={
            "model_type": "vits",
            "model": model.name,
            "tokens": "tokens.txt",
            "data_dir": "espeak-ng-data",
            "sample_rate": sample_rate,
            "language": voice.language,
            "locale": voice.locale,
            "gender": voice.gender,
            "display_name": voice.display_name,
        },
        source=_source(voice.archive_url, archive),
    )


def _stt_component(
    settings: Settings, model: SttModel, root: Path, source: Dict[str, str]
) -> Component:
    sources = {name: _require_file(root / name) for name in model.files.values()}
    version, files = stage_component(settings, model.component_id, sources)
    return Component(
        id=model.component_id,
        kind="stt_model",
        version=version,
        license=model.license,
        attribution=model.attribution,
        files=files,
        stt={
            "model_type": model.model_type,
            "files": dict(model.files),
            "languages": list(model.languages),
            "max_input_sec": model.max_input_sec,
            "sample_rate": 16000,
        },
        source=source,
    )


def build_parakeet(settings: Settings) -> Component:
    """NVIDIA Parakeet TDT 0.6B v3 (int8), as sherpa-onnx publishes it."""
    archive = download(PARAKEET_V3_ARCHIVE_URL, settings.downloads_dir)
    root = _require_dir(extract(archive, settings.extract_dir) / PARAKEET_V3_ARCHIVE_ROOT)
    return _stt_component(settings, PARAKEET_V3, root, _source(PARAKEET_V3_ARCHIVE_URL, archive))


def build_whisper(settings: Settings) -> Component:
    """Whisper turbo (int8) with the cross-attention output word timings need."""
    root = export_whisper_turbo(settings)
    return _stt_component(
        settings,
        WHISPER_TURBO,
        root,
        {
            "export": "scripts/whisper/export-onnx-with-attention.py --model turbo",
            "repository": f"{SHERPA_ONNX_GIT_URL}@v{SHERPA_ONNX_VERSION}",
        },
    )


def build_all(settings: Settings) -> List[Component]:
    components = [build_runtime_web(settings), build_espeak_data(settings)]
    components.extend(build_voice(settings, voice) for voice in TTS_VOICES)
    components.append(build_parakeet(settings))
    components.append(build_whisper(settings))
    return components


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the speech packs and their manifest.")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="after writing the manifest, delete component versions it no longer lists",
    )
    args = parser.parse_args()

    settings = Settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    components = build_all(settings)
    # Every voice and recogniser must load and run in the pinned engine before
    # any client can be told about it (validate.py says why).
    for spec in validation_specs(components, settings.components_dir):
        run_check(spec, spec["label"])
    write_manifest(settings, components)
    if args.prune:
        prune_unreferenced(settings, components)

    total = sum(c.size for c in components)
    logger.info("Built %d components, %.1f MB in total", len(components), total / 1e6)
    for component in components:
        logger.info(
            "  %-40s %8.1f MB  %s",
            component.id,
            component.size / 1e6,
            component.license,
        )


if __name__ == "__main__":
    main()
