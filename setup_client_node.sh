#!/bin/bash
# setup_client_node.sh
# Path: /root/log/setup_client_node.sh
# Setup script for monitoring agents on client servers with Tailscale network
#
# ┌─────────────────────────────────────────────────────────────────────┐
# │                     LOGGING & MONITORING FLOW                      │
# │                                                                    │
# │  All Lingudesk servers follow the same logging pattern:            │
# │                                                                    │
# │  ┌──────────────────────────────────────────────────────────┐      │
# │  │ FastAPI App                                              │      │
# │  │   ├─ stdout (primary)  → Docker json-file driver ──┐    │      │
# │  │   └─ file   (backup)   → /var/log/fastapi/*.log    │    │      │
# │  └────────────────────────────────────────────────┬────┘    │      │
# │                                                   │         │      │
# │  Fluent Bit reads from:                           │         │      │
# │   • Docker container logs (/var/lib/docker/...)  ◄┘         │      │
# │   • System logs (/var/log/syslog, auth.log)                 │      │
# │   • systemd journal                                         │      │
# │                                                             │      │
# │  Fluent Bit does NOT read /var/log/fastapi/*.log            │      │
# │  (that file is only a local backup for server debugging)    │      │
# │                                                             │      │
# │  Fluent Bit ──────────► Loki (log server)                   │      │
# │  Node Exporter ────────► Prometheus (log server)            │      │
# │  cAdvisor ─────────────► Prometheus (log server)            │      │
# │                                                             │      │
# │  Database exporters (postgres/redis):                       │      │
# │   • "db" server: run inside Docker Compose (not systemd)    │      │
# │   • Other servers: run as systemd services (if flagged)     │      │
# └─────────────────────────────────────────────────────────────┘      │
# └─────────────────────────────────────────────────────────────────────┘

set -euo pipefail

# ============================================
# COLOR CODES
# ============================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ============================================
# EXPORTER PORTS
# ============================================
NODE_EXPORTER_PORT=9100
CADVISOR_PORT=9280
POSTGRES_EXPORTER_PORT=9187
REDIS_EXPORTER_PORT=9121
FLUENT_BIT_HTTP_PORT=2020

# ============================================
# VERSIONS
# ============================================
NODE_EXPORTER_VERSION="1.8.2"
POSTGRES_EXPORTER_VERSION="0.15.0"
REDIS_EXPORTER_VERSION="1.55.0"
CADVISOR_VERSION="0.47.2"

# ============================================
# LOG SERVER (Tailscale)
# ============================================
LOG_SERVER_IP="100.122.6.31"

# ============================================
# FLUENT BIT BUFFER
# ============================================
FLUENT_BIT_STORAGE_PATH="/var/log/flb-storage"
FLUENT_BIT_STORAGE_MAX="500M"

# ============================================
# SERVER DEFINITIONS
# ============================================
# Format: NAME|TYPE|IP|FLAGS
# FLAGS: F=FastAPI, P=PostgreSQL, R=Redis, M=MinIO, N=Nginx, T=Traefik
SERVERS=(
    "ai|ai|100.105.173.38|F"
    "auth|auth|100.100.41.55|F"
    "backend|backend|100.116.174.15|F"
    "db|database|100.83.255.98|FPRM"
    "kms|kms|100.100.219.120|F"
    "piper|piper|100.109.226.109|F"
    "sync|sync|100.107.40.66|F"
    "web|frontend|100.110.223.15|FNT"
)

# Servers where postgres/redis exporters run inside Docker Compose
# and should NOT be installed as systemd services by this script.
# On these servers, old systemd exporter services are auto-removed.
DOCKER_EXPORTER_SERVERS=("db")

# ============================================
# HELPER FUNCTIONS
# ============================================
print_message() {
    echo -e "${2}${1}${NC}"
}

print_separator() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_step() {
    local step=$1
    local total=$2
    local message=$3
    print_message "\n[${step}/${total}] ${message}" "$GREEN"
    print_separator
}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi
}

is_service_active() {
    systemctl is-active --quiet "$1" 2>/dev/null
}

command_exists() {
    command -v "$1" &>/dev/null
}

has_flag() {
    local flags=$1
    local flag=$2
    [[ "$flags" == *"$flag"* ]]
}

has_docker_exporters() {
    local server_name=$1
    for ds in "${DOCKER_EXPORTER_SERVERS[@]}"; do
        if [[ "$ds" == "$server_name" ]]; then
            return 0
        fi
    done
    return 1
}

safe_download() {
    local url=$1
    local output=$2
    local retries=3
    local attempt=1

    while [[ $attempt -le $retries ]]; do
        if wget -q --timeout=30 "$url" -O "$output" 2>/dev/null; then
            return 0
        fi
        log_warn "Download attempt ${attempt}/${retries} failed: ${url}"
        attempt=$((attempt + 1))
        sleep 2
    done

    log_error "Failed to download after ${retries} attempts: ${url}"
    return 1
}

