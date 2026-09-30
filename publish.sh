#!/bin/bash
# publish.sh
# Path: /Users/eleheim/projects/piper/publish.sh
# Copies the packs built by ./setup.sh to the web host, verifies every file there, then publishes manifest.json.
#
# Usage:
#   ./publish.sh           upload the component versions the local manifest names,
#                          verify them on the web host, publish the manifest
#   ./publish.sh --prune   the same, then delete component versions on the web
#                          host that the published manifest no longer names
#
# Order is what keeps clients safe: every component file is uploaded and its
# SHA-256 checked on the web host before manifest.json is replaced, so the live
# manifest never names a file that is missing or damaged there. Component
# directories are content-versioned (see app/manifest.py), so uploading a new
# build never touches a file a client may be downloading.
#
# The web host accepts SSH only over Tailscale (web repo: setup_firewall.sh),
# so PUBLISH_HOST in .env is its Tailscale address.

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

PRUNE=false
case "${1:-}" in
    "") ;;
    --prune) PRUNE=true ;;
    *) log_error "Unknown argument: $1 (usage: ./publish.sh [--prune])"; exit 1 ;;
esac

if [[ ! -f .env ]]; then
    log_error ".env not found in $SCRIPT_DIR"
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

for var in PACKS_HOST_DIR PUBLISH_HOST PUBLISH_DIR PUBLISH_URL; do
    if [[ -z "${!var:-}" ]]; then
        log_error "$var is not set in .env"
        exit 1
    fi
done

for cmd in ssh rsync jq curl; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log_error "Required command not found: $cmd"
        exit 1
    fi
done

MANIFEST="$PACKS_HOST_DIR/manifest.json"
if [[ ! -f "$MANIFEST" ]]; then
    log_error "No manifest at $MANIFEST: run ./setup.sh first"
    exit 1
fi
GENERATED_AT="$(jq -r '.generated_at' "$MANIFEST")"

# One SSH connection for every step: a single login, however many uploads.
# Short path: macOS caps a socket path at 104 characters.
CONTROL_DIR="$(mktemp -d /tmp/publish.XXXXXX)"
SSH_OPTS=(-o ControlMaster=auto -o ControlPath="$CONTROL_DIR/%C" -o ControlPersist=120 -o ConnectTimeout=15)
close_connection() {
    ssh "${SSH_OPTS[@]}" -O exit "$PUBLISH_HOST" >/dev/null 2>&1 || true
    rm -rf "$CONTROL_DIR"
}
trap close_connection EXIT
remote() { ssh "${SSH_OPTS[@]}" "$PUBLISH_HOST" "$@"; }
RSYNC_RSH="ssh ${SSH_OPTS[*]}"
export RSYNC_RSH

log_info "Connecting to $PUBLISH_HOST"
remote "mkdir -p '$PUBLISH_DIR/components'"

# "<id> <version>" for every component the manifest names.
COMPONENTS="$(jq -r '.components | to_entries[] | "\(.key) \(.value.version)"' "$MANIFEST")"

while read -r id version; do
    source_dir="$PACKS_HOST_DIR/components/$id/$version"
    if [[ ! -d "$source_dir" ]]; then
        log_error "The manifest names $id/$version but $source_dir does not exist"
        exit 1
    fi
    log_info "Uploading $id/$version"
    remote "mkdir -p '$PUBLISH_DIR/components/$id'"
    rsync -a "$source_dir" "$PUBLISH_HOST:$PUBLISH_DIR/components/$id/"
done <<< "$COMPONENTS"

log_info "Verifying every file's SHA-256 on the web host"
jq -r '.components | to_entries[] | .key as $id | .value.version as $v
       | .value.files[] | "\(.sha256)  components/\($id)/\($v)/\(.path)"' "$MANIFEST" \
    | remote "cd '$PUBLISH_DIR' && sha256sum --quiet --check -"
log_ok "All component files on the web host match the manifest"

# rsync writes to a temporary name and renames it into place, so clients see
# either the old manifest or the new one, never a partial file.
log_info "Publishing manifest.json"
rsync -a "$MANIFEST" "$PUBLISH_HOST:$PUBLISH_DIR/manifest.json"
# The packs service's nginx runs unprivileged and reads the files as "other".
remote "chmod -R a+rX '$PUBLISH_DIR'"

if [[ "$PRUNE" == true ]]; then
    log_info "Removing component versions the manifest no longer names"
    {
        echo "set -euo pipefail"
        echo "cd '$PUBLISH_DIR/components'"
        echo "keep=\$(cat <<'KEEP'"
        while read -r id version; do echo "$id/$version"; done <<< "$COMPONENTS"
        echo "KEEP"
        echo ")"
        cat <<'PRUNE'
shopt -s nullglob
for dir in */*/; do
    dir="${dir%/}"
    if ! grep -qxF "$dir" <<< "$keep"; then
        echo "Pruning $dir"
        rm -rf -- "$dir"
    fi
done
for dir in */; do
    rmdir --ignore-fail-on-non-empty -- "${dir%/}"
done
PRUNE
    } | remote "bash -s"
fi

log_info "Checking $PUBLISH_URL"
SERVED_AT="$(curl -fsS "$PUBLISH_URL" | jq -r '.generated_at')"
if [[ "$SERVED_AT" != "$GENERATED_AT" ]]; then
    log_error "$PUBLISH_URL serves the manifest generated at $SERVED_AT, not $GENERATED_AT: is the web deployment's packs service running with PACKS_DIR=$PUBLISH_DIR?"
    exit 1
fi
log_ok "Published: $PUBLISH_URL (generated $GENERATED_AT)"
