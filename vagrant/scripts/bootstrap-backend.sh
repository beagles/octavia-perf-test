#!/bin/bash
# Bootstrap script for backend HTTP servers
#
# Environment variables:
#   BACKEND_INDEX - Index of this backend server (1, 2, 3, ...)
#   BACKEND_PORT - Port to listen on (default: 80)

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

BACKEND_INDEX="${BACKEND_INDEX:-1}"
BACKEND_PORT="${BACKEND_PORT:-80}"

log_info "Bootstrapping backend server ${BACKEND_INDEX}..."

# Install common packages
install_common_packages

# Install nginx
log_info "Installing nginx..."
apt-get install -y -qq nginx

# Create test content with server identification
log_info "Configuring nginx..."
cat > /var/www/html/index.html <<EOF
<!DOCTYPE html>
<html>
<head>
    <title>Backend Server ${BACKEND_INDEX}</title>
</head>
<body>
    <h1>Backend Server ${BACKEND_INDEX}</h1>
    <p>Hostname: $(hostname)</p>
    <p>IP: $(hostname -I | awk '{print $1}')</p>
    <p>Time: <span id="time"></span></p>
    <script>document.getElementById('time').innerHTML = new Date().toISOString();</script>
</body>
</html>
EOF

# Create health check endpoint
mkdir -p /var/www/html/health
cat > /var/www/html/health/index.html <<EOF
{"status": "healthy", "server": "backend-${BACKEND_INDEX}"}
EOF

# Create API endpoint for POST testing
mkdir -p /var/www/html/api
cat > /var/www/html/api/data <<EOF
{"received": true, "server": "backend-${BACKEND_INDEX}"}
EOF

# Create large file for download testing (1MB)
dd if=/dev/urandom of=/var/www/html/large_file bs=1M count=1 2>/dev/null

# Create variable size endpoints
for size in 1 10 100 1000; do
    dd if=/dev/urandom of=/var/www/html/file_${size}k bs=1K count=${size} 2>/dev/null
done

# Configure nginx
cat > /etc/nginx/sites-available/default <<EOF
server {
    listen ${BACKEND_PORT} default_server;
    listen [::]:${BACKEND_PORT} default_server;

    root /var/www/html;
    index index.html;

    server_name _;

    # Add server identification header
    add_header X-Backend-Server "backend-${BACKEND_INDEX}";

    location / {
        try_files \$uri \$uri/ =404;
    }

    location /health {
        default_type application/json;
        try_files \$uri \$uri/ =404;
    }

    location /api/data {
        default_type application/json;
        # Echo back POST data (simple implementation)
        if (\$request_method = POST) {
            return 200 '{"received": true, "server": "backend-${BACKEND_INDEX}"}';
        }
        try_files \$uri =404;
    }

    # Status page for monitoring
    location /nginx_status {
        stub_status on;
        allow 192.168.0.0/16;
        deny all;
    }
}
EOF

# Enable and restart nginx
systemctl enable nginx
systemctl restart nginx

# Install Python for potential custom test servers
log_info "Setting up Python test server as alternative..."
cat > /opt/simple_server.py <<'PYEOF'
#!/usr/bin/env python3
"""Simple HTTP server with metrics for testing."""

import http.server
import socketserver
import json
import time
import os
import threading
from collections import defaultdict

PORT = int(os.environ.get('BACKEND_PORT', 8080))
BACKEND_INDEX = os.environ.get('BACKEND_INDEX', '1')

# Simple metrics
metrics = defaultdict(int)
metrics_lock = threading.Lock()

class MetricsHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        with metrics_lock:
            metrics['requests'] += 1

        if self.path == '/health':
            self.send_json({'status': 'healthy', 'server': f'backend-{BACKEND_INDEX}'})
        elif self.path == '/metrics':
            with metrics_lock:
                self.send_json(dict(metrics))
        else:
            super().do_GET()

    def do_POST(self):
        with metrics_lock:
            metrics['requests'] += 1
            metrics['posts'] += 1

        content_length = int(self.headers.get('Content-Length', 0))
        with metrics_lock:
            metrics['bytes_received'] += content_length

        self.send_json({
            'received': True,
            'server': f'backend-{BACKEND_INDEX}',
            'bytes': content_length
        })

    def send_json(self, data):
        response = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(response))
        self.send_header('X-Backend-Server', f'backend-{BACKEND_INDEX}')
        self.end_headers()
        self.wfile.write(response)

if __name__ == '__main__':
    with socketserver.TCPServer(("", PORT), MetricsHandler) as httpd:
        print(f"Backend {BACKEND_INDEX} serving on port {PORT}")
        httpd.serve_forever()
PYEOF
chmod +x /opt/simple_server.py

# Create systemd service for Python server (alternative to nginx)
cat > /etc/systemd/system/python-backend.service <<EOF
[Unit]
Description=Python Backend Server
After=network.target

[Service]
Type=simple
Environment=BACKEND_PORT=8080
Environment=BACKEND_INDEX=${BACKEND_INDEX}
ExecStart=/usr/bin/python3 /opt/simple_server.py
Restart=always
WorkingDirectory=/var/www/html

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
# Note: Not starting by default, nginx is primary

log_info "Backend server ${BACKEND_INDEX} setup complete!"
log_info "nginx listening on port ${BACKEND_PORT}"
