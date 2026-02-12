# Octavia Amphora Performance Testing Framework

A standalone performance testing framework for OpenStack Octavia's amphora load balancer driver.

## Features

- **Load Generation**: Locust-based HTTP/HTTPS load testing
- **Infrastructure**: Vagrant + libvirt/KVM standalone VMs
- **Metrics Collection**: Custom collectors for HAProxy stats, amphora API, and system metrics
- **Analysis**: Automated bottleneck detection and reporting

## Requirements

- Linux host with KVM/libvirt support
- Vagrant with libvirt provider
- Python 3.10+
- Nested virtualization enabled (for amphora VMs)

## Quick Start

### 1. Install Dependencies

```bash
# Install Vagrant and libvirt
sudo dnf install vagrant libvirt libvirt-devel  # Fedora/RHEL
sudo apt install vagrant libvirt-daemon-system libvirt-dev  # Ubuntu/Debian

# Install vagrant-libvirt plugin
vagrant plugin install vagrant-libvirt

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Configure the Environment

```bash
# Copy and edit the configuration
cp vagrant/config.yaml.example vagrant/config.yaml
vim vagrant/config.yaml
```

### 3. Start the VMs

```bash
cd vagrant
vagrant up
```

### 4. Run a Performance Test

```bash
./bin/run-test.py --config configs/test_profiles/medium_load.yaml
```

### 5. View the Report

Reports are generated in `./reports/` directory as HTML files.

## Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │                   Load Generator VM                  │
                    │  ┌─────────────┐  ┌──────────────────────────────┐  │
                    │  │   Locust    │  │     Metrics Collectors       │  │
                    │  │  Master +   │  │  - HAProxy Stats (SSH)       │  │
                    │  │  Workers    │  │  - Amphora API (TLS)         │  │
                    │  └──────┬──────┘  │  - System Metrics            │  │
                    │         │         └──────────────────────────────┘  │
                    └─────────┼───────────────────────────────────────────┘
                              │ HTTP Traffic
                              ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           VIP Network (192.168.200.0/24)                │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │   Amphora VM    │
                    │   (HAProxy)     │
                    │  VIP: x.x.x.50  │
                    └────────┬────────┘
                             │
┌────────────────────────────┼────────────────────────────────────────────┐
│                    Member Network (192.168.201.0/24)                    │
└────────────────────────────┼────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  Backend 1    │  │  Backend 2    │  │  Backend 3    │
│  (nginx)      │  │  (nginx)      │  │  (nginx)      │
└───────────────┘  └───────────────┘  └───────────────┘
```

## Directory Structure

```
octavia-perf-test/
├── vagrant/                    # VM infrastructure
│   ├── Vagrantfile
│   ├── config.yaml
│   └── scripts/                # Provisioning scripts
├── locust/                     # Load generation
│   ├── locustfile.py
│   └── scenarios/              # Test scenarios
├── collectors/                 # Metrics collection
│   ├── haproxy_stats.py
│   ├── amphora_api.py
│   ├── system_metrics.py
│   └── storage.py
├── analysis/                   # Analysis & reporting
│   ├── bottleneck_detector.py
│   └── report_generator.py
├── configs/                    # Test configurations
│   └── test_profiles/
├── bin/                        # CLI tools
│   └── run-test.py
└── docs/                       # Documentation
```

## Metrics Collected

### From HAProxy (via stats socket)

| Metric | Description |
|--------|-------------|
| `scur` | Current sessions |
| `slim` | Session limit (maxconn) |
| `stot` | Total sessions |
| `bin`/`bout` | Bytes in/out |
| `ereq` | Request errors |
| `req_rate` | Requests per second |
| `qcur` | Queue length |

### From Amphora API

| Metric | Description |
|--------|-------------|
| `cpu.user/system` | CPU usage |
| `memory.free/total` | Memory usage |
| `load` | 1/5/15 min averages |
| `networks.tx/rx` | Network throughput |

## Bottleneck Detection

The framework automatically identifies:

- **CPU Bottleneck**: High CPU usage, load > cpu_count
- **Memory Bottleneck**: Low free memory, swap usage
- **Connection Limit**: Sessions approaching maxconn
- **Network Bottleneck**: Interface saturation
- **Backend Issues**: Server errors, queue growth

## License

Apache License 2.0
