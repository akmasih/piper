#!/bin/bash
# setup_client_node.sh
# Path: /root/log/setup_client_node.sh
# Setup script for monitoring agents on client servers with Tailscale network

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Safe non-conflicting ports
NODE_EXPORTER_PORT=9100
CADVISOR_PORT=9280
POSTGRES_EXPORTER_PORT=9187
REDIS_EXPORTER_PORT=9121
NGINX_EXPORTER_PORT=9113
FLUENT_BIT_HTTP_PORT=2020

# Function to print colored messages
print_message() {
    echo -e "${2}${1}${NC}"
}

print_separator() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Banner
clear
print_separator
print_message "     LINGUDESK CLIENT NODE SETUP" "$CYAN"
print_message "     Monitoring Agent Installation (Tailscale)" "$CYAN"
print_separator

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   print_message "This script must be run as root" "$RED"
   exit 1
fi

# Server configuration with Tailscale IPs
print_message "\n📋 Server Configuration" "$GREEN"
print_separator

echo "Select your server:"
echo ""
echo "1) Backend Server (100.116.174.15)"
echo "2) Auth Server (100.100.41.55)"
echo "3) Credit Server (100.65.96.3)"
echo "4) DB Server (100.83.255.98)"
echo "5) AI Server (100.105.173.38)"
echo ""
read -p "Enter choice [1-5]: " SERVER_CHOICE

case $SERVER_CHOICE in
    1)
        SERVER_TYPE="backend"
        SERVER_IP="100.116.174.15"
        SERVER_NAME="backend-server"
        SERVER_ID="server-2"
        HAS_FASTAPI=true
        ;;
    2)
        SERVER_TYPE="auth"
        SERVER_IP="100.100.41.55"
        SERVER_NAME="auth-server"
        SERVER_ID="server-3"
        HAS_FASTAPI=true
        ;;
    3)
        SERVER_TYPE="credit"
        SERVER_IP="100.65.96.3"
        SERVER_NAME="credit-server"
        SERVER_ID="server-4"
        HAS_FASTAPI=true
        ;;
    4)
        SERVER_TYPE="database"
        SERVER_IP="100.83.255.98"
        SERVER_NAME="db-server"
        SERVER_ID="server-5"
        HAS_POSTGRES=true
        HAS_REDIS=true
        HAS_MINIO=true
        ;;
    5)
        SERVER_TYPE="ai"
        SERVER_IP="100.105.173.38"
        SERVER_NAME="ai-server"
        SERVER_ID="server-6"
        HAS_FASTAPI=true
        HAS_TRAEFIK=true
        ;;
    *)
        print_message "Invalid choice!" "$RED"
        exit 1
        ;;
esac

print_message "\nConfiguring: ${SERVER_NAME}" "$GREEN"
print_message "Type: ${SERVER_TYPE}" "$GREEN"
print_message "Tailscale IP: ${SERVER_IP}" "$GREEN"
print_message "Server ID: ${SERVER_ID}" "$GREEN"
print_separator

# Constants
NODE_EXPORTER_VERSION="1.7.0"
LOG_SERVER_IP="100.122.6.31"

# Installation counter
STEP=1
TOTAL_STEPS=5

# Step 1: System Update
print_message "\n[${STEP}/${TOTAL_STEPS}] Updating system packages..." "$GREEN"
((STEP++))
apt-get update -qq
apt-get install -y -qq curl wget net-tools jq

# Step 2: Install Node Exporter
print_message "\n[${STEP}/${TOTAL_STEPS}] Installing Node Exporter..." "$GREEN"
((STEP++))

if ! systemctl is-active --quiet node_exporter; then
    wget -q https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
    tar xzf node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
    mv node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/
    rm -rf node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64*
    
    cat > /etc/systemd/system/node_exporter.service << EOF
[Unit]
Description=Node Exporter
After=network.target

[Service]
User=root
Type=simple
ExecStart=/usr/local/bin/node_exporter \\
    --web.listen-address=:${NODE_EXPORTER_PORT} \\
    --collector.filesystem.mount-points-exclude=^/(dev|proc|sys|run)($|/) \\
    --collector.filesystem.fs-types-exclude=^(autofs|binfmt_misc|cgroup2?|configfs|debugfs|devpts|devtmpfs|fusectl|hugetlbfs|iso9660|mqueue|nsfs|overlay|proc|procfs|pstore|rpc_pipefs|securityfs|selinuxfs|squashfs|sysfs|tracefs|tmpfs)$
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    
    systemctl daemon-reload
    systemctl enable node_exporter
    systemctl start node_exporter
    print_message "✅ Node Exporter installed on port ${NODE_EXPORTER_PORT}" "$GREEN"