# ============================================
# FIND FLUENT BIT BINARY
# ============================================
# Fluent Bit can be installed in different locations depending on
# the installation method. This function finds the actual binary path.
find_fluent_bit_binary() {
    # Check common installation paths in priority order
    local search_paths=(
        "/usr/local/bin/fluent-bit"
        "/opt/fluent-bit/bin/fluent-bit"
        "/usr/bin/fluent-bit"
        "/opt/td-agent-bit/bin/fluent-bit"
    )

    for path in "${search_paths[@]}"; do
        if [[ -x "$path" ]]; then
            echo "$path"
            return 0
        fi
    done

    # Fallback: use which
    if command_exists fluent-bit; then
        which fluent-bit
        return 0
    fi

    return 1
}

# Ensure fluent-bit is accessible from /usr/local/bin for consistent
# systemd service configuration across all servers
ensure_fluent_bit_symlink() {
    if [[ -x /usr/local/bin/fluent-bit ]]; then
        return 0
    fi

    local actual_path
    actual_path=$(find_fluent_bit_binary) || return 1

    if [[ "$actual_path" != "/usr/local/bin/fluent-bit" ]]; then
        ln -sf "$actual_path" /usr/local/bin/fluent-bit
        log_info "Created symlink /usr/local/bin/fluent-bit → ${actual_path}"
    fi
}

# ============================================
# CLEANUP: REMOVE OLD SYSTEMD EXPORTERS
# ============================================
cleanup_systemd_exporters() {
    log_info "Checking for old systemd-based exporters to clean up..."

    local cleaned=false

    # Remove postgres_exporter systemd service if present
    if systemctl list-unit-files postgres_exporter.service &>/dev/null 2>&1; then
        if is_service_active postgres_exporter; then
            systemctl stop postgres_exporter
            log_info "Stopped postgres_exporter systemd service"
        fi
        systemctl disable postgres_exporter 2>/dev/null || true
        rm -f /etc/systemd/system/postgres_exporter.service
        rm -f /usr/local/bin/postgres_exporter
        systemctl daemon-reload
        log_info "Removed postgres_exporter systemd service (now runs in Docker)"
        cleaned=true
    fi

    # Remove redis_exporter systemd service if present
    if systemctl list-unit-files redis_exporter.service &>/dev/null 2>&1; then
        if is_service_active redis_exporter; then
            systemctl stop redis_exporter
            log_info "Stopped redis_exporter systemd service"
        fi
        systemctl disable redis_exporter 2>/dev/null || true
        rm -f /etc/systemd/system/redis_exporter.service
        rm -f /usr/local/bin/redis_exporter
        systemctl daemon-reload
        log_info "Removed redis_exporter systemd service (now runs in Docker)"
        cleaned=true
    fi

    # Clean up old Fluent Bit fastapi tail DB and storage
    if [[ -f /var/log/flb_fastapi.db ]]; then
        rm -f /var/log/flb_fastapi.db
        log_info "Removed old flb_fastapi.db (FastAPI logs now via Docker input)"
        cleaned=true
    fi

    if [[ "$cleaned" == false ]]; then
        log_info "No old systemd exporters found to clean up"
    fi
}

# ============================================
# INSTALL: NODE EXPORTER
# ============================================
install_node_exporter() {
    print_step "$1" "$2" "Installing Node Exporter v${NODE_EXPORTER_VERSION}"

    if is_service_active node_exporter; then
        local current_version
        current_version=$(/usr/local/bin/node_exporter --version 2>&1 | head -1 | grep -oP 'version \K[0-9.]+' || echo "unknown")

        if [[ "$current_version" == "$NODE_EXPORTER_VERSION" ]]; then
            log_info "Node Exporter v${NODE_EXPORTER_VERSION} already running"
            return 0
        fi

        log_warn "Node Exporter v${current_version} found, upgrading to v${NODE_EXPORTER_VERSION}"
        systemctl stop node_exporter
    fi

    local archive="node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
    local url="https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/${archive}"

    cd /tmp
    safe_download "$url" "$archive" || return 1
    tar xzf "$archive"
    mv "node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter" /usr/local/bin/
    rm -rf "node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64" "$archive"

    cat > /etc/systemd/system/node_exporter.service << EOF
[Unit]
Description=Prometheus Node Exporter v${NODE_EXPORTER_VERSION}
Documentation=https://prometheus.io/docs/guides/node-exporter/
After=network-online.target
Wants=network-online.target

[Service]
User=root
Group=root
Type=simple
ExecStart=/usr/local/bin/node_exporter \\
    --web.listen-address=:${NODE_EXPORTER_PORT} \\
    --no-collector.arp \\
    --collector.filesystem.mount-points-exclude="^/(dev|proc|sys|run|var/lib/docker)(\$|/)" \\
    --collector.netclass.ignored-devices="^(veth|docker|br-).*"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable node_exporter
    systemctl start node_exporter

    if is_service_active node_exporter; then
        log_info "Node Exporter v${NODE_EXPORTER_VERSION} installed on port ${NODE_EXPORTER_PORT}"
    else
        log_error "Node Exporter failed to start"
        journalctl -u node_exporter -n 5 --no-pager
        return 1
    fi
}

