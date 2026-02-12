#!/bin/bash
# Common functions for provisioning scripts

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Wait for apt lock to be released
wait_for_apt() {
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
        log_info "Waiting for apt lock..."
        sleep 5
    done
}

# Update and install common packages
install_common_packages() {
    wait_for_apt
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq \
        curl \
        wget \
        git \
        vim \
        htop \
        iotop \
        sysstat \
        net-tools \
        iputils-ping \
        dnsutils \
        socat \
        jq \
        python3 \
        python3-pip \
        python3-venv
}

# Configure SSH for easier access
configure_ssh() {
    # Allow password authentication for testing
    sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config
    systemctl restart sshd
}

# Set timezone
set_timezone() {
    timedatectl set-timezone UTC
}
