#!/bin/bash
# setup.sh
# Path: /root/piper/setup.sh
# Builds the speech packs (voices, recognisers, browser engine) and their manifest.json into the local PACKS_HOST_DIR.
#
# Usage:
#   ./setup.sh           build or refresh every component and write the manifest
#   ./setup.sh --prune   the same, then delete component versions no longer listed
#
# Run it on a workstation — a Mac with Docker Desktop, or any Linux machine with
# Docker — never on the web host: the Whisper export takes several gigabytes of
# memory and every core for minutes. It needs only Docker and jq (on a Mac:
# `brew install jq`). The finished packs land in PACKS_HOST_DIR; ./publish.sh
# uploads them to the web hosts, whose `packs` service serves them at
# https://<domain>/packs/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

if [[ ! -f .env ]]; then
    log_error ".env not found in $SCRIPT_DIR"
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

for var in PACKS_HOST_DIR WORK_HOST_DIR LOG_LEVEL; do
    if [[ -z "${!var:-}" ]]; then
        log_error "$var is not set in .env"
        exit 1
    fi
done

for cmd in docker jq; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log_error "Required command not found: $cmd"
        exit 1
    fi
done
if ! docker compose version >/dev/null 2>&1; then
    log_error "'docker compose' (v2) is required"
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    log_error "The Docker daemon is not reachable (on a Mac: start Docker Desktop)"
    exit 1
fi

# The container runs as the invoking user (docker-compose.yml), so the
# directories it writes into are simply created by that user here.
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
export HOST_UID HOST_GID
mkdir -p "$PACKS_HOST_DIR" "$WORK_HOST_DIR"

log_info "Building the builder image"
docker compose build builder

log_info "Building packs into $PACKS_HOST_DIR"
docker compose run --rm builder "$@"

MANIFEST="$PACKS_HOST_DIR/manifest.json"
if [[ ! -f "$MANIFEST" ]]; then
    log_error "The build finished without writing $MANIFEST"
    exit 1
fi

log_ok "Manifest written: $MANIFEST"
log_info "Upload it to the web hosts with ./publish.sh"
echo
jq -r '"engine: \(.engine.name) \(.engine.version)   generated: \(.generated_at)"' "$MANIFEST"
echo
jq -r '.packs[] | "\(.id)\t\(.language)\t\(.components | join(", "))"' "$MANIFEST" | column -t -s $'\t'
echo
jq -r '.components | to_entries[] | "\(.key)\t\(.value.version)\t\(.value.size / 1000000 | floor) MB\t\(.value.license)"' "$MANIFEST" | column -t -s $'\t'
