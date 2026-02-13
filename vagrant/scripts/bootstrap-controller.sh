#!/bin/bash
# Bootstrap script for OpenStack controller VM
#
# This script sets up a minimal OpenStack environment using DevStack
# with Octavia for load balancing.
#
# Environment variables:
#   MGMT_IP - Management network IP of this controller
#   VIP_NETWORK - VIP network CIDR
#   MEMBER_NETWORK - Member network CIDR
#   DEVSTACK_BRANCH - DevStack branch to use
#   OCTAVIA_MGMT_SUBNET - Octavia management subnet
#   OCTAVIA_MGMT_SUBNET_START - Start of DHCP range
#   OCTAVIA_MGMT_SUBNET_END - End of DHCP range
#   OCTAVIA_HM_BIND_IP - Health manager bind IP
#   OCTAVIA_HM_PORT - Health manager port

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

# Default values
MGMT_IP="${MGMT_IP:-192.168.150.10}"
VIP_NETWORK="${VIP_NETWORK:-192.168.200.0/24}"
MEMBER_NETWORK="${MEMBER_NETWORK:-192.168.201.0/24}"
DEVSTACK_BRANCH="${DEVSTACK_BRANCH:-master}"
OCTAVIA_MGMT_SUBNET="${OCTAVIA_MGMT_SUBNET:-192.168.150.0/24}"
OCTAVIA_MGMT_SUBNET_START="${OCTAVIA_MGMT_SUBNET_START:-192.168.150.100}"
OCTAVIA_MGMT_SUBNET_END="${OCTAVIA_MGMT_SUBNET_END:-192.168.150.200}"
OCTAVIA_HM_BIND_IP="${OCTAVIA_HM_BIND_IP:-192.168.150.10}"
OCTAVIA_HM_PORT="${OCTAVIA_HM_PORT:-5555}"

log_info "Bootstrapping OpenStack controller..."
log_info "Management IP: ${MGMT_IP}"
log_info "VIP Network: ${VIP_NETWORK}"
log_info "Member Network: ${MEMBER_NETWORK}"

# Install common packages
install_common_packages

# Install additional dependencies for DevStack
log_info "Installing DevStack dependencies..."
apt-get install -y -qq \
    bridge-utils \
    ebtables \
    iptables \
    libvirt-clients \
    libvirt-daemon-system \
    qemu-kvm

# Create stack user
log_info "Creating stack user..."
if ! id stack &>/dev/null; then
    useradd -s /bin/bash -d /opt/stack -m stack
    echo "stack ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/stack
    chmod 0440 /etc/sudoers.d/stack
fi

# Clone DevStack
log_info "Cloning DevStack..."
if [ ! -d /opt/stack/devstack ]; then
    sudo -u stack git clone https://opendev.org/openstack/devstack /opt/stack/devstack
    cd /opt/stack/devstack
    sudo -u stack git checkout ${DEVSTACK_BRANCH}
fi

# Create local.conf for DevStack
log_info "Creating DevStack local.conf..."
cat > /opt/stack/devstack/local.conf <<EOF
[[local|localrc]]
# Basic settings
HOST_IP=${MGMT_IP}
SERVICE_HOST=${MGMT_IP}
ADMIN_PASSWORD=secret
DATABASE_PASSWORD=secret
RABBIT_PASSWORD=secret
SERVICE_PASSWORD=secret

# Configure Neutron with OVN
Q_AGENT=ovn
Q_ML2_PLUGIN_MECHANISM_DRIVERS=ovn
Q_ML2_PLUGIN_TYPE_DRIVERS=local,flat,vlan,geneve
Q_ML2_TENANT_NETWORK_TYPE="geneve"
ENABLE_CHASSIS_AS_GW=True

# Enable OVN services
enable_service ovn-northd
enable_service ovn-controller
enable_service networking-ovn-metadata-agent
enable_service q-svc
enable_service q-trunk
enable_service q-dns
enable_service q-port-forwarding
enable_service q-log

# Disable legacy Neutron services (not needed with OVN)
disable_service q-agt
disable_service q-l3
disable_service q-dhcp
disable_service q-meta
disable_service cinder c-sch c-api c-vol

# Disable services we don't need for perf testing
disable_service tempest
disable_service horizon

# Enable Octavia
enable_plugin octavia https://opendev.org/openstack/octavia ${DEVSTACK_BRANCH}
enable_service octavia
enable_service o-api
enable_service o-cw
enable_service o-hm
enable_service o-hk
enable_service o-da

# Octavia settings
OCTAVIA_NODE="api"
OCTAVIA_MGMT_SUBNET=${OCTAVIA_MGMT_SUBNET}
OCTAVIA_MGMT_SUBNET_START=${OCTAVIA_MGMT_SUBNET_START}
OCTAVIA_MGMT_SUBNET_END=${OCTAVIA_MGMT_SUBNET_END}

# Use the prebuilt amphora image for faster setup
# Set to False if you want to build your own
OCTAVIA_USE_PREGENERATED_CERTS=True

# Logging
LOGFILE=/opt/stack/logs/stack.sh.log
LOGDIR=/opt/stack/logs
LOG_COLOR=False

# Networking
FLOATING_RANGE=${VIP_NETWORK}
Q_FLOATING_ALLOCATION_POOL=start=192.168.200.50,end=192.168.200.100
PUBLIC_NETWORK_GATEWAY=192.168.200.1
Q_USE_SECGROUP=True
Q_L3_ENABLED=True

# Additional plugins for observability (optional)
# enable_plugin osprofiler https://opendev.org/openstack/osprofiler

[[post-config|\$OCTAVIA_CONF]]
[controller_worker]
amp_image_owner_id = admin

[health_manager]
bind_ip = ${OCTAVIA_HM_BIND_IP}
bind_port = ${OCTAVIA_HM_PORT}
heartbeat_interval = 5
health_check_interval = 5

[haproxy_amphora]
# Enable stats socket for metrics collection
haproxy_sock_path = /var/lib/octavia

[api_settings]
# Enable all providers
enabled_provider_drivers = amphora:Amphora driver
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

log_info "Controller bootstrap complete!"
log_info ""
log_info "To install OpenStack, run as stack user:"
log_info "  sudo -u stack /opt/stack/run_devstack.sh"
log_info ""
log_info "This will take 30-60 minutes to complete."
log_info "After installation, source /opt/stack/devstack/openrc admin admin"
