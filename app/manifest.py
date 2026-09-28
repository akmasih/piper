# manifest.py
# Path: /root/piper/app/manifest.py
# Stages each component into an immutable, content-versioned directory and writes the manifest the clients read.
#
# Layout under PACKS_DIR (served as /packs/ by the web host):
#
#   manifest.json
#   components/<component id>/<version>/<file path>
#
# `version` is derived from the files themselves (the SHA-256 of their sorted
# path/hash list), so a URL never changes meaning: a rebuilt component with new
# bytes lands in a new directory, a rebuilt component with the same bytes lands in
# the same one, and a client halfway through a download is never served a file
# from a different build. That is what lets the web host cache every component
# file as immutable and serve only manifest.json as always-revalidate.
#
# The manifest is written last, to a temporary name, and renamed into place, so a
# client never reads a manifest that names a component still being copied.

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from config import MANIFEST_SCHEMA, PACKS, SHERPA_ONNX_VERSION, Settings
from fetch import sha256_of

logger = logging.getLogger(__name__)


@dataclass
class StagedFile:
    """One file of a component, as the client will fetch and verify it."""

    path: str
    size: int
    sha256: str


@dataclass
class Component:
    """A component ready to be listed in the manifest."""

    id: str
    kind: str
    version: str
    license: str
    attribution: str
    files: List[StagedFile]
    requires: List[str] = field(default_factory=list)
    tts: Optional[Dict[str, object]] = None
    stt: Optional[Dict[str, object]] = None
    source: Dict[str, str] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)


def stage_component(
    settings: Settings,
    component_id: str,
    sources: Dict[str, Path],
) -> tuple[str, List[StagedFile]]:
    """
    Copy `sources` (published path -> file on disk) into the component's
    content-versioned directory. Returns the version and the file list.
    """
    if not sources:
        raise ValueError(f"Component {component_id} has no files")

    files = [
        StagedFile(path=published, size=source.stat().st_size, sha256=sha256_of(source))
        for published, source in sorted(sources.items())
    ]
    listing = "".join(f"{f.path}\0{f.sha256}\n" for f in files).encode("utf-8")
    version = hashlib.sha256(listing).hexdigest()[:16]

    component_root = settings.components_dir / component_id
    final_dir = component_root / version
    if (final_dir / ".complete").is_file():
        logger.info("Component %s %s already staged", component_id, version)
        return version, files

    staging_dir = component_root / f".staging-{version}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    for published, source in sources.items():
        target = staging_dir / published
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (staging_dir / ".complete").write_text(version, encoding="utf-8")

    if final_dir.exists():
        shutil.rmtree(final_dir)
    staging_dir.rename(final_dir)
    logger.info(
        "Staged component %s %s (%d files, %d bytes)",
        component_id,
        version,
        len(files),
        sum(f.size for f in files),
    )
    return version, files


def write_manifest(settings: Settings, components: List[Component]) -> Path:
    """Write manifest.json atomically. Every pack's components must be present."""
    by_id = {c.id: c for c in components}
    for pack in PACKS:
        for component_id in pack.components:
            if component_id not in by_id:
                raise RuntimeError(f"Pack {pack.id} names unknown component {component_id}")
        if pack.default_voice and pack.default_voice not in pack.components:
            raise RuntimeError(f"Pack {pack.id} default voice is not one of its components")
    for component in components:
        for required in component.requires:
            if required not in by_id:
                raise RuntimeError(f"Component {component.id} requires unknown {required}")

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": {"name": "sherpa-onnx", "version": SHERPA_ONNX_VERSION},
        "runtimes": {"web": "runtime-web"},
        "components": {
            c.id: {
                "kind": c.kind,
                "version": c.version,
                "size": c.size,
                "license": c.license,
                "attribution": c.attribution,
                "requires": c.requires,
                "files": [{"path": f.path, "size": f.size, "sha256": f.sha256} for f in c.files],
                "tts": c.tts,
                "stt": c.stt,
                "source": c.source,
            }
            for c in components
        },
        "packs": [
            {
                "id": p.id,
                "feature": p.feature,
                "language": p.language,
                "components": list(p.components),
                "default_voice": p.default_voice or None,
            }
            for p in PACKS
        ],
    }

    settings.packs_dir.mkdir(parents=True, exist_ok=True)
    temporary = settings.manifest_path.with_name(".manifest.json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(settings.manifest_path)
    logger.info("Wrote %s", settings.manifest_path)
    return settings.manifest_path


def prune_unreferenced(settings: Settings, components: List[Component]) -> None:
    """Remove component versions the current manifest no longer names."""
    keep = {(c.id, c.version) for c in components}
    if not settings.components_dir.is_dir():
        return
    for component_root in settings.components_dir.iterdir():
        if not component_root.is_dir():
            continue
        for version_dir in component_root.iterdir():
            if (component_root.name, version_dir.name) not in keep:
                logger.info("Pruning %s/%s", component_root.name, version_dir.name)
                shutil.rmtree(version_dir)
        if not any(component_root.iterdir()):
            component_root.rmdir()
