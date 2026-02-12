"""System metrics collector for backend servers via SSH."""

import logging
import re
from typing import Any, Dict, List, Optional

import paramiko

logger = logging.getLogger(__name__)


class SystemMetricsCollector:
    """Collects system metrics from Linux servers via SSH.

    Collects:
    - CPU usage from /proc/stat
    - Memory usage from /proc/meminfo
    - Network throughput from /proc/net/dev
    - Load averages from /proc/loadavg
    - Disk usage from df command

    Designed for collecting metrics from backend servers during load tests.
    """

    def __init__(
        self,
        host_ip: str,
        host_id: str,
        ssh_username: str = "vagrant",
        ssh_key_path: Optional[str] = None,
        ssh_password: Optional[str] = None,
        ssh_port: int = 22
    ):
        """Initialize the system metrics collector.

        Args:
            host_ip: IP address of the target host
            host_id: Identifier for this host (e.g., 'backend-1')
            ssh_username: SSH username
            ssh_key_path: Path to SSH private key
            ssh_password: SSH password (alternative to key)
            ssh_port: SSH port
        """
        self.host_ip = host_ip
        self.host_id = host_id
        self.ssh_username = ssh_username
        self.ssh_key_path = ssh_key_path
        self.ssh_password = ssh_password
        self.ssh_port = ssh_port
        self._ssh_client: Optional[paramiko.SSHClient] = None
        self._prev_cpu: Optional[Dict[str, int]] = None

    def connect(self):
        """Establish SSH connection."""
        if self._ssh_client is not None:
            return

        self._ssh_client = paramiko.SSHClient()
        self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            'hostname': self.host_ip,
            'port': self.ssh_port,
            'username': self.ssh_username,
        }

        if self.ssh_key_path:
            connect_kwargs['key_filename'] = self.ssh_key_path
        elif self.ssh_password:
            connect_kwargs['password'] = self.ssh_password

        try:
            self._ssh_client.connect(**connect_kwargs)
            logger.info(f"Connected to {self.host_id} ({self.host_ip})")
        except Exception as e:
            self._ssh_client = None
            logger.error(f"Failed to connect to {self.host_id}: {e}")
            raise

    def disconnect(self):
        """Close SSH connection."""
        if self._ssh_client:
            self._ssh_client.close()
            self._ssh_client = None
            logger.info(f"Disconnected from {self.host_id}")

    def _execute_command(self, command: str) -> str:
        """Execute a command via SSH and return output."""
        if self._ssh_client is None:
            self.connect()

        try:
            stdin, stdout, stderr = self._ssh_client.exec_command(command)
            return stdout.read().decode('utf-8').strip()
        except Exception as e:
            logger.error(f"Command execution failed on {self.host_id}: {e}")
            raise

    def get_cpu_stats(self) -> Dict[str, Any]:
        """Get CPU statistics from /proc/stat.

        Returns:
            Dictionary with CPU tick counts and calculated usage
        """
        output = self._execute_command('cat /proc/stat | head -1')

        # Parse: cpu  user nice system idle iowait irq softirq ...
        parts = output.split()
        if len(parts) < 8:
            return {}

        cpu_stats = {
            'user': int(parts[1]),
            'nice': int(parts[2]),
            'system': int(parts[3]),
            'idle': int(parts[4]),
            'iowait': int(parts[5]),
            'irq': int(parts[6]),
            'softirq': int(parts[7]),
        }
        cpu_stats['total'] = sum(cpu_stats.values())

        # Calculate CPU usage percentage if we have previous values
        usage_pct = None
        if self._prev_cpu:
            total_delta = cpu_stats['total'] - self._prev_cpu['total']
            idle_delta = cpu_stats['idle'] - self._prev_cpu['idle']
            if total_delta > 0:
                usage_pct = ((total_delta - idle_delta) / total_delta) * 100

        self._prev_cpu = cpu_stats.copy()

        return {
            **cpu_stats,
            'usage_percent': usage_pct
        }

    def get_cpu_count(self) -> int:
        """Get number of CPU cores."""
        output = self._execute_command('nproc')
        return int(output) if output.isdigit() else 1

    def get_memory_stats(self) -> Dict[str, int]:
        """Get memory statistics from /proc/meminfo.

        Returns:
            Dictionary with memory stats in KB
        """
        output = self._execute_command('cat /proc/meminfo')

        result = {}
        re_parser = re.compile(r'^(?P<key>\S+):\s*(?P<value>\d+)')

        for line in output.split('\n'):
            match = re_parser.match(line)
            if match:
                key, value = match.groups()
                # Remove trailing 'kB' if present in key
                key = key.rstrip(':')
                result[key] = int(value)

        return {
            'total': result.get('MemTotal', 0),
            'free': result.get('MemFree', 0),
            'available': result.get('MemAvailable', 0),
            'buffers': result.get('Buffers', 0),
            'cached': result.get('Cached', 0),
            'swap_total': result.get('SwapTotal', 0),
            'swap_free': result.get('SwapFree', 0),
            'swap_used': result.get('SwapTotal', 0) - result.get('SwapFree', 0)
        }

    def get_load_average(self) -> List[float]:
        """Get load averages from /proc/loadavg.

        Returns:
            List of [1min, 5min, 15min] load averages
        """
        output = self._execute_command('cat /proc/loadavg')
        parts = output.split()
        return [float(parts[0]), float(parts[1]), float(parts[2])]

    def get_network_stats(self) -> Dict[str, Dict[str, int]]:
        """Get network interface statistics from /proc/net/dev.

        Returns:
            Dictionary of interface -> {rx_bytes, tx_bytes, ...}
        """
        output = self._execute_command('cat /proc/net/dev')

        result = {}
        for line in output.split('\n')[2:]:  # Skip header lines
            if ':' not in line:
                continue

            parts = line.split(':')
            interface = parts[0].strip()
            values = parts[1].split()

            if len(values) >= 10:
                result[interface] = {
                    'rx_bytes': int(values[0]),
                    'rx_packets': int(values[1]),
                    'rx_errors': int(values[2]),
                    'rx_dropped': int(values[3]),
                    'tx_bytes': int(values[8]),
                    'tx_packets': int(values[9]),
                    'tx_errors': int(values[10]),
                    'tx_dropped': int(values[11])
                }

        return result

    def get_disk_usage(self, path: str = '/') -> Dict[str, int]:
        """Get disk usage for a path.

        Args:
            path: Filesystem path to check

        Returns:
            Dictionary with used, available, total in bytes
        """
        output = self._execute_command(f'df -B1 {path} | tail -1')
        parts = output.split()

        if len(parts) >= 4:
            return {
                'total': int(parts[1]),
                'used': int(parts[2]),
                'available': int(parts[3])
            }
        return {}

    def get_process_count(self, process_name: str) -> int:
        """Count running processes matching a name.

        Args:
            process_name: Process name to count (e.g., 'nginx', 'haproxy')

        Returns:
            Number of matching processes
        """
        output = self._execute_command(f'pgrep -c {process_name} || echo 0')
        return int(output)

    def get_nginx_stats(self) -> Optional[Dict[str, Any]]:
        """Get nginx stub_status if available.

        Returns:
            Dictionary with nginx stats or None if not available
        """
        try:
            output = self._execute_command(
                'curl -s http://localhost/nginx_status 2>/dev/null'
            )
            if 'Active connections' not in output:
                return None

            stats = {}
            lines = output.split('\n')

            # Parse "Active connections: N"
            match = re.search(r'Active connections:\s*(\d+)', lines[0])
            if match:
                stats['active_connections'] = int(match.group(1))

            # Parse "server accepts handled requests"
            if len(lines) >= 3:
                values = lines[2].split()
                if len(values) >= 3:
                    stats['accepts'] = int(values[0])
                    stats['handled'] = int(values[1])
                    stats['requests'] = int(values[2])

            # Parse "Reading: X Writing: Y Waiting: Z"
            if len(lines) >= 4:
                match = re.search(
                    r'Reading:\s*(\d+)\s*Writing:\s*(\d+)\s*Waiting:\s*(\d+)',
                    lines[3]
                )
                if match:
                    stats['reading'] = int(match.group(1))
                    stats['writing'] = int(match.group(2))
                    stats['waiting'] = int(match.group(3))

            return stats
        except Exception:
            return None

    def collect(self) -> Dict[str, Any]:
        """Collect all system metrics.

        Returns:
            Dictionary with all collected metrics
        """
        try:
            cpu = self.get_cpu_stats()
            memory = self.get_memory_stats()
            load = self.get_load_average()
            network = self.get_network_stats()
            disk = self.get_disk_usage()

            # Calculate utilization percentages
            mem_util = 0
            if memory.get('total', 0) > 0:
                mem_available = memory.get('available', memory.get('free', 0))
                mem_util = (
                    (memory['total'] - mem_available) / memory['total'] * 100
                )

            disk_util = 0
            if disk.get('total', 0) > 0:
                disk_util = disk['used'] / disk['total'] * 100

            # Sum network stats across interfaces
            total_rx = sum(n.get('rx_bytes', 0) for n in network.values())
            total_tx = sum(n.get('tx_bytes', 0) for n in network.values())

            return {
                'host_id': self.host_id,
                'cpu': cpu,
                'cpu_count': self.get_cpu_count(),
                'memory': memory,
                'load': load,
                'networks': network,
                'disk': disk,
                'utilization': {
                    'cpu': cpu.get('usage_percent'),
                    'memory': mem_util,
                    'disk': disk_util
                },
                'totals': {
                    'network_rx': total_rx,
                    'network_tx': total_tx
                }
            }
        except Exception as e:
            logger.error(f"Failed to collect metrics from {self.host_id}: {e}")
            return {'host_id': self.host_id, 'error': str(e)}

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False


