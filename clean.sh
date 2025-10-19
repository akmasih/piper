#!/bin/bash
# File: clean.sh - /root/piper/clean.sh
# Cleanup script for Piper TTS Service - removes Docker containers, images, and temporary files

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Configuration
PIPER_DIR="/root/piper"
MODELS_DIR="${PIPER_DIR}/models"

# Function to print colored messages
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to print section header
print_header() {
    echo
    print_message "${CYAN}" "======================================"
    print_message "${CYAN}" "$1"
    print_message "${CYAN}" "======================================"
    echo
}

# Function to check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_message "${RED}" "This script must be run as root"
        exit 1
    fi
}

# Function to show cleanup menu
show_menu() {
    clear
    print_header "Piper TTS Service Cleanup Menu"
    
    echo -e "${BLUE}Select cleanup level:${NC}"
    echo
    echo -e "  ${GREEN}1)${NC} Light Cleanup (Stop containers only)"
    echo -e "  ${YELLOW}2)${NC} Standard Cleanup (Stop containers + Remove containers)"
    echo -e "  ${YELLOW}3)${NC} Medium Cleanup (Standard + Remove images)"
    echo -e "  ${MAGENTA}4)${NC} Deep Cleanup (Medium + Remove volumes + Clean logs)"
    echo -e "  ${RED}5)${NC} Full Cleanup (Deep + Remove models) ${RED}[WARNING: Re-download required]${NC}"
    echo -e "  ${CYAN}6)${NC} Docker System Prune (Clean all unused Docker resources)"
    echo
    echo -e "  ${BLUE}0)${NC} Exit"
    echo
    echo -n "Enter your choice [0-6]: "
}

# Function to stop containers
stop_containers() {
    print_header "Stopping Piper TTS Containers"
    
    cd "${PIPER_DIR}" 2>/dev/null || {
        print_message "${YELLOW}" "Project directory not found, checking for running containers..."
    }
    
    # Try docker compose stop first
    if [ -f "${PIPER_DIR}/docker-compose.yml" ]; then
        print_message "${YELLOW}" "Stopping services via Docker Compose..."
        if docker compose down 2>/dev/null; then
            print_message "${GREEN}" "✓ Services stopped via Docker Compose"
        else
            print_message "${YELLOW}" "Docker Compose not running or already stopped"
        fi
    fi
    
    # Stop specific containers by name
    local containers=("piper-tts")
    
    for container in "${containers[@]}"; do
        if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
            print_message "${YELLOW}" "Stopping container: ${container}"
            docker stop "${container}" 2>/dev/null || true
            print_message "${GREEN}" "✓ Container ${container} stopped"
        fi
    done
    
    print_message "${GREEN}" "✓ All containers stopped"
}

# Function to remove containers
remove_containers() {
    print_header "Removing Piper TTS Containers"
    
    cd "${PIPER_DIR}" 2>/dev/null || true
    
    # Try docker compose down with remove
    if [ -f "${PIPER_DIR}/docker-compose.yml" ]; then
        print_message "${YELLOW}" "Removing services via Docker Compose..."
        docker compose down --remove-orphans 2>/dev/null || true
        print_message "${GREEN}" "✓ Services removed via Docker Compose"
    fi
    
    # Remove specific containers by name
    local containers=("piper-tts")
    
    for container in "${containers[@]}"; do
        if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
            print_message "${YELLOW}" "Removing container: ${container}"
            docker rm -f "${container}" 2>/dev/null || true
            print_message "${GREEN}" "✓ Container ${container} removed"
        fi
    done
    
    print_message "${GREEN}" "✓ All containers removed"
}

# Function to remove Docker images
remove_images() {
    print_header "Removing Piper TTS Docker Images"
    
    local images=("piper-tts:latest" "piper-tts")
    local removed=0
    
    for image in "${images[@]}"; do
        if docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^${image}"; then
            print_message "${YELLOW}" "Removing image: ${image}"
            docker rmi -f "${image}" 2>/dev/null || true
            ((removed++))
            print_message "${GREEN}" "✓ Image ${image} removed"
        fi
    done
    
    # Remove dangling images related to piper
    print_message "${YELLOW}" "Removing dangling images..."
    docker images -f "dangling=true" -q | xargs -r docker rmi 2>/dev/null || true
    
    if [ $removed -eq 0 ]; then
        print_message "${YELLOW}" "No Piper TTS images found"
    else
        print_message "${GREEN}" "✓ ${removed} image(s) removed"
    fi
}