else
    print_message "✓ Node Exporter already running" "$YELLOW"
fi

# Step 3: Install Fluent Bit
print_message "\n[${STEP}/${TOTAL_STEPS}] Installing Fluent Bit..." "$GREEN"
((STEP++))

if ! systemctl is-active --quiet fluent-bit; then
    curl https://raw.githubusercontent.com/fluent/fluent-bit/master/install.sh | sh
    sleep 2
    
    cat > /etc/fluent-bit/parsers.conf << 'EOF'
[PARSER]
    Name   json
    Format json

[PARSER]
    Name   docker
    Format json
    Time_Key time
    Time_Format %Y-%m-%dT%H:%M:%S.%LZ

[PARSER]
    Name   syslog
    Format regex
    Regex  ^<(?<pri>[0-9]+)>(?<time>[^ ]* {1,2}[^ ]* [^ ]*) (?<host>[^ ]*) (?<ident>[a-zA-Z0-9_\/\.\-]*)(?:\[(?<pid>[0-9]+)\])?(?:[^\:]*\:)? *(?<message>.*)$
    Time_Key time
    Time_Format %b %d %H:%M:%S

[PARSER]
    Name   nginx
    Format regex
    Regex ^(?<remote>[^ ]*) (?<host>[^ ]*) (?<user>[^ ]*) \[(?<time>[^\]]*)\] "(?<method>\S+)(?: +(?<path>[^\"]*?)(?: +\S*)?)?" (?<code>[^ ]*) (?<size>[^ ]*)(?: "(?<referer>[^\"]*)" "(?<agent>[^\"]*)")?$
    Time_Key time
    Time_Format %d/%b/%Y:%H:%M:%S %z
EOF
    
    cat > /etc/fluent-bit/fluent-bit.conf << EOF
[SERVICE]
    Flush           5
    Daemon          Off
    Log_Level       info
    Parsers_File    /etc/fluent-bit/parsers.conf
    HTTP_Server     On
    HTTP_Listen     0.0.0.0
    HTTP_Port       ${FLUENT_BIT_HTTP_PORT}

# System logs
[INPUT]
    Name              systemd
    Tag               systemd.*
    Read_From_Tail    On

[INPUT]
    Name              tail
    Tag               system.syslog
    Path              /var/log/syslog
    Path_Key          filename
    DB                /var/log/flb_syslog.db
    Skip_Long_Lines   On

# Metrics
[INPUT]
    Name              cpu
    Tag               metrics.cpu
    Interval_Sec      30

[INPUT]
    Name              mem
    Tag               metrics.memory
    Interval_Sec      30

[INPUT]
    Name              disk
    Tag               metrics.disk
    Interval_Sec      60
    Interval_NSec     0
EOF

    # Add service-specific inputs
    if [ "$HAS_POSTGRES" = true ]; then
        cat >> /etc/fluent-bit/fluent-bit.conf << 'EOF'

# PostgreSQL logs
[INPUT]
    Name              tail
    Tag               postgres.log
    Path              /var/log/postgresql/*.log
    Path_Key          filename
    DB                /var/log/flb_postgres.db
    Skip_Long_Lines   On
EOF
    fi

    if [ "$HAS_REDIS" = true ]; then
        cat >> /etc/fluent-bit/fluent-bit.conf << 'EOF'

# Redis logs
[INPUT]
    Name              tail
    Tag               redis.log
    Path              /var/log/redis/*.log
    Path_Key          filename
    DB                /var/log/flb_redis.db
    Skip_Long_Lines   On
EOF
    fi

    if [ "$HAS_FASTAPI" = true ]; then
        mkdir -p /var/log/fastapi
        cat >> /etc/fluent-bit/fluent-bit.conf << 'EOF'

# FastAPI logs
[INPUT]
    Name              tail
    Tag               fastapi.log
    Path              /var/log/fastapi/*.log
    Parser            json
    Path_Key          filename
    DB                /var/log/flb_fastapi.db
    Skip_Long_Lines   On
EOF
    fi

    # Docker logs if Docker is installed
    if command -v docker &> /dev/null; then
        cat >> /etc/fluent-bit/fluent-bit.conf << 'EOF'

# Docker container logs
[INPUT]
    Name              tail
    Tag               docker.container
    Path              /var/lib/docker/containers/*/*.log
    Parser            docker
    Path_Key          container_id
    DB                /var/log/flb_docker.db
    Skip_Long_Lines   On
