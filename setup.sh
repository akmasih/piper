#!/bin/bash
# File: setup.sh - /root/piper/setup.sh
# Comprehensive installation script for Piper TTS Service in Lingudesk system

set -e

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PIPER_DIR="/root/piper"
MODELS_DIR="${PIPER_DIR}/models"
APP_DIR="${PIPER_DIR}/app"
HUGGINGFACE_BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"

# Model definitions with correct path structure
get_model_path() {
    local lang=$1
    case $lang in
        en) echo "en/en_US/lessac/high/en_US-lessac-high" ;;
        de) echo "de/de_DE/thorsten/high/de_DE-thorsten-high" ;;
        fr) echo "fr/fr_FR/siwis/medium/fr_FR-siwis-medium" ;;
        es) echo "es/es_ES/carlfm/x_low/es_ES-carlfm-x_low" ;;
        it) echo "it/it_IT/riccardo/x_low/it_IT-riccardo-x_low" ;;
        fa) echo "fa/fa_IR/gyro/medium/fa_IR-gyro-medium" ;;
        *) echo "" ;;
    esac
}

# Function to print colored messages
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to print section header
print_header() {
    echo
    print_message "${BLUE}" "======================================"
    print_message "${BLUE}" "$1"
    print_message "${BLUE}" "======================================"
    echo
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check and start Docker daemon
check_and_start_docker() {
    print_header "Checking Docker Service"
    
    if ! command_exists docker; then
        print_message "${RED}" "Docker is not installed!"
        print_message "${YELLOW}" "Installing Docker..."
        
        # Install Docker
        curl -fsSL https://get.docker.com -o get-docker.sh
        sh get-docker.sh
        rm get-docker.sh
        
        print_message "${GREEN}" "✓ Docker installed"
    fi
    
    # Check if Docker daemon is running
    if ! docker info >/dev/null 2>&1; then
        print_message "${YELLOW}" "Docker daemon is not running. Starting Docker..."
        
        # Start Docker service
        systemctl start docker
        systemctl enable docker
        
        # Wait for Docker to start
        local max_wait=30
        local waited=0
        while ! docker info >/dev/null 2>&1; do
            if [ $waited -ge $max_wait ]; then
                print_message "${RED}" "Failed to start Docker daemon"
                exit 1
            fi
            sleep 1
            ((waited++))
        done
        
        print_message "${GREEN}" "✓ Docker daemon started"
    else
        print_message "${GREEN}" "✓ Docker daemon is running"
    fi
    
    # Check Docker Compose
    if ! docker compose version >/dev/null 2>&1; then
        print_message "${RED}" "Docker Compose v2 is not available!"
        print_message "${YELLOW}" "Please ensure Docker Compose plugin is installed"
        exit 1
    fi
    
    print_message "${GREEN}" "✓ Docker Compose v2 is available"
}

# Function to check system requirements
check_requirements() {
    print_header "Checking System Requirements"
    
    local missing_packages=()
    
    # Check for required commands
    if ! command_exists curl; then
        missing_packages+=("curl")
    fi
    
    if ! command_exists wget; then
        missing_packages+=("wget")
    fi
    
    if ! command_exists python3; then
        missing_packages+=("python3")
    fi
    
    if ! command_exists pip3; then
        missing_packages+=("python3-pip")
    fi
    
    if [ ${#missing_packages[@]} -gt 0 ]; then
        print_message "${YELLOW}" "Installing missing packages: ${missing_packages[*]}"
        apt-get update
        apt-get install -y "${missing_packages[@]}"
    fi
    
    print_message "${GREEN}" "✓ All system requirements met"
}

# Function to check if Tailscale is installed and configured
check_tailscale() {
    print_header "Checking Tailscale Configuration"
    
    if ! command_exists tailscale; then
        print_message "${RED}" "Tailscale is not installed!"
        print_message "${YELLOW}" "Installing Tailscale..."
        curl -fsSL https://tailscale.com/install.sh | sh
    fi
    
    if ! tailscale status >/dev/null 2>&1; then
        print_message "${YELLOW}" "Tailscale is not connected"
        print_message "${YELLOW}" "Please authenticate Tailscale with: sudo tailscale up"
        print_message "${YELLOW}" "Press Enter to continue after Tailscale is authenticated..."
        read -r
    fi
    
    local current_ip
    current_ip=$(tailscale ip -4 2>/dev/null | head -n 1)
    local expected_ip="100.109.226.109"
    
    if [ "$current_ip" != "$expected_ip" ]; then
        print_message "${YELLOW}" "Warning: Current Tailscale IP ($current_ip) differs from expected IP ($expected_ip)"
        print_message "${YELLOW}" "Please verify your Tailscale configuration"
    else
        print_message "${GREEN}" "✓ Tailscale configured correctly with IP: $current_ip"
    fi
}

# Function to create directory structure
create_directory_structure() {
    print_header "Creating Directory Structure"
    
    mkdir -p "${PIPER_DIR}"
    mkdir -p "${MODELS_DIR}"
    mkdir -p "${APP_DIR}"
    mkdir -p "/tmp/piper"
    chmod 777 "/tmp/piper"
    
    # Create model subdirectories
    for lang in en de fr es it fa; do
        mkdir -p "${MODELS_DIR}/${lang}"
    done
    
    print_message "${GREEN}" "✓ Directory structure created"
}

# Function to download a voice model
download_model() {
    local lang=$1
    local full_path=$(get_model_path "$lang")
    
    # Verify we have a valid path
    if [ -z "$full_path" ]; then
        print_message "${RED}" "  ✗ Invalid language: ${lang}"
        return 1
    fi
    
    # Extract model name (last part of path)
    local model_name=$(basename "${full_path}")
    
    print_message "${YELLOW}" "Downloading model for ${lang}: ${model_name}"
    
    local model_url="${HUGGINGFACE_BASE_URL}/${full_path}.onnx"
    local config_url="${HUGGINGFACE_BASE_URL}/${full_path}.onnx.json"
    
    local model_file="${MODELS_DIR}/${lang}/${model_name}.onnx"
    local config_file="${MODELS_DIR}/${lang}/${model_name}.onnx.json"
    
    # Check if model already exists and is valid
    if [ -f "${model_file}" ] && [ -f "${config_file}" ]; then
        local model_size="0"
        if [ -f "${model_file}" ]; then
            model_size=$(stat -c%s "${model_file}" 2>/dev/null) || model_size="0"
        fi
        
        if [ "$model_size" -gt 1000000 ]; then
            print_message "${GREEN}" "  ✓ Model already exists: ${model_name}"
            return 0
        else
            print_message "${YELLOW}" "  ! Model file corrupted or incomplete, re-downloading..."
            rm -f "${model_file}" "${config_file}"
        fi
    fi
    
    # Download model file with retry
    local retry=0
    local max_retries=3
    while [ $retry -lt $max_retries ]; do
        if wget --timeout=180 --tries=1 -q --show-progress "${model_url}?download=true" -O "${model_file}.tmp" 2>&1; then
            # Verify downloaded file
            local downloaded_size="0"
            if [ -f "${model_file}.tmp" ]; then
                downloaded_size=$(stat -c%s "${model_file}.tmp" 2>/dev/null) || downloaded_size="0"
            fi
            
            if [ "$downloaded_size" -gt 1000000 ]; then
                mv "${model_file}.tmp" "${model_file}"
                local size_human=$(numfmt --to=iec-i --suffix=B "$downloaded_size" 2>/dev/null) || size_human="${downloaded_size} bytes"
                print_message "${GREEN}" "  ✓ Downloaded model file ($size_human)"
                break
            else
                print_message "${YELLOW}" "  ! Downloaded file too small, retrying..."
                rm -f "${model_file}.tmp"
                ((retry++))
            fi
        else
            ((retry++))
            rm -f "${model_file}.tmp"
            if [ $retry -lt $max_retries ]; then
                print_message "${YELLOW}" "  ! Download failed, retrying ($retry/$max_retries)..."
                sleep 3
            else
                print_message "${RED}" "  ✗ Failed to download model file after $max_retries attempts"
                return 1
            fi
        fi
    done
    
    # Download config file with retry
    retry=0
    while [ $retry -lt $max_retries ]; do
        if wget --timeout=60 --tries=1 -q --show-progress "${config_url}?download=true" -O "${config_file}.tmp" 2>&1; then
            # Verify it's a valid JSON (basic check)
            if [ -f "${config_file}.tmp" ] && grep -q "{" "${config_file}.tmp" 2>/dev/null; then
                mv "${config_file}.tmp" "${config_file}"
                print_message "${GREEN}" "  ✓ Downloaded config file"
                break
            else
                print_message "${YELLOW}" "  ! Invalid config file, retrying..."
                rm -f "${config_file}.tmp"
                ((retry++))
            fi
        else
            ((retry++))
            rm -f "${config_file}.tmp"
            if [ $retry -lt $max_retries ]; then
                print_message "${YELLOW}" "  ! Download failed, retrying ($retry/$max_retries)..."
                sleep 2
            else
                print_message "${RED}" "  ✗ Failed to download config file after $max_retries attempts"
                rm -f "${model_file}"
                return 1
            fi
        fi
    done
    
    print_message "${GREEN}" "  ✓ Model ${model_name} downloaded successfully"
    return 0
}

# Function to download all models
download_all_models() {
    print_header "Downloading Voice Models from Hugging Face"
    
    # Temporarily disable exit on error for download section
    set +e
    
    local failed_models=()
    local success_count=0
    local total_count=0
    
    # Download in specific order
    local lang_order=("en" "de" "fr" "es" "it" "fa")
    
    print_message "${BLUE}" "Starting model download process..."
    
    for lang in "${lang_order[@]}"; do
        ((total_count++))
        print_message "${BLUE}" "Processing language: ${lang}"
        
        if download_model "${lang}"; then
            ((success_count++))
        else
            failed_models+=("${lang}")
        fi
        echo
    done
    
    # Re-enable exit on error
    set -e
    
    print_message "${GREEN}" "Successfully downloaded: ${success_count}/${total_count} models"
    
    if [ ${#failed_models[@]} -gt 0 ]; then
        print_message "${YELLOW}" "Failed models: ${failed_models[*]}"
        print_message "${YELLOW}" "Note: The service will attempt to download missing models on first use"
        print_message "${YELLOW}" "You can manually download from: ${HUGGINGFACE_BASE_URL}"
    fi
}

# Function to install system dependencies
install_system_dependencies() {
    print_header "Installing System Dependencies"
    
    print_message "${YELLOW}" "Updating package lists..."
    apt-get update -qq
    
    print_message "${YELLOW}" "Installing required packages..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        curl \
        wget \
        ffmpeg \
        libsndfile1 \
        espeak-ng \
        python3 \
        python3-pip \
        python3-venv \
        build-essential \
        > /dev/null 2>&1
    
    print_message "${GREEN}" "✓ System dependencies installed"
}

# Function to install Node Exporter for monitoring
install_node_exporter() {
    print_header "Installing Node Exporter for Monitoring"
    
    if systemctl is-active --quiet node_exporter 2>/dev/null; then
        print_message "${GREEN}" "✓ Node Exporter is already running"
        return 0
    fi
    
    local node_exporter_version="1.8.2"
    local node_exporter_url="https://github.com/prometheus/node_exporter/releases/download/v${node_exporter_version}/node_exporter-${node_exporter_version}.linux-amd64.tar.gz"
    
    print_message "${YELLOW}" "Downloading Node Exporter ${node_exporter_version}..."
    
    cd /tmp
    wget -q --show-progress "${node_exporter_url}"
    tar xzf "node_exporter-${node_exporter_version}.linux-amd64.tar.gz"
    cp "node_exporter-${node_exporter_version}.linux-amd64/node_exporter" /usr/local/bin/
    rm -rf "node_exporter-${node_exporter_version}.linux-amd64"*
    
    # Create systemd service
    cat > /etc/systemd/system/node_exporter.service <<'EOF'
[Unit]
Description=Node Exporter
Wants=network-online.target
After=network-online.target

[Service]
User=nobody
Group=nogroup
Type=simple
ExecStart=/usr/local/bin/node_exporter --web.listen-address=:9100

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    systemctl enable node_exporter > /dev/null 2>&1
    systemctl start node_exporter
    
    print_message "${GREEN}" "✓ Node Exporter installed and started on port 9100"
}

# Function to install Fluent Bit for log forwarding
install_fluent_bit() {
    print_header "Installing Fluent Bit for Log Forwarding"
    
    if command_exists fluent-bit; then
        print_message "${GREEN}" "✓ Fluent Bit is already installed"
        return 0
    fi
    
    print_message "${YELLOW}" "Installing Fluent Bit..."
    
    curl -sSL https://raw.githubusercontent.com/fluent/fluent-bit/master/install.sh | sh > /dev/null 2>&1
    
    # Create Fluent Bit configuration for Piper logs
    mkdir -p /etc/fluent-bit
    cat > /etc/fluent-bit/fluent-bit.conf <<'EOF'
[SERVICE]
    Flush        5
    Daemon       Off
    Log_Level    info

[INPUT]
    Name              tail
    Path              /var/log/piper/*.log
    Tag               piper.*
    Parser            json
    Refresh_Interval  5

[INPUT]
    Name              systemd
    Tag               systemd.*
    Systemd_Filter    _SYSTEMD_UNIT=docker.service

[OUTPUT]
    Name              forward
    Match             *
    Host              100.122.6.31
    Port              3100
EOF
    
    # Create systemd service for Fluent Bit
    cat > /etc/systemd/system/fluent-bit.service <<'EOF'
[Unit]
Description=Fluent Bit
Documentation=https://docs.fluentbit.io/
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/fluent-bit -c /etc/fluent-bit/fluent-bit.conf
Restart=always

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    systemctl enable fluent-bit > /dev/null 2>&1
    systemctl start fluent-bit
    
    print_message "${GREEN}" "✓ Fluent Bit installed and configured"
}

# Function to install cAdvisor for container metrics
install_cadvisor() {
    print_header "Installing cAdvisor for Container Metrics"
    
    # Ensure Docker daemon is running
    if ! docker info >/dev/null 2>&1; then
        print_message "${RED}" "Docker daemon is not running. Cannot install cAdvisor."
        print_message "${YELLOW}" "Skipping cAdvisor installation."
        return 1
    fi
    
    # Check if cAdvisor is already running
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q '^cadvisor$'; then
        print_message "${YELLOW}" "cAdvisor container already exists"
        
        # Start if stopped
        if ! docker ps --format '{{.Names}}' | grep -q '^cadvisor$'; then
            print_message "${YELLOW}" "Starting existing cAdvisor container..."
            docker start cadvisor > /dev/null 2>&1
        fi
        
        print_message "${GREEN}" "✓ cAdvisor is running"
        return 0
    fi
    
    print_message "${YELLOW}" "Starting cAdvisor container..."
    
    docker run -d \
        --name=cadvisor \
        --restart=unless-stopped \
        --volume=/:/rootfs:ro \
        --volume=/var/run:/var/run:ro \
        --volume=/sys:/sys:ro \
        --volume=/var/lib/docker/:/var/lib/docker:ro \
        --volume=/dev/disk/:/dev/disk:ro \
        --publish=8080:8080 \
        --privileged \
        --device=/dev/kmsg \
        gcr.io/cadvisor/cadvisor:latest \
        > /dev/null 2>&1
    
    if [ $? -eq 0 ]; then
        print_message "${GREEN}" "✓ cAdvisor installed and running on port 8080"
    else
        print_message "${YELLOW}" "Warning: Failed to start cAdvisor (non-critical)"
    fi
}

# Function to verify .env file
verify_env_file() {
    print_header "Verifying Configuration Files"
    
    if [ ! -f "${PIPER_DIR}/.env" ]; then
        print_message "${RED}" ".env file not found at ${PIPER_DIR}/.env"
        print_message "${YELLOW}" "Please ensure .env file is present before running this script"
        exit 1
    fi
    
    print_message "${GREEN}" "✓ .env file found"
    
    # Check required environment variables
    local required_vars=(
        "SERVER_NAME"
        "TAILSCALE_IP"
        "PORT"
        "BACKEND_IP"
        "MODEL_EN"
        "MODEL_DE"
        "MODEL_FR"
        "MODEL_ES"
        "MODEL_IT"
        "MODEL_FA"
    )
    
    local missing_vars=()
    
    for var in "${required_vars[@]}"; do
        if ! grep -q "^${var}=" "${PIPER_DIR}/.env"; then
            missing_vars+=("${var}")
        fi
    done
    
    if [ ${#missing_vars[@]} -gt 0 ]; then
        print_message "${RED}" "Missing required environment variables: ${missing_vars[*]}"
        exit 1
    fi
    
    print_message "${GREEN}" "✓ All required environment variables present"
}

# Function to build Docker image
build_docker_image() {
    print_header "Building Docker Image"
    
    if [ ! -f "${PIPER_DIR}/Dockerfile" ]; then
        print_message "${RED}" "Dockerfile not found at ${PIPER_DIR}/Dockerfile"
        exit 1
    fi
    
    cd "${PIPER_DIR}"
    
    print_message "${YELLOW}" "Building Piper TTS Docker image (this may take several minutes)..."
    
    if docker build -t piper-tts:latest . > /tmp/docker_build.log 2>&1; then
        print_message "${GREEN}" "✓ Docker image built successfully"
    else
        print_message "${RED}" "✗ Failed to build Docker image"
        print_message "${RED}" "Check log: /tmp/docker_build.log"
        tail -n 20 /tmp/docker_build.log
        exit 1
    fi
}

# Function to create log directory
create_log_directory() {
    print_header "Creating Log Directory"
    
    mkdir -p /var/log/piper
    chmod 755 /var/log/piper
    
    print_message "${GREEN}" "✓ Log directory created"
}

# Function to start services
start_services() {
    print_header "Starting Piper TTS Service"
    
    cd "${PIPER_DIR}"
    
    print_message "${YELLOW}" "Starting services with Docker Compose..."
    
    if docker compose up -d > /tmp/docker_compose.log 2>&1; then
        print_message "${GREEN}" "✓ Piper TTS service started successfully"
    else
        print_message "${RED}" "✗ Failed to start services"
        print_message "${RED}" "Check log: /tmp/docker_compose.log"
        tail -n 20 /tmp/docker_compose.log
        exit 1
    fi
    
    # Wait for service to be healthy
    print_message "${YELLOW}" "Waiting for service to be healthy (this may take 1-2 minutes)..."
    local max_attempts=60
    local attempt=0
    
    while [ $attempt -lt $max_attempts ]; do
        if docker compose ps 2>/dev/null | grep -q "healthy\|running"; then
            sleep 3
            if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
                print_message "${GREEN}" "✓ Service is healthy and ready"
                return 0
            fi
        fi
        sleep 2
        ((attempt++))
        
        # Show progress every 10 attempts
        if [ $((attempt % 10)) -eq 0 ]; then
            print_message "${YELLOW}" "  Still waiting... ($attempt/$max_attempts)"
        fi
    done
    
    print_message "${YELLOW}" "Warning: Service health check timeout"
    print_message "${YELLOW}" "The service may still be starting. Check logs with: docker compose logs -f"
}

# Function to test service
test_service() {
    print_header "Testing Piper TTS Service"
    
    sleep 3
    
    print_message "${YELLOW}" "Testing health endpoint..."
    
    local health_url="http://localhost:8000/health"
    local response
    
    if response=$(curl -s "${health_url}" 2>/dev/null); then
        print_message "${GREEN}" "✓ Health check passed"
        echo "${response}" | python3 -m json.tool 2>/dev/null || echo "${response}"
    else
        print_message "${YELLOW}" "Warning: Health check failed"
        print_message "${YELLOW}" "Service may still be initializing. Check: docker compose logs piper-tts"
    fi
}

# Function to display service information
display_service_info() {
    print_header "Service Information"
    
    cat <<EOF
${GREEN}Piper TTS Service Installation Complete!${NC}

${BLUE}Service Details:${NC}
  Server Name:      piper
  Tailscale IP:     100.109.226.109
  Internal Port:    8000
  Backend IP:       100.116.174.15

${BLUE}Monitoring:${NC}
  Node Exporter:    http://localhost:9100/metrics
  cAdvisor:         http://localhost:8080
  Fluent Bit:       Forwarding to 100.122.6.31:3100

${BLUE}Endpoints:${NC}
  Health Check:     http://100.109.226.109:8000/health
  Voice List:       http://100.109.226.109:8000/tts/voices
  Generate Speech:  http://100.109.226.109:8000/tts/generate

${BLUE}Useful Commands:${NC}
  View logs:        cd ${PIPER_DIR} && docker compose logs -f
  Restart service:  cd ${PIPER_DIR} && docker compose restart
  Stop service:     cd ${PIPER_DIR} && docker compose down
  Check status:     cd ${PIPER_DIR} && docker compose ps
  View container:   docker ps

${BLUE}Model Directories:${NC}
  Models location:  ${MODELS_DIR}
  Temp directory:   /tmp/piper

${BLUE}Configuration:${NC}
  Environment:      ${PIPER_DIR}/.env
  Docker Compose:   ${PIPER_DIR}/docker-compose.yml

${YELLOW}Note:${NC} The service is only accessible from the backend server (100.116.174.15)
and through Tailscale network. External access is restricted for security.

${BLUE}Troubleshooting:${NC}
  If service fails to start:
    1. Check Docker logs: docker compose logs piper-tts
    2. Verify Tailscale: tailscale status
    3. Check port: netstat -tulpn | grep 8000
    4. Restart Docker: systemctl restart docker
    5. View build log: cat /tmp/docker_build.log

EOF
}

# Function to setup monitoring firewall
setup_monitoring_firewall() {
    print_header "Configuring Firewall for Monitoring"
    
    if command_exists ufw; then
        print_message "${YELLOW}" "Configuring UFW firewall rules..."
        
        # Allow from log server
        ufw allow from 100.122.6.31 to any port 9100 comment 'Node Exporter from log server' > /dev/null 2>&1
        ufw allow from 100.122.6.31 to any port 8080 comment 'cAdvisor from log server' > /dev/null 2>&1
        
        print_message "${GREEN}" "✓ Firewall rules configured"
    else
        print_message "${YELLOW}" "UFW not installed. Skipping firewall configuration."
    fi
}

# Main installation function
main() {
    clear
    print_header "Piper TTS Service Installation Script"
    print_message "${BLUE}" "This script will install and configure Piper TTS service"
    print_message "${BLUE}" "for the Lingudesk platform"
    echo
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then
        print_message "${RED}" "This script must be run as root"
        exit 1
    fi
    
    # Run installation steps
    check_requirements
    check_and_start_docker
    check_tailscale
    install_system_dependencies
    create_directory_structure
    create_log_directory
    verify_env_file
    download_all_models
    install_node_exporter
    install_fluent_bit
    install_cadvisor
    setup_monitoring_firewall
    build_docker_image
    start_services
    test_service
    display_service_info
    
    print_header "Installation Complete"
    print_message "${GREEN}" "Piper TTS service is now running!"
    print_message "${YELLOW}" "Verify backend can access: http://100.109.226.109:8000/health"
    
    exit 0
}

# Run main function
main