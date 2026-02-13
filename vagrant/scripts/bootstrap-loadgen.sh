#!/bin/bash
# Bootstrap script for load generator VM
#
# Installs Locust and metric collection tools

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

log_info "Bootstrapping load generator VM..."

# Install common packages
install_common_packages

# Install additional tools for metrics collection
log_info "Installing metrics collection tools..."
apt-get install -y -qq \
    python3-dev \
    libffi-dev \
    libssl-dev \
    build-essential

# Create virtual environment
log_info "Creating Python virtual environment..."
python3 -m venv /opt/perf-test-venv
source /opt/perf-test-venv/bin/activate

# Install Python dependencies
log_info "Installing Python dependencies..."
pip install --upgrade pip
pip install \
    locust \
    paramiko \
    requests \
    sqlalchemy \
    PyYAML \
    matplotlib \
    jinja2 \
    click \
    tabulate

# Install from the synced project directory if available
if [ -f /opt/octavia-perf-test/requirements.txt ]; then
    log_info "Installing project requirements..."
    pip install -r /opt/octavia-perf-test/requirements.txt
fi

# Create activation script
cat > /etc/profile.d/perf-test.sh <<'EOF'
# Activate performance test environment
alias activate-perf='source /opt/perf-test-venv/bin/activate'

# Add project bin to PATH if available
if [ -d /opt/octavia-perf-test/bin ]; then
    export PATH="/opt/octavia-perf-test/bin:$PATH"
fi
EOF

# Create convenience scripts
mkdir -p /opt/bin

# Script to run Locust
cat > /opt/bin/run-locust <<'EOF'
#!/bin/bash
source /opt/perf-test-venv/bin/activate
cd /opt/octavia-perf-test
exec locust "$@"
EOF
chmod +x /opt/bin/run-locust

# Script to run the performance test
cat > /opt/bin/run-perf-test <<'EOF'
#!/bin/bash
source /opt/perf-test-venv/bin/activate
cd /opt/octavia-perf-test
exec python bin/run-test.py "$@"
EOF
chmod +x /opt/bin/run-perf-test

# Add to PATH
echo 'export PATH="/opt/bin:$PATH"' >> /etc/profile.d/perf-test.sh

# Configure SSH for connecting to other VMs
log_info "Configuring SSH..."
mkdir -p /root/.ssh
chmod 700 /root/.ssh

# Generate SSH key if not exists
if [ ! -f /root/.ssh/id_rsa ]; then
    ssh-keygen -t rsa -b 4096 -N "" -f /root/.ssh/id_rsa
fi

# Create SSH config for easier access
cat > /root/.ssh/config <<EOF
Host *
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
EOF
chmod 600 /root/.ssh/config

# Create directory for test results
mkdir -p /var/lib/perf-test/{results,reports,metrics}
chmod 755 /var/lib/perf-test

log_info "Load generator setup complete!"
log_info "To activate the environment: source /opt/perf-test-venv/bin/activate"
log_info "Project directory: /opt/octavia-perf-test"