EOF
    fi

    # Add filters and output to Loki
    cat >> /etc/fluent-bit/fluent-bit.conf << EOF

# Add metadata
[FILTER]
    Name              record_modifier
    Match             *
    Record            hostname ${SERVER_NAME}
    Record            server_type ${SERVER_TYPE}
    Record            server_ip ${SERVER_IP}
    Record            server_id ${SERVER_ID}

# Send to Loki
[OUTPUT]
    Name              http
    Match             *
    Host              ${LOG_SERVER_IP}
    Port              3100
    URI               /loki/api/v1/push
    Format            json
    json_date_key     timestamp
    json_date_format  iso8601
    Headers           Content-Type application/json
    Retry_Limit       5
EOF
    
    systemctl daemon-reload
    systemctl enable fluent-bit
    systemctl start fluent-bit || {
        print_message "⚠ Fluent Bit start failed, checking..." "$YELLOW"
        journalctl -u fluent-bit -n 10 --no-pager
    }
    print_message "✅ Fluent Bit installed" "$GREEN"
else
    print_message "✓ Fluent Bit already running" "$YELLOW"
fi

# Step 4: Install cAdvisor
print_message "\n[${STEP}/${TOTAL_STEPS}] Installing cAdvisor..." "$GREEN"
((STEP++))

if command -v docker &> /dev/null; then
    if docker ps -a | grep -q cadvisor; then
        docker stop cadvisor 2>/dev/null || true
        docker rm cadvisor 2>/dev/null || true
        print_message "Removed old cAdvisor" "$YELLOW"
    fi
    
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
        gcr.io/cadvisor/cadvisor:v0.47.2
    
    print_message "✅ cAdvisor installed on port ${CADVISOR_PORT}" "$GREEN"
else
    print_message "⚠ Docker not installed, skipping cAdvisor" "$YELLOW"
fi

# Step 5: Install specific exporters
print_message "\n[${STEP}/${TOTAL_STEPS}] Installing service-specific exporters..." "$GREEN"
((STEP++))

# PostgreSQL Exporter
if [ "$HAS_POSTGRES" = true ]; then
    if ! systemctl is-active --quiet postgres_exporter; then
        wget -q https://github.com/prometheus-community/postgres_exporter/releases/download/v0.15.0/postgres_exporter-0.15.0.linux-amd64.tar.gz
        tar xzf postgres_exporter-0.15.0.linux-amd64.tar.gz
        mv postgres_exporter-0.15.0.linux-amd64/postgres_exporter /usr/local/bin/
        rm -rf postgres_exporter-0.15.0.linux-amd64*
        
        cat > /etc/systemd/system/postgres_exporter.service << EOF
[Unit]
Description=PostgreSQL Exporter
After=network.target postgresql.service

[Service]
User=postgres
Group=postgres
Type=simple
Environment="DATA_SOURCE_NAME=postgresql://postgres:password@localhost:5432/postgres?sslmode=disable"
ExecStart=/usr/local/bin/postgres_exporter --web.listen-address=:${POSTGRES_EXPORTER_PORT}
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
        
        systemctl daemon-reload
        systemctl enable postgres_exporter
        systemctl start postgres_exporter || true
        print_message "✅ PostgreSQL Exporter on port ${POSTGRES_EXPORTER_PORT}" "$GREEN"
    fi
fi

# Redis Exporter
if [ "$HAS_REDIS" = true ]; then
    if ! systemctl is-active --quiet redis_exporter; then
        wget -q https://github.com/oliver006/redis_exporter/releases/download/v1.55.0/redis_exporter-v1.55.0.linux-amd64.tar.gz
        tar xzf redis_exporter-v1.55.0.linux-amd64.tar.gz
        mv redis_exporter-v1.55.0.linux-amd64/redis_exporter /usr/local/bin/
        rm -rf redis_exporter-v1.55.0.linux-amd64*
        
        cat > /etc/systemd/system/redis_exporter.service << EOF
[Unit]
Description=Redis Exporter
After=network.target redis.service

[Service]
User=root
Type=simple
ExecStart=/usr/local/bin/redis_exporter --web.listen-address=:${REDIS_EXPORTER_PORT}
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
        
        systemctl daemon-reload
        systemctl enable redis_exporter
        systemctl start redis_exporter || true
        print_message "✅ Redis Exporter on port ${REDIS_EXPORTER_PORT}" "$GREEN"
    fi
fi

