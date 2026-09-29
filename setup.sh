#!/bin/bash
# setup.sh
# Path: /root/piper/setup.sh
# Builds the speech packs (voices, recognisers, browser engine) and publishes manifest.json into PACKS_HOST_DIR.
#
# Usage:
#   ./setup.sh           build or refresh every component and write the manifest
#   ./setup.sh --prune   the same, then delete component versions no longer listed
#
# PACKS_HOST_DIR is what the web deployment's `packs` service serves at
# https://<domain>/packs/. Run it on the web host to build in place, or on any
# other machine (a Mac with Docker Desktop included) and copy PACKS_HOST_DIR to
# the web host afterwards: components/ first, manifest.json last.

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

# The builder runs as the user running this script (docker-compose.yml).
BUILDER_UID="$(id -u)"
BUILDER_GID="$(id -g)"
export BUILDER_UID BUILDER_GID
mkdir -p "$PACKS_HOST_DIR" "$WORK_HOST_DIR/home"

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
echo
jq -r '"engine: \(.engine.name) \(.engine.version)   generated: \(.generated_at)"' "$MANIFEST"
echo
jq -r '.packs[] | "\(.id)\t\(.language)\t\(.components | join(", "))"' "$MANIFEST" | column -t -s $'\t'
echo
jq -r '.components | to_entries[] | "\(.key)\t\(.value.version)\t\(.value.size / 1000000 | floor) MB\t\(.value.license)"' "$MANIFEST" | column -t -s $'\t'