# Function to remove volumes
remove_volumes() {
    print_header "Removing Docker Volumes"
    
    cd "${PIPER_DIR}" 2>/dev/null || true
    
    # Remove volumes via docker compose
    if [ -f "${PIPER_DIR}/docker-compose.yml" ]; then
        print_message "${YELLOW}" "Removing volumes via Docker Compose..."
        docker compose down -v 2>/dev/null || true
    fi
    
    # List and remove piper-related volumes
    local volumes=$(docker volume ls --format '{{.Name}}' | grep -i piper || true)
    
    if [ -n "$volumes" ]; then
        print_message "${YELLOW}" "Found volumes to remove:"
        echo "$volumes"
        for volume in $volumes; do
            print_message "${YELLOW}" "Removing volume: ${volume}"
            docker volume rm -f "${volume}" 2>/dev/null || true
            print_message "${GREEN}" "✓ Volume ${volume} removed"
        done
    else
        print_message "${YELLOW}" "No Piper-related volumes found"
    fi
    
    print_message "${GREEN}" "✓ Volumes cleanup complete"
}

# Function to remove networks
remove_networks() {
    print_header "Removing Docker Networks"
    
    cd "${PIPER_DIR}" 2>/dev/null || true
    
    local networks=("piper-network" "piper_piper-network")
    
    for network in "${networks[@]}"; do
        if docker network ls --format '{{.Name}}' | grep -q "^${network}$"; then
            print_message "${YELLOW}" "Removing network: ${network}"
            docker network rm "${network}" 2>/dev/null || true
            print_message "${GREEN}" "✓ Network ${network} removed"
        fi
    done
    
    print_message "${GREEN}" "✓ Networks cleanup complete"
}

