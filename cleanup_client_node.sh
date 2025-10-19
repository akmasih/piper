#!/bin/bash
# cleanup_client_node.sh
# Path: /root/log/cleanup_client_node.sh
# Complete cleanup script to remove all monitoring components from client servers

set -e

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

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
print_message "     LINGUDESK CLIENT NODE CLEANUP" "$CYAN"
print_message "     Complete Monitoring Stack Removal" "$CYAN"
print_separator

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   print_message "This script must be run as root" "$RED"
   exit 1
fi

# Warning
print_message "\n⚠️  WARNING: This will remove:" "$RED"
print_message "   • Node Exporter" "$YELLOW"
print_message "   • Fluent Bit" "$YELLOW"
print_message "   • cAdvisor (Docker container)" "$YELLOW"
print_message "   • PostgreSQL Exporter (if installed)" "$YELLOW"
print_message "   • Redis Exporter (if installed)" "$YELLOW"
print_message "   • Nginx Exporter (if installed)" "$YELLOW"
print_message "   • All related configuration files" "$YELLOW"
print_separator

read -p "Are you sure you want to continue? (yes/NO): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    print_message "Cleanup cancelled." "$GREEN"
    exit 0
fi

# Step 1: Stop and remove Node Exporter
print_message "\n[1/7] Removing Node Exporter..." "$GREEN"

if systemctl is-active --quiet node_exporter; then
    systemctl stop node_exporter
    systemctl disable node_exporter
    print_message "✓ Node Exporter service stopped" "$GREEN"
fi

if [ -f /etc/systemd/system/node_exporter.service ]; then
    rm -f /etc/systemd/system/node_exporter.service
    print_message "✓ Node Exporter service file removed" "$GREEN"
fi

if [ -f /usr/local/bin/node_exporter ]; then
    rm -f /usr/local/bin/node_exporter
    print_message "✓ Node Exporter binary removed" "$GREEN"
else
    print_message "✓ Node Exporter not found" "$YELLOW"
fi

# Step 2: Stop and remove Fluent Bit
print_message "\n[2/7] Removing Fluent Bit..." "$GREEN"

if systemctl is-active --quiet fluent-bit; then
    systemctl stop fluent-bit
    systemctl disable fluent-bit
    print_message "✓ Fluent Bit service stopped" "$GREEN"
fi

if systemctl is-active --quiet td-agent-bit; then
    systemctl stop td-agent-bit
    systemctl disable td-agent-bit
    print_message "✓ TD Agent Bit service stopped" "$GREEN"
fi

# Remove Fluent Bit package
if command -v fluent-bit &> /dev/null; then
    if command -v apt-get &> /dev/null; then
        apt-get remove --purge -y fluent-bit td-agent-bit 2>/dev/null || true
        apt-get autoremove -y 2>/dev/null || true
    elif command -v yum &> /dev/null; then
        yum remove -y fluent-bit td-agent-bit 2>/dev/null || true
    fi
    print_message "✓ Fluent Bit package removed" "$GREEN"
fi

# Remove Fluent Bit config files
if [ -d /etc/fluent-bit ]; then
    rm -rf /etc/fluent-bit
    print_message "✓ Fluent Bit configuration removed" "$GREEN"
fi

if [ -d /etc/td-agent-bit ]; then
    rm -rf /etc/td-agent-bit
    print_message "✓ TD Agent Bit configuration removed" "$GREEN"
fi

# Remove Fluent Bit logs
rm -f /var/log/flb_*.db 2>/dev/null || true
rm -f /var/log/fluent-bit*.log 2>/dev/null || true

# Step 3: Stop and remove cAdvisor
print_message "\n[3/7] Removing cAdvisor..." "$GREEN"

if command -v docker &> /dev/null; then
    if docker ps -a | grep -q cadvisor; then
        docker stop cadvisor 2>/dev/null || true
        docker rm -f cadvisor 2>/dev/null || true
        print_message "✓ cAdvisor container removed" "$GREEN"
    else
        print_message "✓ cAdvisor not found" "$YELLOW"
    fi
    
    # Remove cAdvisor image
    docker rmi gcr.io/cadvisor/cadvisor:v0.47.2 2>/dev/null || true
else
    print_message "✓ Docker not installed" "$YELLOW"
fi

# Step 4: Stop and remove PostgreSQL Exporter
print_message "\n[4/7] Removing PostgreSQL Exporter..." "$GREEN"

if systemctl is-active --quiet postgres_exporter; then
    systemctl stop postgres_exporter
    systemctl disable postgres_exporter
    print_message "✓ PostgreSQL Exporter service stopped" "$GREEN"
fi

if [ -f /etc/systemd/system/postgres_exporter.service ]; then
    rm -f /etc/systemd/system/postgres_exporter.service
    print_message "✓ PostgreSQL Exporter service file removed" "$GREEN"
fi

if [ -f /usr/local/bin/postgres_exporter ]; then
    rm -f /usr/local/bin/postgres_exporter
    print_message "✓ PostgreSQL Exporter binary removed" "$GREEN"
else
    print_message "✓ PostgreSQL Exporter not found" "$YELLOW"
fi

# Step 5: Stop and remove Redis Exporter
print_message "\n[5/7] Removing Redis Exporter..." "$GREEN"

if systemctl is-active --quiet redis_exporter; then
    systemctl stop redis_exporter
    systemctl disable redis_exporter
    print_message "✓ Redis Exporter service stopped" "$GREEN"
fi

