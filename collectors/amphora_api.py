"""Amphora REST API collector for system metrics."""

import logging
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class AmphoraAPICollector:
    """Collects system metrics from the Amphora REST API.

    The amphora agent provides system metrics via its REST API:
    - GET /1.0/info: Basic amphora info (hostname, versions)
    - GET /1.0/details: Full system metrics (CPU, memory, disk, network, load)

    API is served over HTTPS on port 9443 with client certificate auth.

    Metrics available from /1.0/details:
    - hostname: Amphora hostname
    - haproxy_version: HAProxy version string
    - api_version: Amphora agent API version
    - networks: {interface: {network_tx, network_rx}}
    - active: Whether amphora is active
    - haproxy_count: Number of running HAProxy processes
    - cpu_count: Number of CPU cores
    - cpu: {total, user, system, soft_irq}
    - memory: {total, free, buffers, cached, swap_used, shared, slab}
    - disk: {used, available}
    - load: [1min, 5min, 15min]
    - topology: SINGLE or ACTIVE_STANDBY
    - listeners: List of listener UUIDs
    """

    DEFAULT_PORT = 9443
    DEFAULT_TIMEOUT = 10

    def __init__(
        self,
        amphora_ip: str,
        client_cert_path: Optional[str] = None,
        client_key_path: Optional[str] = None,
        server_ca_path: Optional[str] = None,
        port: int = DEFAULT_PORT,
        timeout: int = DEFAULT_TIMEOUT,
        verify_ssl: bool = True
    ):
        """Initialize the Amphora API collector.

        Args:
            amphora_ip: IP address of the amphora
            client_cert_path: Path to client certificate for mTLS
            client_key_path: Path to client key (if separate from cert)
            server_ca_path: Path to CA cert to verify amphora server
            port: API port (default 9443)
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
        """
        self.amphora_ip = amphora_ip
        self.port = port
        self.timeout = timeout
        self.base_url = f"https://{amphora_ip}:{port}"

        # Configure session with TLS
        self.session = requests.Session()

        # Set up client certificate if provided
        if client_cert_path:
            if client_key_path:
                self.session.cert = (client_cert_path, client_key_path)
            else:
                self.session.cert = client_cert_path

        # Set up server verification
        if verify_ssl and server_ca_path:
            self.session.verify = server_ca_path
        elif not verify_ssl:
            self.session.verify = False
            # Disable SSL warnings when verification is off
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Set up retries
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        """Make an API request.

        Args:
            method: HTTP method
            path: API path (e.g., '/1.0/info')
            **kwargs: Additional requests kwargs

        Returns:
            JSON response as dictionary
        """
        url = f"{self.base_url}{path}"
        kwargs.setdefault('timeout', self.timeout)

        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise

    def get_info(self) -> Dict[str, Any]:
        """Get basic amphora information.

        Returns:
            Dictionary with hostname, haproxy_version, api_version
        """
        return self._request('GET', '/1.0/info')

    def get_details(self) -> Dict[str, Any]:
        """Get detailed amphora system metrics.

        Returns:
            Dictionary with full system metrics including:
            - hostname, haproxy_version, api_version
            - networks: {interface: {network_tx, network_rx}}
            - active: bool
            - haproxy_count: int
            - cpu_count: int
            - cpu: {total, user, system, soft_irq}
            - memory: {total, free, buffers, cached, swap_used, shared, slab}
            - disk: {used, available}
            - load: [1min, 5min, 15min]
            - topology: str
            - listeners: list
        """
        return self._request('GET', '/1.0/details')

    def get_listeners(self) -> Dict[str, Any]:
        """Get list of listeners on the amphora.

        Returns:
            Dictionary with listener information
        """
        return self._request('GET', '/1.0/listeners')

    def get_cpu_metrics(self) -> Dict[str, Any]:
        """Get CPU-related metrics.

        Returns:
            Dictionary with:
            - cpu_count: Number of CPU cores
            - cpu_user: User CPU ticks
            - cpu_system: System CPU ticks
            - cpu_softirq: Soft IRQ ticks
            - cpu_total: Total CPU ticks
            - load: [1min, 5min, 15min] load averages
        """
        details = self.get_details()

        cpu = details.get('cpu', {})
        load = details.get('load', [0, 0, 0])

        return {
            'cpu_count': details.get('cpu_count', 0),
            'cpu_user': int(cpu.get('user', 0)),
            'cpu_system': int(cpu.get('system', 0)),
            'cpu_softirq': int(cpu.get('soft_irq', 0)),
            'cpu_total': int(cpu.get('total', 0)),
            'load_1': float(load[0]) if load else 0,
            'load_5': float(load[1]) if len(load) > 1 else 0,
            'load_15': float(load[2]) if len(load) > 2 else 0
        }

    def get_memory_metrics(self) -> Dict[str, int]:
        """Get memory-related metrics.

        Returns:
            Dictionary with memory stats in KB:
            - total, free, buffers, cached, swap_used, shared, slab
        """
        details = self.get_details()
        memory = details.get('memory', {})

        return {
            'total': memory.get('total', 0),
            'free': memory.get('free', 0),
            'buffers': memory.get('buffers', 0),
            'cached': memory.get('cached', 0),
            'swap_used': memory.get('swap_used', 0),
            'shared': memory.get('shared', 0),
            'slab': memory.get('slab', 0)
        }

    def get_network_metrics(self) -> Dict[str, Dict[str, int]]:
        """Get network interface metrics.

        Returns:
            Dictionary with per-interface metrics:
            {interface_name: {network_tx: bytes, network_rx: bytes}}
        """
        details = self.get_details()
        return details.get('networks', {})

    def get_disk_metrics(self) -> Dict[str, int]:
        """Get disk usage metrics.

        Returns:
            Dictionary with disk stats in bytes:
            - used, available
        """
        details = self.get_details()
        return details.get('disk', {})

    def get_utilization(self) -> Dict[str, float]:
        """Calculate resource utilization percentages.

        Returns:
            Dictionary with utilization percentages:
            - cpu_utilization: Estimated CPU usage %
            - memory_utilization: Memory usage %
            - disk_utilization: Disk usage %
        """
        details = self.get_details()

        # CPU utilization estimate (load average / cpu_count)
        cpu_count = details.get('cpu_count', 1)
        load = details.get('load', [0])
        cpu_util = (float(load[0]) / cpu_count * 100) if cpu_count > 0 else 0

        # Memory utilization
        memory = details.get('memory', {})
        mem_total = memory.get('total', 1)
        mem_free = memory.get('free', 0)
        mem_buffers = memory.get('buffers', 0)
        mem_cached = memory.get('cached', 0)
        # Available memory = free + buffers + cached
        mem_available = mem_free + mem_buffers + mem_cached
        mem_util = ((mem_total - mem_available) / mem_total * 100) \
            if mem_total > 0 else 0

        # Disk utilization
        disk = details.get('disk', {})
        disk_used = disk.get('used', 0)
        disk_available = disk.get('available', 0)
        disk_total = disk_used + disk_available
        disk_util = (disk_used / disk_total * 100) if disk_total > 0 else 0

        return {
            'cpu_utilization': min(cpu_util, 100),
            'memory_utilization': min(mem_util, 100),
            'disk_utilization': min(disk_util, 100)
        }

    def collect(self) -> Dict[str, Any]:
        """Collect all metrics in one call.

        Returns:
            Dictionary with all amphora metrics
        """
        try:
            details = self.get_details()
            utilization = self.get_utilization()

            return {
                'hostname': details.get('hostname'),
                'haproxy_version': details.get('haproxy_version'),
                'api_version': details.get('api_version'),
                'active': details.get('active'),
                'haproxy_count': details.get('haproxy_count'),
                'topology': details.get('topology'),
                'cpu_count': details.get('cpu_count'),
                'cpu': details.get('cpu', {}),
                'memory': details.get('memory', {}),
                'disk': details.get('disk', {}),
                'load': details.get('load', []),
                'networks': details.get('networks', {}),
                'listeners': details.get('listeners', []),
                'utilization': utilization
            }
        except Exception as e:
            logger.error(f"Failed to collect amphora metrics: {e}")
            return {'error': str(e)}

    def is_healthy(self) -> bool:
        """Check if amphora is healthy.

        Returns:
            True if amphora is reachable and active
        """
        try:
            details = self.get_details()
            return details.get('active', False)
        except Exception:
            return False

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.session.close()
        return False