# Final Verification
print_separator
print_message "\n📊 Installation Summary:" "$CYAN"
print_separator

print_message "\nService Status:" "$YELLOW"
echo "════════════════════════════════════════════════"
printf "%-25s %-10s %-15s\n" "SERVICE" "STATUS" "PORT"
echo "════════════════════════════════════════════════"

# Node Exporter
if systemctl is-active --quiet node_exporter; then
    printf "%-25s ${GREEN}%-10s${NC} %-15s\n" "Node Exporter" "✓ Running" "${NODE_EXPORTER_PORT}"
else
    printf "%-25s ${RED}%-10s${NC} %-15s\n" "Node Exporter" "✗ Failed" "${NODE_EXPORTER_PORT}"
fi

# Fluent Bit
if systemctl is-active --quiet fluent-bit; then
    printf "%-25s ${GREEN}%-10s${NC} %-15s\n" "Fluent Bit" "✓ Running" "${FLUENT_BIT_HTTP_PORT}"
else
    printf "%-25s ${YELLOW}%-10s${NC} %-15s\n" "Fluent Bit" "⚠ Check" "${FLUENT_BIT_HTTP_PORT}"
fi

# cAdvisor
if docker ps 2>/dev/null | grep -q cadvisor; then
    printf "%-25s ${GREEN}%-10s${NC} %-15s\n" "cAdvisor" "✓ Running" "${CADVISOR_PORT}"
else
    [ -x "$(command -v docker)" ] && STATUS="${RED}✗ Failed${NC}" || STATUS="${YELLOW}N/A${NC}"
    printf "%-25s %-10s %-15s\n" "cAdvisor" "$STATUS" "${CADVISOR_PORT}"
fi

# Service-specific exporters
[ "$HAS_POSTGRES" = true ] && {
    if systemctl is-active --quiet postgres_exporter; then
        printf "%-25s ${GREEN}%-10s${NC} %-15s\n" "PostgreSQL Exporter" "✓ Running" "${POSTGRES_EXPORTER_PORT}"
    else
        printf "%-25s ${YELLOW}%-10s${NC} %-15s\n" "PostgreSQL Exporter" "⚠ Check" "${POSTGRES_EXPORTER_PORT}"
    fi
}

[ "$HAS_REDIS" = true ] && {
    if systemctl is-active --quiet redis_exporter; then
        printf "%-25s ${GREEN}%-10s${NC} %-15s\n" "Redis Exporter" "✓ Running" "${REDIS_EXPORTER_PORT}"
    else
        printf "%-25s ${YELLOW}%-10s${NC} %-15s\n" "Redis Exporter" "⚠ Check" "${REDIS_EXPORTER_PORT}"
    fi
}

echo "════════════════════════════════════════════════"

# Connectivity test
print_message "\n🌐 Connectivity Test:" "$CYAN"
if curl -s --connect-timeout 2 http://${LOG_SERVER_IP}:3100/ready > /dev/null 2>&1; then
    print_message "✅ Loki is reachable at ${LOG_SERVER_IP}:3100" "$GREEN"
else
    print_message "⌚ Cannot reach Loki at ${LOG_SERVER_IP}:3100" "$RED"
    print_message "   Check if Log Server is running" "$YELLOW"
fi

if curl -s --connect-timeout 2 http://${LOG_SERVER_IP}:9090/-/healthy > /dev/null 2>&1; then
    print_message "✅ Prometheus is reachable at ${LOG_SERVER_IP}:9090" "$GREEN"
else
    print_message "⚠ Prometheus not reachable" "$YELLOW"
fi

print_separator
print_message "\n✨ Installation completed for ${SERVER_NAME}!" "$GREEN"
print_separator

print_message "\n📝 Quick Test Commands:" "$BLUE"
print_message "════════════════════════════════════" "$BLUE"
echo "# Test Node Exporter:"
echo "curl -s http://localhost:${NODE_EXPORTER_PORT}/metrics | grep node_"
echo ""
echo "# Test cAdvisor:"
echo "curl -s http://localhost:${CADVISOR_PORT}/metrics | grep container_"
echo ""
echo "# Check Fluent Bit logs:"
echo "journalctl -u fluent-bit -n 20 -f"
echo ""
echo "# Test Loki connection:"
echo "curl http://${LOG_SERVER_IP}:3100/ready"

print_separator
print_message "\n📊 View in Grafana:" "$CYAN"
print_message "https://log.lingudesk.com" "$GREEN"
print_message "Look for '${SERVER_NAME}' in dashboards" "$GREEN"
print_separator