# ============================================
# INSTALL: FLUENT BIT
# ============================================
install_fluent_bit() {
    print_step "$1" "$2" "Installing Fluent Bit"

    if ! command_exists fluent-bit; then
        curl -fsSL https://raw.githubusercontent.com/fluent/fluent-bit/master/install.sh | sh
        sleep 2
        log_info "Fluent Bit installed"
    else
        log_info "Fluent Bit already installed"
    fi

    # Ensure fluent-bit is accessible from /usr/local/bin
    # Official installer places binary in /opt/fluent-bit/bin/ but systemd
    # service references /usr/local/bin/fluent-bit for consistency
    ensure_fluent_bit_symlink
}

# ============================================
# CONFIGURE: FLUENT BIT PARSERS
# ============================================
configure_fluent_bit_parsers() {
    cat > /etc/fluent-bit/parsers.conf << 'PARSERS_EOF'
[PARSER]
    Name        json
    Format      json
    Time_Key    time
    Time_Format %Y-%m-%dT%H:%M:%S.%LZ

[PARSER]
    Name        docker
    Format      json
    Time_Key    time
    Time_Format %Y-%m-%dT%H:%M:%S.%LZ

[PARSER]
    Name        syslog
    Format      regex
    Regex       ^<(?<pri>[0-9]+)>(?<time>[^ ]* {1,2}[^ ]* [^ ]*) (?<host>[^ ]*) (?<ident>[a-zA-Z0-9_\/\.\-]*)(?:\[(?<pid>[0-9]+)\])?(?:[^\:]*\:)? *(?<message>.*)$
    Time_Key    time
    Time_Format %b %d %H:%M:%S

[PARSER]
    Name        nginx
    Format      regex
    Regex       ^(?<remote>[^ ]*) (?<host>[^ ]*) (?<user>[^ ]*) \[(?<time>[^\]]*)\] "(?<method>\S+)(?: +(?<path>[^\"]*?)(?: +\S*)?)?" (?<code>[^ ]*) (?<size>[^ ]*)(?: "(?<referer>[^\"]*)" "(?<agent>[^\"]*)")?$
    Time_Key    time
    Time_Format %d/%b/%Y:%H:%M:%S %z
PARSERS_EOF

    log_info "Fluent Bit parsers configured"
}

