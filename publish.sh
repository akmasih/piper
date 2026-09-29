#!/bin/bash
# publish.sh
# Path: /root/piper/publish.sh
# Uploads the locally built speech packs to every web host in PUBLISH_TARGETS: components first, manifest last and atomically.
#
# Usage:
#   ./publish.sh           upload new component versions, then swap in the manifest
#   ./publish.sh --prune   the same, then delete component versions on the hosts
#                          that the new manifest no longer lists
#
# Order is the contract with the clients (web repo: deployment/packs/nginx.conf):
# component files live under content-versioned paths and are cached as
# immutable, and manifest.json is the only file that changes meaning. So every
# component a manifest names is on the host before that manifest is, and the
# manifest is uploaded under a temporary name and renamed into place, so a
# client never reads a manifest that names a file still being copied. Pruning
# runs only after the swap, so no live manifest ever points at a deleted file.
#
# Needs ssh access to each host and rsync on both ends (the rsync macOS ships
# is enough: only -r -l -t --exclude --delete are used).

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
    *)
        log_error "Unknown argument: $1 (usage: ./publish.sh [--prune])"
        exit 1
        ;;
esac

if [[ ! -f .env ]]; then
    log_error ".env not found in $SCRIPT_DIR"
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

for var in PACKS_HOST_DIR PUBLISH_TARGETS; do
    if [[ -z "${!var:-}" ]]; then
        log_error "$var is not set in .env"
        exit 1
    fi
done

for cmd in ssh rsync jq; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        log_error "Required command not found: $cmd"
        exit 1
    fi
done

MANIFEST="$PACKS_HOST_DIR/manifest.json"
COMPONENTS="$PACKS_HOST_DIR/components"
if [[ ! -f "$MANIFEST" ]]; then
    log_error "No manifest at $MANIFEST: run ./setup.sh first"
    exit 1
fi

# Every file the manifest names must exist locally with the size it states,
# or the upload would publish a manifest that promises a file nobody has.
missing=0
while IFS=$'\t' read -r path size; do
    local_file="$COMPONENTS/$path"
    if [[ ! -f "$local_file" ]]; then
        log_error "The manifest names a file that is not built: $local_file"
        missing=$((missing + 1))
        continue
    fi
    actual="$(wc -c <"$local_file" | tr -d ' ')"
    if [[ "$actual" != "$size" ]]; then
        log_error "$local_file is $actual bytes, the manifest says $size"
        missing=$((missing + 1))
    fi
done < <(jq -r '.components | to_entries[] | .key as $id | .value.version as $v
                | .value.files[] | "\($id)/\($v)/\(.path)\t\(.size)"' "$MANIFEST")
if [[ "$missing" -ne 0 ]]; then
    log_error "$missing file(s) do not match the manifest; nothing was uploaded"
    exit 1
fi

# --prune mirrors the local components directory onto the hosts, so it is only
# the manifest's own set when the local build was pruned too. Anything else
# would keep dead versions on the hosts while claiming to have pruned them.
if [[ "$PRUNE" == true ]]; then
    expected="$(jq -r '.components | to_entries[] | "\(.key)/\(.value.version)"' "$MANIFEST" | sort)"
    present="$(cd "$COMPONENTS" && find . -mindepth 2 -maxdepth 2 -type d ! -name '.*' | sed 's|^\./||' | sort)"
    if [[ "$expected" != "$present" ]]; then
        log_error "$COMPONENTS holds component versions the manifest does not list: run ./setup.sh --prune first"
        exit 1
    fi
fi

# Split and check every target before touching any host, so a typo in the
# last one does not leave the first ones published and the rest not.
targets=()
for target in $PUBLISH_TARGETS; do
    host="${target%%:*}"
    dir="${target#*:}"
    if [[ "$host" == "$target" || -z "$host" || "$dir" != /* ]]; then
        log_error "PUBLISH_TARGETS entry '$target' is not <user>@<host>:/absolute/directory"
        exit 1
    fi
    targets+=("$target")
done
if [[ "${#targets[@]}" -eq 0 ]]; then
    log_error "PUBLISH_TARGETS in .env names no host"
    exit 1
fi

publish_to() {
    local target="$1"
    local host="${target%%:*}"
    local dir="${target#*:}"

    log_info "[$host] Uploading components into $dir/components"
    ssh "$host" "mkdir -p '$dir/components'"
    rsync -r -l -t --exclude='.staging-*' "$COMPONENTS/" "$host:$dir/components/"

    log_info "[$host] Swapping in the manifest"
    rsync -t "$MANIFEST" "$host:$dir/.manifest.json.tmp"
    ssh "$host" "mv -f '$dir/.manifest.json.tmp' '$dir/manifest.json'"

    if [[ "$PRUNE" == true ]]; then
        log_info "[$host] Deleting component versions the manifest no longer lists"
        rsync -r -l -t --delete --exclude='.staging-*' "$COMPONENTS/" "$host:$dir/components/"
    fi

    log_ok "[$host] Published to $dir"
}

for target in "${targets[@]}"; do
    publish_to "$target"
done

echo
jq -r '"engine: \(.engine.name) \(.engine.version)   generated: \(.generated_at)"' "$MANIFEST"
log_ok "Published to ${#targets[@]} host(s)"
