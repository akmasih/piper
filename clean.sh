#!/bin/bash
# clean.sh
# Path: /root/piper/clean.sh
# Cleanup for the speech pack builder: its container and image, the build cache, and (on request) the local packs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_message() { echo -e "${1}${2}${NC}"; }

print_header() {
    echo
    print_message "$CYAN" "======================================"
    print_message "$CYAN" "$1"
    print_message "$CYAN" "======================================"
    echo
}

if [[ ! -f .env ]]; then
    print_message "$RED" ".env not found in $SCRIPT_DIR"
    exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a

# docker-compose.yml runs the builder as the invoking user and refuses to load
# without these, `down` included.
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
export HOST_UID HOST_GID

remove_builder() {
    print_header "Removing builder container and image"
    docker compose down --remove-orphans --rmi local
    print_message "$GREEN" "✓ Builder container and image removed"
}

clear_work_cache() {
    print_header "Clearing build cache: $WORK_HOST_DIR"
    print_message "$YELLOW" "The next build downloads every archive again and re-exports Whisper."
    rm -rf "${WORK_HOST_DIR:?}"/*
    print_message "$GREEN" "✓ Build cache cleared"
}

remove_packs() {
    print_header "Removing the local packs: $PACKS_HOST_DIR"
    print_message "$YELLOW" "The web hosts keep what ./publish.sh uploaded; the next ./publish.sh needs a new ./setup.sh first."
    echo -n "Type 'remove packs' to confirm: "
    read -r answer
    if [[ "$answer" != "remove packs" ]]; then
        print_message "$YELLOW" "Cancelled"
        return
    fi
    rm -rf "${PACKS_HOST_DIR:?}"/*
    print_message "$GREEN" "✓ Local packs removed"
}

show_menu() {
    print_header "Speech Pack Builder Cleanup"
    echo -e "  ${GREEN}1)${NC} Remove builder container and image"
    echo -e "  ${YELLOW}2)${NC} 1 + clear the build cache (downloads, Whisper export)"
    echo -e "  ${RED}3)${NC} 2 + remove the local packs ${RED}[rebuild before the next publish]${NC}"
    echo
    echo -e "  ${BLUE}0)${NC} Exit"
    echo
    echo -n "Enter your choice [0-3]: "
}

show_menu
read -r choice
case "$choice" in
    1) remove_builder ;;
    2) remove_builder; clear_work_cache ;;
    3) remove_builder; clear_work_cache; remove_packs ;;
    0) exit 0 ;;
    *) print_message "$RED" "Invalid choice: $choice"; exit 1 ;;
esac