# ============================================
# CONFIGURE: FLUENT BIT MAIN CONFIG
# ============================================
configure_fluent_bit() {
    print_step "$1" "$2" "Configuring Fluent Bit for ${SERVER_NAME}"

    configure_fluent_bit_parsers

    mkdir -p "${FLUENT_BIT_STORAGE_PATH}"

    # --- SERVICE section ---
    cat > /etc/fluent-bit/fluent-bit.conf << EOF
# Fluent Bit Configuration for ${SERVER_NAME}
# Auto-generated by setup_client_node.sh
#
# FastAPI logs are collected via Docker container logs (docker.* input),
# NOT via a separate tail input on /var/log/fastapi/*.log.
# The file on disk is only a local backup.

[SERVICE]
    Flush           5
    Daemon          Off
    Log_Level       info
    Parsers_File    /etc/fluent-bit/parsers.conf
    HTTP_Server     On
    HTTP_Listen     0.0.0.0
    HTTP_Port       ${FLUENT_BIT_HTTP_PORT}
    storage.path    ${FLUENT_BIT_STORAGE_PATH}
    storage.sync    normal
    storage.checksum  off
    storage.max_chunks_up  128

# ============================================
# INPUTS - System Logs
# ============================================

[INPUT]
    Name              systemd
    Tag               systemd.*
    Read_From_Tail    On
    Strip_Underscores On

[INPUT]
    Name              tail
    Tag               syslog
    Path              /var/log/syslog
    DB                /var/log/flb_syslog.db
    Skip_Long_Lines   On
    Refresh_Interval  10

[INPUT]
    Name              tail
    Tag               auth.log
    Path              /var/log/auth.log
    DB                /var/log/flb_auth.db
    Skip_Long_Lines   On
    Refresh_Interval  10

# ============================================
# INPUTS - Docker Container Logs
# ============================================
# This captures ALL container logs including FastAPI application logs.
# FastAPI writes structured JSON to stdout → Docker json-file driver → here.

[INPUT]
    Name              tail
    Tag               docker.<container_name>
    Tag_Regex         /var/lib/docker/containers/(?<container_id>[a-z0-9]+)/[a-z0-9]+-json\\.log
    Path              /var/lib/docker/containers/*/*.log
    Exclude_Path      /var/lib/docker/containers/*/*-json.log.*.gz
    DB                /var/log/flb_docker.db
    Parser            docker
    Skip_Long_Lines   On
    Refresh_Interval  10
    Mem_Buf_Limit     10MB
    storage.type      filesystem
EOF

    # --- Nginx logs (web server) ---
    if has_flag "$SERVER_FLAGS" "N"; then
        cat >> /etc/fluent-bit/fluent-bit.conf << 'EOF'

# ============================================
# INPUTS - Nginx Logs
# ============================================

[INPUT]
    Name              tail
    Tag               nginx.access
    Path              /var/log/nginx/access.log
    Parser            nginx
    DB                /var/log/flb_nginx_access.db
    Skip_Long_Lines   On
    Refresh_Interval  10
    storage.type      filesystem

[INPUT]
    Name              tail
    Tag               nginx.error
    Path              /var/log/nginx/error.log
    DB                /var/log/flb_nginx_error.db
    Skip_Long_Lines   On
    Refresh_Interval  10
    storage.type      filesystem
EOF
    fi

    # --- Traefik logs (web server) ---
    if has_flag "$SERVER_FLAGS" "T"; then
        cat >> /etc/fluent-bit/fluent-bit.conf << 'EOF'

# ============================================
# INPUTS - Traefik Logs
# ============================================

[INPUT]
    Name              tail
    Tag               traefik.access
    Path              /var/log/traefik/access.log
    Parser            json
    DB                /var/log/flb_traefik_access.db
    Skip_Long_Lines   On
    Refresh_Interval  10
    storage.type      filesystem

[INPUT]
    Name              tail
    Tag               traefik.log
    Path              /var/log/traefik/traefik.log
    Parser            json
    DB                /var/log/flb_traefik.db
    Skip_Long_Lines   On
    Refresh_Interval  10
    storage.type      filesystem
EOF
    fi

    # --- Filters and Output ---
    cat >> /etc/fluent-bit/fluent-bit.conf << EOF

# ============================================
# FILTERS - Add Server Information
# ============================================

[FILTER]
    Name              record_modifier
    Match             *
    Record            hostname ${SERVER_NAME}
    Record            server_type ${SERVER_TYPE}
    Record            server_ip ${SERVER_IP}

[FILTER]
    Name              modify
    Match             systemd.*
    Add               log_type systemd

[FILTER]
    Name              modify
    Match             docker.*
    Add               log_type docker

# ============================================
# FILTERS - Extract Container Name from Docker Logs
# ============================================

[FILTER]
    Name              lua
    Match             docker.*
    script            /etc/fluent-bit/extract_container.lua
    call              extract_container_name

# ============================================
# FILTERS - Exclude Noisy System Logs
# ============================================

# Drop routine sshd session open/close messages
[FILTER]
    Name              grep
    Match             syslog
    Exclude           log pam_unix\(sshd:session\)

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log Disconnected from user

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log Received disconnect from.*disconnected by user

# Drop systemd session/scope lifecycle noise
[FILTER]
    Name              grep
    Match             syslog
    Exclude           log Started session-.*\.scope

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log New session .* of user

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log Session .* logged out

# Drop tailscaled disco/peer reconfiguration chatter
[FILTER]
    Name              grep
    Match             syslog
    Exclude           log tailscaled.*disco:

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log tailscaled.*idle peer.*now active

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log tailscaled.*Reconfig:.*configuring userspace WireGuard

# Drop systemd-resolved DNS feature set toggling
[FILTER]
    Name              grep
    Match             syslog
    Exclude           log systemd-resolved.*Using degraded feature set

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log systemd-resolved.*Grace period over.*resuming full feature set

# Drop sysstat-collect routine runs
[FILTER]
    Name              grep
    Match             syslog
    Exclude           log sysstat-collect.service

# Drop Docker container scope lifecycle messages
[FILTER]
    Name              grep
    Match             syslog
    Exclude           log docker-.*\.scope: Deactivated successfully

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log docker-.*\.scope: Consumed

# Drop containerd shim lifecycle messages
[FILTER]
    Name              grep
    Match             syslog
    Exclude           log containerd.*shim disconnected

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log containerd.*cleaning up after shim

# Drop kernel Docker bridge/veth network noise
[FILTER]
    Name              grep
    Match             syslog
    Exclude           log kernel:.*br-.*entered forwarding state

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log kernel:.*br-.*entered blocking state

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log kernel:.*br-.*entered disabled state

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log kernel:.*veth.*renamed from veth

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log kernel:.*veth.*entered promiscuous mode

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log kernel:.*veth.*left promiscuous mode

# Drop systemd-networkd veth carrier events
[FILTER]
    Name              grep
    Match             syslog
    Exclude           log systemd-networkd.*veth.*Gained carrier

[FILTER]
    Name              grep
    Match             syslog
    Exclude           log systemd-networkd.*veth.*Lost carrier

# Drop Docker daemon routine container lifecycle
[FILTER]
    Name              grep
    Match             syslog
    Exclude           log dockerd.*ignoring event

# ============================================
# OUTPUT - Send to Loki on Log Server
# ============================================

[OUTPUT]
    Name              loki
    Match             *
    Host              ${LOG_SERVER_IP}
    Port              3100
    Labels            job=fluent-bit, server=${SERVER_NAME}, server_type=${SERVER_TYPE}
    Label_Keys        \$hostname, \$server_type, \$log_type, \$container_name
    Line_Format       json
    Retry_Limit       False
    storage.total_limit_size  ${FLUENT_BIT_STORAGE_MAX}
EOF

    # --- Create Lua script for container name extraction ---
    cat > /etc/fluent-bit/extract_container.lua << 'LUA_EOF'
-- extract_container.lua
-- Extract container name from Docker log file path for Loki labels

function extract_container_name(tag, timestamp, record)
    -- Docker json-file driver with tag option puts container name in "attrs.tag"
    if record["attrs"] and record["attrs"]["tag"] then
        record["container_name"] = record["attrs"]["tag"]
        return 1, timestamp, record
    end

    -- Fallback: try to extract from source field if present
    if record["source"] then
        record["log_stream"] = record["source"]
    end

    return 1, timestamp, record
end
LUA_EOF

    # Restart Fluent Bit
    systemctl daemon-reload
    systemctl enable fluent-bit
    systemctl restart fluent-bit

    if is_service_active fluent-bit; then
        log_info "Fluent Bit configured and running"
        log_info "Filesystem buffer enabled at ${FLUENT_BIT_STORAGE_PATH}"
    else
        log_warn "Fluent Bit failed to start — check logs:"
        journalctl -u fluent-bit -n 10 --no-pager
    fi
}