# Function to clean temporary files and logs
clean_temp_files() {
    print_header "Cleaning Temporary Files and Logs"
    
    # Clean temp directory
    if [ -d "/tmp/piper" ]; then
        print_message "${YELLOW}" "Cleaning /tmp/piper directory..."
        rm -rf /tmp/piper/* 2>/dev/null || true
        print_message "${GREEN}" "✓ Temp directory cleaned"
    fi
    
    # Clean log files
    if [ -d "/var/log/piper" ]; then
        print_message "${YELLOW}" "Cleaning log files..."
        rm -rf /var/log/piper/*.log 2>/dev/null || true
        print_message "${GREEN}" "✓ Log files cleaned"
    fi
    
    # Clean Docker logs
    if [ -f "/tmp/docker_build.log" ]; then
        print_message "${YELLOW}" "Removing Docker build log..."
        rm -f /tmp/docker_build.log
        print_message "${GREEN}" "✓ Build log removed"
    fi
    
    if [ -f "/tmp/docker_compose.log" ]; then
        print_message "${YELLOW}" "Removing Docker Compose log..."
        rm -f /tmp/docker_compose.log
        print_message "${GREEN}" "✓ Compose log removed"
    fi
    
    # Clean application temp files in project directory
    if [ -d "${PIPER_DIR}/temp" ]; then
        print_message "${YELLOW}" "Cleaning application temp files..."
        rm -rf "${PIPER_DIR}/temp"/* 2>/dev/null || true
        print_message "${GREEN}" "✓ Application temp files cleaned"
    fi
    
    print_message "${GREEN}" "✓ Temporary files and logs cleaned"
}

# Function to remove models
remove_models() {
    print_header "Removing Voice Models"
    
    print_message "${RED}" "⚠️  WARNING: This will remove all downloaded voice models!"
    print_message "${RED}" "⚠️  You will need to re-download them (may take significant time)"
    print_message "${YELLOW}" ""
    print_message "${YELLOW}" "Models directory: ${MODELS_DIR}"
    
    if [ -d "${MODELS_DIR}" ]; then
        local model_count=$(find "${MODELS_DIR}" -name "*.onnx" 2>/dev/null | wc -l)
        print_message "${YELLOW}" "Found ${model_count} model file(s)"
        echo
        echo -n "Are you absolutely sure? Type 'yes' to confirm: "
        read -r confirmation
        
        if [ "$confirmation" = "yes" ]; then
            print_message "${YELLOW}" "Removing models directory..."
            rm -rf "${MODELS_DIR}"/* 2>/dev/null || true
            
            # Recreate directory structure
            for lang in en de fr es it fa; do
                mkdir -p "${MODELS_DIR}/${lang}"
            done
            
            print_message "${GREEN}" "✓ Models removed and directory structure recreated"
        else
            print_message "${YELLOW}" "Model removal cancelled"
        fi
    else
        print_message "${YELLOW}" "Models directory not found"
    fi
}

# Function to perform Docker system prune
docker_system_prune() {
    print_header "Docker System Prune"
    
    print_message "${YELLOW}" "This will remove:"
    echo "  - All stopped containers"
    echo "  - All networks not used by at least one container"
    echo "  - All dangling images"
    echo "  - All dangling build cache"
    echo
    print_message "${RED}" "⚠️  This affects ALL Docker resources, not just Piper!"
    echo
    echo -n "Continue? [y/N]: "
    read -r response
    
    if [[ "$response" =~ ^[Yy]$ ]]; then
        print_message "${YELLOW}" "Running Docker system prune..."
        docker system prune -f
        print_message "${GREEN}" "✓ Docker system prune completed"
        
        echo
        echo -n "Also remove all unused images? [y/N]: "
        read -r response
        
        if [[ "$response" =~ ^[Yy]$ ]]; then
            print_message "${YELLOW}" "Removing all unused images..."
            docker image prune -a -f
            print_message "${GREEN}" "✓ All unused images removed"
        fi
    else
        print_message "${YELLOW}" "Docker system prune cancelled"
    fi
}

# Function to display cleanup summary
show_summary() {
    print_header "Cleanup Summary"
    
    echo -e "${BLUE}Current Status:${NC}"
    echo
    
    # Check containers
    local container_count=$(docker ps -a --format '{{.Names}}' | grep -c "piper" || echo "0")
    echo -e "  Piper Containers: ${container_count}"
    
    # Check images
    local image_count=$(docker images --format '{{.Repository}}' | grep -c "piper" || echo "0")
    echo -e "  Piper Images: ${image_count}"
    
    # Check volumes
    local volume_count=$(docker volume ls --format '{{.Name}}' | grep -c "piper" || echo "0")
    echo -e "  Piper Volumes: ${volume_count}"
    
    # Check models
    if [ -d "${MODELS_DIR}" ]; then
        local model_count=$(find "${MODELS_DIR}" -name "*.onnx" 2>/dev/null | wc -l)
        echo -e "  Voice Models: ${model_count}"
    else
        echo -e "  Voice Models: 0"
    fi
    
    # Check temp files
    if [ -d "/tmp/piper" ]; then
        local temp_size=$(du -sh /tmp/piper 2>/dev/null | cut -f1)
        echo -e "  Temp Files: ${temp_size}"
    else
        echo -e "  Temp Files: 0B"
    fi
    
    echo
}

# Level 1: Light Cleanup
light_cleanup() {
    print_header "Light Cleanup"
    print_message "${BLUE}" "Stopping containers only..."
    echo
    
    stop_containers
    
    print_message "${GREEN}" "✓ Light cleanup completed!"
    echo
    print_message "${YELLOW}" "To start services again: cd ${PIPER_DIR} && docker compose up -d"
}

# Level 2: Standard Cleanup
standard_cleanup() {
    print_header "Standard Cleanup"
    print_message "${BLUE}" "Stopping and removing containers..."
    echo
    
    stop_containers
    remove_containers
    remove_networks
    
    print_message "${GREEN}" "✓ Standard cleanup completed!"
    echo
    print_message "${YELLOW}" "To rebuild and start: cd ${PIPER_DIR} && docker compose up -d --build"
}

# Level 3: Medium Cleanup
medium_cleanup() {
    print_header "Medium Cleanup"
    print_message "${BLUE}" "Removing containers, images, and networks..."
    echo
    
    stop_containers
    remove_containers
    remove_images
    remove_networks
    
    print_message "${GREEN}" "✓ Medium cleanup completed!"
    echo
    print_message "${YELLOW}" "To rebuild and start: cd ${PIPER_DIR} && docker compose up -d --build"
}

# Level 4: Deep Cleanup
deep_cleanup() {
    print_header "Deep Cleanup"
    print_message "${BLUE}" "Full cleanup except models..."
    echo
    
    stop_containers
    remove_containers
    remove_images
    remove_volumes
    remove_networks
    clean_temp_files
    
    print_message "${GREEN}" "✓ Deep cleanup completed!"
    echo
    print_message "${YELLOW}" "To rebuild and start: cd ${PIPER_DIR} && docker compose up -d --build"
}

# Level 5: Full Cleanup
full_cleanup() {
    print_header "Full Cleanup"
    print_message "${RED}" "⚠️  COMPLETE CLEANUP INCLUDING MODELS ⚠️"
    echo
    
    echo -n "This will remove EVERYTHING including models. Continue? [y/N]: "
    read -r response
    
    if [[ "$response" =~ ^[Yy]$ ]]; then
        stop_containers
        remove_containers
        remove_images
        remove_volumes
        remove_networks
        clean_temp_files
        remove_models
        
        print_message "${GREEN}" "✓ Full cleanup completed!"
        echo
        print_message "${YELLOW}" "To rebuild and start: cd ${PIPER_DIR} && bash setup.sh"
    else
        print_message "${YELLOW}" "Full cleanup cancelled"
    fi
}

# Main function
main() {
    check_root
    
    while true; do
        show_menu
        read -r choice
        
        case $choice in
            1)
                light_cleanup
                ;;
            2)
                standard_cleanup
                ;;
            3)
                medium_cleanup
                ;;
            4)
                deep_cleanup
                ;;
            5)
                full_cleanup
                ;;
            6)
                docker_system_prune
                ;;
            0)
                print_message "${GREEN}" "Exiting cleanup script"
                exit 0
                ;;
            *)
                print_message "${RED}" "Invalid option. Please try again."
                ;;
        esac
        
        echo
        show_summary
        echo
        print_message "${CYAN}" "Press Enter to continue..."
        read -r
    done
}

# Run main function
main