class MultiHostCollector:
    """Collect metrics from multiple hosts in parallel."""

    def __init__(self, hosts: List[Dict[str, Any]]):
        """Initialize with list of host configurations.

        Args:
            hosts: List of dicts with 'ip', 'id', and optional SSH params
        """
        self.collectors = []
        for host in hosts:
            collector = SystemMetricsCollector(
                host_ip=host['ip'],
                host_id=host['id'],
                ssh_username=host.get('username', 'vagrant'),
                ssh_key_path=host.get('ssh_key'),
                ssh_password=host.get('password')
            )
            self.collectors.append(collector)

    def connect_all(self):
        """Connect to all hosts."""
        for collector in self.collectors:
            try:
                collector.connect()
            except Exception as e:
                logger.error(
                    f"Failed to connect to {collector.host_id}: {e}"
                )

    def disconnect_all(self):
        """Disconnect from all hosts."""
        for collector in self.collectors:
            collector.disconnect()

    def collect_all(self) -> Dict[str, Dict[str, Any]]:
        """Collect metrics from all hosts.

        Returns:
            Dictionary mapping host_id to metrics
        """
        results = {}
        for collector in self.collectors:
            try:
                results[collector.host_id] = collector.collect()
            except Exception as e:
                results[collector.host_id] = {
                    'host_id': collector.host_id,
                    'error': str(e)
                }
        return results

    def __enter__(self):
        """Context manager entry."""
        self.connect_all()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect_all()
        return False