# ============================================
# INSTALL: CADVISOR
# ============================================
install_cadvisor() {
    print_step "$1" "$2" "Installing cAdvisor v${CADVISOR_VERSION}"

    if ! command_exists docker; then
        log_warn "Docker not installed, skipping cAdvisor"
        return 0
    fi

    # Remove old container if exists
    docker stop cadvisor 2>/dev/null || true
    docker rm cadvisor 2>/dev/null || true

    docker run \
        --volume=/:/rootfs:ro \
        --volume=/var/run:/var/run:ro \
        --volume=/sys:/sys:ro \
        --volume=/var/lib/docker/:/var/lib/docker:ro \
        --volume=/dev/disk/:/dev/disk:ro \
        --publish=${CADVISOR_PORT}:8080 \
        --detach=true \
        --name=cadvisor \
        --restart=unless-stopped \
        --privileged \
        --device=/dev/kmsg \
        "gcr.io/cadvisor/cadvisor:v${CADVISOR_VERSION}"

    if docker ps --format '{{.Names}}' | grep -q cadvisor; then
        log_info "cAdvisor v${CADVISOR_VERSION} installed on port ${CADVISOR_PORT}"
    else
        log_error "cAdvisor failed to start"
        docker logs cadvisor 2>/dev/null | tail -5
    fi
}