if [ -f /etc/systemd/system/redis_exporter.service ]; then
    rm -f /etc/systemd/system/redis_exporter.service
    print_message "✓ Redis Exporter service file removed" "$GREEN"
fi

if [ -f /usr/local/bin/redis_exporter ]; then
    rm -f /usr/local/bin/redis_exporter
    print_message "✓ Redis Exporter binary removed" "$GREEN"
else
    print_message "✓ Redis Exporter not found" "$YELLOW"
fi

# Step 6: Stop and remove Nginx Prometheus Exporter
print_message "\n[6/7] Removing Nginx Prometheus Exporter..." "$GREEN"

if systemctl is-active --quiet nginx-prometheus-exporter; then
    systemctl stop nginx-prometheus-exporter
    systemctl disable nginx-prometheus-exporter
    print_message "✓ Nginx Exporter service stopped" "$GREEN"
fi

if [ -f /etc/systemd/system/nginx-prometheus-exporter.service ]; then
    rm -f /etc/systemd/system/nginx-prometheus-exporter.service
    print_message "✓ Nginx Exporter service file removed" "$GREEN"
fi

if [ -f /usr/local/bin/nginx-prometheus-exporter ]; then
    rm -f /usr/local/bin/nginx-prometheus-exporter
    print_message "✓ Nginx Exporter binary removed" "$GREEN"
else
    print_message "✓ Nginx Exporter not found" "$YELLOW"
fi

# Remove nginx stub_status config if exists
if [ -f /etc/nginx/sites-enabled/stub_status ]; then
    rm -f /etc/nginx/sites-enabled/stub_status
    rm -f /etc/nginx/sites-available/stub_status
    nginx -t && nginx -s reload 2>/dev/null || true
    print_message "✓ Nginx stub_status configuration removed" "$GREEN"
fi

# Step 7: Clean up systemd and firewall
print_message "\n[7/7] Cleaning up system configuration..." "$GREEN"

# Reload systemd
systemctl daemon-reload
print_message "✓ Systemd daemon reloaded" "$GREEN"

# Remove firewall rules (if ufw is installed)
if command -v ufw &> /dev/null; then
    # Remove monitoring-related rules
    ufw --force delete allow from 10.0.0.7 to any port 9100 2>/dev/null || true
    ufw --force delete allow from 10.0.0.7 to any port 9280 2>/dev/null || true
    ufw --force delete allow from 10.0.0.7 to any port 8080 2>/dev/null || true
    ufw --force delete allow from 10.0.0.7 to any port 9113 2>/dev/null || true
    ufw --force delete allow from 10.0.0.7 to any port 9187 2>/dev/null || true
    ufw --force delete allow from 10.0.0.7 to any port 9121 2>/dev/null || true
    ufw --force delete allow from 10.0.0.7 to any port 2020 2>/dev/null || true
    ufw reload 2>/dev/null || true
    print_message "✓ Firewall rules cleaned" "$GREEN"
else
    print_message "✓ UFW not installed" "$YELLOW"
fi

# Clean up temporary files
rm -f /tmp/node_exporter* 2>/dev/null || true
rm -f /tmp/postgres_exporter* 2>/dev/null || true
rm -f /tmp/redis_exporter* 2>/dev/null || true
rm -f /tmp/nginx-prometheus-exporter* 2>/dev/null || true
rm -f /tmp/setup_client_node.sh 2>/dev/null || true

print_separator
print_message "\n✅ CLEANUP COMPLETED SUCCESSFULLY!" "$GREEN"
print_separator

# Final verification
print_message "\n📊 Verification:" "$CYAN"
print_message "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" "$BLUE"

# Check if services are removed
echo -n "Node Exporter: "
if ! systemctl is-active --quiet node_exporter && [ ! -f /usr/local/bin/node_exporter ]; then
    print_message "REMOVED ✓" "$GREEN"
else
    print_message "Still present ✗" "$RED"
fi

echo -n "Fluent Bit: "
if ! systemctl is-active --quiet fluent-bit && ! command -v fluent-bit &> /dev/null; then
    print_message "REMOVED ✓" "$GREEN"
else
    print_message "Still present ✗" "$RED"
fi

echo -n "cAdvisor: "
if ! docker ps 2>/dev/null | grep -q cadvisor; then
    print_message "REMOVED ✓" "$GREEN"
else
    print_message "Still present ✗" "$RED"
fi

echo -n "PostgreSQL Exporter: "
if ! systemctl is-active --quiet postgres_exporter && [ ! -f /usr/local/bin/postgres_exporter ]; then
    print_message "REMOVED ✓" "$GREEN"
else
    print_message "Still present ✗" "$RED"
fi

echo -n "Redis Exporter: "
if ! systemctl is-active --quiet redis_exporter && [ ! -f /usr/local/bin/redis_exporter ]; then
    print_message "REMOVED ✓" "$GREEN"
else
    print_message "Still present ✗" "$RED"
fi

echo -n "Nginx Exporter: "
if ! systemctl is-active --quiet nginx-prometheus-exporter && [ ! -f /usr/local/bin/nginx-prometheus-exporter ]; then
    print_message "REMOVED ✓" "$GREEN"
else
    print_message "Still present ✗" "$RED"
fi

print_separator
print_message "\n🎯 Next Steps:" "$YELLOW"
print_message "1. If you want to reinstall monitoring, run setup_client_node.sh" "$NC"
print_message "2. Check that your application services are still running" "$NC"
print_message "3. Verify no important data was affected" "$NC"
print_separator