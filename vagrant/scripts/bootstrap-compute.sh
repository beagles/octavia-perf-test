#!/bin/bash
# Bootstrap script for Nova compute node
#
# This script sets up a compute node that will host amphora VMs.
#
# Environment variables:
#   CONTROLLER_IP - IP address of the controller
#   COMPUTE_INDEX - Index of this compute node

set -e

# Inline common functions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

wait_for_apt() {
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
        log_info "Waiting for apt lock..."
        sleep 5
    done
}

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

CONTROLLER_IP="${CONTROLLER_IP:-192.168.150.10}"
COMPUTE_INDEX="${COMPUTE_INDEX:-1}"

log_info "Bootstrapping compute node ${COMPUTE_INDEX}..."
log_info "Controller IP: ${CONTROLLER_IP}"

# Install common packages
install_common_packages

# Check for nested virtualization support
log_info "Checking nested virtualization..."
if grep -E 'vmx|svm' /proc/cpuinfo > /dev/null; then
    log_info "Nested virtualization supported"
else
    log_warn "Nested virtualization may not be available"
fi

# Install KVM and libvirt
log_info "Installing KVM and libvirt..."
apt-get install -y -qq \
    qemu-kvm \
    libvirt-daemon-system \
    libvirt-clients \
    virtinst \
    bridge-utils \
    cpu-checker

# Verify KVM is working
if kvm-ok > /dev/null 2>&1; then
    log_info "KVM acceleration available"
else
    log_warn "KVM acceleration not available, VMs will be slow"
fi

# Enable and start libvirtd
systemctl enable libvirtd
systemctl start libvirtd

# Create stack user (for DevStack compute node setup)
log_info "Creating stack user..."
if ! id stack &>/dev/null; then
    useradd -s /bin/bash -d /opt/stack -m stack
    echo "stack ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/stack
    chmod 0440 /etc/sudoers.d/stack
fi

# Add stack to libvirt group
usermod -a -G libvirt stack

# Clone DevStack for compute node
log_info "Cloning DevStack..."
if [ ! -d /opt/stack/devstack ]; then
    sudo -u stack git clone https://opendev.org/openstack/devstack /opt/stack/devstack
fi

# Create local.conf for compute node
log_info "Creating DevStack local.conf for compute node..."
COMPUTE_IP=$(hostname -I | awk '{print $1}')

cat > /opt/stack/devstack/local.conf <<EOF
[[local|localrc]]
# This is a compute node
HOST_IP=${COMPUTE_IP}
SERVICE_HOST=${CONTROLLER_IP}
MYSQL_HOST=${CONTROLLER_IP}
RABBIT_HOST=${CONTROLLER_IP}
GLANCE_HOST=${CONTROLLER_IP}

ADMIN_PASSWORD=secret
DATABASE_PASSWORD=secret
RABBIT_PASSWORD=secret
SERVICE_PASSWORD=secret

# Only run compute services
ENABLED_SERVICES=n-cpu,neutron

# Logging
LOGFILE=/opt/stack/logs/stack.sh.log
LOGDIR=/opt/stack/logs
LOG_COLOR=False

# Nova compute settings
NOVA_VNC_ENABLED=True
NOVNCPROXY_URL="http://${CONTROLLER_IP}:6080/vnc_auto.html"
VNCSERVER_LISTEN=\$HOST_IP
VNCSERVER_PROXYCLIENT_ADDRESS=\$HOST_IP
EOF

chown stack:stack /opt/stack/devstack/local.conf

# Create script to run DevStack
cat > /opt/stack/run_devstack.sh <<'EOF'
#!/bin/bash
cd /opt/stack/devstack
./stack.sh
EOF
chmod +x /opt/stack/run_devstack.sh
chown stack:stack /opt/stack/run_devstack.sh

log_info "Compute node ${COMPUTE_INDEX} bootstrap complete!"
log_info ""
log_info "To join the OpenStack cluster, run as stack user:"
log_info "  sudo -u stack /opt/stack/run_devstack.sh"
log_info ""
log_info "Note: Run this AFTER the controller DevStack is complete."