# ============================================
# INSTALL: POSTGRES EXPORTER (systemd)
# Only for servers NOT in DOCKER_EXPORTER_SERVERS
# ============================================
install_postgres_exporter() {
    if is_service_active postgres_exporter; then
        local current_version
        current_version=$(/usr/local/bin/postgres_exporter --version 2>&1 | head -1 | grep -oP 'version \K[0-9.]+' || echo "unknown")

        if [[ "$current_version" == "$POSTGRES_EXPORTER_VERSION" ]]; then
            log_info "PostgreSQL Exporter v${POSTGRES_EXPORTER_VERSION} already running"
            return 0
        fi

        log_warn "PostgreSQL Exporter v${current_version} found, upgrading to v${POSTGRES_EXPORTER_VERSION}"
        systemctl stop postgres_exporter
    fi

    local archive="postgres_exporter-${POSTGRES_EXPORTER_VERSION}.linux-amd64.tar.gz"
    local url="https://github.com/prometheus-community/postgres_exporter/releases/download/v${POSTGRES_EXPORTER_VERSION}/${archive}"

    cd /tmp
    safe_download "$url" "$archive" || return 1
    tar xzf "$archive"
    mv "postgres_exporter-${POSTGRES_EXPORTER_VERSION}.linux-amd64/postgres_exporter" /usr/local/bin/
    rm -rf "postgres_exporter-${POSTGRES_EXPORTER_VERSION}.linux-amd64" "$archive"

    print_message "\nPostgreSQL Exporter Configuration:" "$CYAN"

    local pg_user="db_user"
    local pg_pass=""
    local pg_db="lingudesk"
    local env_file="/root/db/.env"

    if [[ -f "$env_file" ]]; then
        pg_user=$(grep -E '^POSTGRES_USER=' "$env_file" | cut -d'=' -f2 || echo "db_user")
        pg_pass=$(grep -E '^POSTGRES_PASSWORD=' "$env_file" | cut -d'=' -f2 || echo "")
        pg_db=$(grep -E '^POSTGRES_DB=' "$env_file" | cut -d'=' -f2 || echo "lingudesk")
        if [[ -n "$pg_pass" ]]; then
            log_info "Loaded PostgreSQL credentials from ${env_file}"
        fi
    fi

    if [[ -z "$pg_pass" ]]; then
        read -rsp "PostgreSQL Password: " pg_pass
        echo ""
        if [[ -z "$pg_pass" ]]; then
            log_error "PostgreSQL password is required"
            return 1
        fi
    fi

    local pg_host="${SERVER_IP}"

    cat > /etc/systemd/system/postgres_exporter.service << EOF
[Unit]
Description=Prometheus PostgreSQL Exporter v${POSTGRES_EXPORTER_VERSION}
After=network.target

[Service]
User=root
Type=simple
Environment="DATA_SOURCE_NAME=postgresql://${pg_user}:${pg_pass}@${pg_host}:5432/${pg_db}?sslmode=disable"
ExecStart=/usr/local/bin/postgres_exporter --web.listen-address=:${POSTGRES_EXPORTER_PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable postgres_exporter
    systemctl start postgres_exporter

    sleep 2

    if is_service_active postgres_exporter; then
        log_info "PostgreSQL Exporter on port ${POSTGRES_EXPORTER_PORT} → ${pg_host}:5432"
    else
        log_warn "PostgreSQL Exporter failed to start"
        journalctl -u postgres_exporter -n 5 --no-pager
    fi
}

# ============================================
# INSTALL: REDIS EXPORTER (systemd)
# Only for servers NOT in DOCKER_EXPORTER_SERVERS
# ============================================
install_redis_exporter() {
    if is_service_active redis_exporter; then
        local current_version
        current_version=$(/usr/local/bin/redis_exporter --version 2>&1 | grep -oP 'v\K[0-9.]+' || echo "unknown")

        if [[ "$current_version" == "$REDIS_EXPORTER_VERSION" ]]; then
            log_info "Redis Exporter v${REDIS_EXPORTER_VERSION} already running"
            return 0
        fi

        log_warn "Redis Exporter v${current_version} found, upgrading to v${REDIS_EXPORTER_VERSION}"
        systemctl stop redis_exporter
    fi

    local archive="redis_exporter-v${REDIS_EXPORTER_VERSION}.linux-amd64.tar.gz"
    local url="https://github.com/oliver006/redis_exporter/releases/download/v${REDIS_EXPORTER_VERSION}/${archive}"

    cd /tmp
    safe_download "$url" "$archive" || return 1
    tar xzf "$archive"
    mv "redis_exporter-v${REDIS_EXPORTER_VERSION}.linux-amd64/redis_exporter" /usr/local/bin/
    rm -rf "redis_exporter-v${REDIS_EXPORTER_VERSION}.linux-amd64" "$archive"

    print_message "\nRedis Exporter Configuration:" "$CYAN"

    local redis_pass=""
    local env_file="/root/db/.env"

    if [[ -f "$env_file" ]]; then
        redis_pass=$(grep -E '^REDIS_PASSWORD=' "$env_file" | cut -d'=' -f2 || echo "")
        if [[ -n "$redis_pass" ]]; then
            log_info "Loaded Redis credentials from ${env_file}"
        fi
    fi

    if [[ -z "$redis_pass" ]]; then
        read -rsp "Redis Password: " redis_pass
        echo ""
        if [[ -z "$redis_pass" ]]; then
            log_error "Redis password is required"
            return 1
        fi
    fi

    local redis_host="${SERVER_IP}"

    cat > /etc/systemd/system/redis_exporter.service << EOF
[Unit]
Description=Prometheus Redis Exporter v${REDIS_EXPORTER_VERSION}
After=network.target

[Service]
User=root
Type=simple
ExecStart=/usr/local/bin/redis_exporter \\
    --web.listen-address=:${REDIS_EXPORTER_PORT} \\
    --redis.addr=redis://${redis_host}:6379 \\
    --redis.password=${redis_pass}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable redis_exporter
    systemctl start redis_exporter

    sleep 2

    if is_service_active redis_exporter; then
        log_info "Redis Exporter on port ${REDIS_EXPORTER_PORT} → ${redis_host}:6379"
    else
        log_warn "Redis Exporter failed to start"
        journalctl -u redis_exporter -n 5 --no-pager
    fi
}

# ============================================
# INSTALL: SERVICE-SPECIFIC EXPORTERS
# ============================================
install_service_exporters() {
    print_step "$1" "$2" "Installing service-specific exporters"

    if has_docker_exporters "$SERVER_NAME"; then
        log_info "Server '${SERVER_NAME}' runs postgres/redis exporters inside Docker Compose"
        log_info "Skipping systemd-based exporter installation"
        cleanup_systemd_exporters
        return 0
    fi

    local installed=false

    if has_flag "$SERVER_FLAGS" "P"; then
        install_postgres_exporter
        installed=true
    fi

    if has_flag "$SERVER_FLAGS" "R"; then
        install_redis_exporter
        installed=true
    fi

    if [[ "$installed" == false ]]; then
        log_info "No database exporters needed for this server"
    fi
}

# ============================================
# VERIFY: CHECK ALL SERVICES
# ============================================
verify_installation() {
    print_step "$1" "$2" "Verifying installation"

    print_separator
    print_message "     INSTALLATION COMPLETE!" "$GREEN"
    print_separator

    print_message "\nSERVICE STATUS:" "$CYAN"
    echo "════════════════════════════════════════════════════"
    printf "%-25s %-12s %-10s\n" "SERVICE" "STATUS" "PORT"
    echo "════════════════════════════════════════════════════"

    # Node Exporter
    if is_service_active node_exporter; then
        printf "%-25s ${GREEN}%-12s${NC} %-10s\n" "Node Exporter" "Running" "${NODE_EXPORTER_PORT}"
    else
        printf "%-25s ${RED}%-12s${NC} %-10s\n" "Node Exporter" "Failed" "${NODE_EXPORTER_PORT}"
    fi

    # Fluent Bit
    if is_service_active fluent-bit; then
        printf "%-25s ${GREEN}%-12s${NC} %-10s\n" "Fluent Bit" "Running" "${FLUENT_BIT_HTTP_PORT}"
    else
        printf "%-25s ${YELLOW}%-12s${NC} %-10s\n" "Fluent Bit" "Check" "${FLUENT_BIT_HTTP_PORT}"
    fi

    # cAdvisor
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q cadvisor; then
        printf "%-25s ${GREEN}%-12s${NC} %-10s\n" "cAdvisor" "Running" "${CADVISOR_PORT}"
    else
        printf "%-25s ${YELLOW}%-12s${NC} %-10s\n" "cAdvisor" "Check" "${CADVISOR_PORT}"
    fi

    # PostgreSQL Exporter
    if has_flag "$SERVER_FLAGS" "P"; then
        if has_docker_exporters "$SERVER_NAME"; then
            if docker ps --format '{{.Names}}' 2>/dev/null | grep -q lingudesk_postgres_exporter; then
                printf "%-25s ${GREEN}%-12s${NC} %-10s\n" "PostgreSQL Exporter" "Docker" "${POSTGRES_EXPORTER_PORT}"
            else
                printf "%-25s ${YELLOW}%-12s${NC} %-10s\n" "PostgreSQL Exporter" "Check DC" "${POSTGRES_EXPORTER_PORT}"
            fi
        else
            if is_service_active postgres_exporter; then
                printf "%-25s ${GREEN}%-12s${NC} %-10s\n" "PostgreSQL Exporter" "Running" "${POSTGRES_EXPORTER_PORT}"
            else
                printf "%-25s ${YELLOW}%-12s${NC} %-10s\n" "PostgreSQL Exporter" "Check" "${POSTGRES_EXPORTER_PORT}"
            fi
        fi
    fi

    # Redis Exporter
    if has_flag "$SERVER_FLAGS" "R"; then
        if has_docker_exporters "$SERVER_NAME"; then
            if docker ps --format '{{.Names}}' 2>/dev/null | grep -q lingudesk_redis_exporter; then
                printf "%-25s ${GREEN}%-12s${NC} %-10s\n" "Redis Exporter" "Docker" "${REDIS_EXPORTER_PORT}"
            else
                printf "%-25s ${YELLOW}%-12s${NC} %-10s\n" "Redis Exporter" "Check DC" "${REDIS_EXPORTER_PORT}"
            fi
        else
            if is_service_active redis_exporter; then
                printf "%-25s ${GREEN}%-12s${NC} %-10s\n" "Redis Exporter" "Running" "${REDIS_EXPORTER_PORT}"
            else
                printf "%-25s ${YELLOW}%-12s${NC} %-10s\n" "Redis Exporter" "Check" "${REDIS_EXPORTER_PORT}"
            fi
        fi
    fi

    echo "════════════════════════════════════════════════════"

    # Connectivity test
    print_message "\nCONNECTIVITY TEST:" "$CYAN"
    print_separator

    if curl -s --connect-timeout 3 "http://${LOG_SERVER_IP}:3100/ready" >/dev/null 2>&1; then
        log_info "Loki is reachable at ${LOG_SERVER_IP}:3100"
    else
        log_error "Cannot reach Loki at ${LOG_SERVER_IP}:3100"
        log_warn "Check if Log Server is running and Tailscale is connected"
    fi

    if curl -s --connect-timeout 3 "http://${LOG_SERVER_IP}:9090/-/healthy" >/dev/null 2>&1; then
        log_info "Prometheus is reachable at ${LOG_SERVER_IP}:9090"
    else
        log_warn "Prometheus not reachable at ${LOG_SERVER_IP}:9090"
    fi

    print_separator

    # Show filesystem buffer info
    print_message "\nFILESYSTEM BUFFER:" "$CYAN"
    print_separator
    echo "Path: ${FLUENT_BIT_STORAGE_PATH}"
    echo "Max:  ${FLUENT_BIT_STORAGE_MAX}"
    echo "If Loki is unreachable, logs are buffered locally and sent when connection resumes."
    print_separator

    print_message "\nQUICK TEST COMMANDS:" "$CYAN"
    print_separator
    echo "# Test Node Exporter:"
    echo "curl -s http://localhost:${NODE_EXPORTER_PORT}/metrics | head -20"
    echo ""
    echo "# Test cAdvisor:"
    echo "curl -s http://localhost:${CADVISOR_PORT}/metrics | head -20"
    echo ""
    echo "# Check Fluent Bit status:"
    echo "journalctl -u fluent-bit -n 20 -f"
    echo ""
    echo "# Check Fluent Bit buffer usage:"
    echo "curl -s http://localhost:${FLUENT_BIT_HTTP_PORT}/api/v1/storage | jq"
    echo ""
    echo "# Test Loki connection:"
    echo "curl http://${LOG_SERVER_IP}:3100/ready"

    if has_docker_exporters "$SERVER_NAME"; then
        echo ""
        echo "# Test PostgreSQL Exporter (Docker):"
        echo "curl -s http://localhost:${POSTGRES_EXPORTER_PORT}/metrics | grep pg_up"
        echo ""
        echo "# Test Redis Exporter (Docker):"
        echo "curl -s http://localhost:${REDIS_EXPORTER_PORT}/metrics | grep redis_up"
    fi

    print_separator

    print_message "\nVIEW IN GRAFANA:" "$CYAN"
    print_message "https://log.lingudesk.com" "$GREEN"
    print_message "Look for '${SERVER_NAME}' in dashboards" "$GREEN"
    print_separator

    print_message "\nSetup completed for ${SERVER_NAME}!" "$GREEN"
    print_separator
}

# ============================================
# MAIN
# ============================================
main() {
    check_root

    clear
    print_separator
    print_message "     LINGUDESK CLIENT NODE SETUP" "$CYAN"
    print_message "     Monitoring Agent Installation (Tailscale)" "$CYAN"
    print_separator

    # --- Server selection menu ---
    print_message "\nSelect your server:\n" "$GREEN"

    for i in "${!SERVERS[@]}"; do
        IFS='|' read -r name type ip flags <<< "${SERVERS[$i]}"
        printf "  %d) %-10s - %-22s (%s)\n" "$((i + 1))" "$name" "$type" "$ip"
    done
    echo ""

    read -rp "Enter choice [1-${#SERVERS[@]}]: " SERVER_CHOICE

    if ! [[ "$SERVER_CHOICE" =~ ^[0-9]+$ ]] || \
       [[ "$SERVER_CHOICE" -lt 1 ]] || \
       [[ "$SERVER_CHOICE" -gt ${#SERVERS[@]} ]]; then
        log_error "Invalid choice!"
        exit 1
    fi

    local index=$((SERVER_CHOICE - 1))
    IFS='|' read -r SERVER_NAME SERVER_TYPE SERVER_IP SERVER_FLAGS <<< "${SERVERS[$index]}"

    export SERVER_NAME SERVER_TYPE SERVER_IP SERVER_FLAGS

    print_separator
    print_message "Configuring: ${SERVER_NAME}" "$GREEN"
    print_message "Type:        ${SERVER_TYPE}" "$GREEN"
    print_message "IP:          ${SERVER_IP}" "$GREEN"
    print_message "Flags:       ${SERVER_FLAGS}" "$GREEN"

    if has_docker_exporters "$SERVER_NAME"; then
        print_message "" "$CYAN"
        print_message "Note: postgres/redis exporters run inside Docker Compose" "$CYAN"
        print_message "      Old systemd services will be cleaned up automatically" "$CYAN"
    fi

    print_separator

    read -rp "Continue with installation? (Y/n): " CONFIRM
    if [[ "${CONFIRM,,}" == "n" ]]; then
        print_message "Installation cancelled." "$YELLOW"
        exit 0
    fi

    local TOTAL_STEPS=6

    # --- Step 1: System update ---
    print_step 1 $TOTAL_STEPS "Updating system packages"
    apt-get update -qq
    apt-get install -y -qq curl wget net-tools jq >/dev/null 2>&1
    log_info "System packages updated"

    # --- Step 2: Node Exporter ---
    install_node_exporter 2 $TOTAL_STEPS

    # --- Step 3: Fluent Bit ---
    install_fluent_bit 3 $TOTAL_STEPS

    # --- Step 4: Configure Fluent Bit ---
    configure_fluent_bit 4 $TOTAL_STEPS

    # --- Step 5: cAdvisor ---
    install_cadvisor 5 $TOTAL_STEPS

    # --- Step 6: Service exporters (or cleanup if Dockerized) ---
    install_service_exporters 6 $TOTAL_STEPS

    # --- Verification ---
    verify_installation 7 7
}

main "$@"