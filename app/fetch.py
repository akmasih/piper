# fetch.py
# Path: /Users/eleheim/projects/piper/app/fetch.py
# Downloads pinned upstream archives once into the work directory and extracts them.
#
# The work directory is a cache keyed by the archive's file name: a second build
# reuses what the first one downloaded, which matters for the multi-gigabyte
# Whisper checkpoint and the Parakeet archive. A download is written to a
# temporary name and renamed only when complete, so an interrupted build never
# leaves a truncated archive that the next build would trust.

import hashlib
import logging
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024


def sha256_of(path: Path) -> str:
    """Hex SHA-256 of a file, read in chunks so large models never sit in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, downloads_dir: Path) -> Path:
    """Download `url` into `downloads_dir` unless an earlier build already did."""
    downloads_dir.mkdir(parents=True, exist_ok=True)
    target = downloads_dir / url.rsplit("/", 1)[-1]
    if target.is_file():
        logger.info("Using cached download %s", target.name)
        return target

    partial = target.with_name(target.name + ".part")
    logger.info("Downloading %s", url)
    request = urllib.request.Request(url, headers={"User-Agent": "speech-pack-builder"})
    with urllib.request.urlopen(request) as response, partial.open("wb") as out:
        if response.status != 200:
            raise RuntimeError(f"GET {url} answered HTTP {response.status}")
        shutil.copyfileobj(response, out, _CHUNK)
    partial.rename(target)
    logger.info("Downloaded %s (%d bytes)", target.name, target.stat().st_size)
    return target


def extract(archive: Path, extract_dir: Path) -> Path:
    """
    Extract a .tar.bz2 / .tar.gz archive into its own directory under `extract_dir`.

    Returns the directory the archive was extracted into. Extraction is skipped
    when a completed extraction of the same archive exists (marked by a stamp
    file written last).
    """
    destination = extract_dir / archive.name.split(".tar.")[0]
    stamp = destination / ".extracted"
    if stamp.is_file():
        return destination

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    logger.info("Extracting %s", archive.name)
    with tarfile.open(archive) as tar:
        tar.extractall(destination, filter="data")
    stamp.write_text(archive.name, encoding="utf-8")
    return destination


def git_checkout(url: str, tag: str, checkout_dir: Path) -> Path:
    """Shallow-clone `url` at `tag` into `checkout_dir` (once)."""
    target = checkout_dir / f"{url.rsplit('/', 1)[-1]}-{tag}"
    if (target / ".git").is_dir():
        return target
    checkout_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Cloning %s at %s", url, tag)
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", tag, url, str(target)],
        check=True,
    )
    return target
