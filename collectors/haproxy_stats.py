"""HAProxy statistics collector via SSH and stats socket."""

import csv
import io
import logging
from typing import Any, Dict, List, Optional

import paramiko

logger = logging.getLogger(__name__)


class HAProxyStatsCollector:
    """Collects metrics from HAProxy stats socket via SSH.

    The HAProxy stats socket provides detailed metrics via the 'show stat'
    command. This collector SSHs into the amphora and queries the socket.

    Key metrics from HAProxy CSV output:
    - pxname: proxy name (frontend/backend/listener ID)
    - svname: server name (FRONTEND, BACKEND, or member name)
    - scur: current sessions
    - smax: max sessions
    - slim: session limit
    - stot: total sessions
    - bin: bytes in
    - bout: bytes out
    - dreq: denied requests
    - ereq: request errors
    - status: UP/DOWN/OPEN/FULL
    - weight: server weight
    - rate: sessions per second
    - rate_max: max sessions per second
    - hrsp_1xx through hrsp_5xx: HTTP response codes
    - req_rate: HTTP requests per second
    - req_tot: total HTTP requests
    - cli_abrt: client aborts
    - srv_abrt: server aborts
    - qcur: current queue length
    - qmax: max queue length

    Reference: http://cbonte.github.io/haproxy-dconv/configuration-1.4.html#9
    """

    # HAProxy socket path (from Octavia constants)
    SOCKET_PATH_TEMPLATE = "/var/lib/octavia/{lb_id}.sock"

    def __init__(
        self,
        amphora_ip: str,
        lb_id: str,
        ssh_username: str = "ubuntu",
        ssh_key_path: Optional[str] = None,
        ssh_password: Optional[str] = None,
        ssh_port: int = 22
    ):
        """Initialize the HAProxy stats collector.

        Args:
            amphora_ip: IP address of the amphora VM
            lb_id: Load balancer ID (for socket path)
            ssh_username: SSH username for amphora
            ssh_key_path: Path to SSH private key
            ssh_password: SSH password (alternative to key)
            ssh_port: SSH port (default 22)
        """
        self.amphora_ip = amphora_ip
        self.lb_id = lb_id
        self.socket_path = self.SOCKET_PATH_TEMPLATE.format(lb_id=lb_id)
        self.ssh_username = ssh_username
        self.ssh_key_path = ssh_key_path
        self.ssh_password = ssh_password
        self.ssh_port = ssh_port
        self._ssh_client: Optional[paramiko.SSHClient] = None

    def connect(self):
        """Establish SSH connection to amphora."""
        if self._ssh_client is not None:
            return

        self._ssh_client = paramiko.SSHClient()
        self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            'hostname': self.amphora_ip,
            'port': self.ssh_port,
            'username': self.ssh_username,
        }

        if self.ssh_key_path:
            connect_kwargs['key_filename'] = self.ssh_key_path
        elif self.ssh_password:
            connect_kwargs['password'] = self.ssh_password

        try:
            self._ssh_client.connect(**connect_kwargs)
            logger.info(f"Connected to amphora {self.amphora_ip}")
        except Exception as e:
            self._ssh_client = None
            logger.error(f"Failed to connect to amphora: {e}")
            raise

    def disconnect(self):
        """Close SSH connection."""
        if self._ssh_client:
            self._ssh_client.close()
            self._ssh_client = None
            logger.info(f"Disconnected from amphora {self.amphora_ip}")

    def _execute_command(self, command: str) -> str:
        """Execute a command via SSH and return output."""
        if self._ssh_client is None:
            self.connect()

        try:
            stdin, stdout, stderr = self._ssh_client.exec_command(command)
            output = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')

            if error and 'warning' not in error.lower():
                logger.warning(f"Command stderr: {error}")

            return output
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            raise

    def _query_socket(self, query: str) -> str:
        """Query the HAProxy stats socket.

        Args:
            query: HAProxy command (e.g., 'show stat', 'show info')

        Returns:
            Raw output from HAProxy
        """
        # Use socat to query the Unix socket
        command = f'echo "{query}" | sudo socat unix-connect:{self.socket_path} stdio'
        return self._execute_command(command)

    def show_info(self) -> Dict[str, str]:
        """Get HAProxy process information.

        Returns:
            Dictionary with HAProxy info (version, uptime, connections, etc.)
        """
        output = self._query_socket('show info')
        result = {}

        for line in output.strip().split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                result[key.strip()] = value.strip()

        return result

    def show_stat(
        self,
        proxy_iid: int = -1,
        object_type: int = -1,
        server_id: int = -1
    ) -> List[Dict[str, Any]]:
        """Get HAProxy statistics.

        Args:
            proxy_iid: Proxy ID (-1 for all)
            object_type: 1=frontends, 2=backends, 4=servers, -1=all
            server_id: Server ID (-1 for all)

        Returns:
            List of dictionaries with stats for each proxy/server
        """
        query = f'show stat {proxy_iid} {object_type} {server_id}'
        output = self._query_socket(query)

        # HAProxy CSV output starts with '# ' header
        if output.startswith('# '):
            output = output[2:]

        # Parse CSV
        reader = csv.DictReader(io.StringIO(output))
        stats = list(reader)

        # Filter out internal prometheus proxy stats
        stats = [s for s in stats if 'prometheus' not in s.get('pxname', '')]

        return stats

    def get_frontend_stats(self) -> List[Dict[str, Any]]:
        """Get frontend (listener) statistics.

        Returns:
            List of frontend stats dictionaries
        """
        stats = self.show_stat(object_type=1)  # 1 = frontends
        return [s for s in stats if s.get('svname') == 'FRONTEND']

    def get_backend_stats(self) -> List[Dict[str, Any]]:
        """Get backend (pool) statistics.

        Returns:
            List of backend stats dictionaries
        """
        stats = self.show_stat(object_type=2)  # 2 = backends
        return [s for s in stats if s.get('svname') == 'BACKEND']

    def get_server_stats(self) -> List[Dict[str, Any]]:
        """Get server (member) statistics.

        Returns:
            List of server stats dictionaries
        """
        stats = self.show_stat(object_type=4)  # 4 = servers
        return [s for s in stats
                if s.get('svname') not in ('FRONTEND', 'BACKEND')]

    def get_all_stats(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all statistics organized by type.

        Returns:
            Dictionary with 'frontends', 'backends', and 'servers' keys
        """
        all_stats = self.show_stat()

        return {
            'frontends': [s for s in all_stats
                          if s.get('svname') == 'FRONTEND'],
            'backends': [s for s in all_stats
                         if s.get('svname') == 'BACKEND'],
            'servers': [s for s in all_stats
                        if s.get('svname') not in ('FRONTEND', 'BACKEND')]
        }

    def get_connection_stats(self) -> Dict[str, Any]:
        """Get connection-related statistics summary.

        Returns:
            Dictionary with connection metrics
        """
        info = self.show_info()
        stats = self.get_frontend_stats()

        total_scur = sum(int(s.get('scur', 0) or 0) for s in stats)
        total_slim = sum(int(s.get('slim', 0) or 0) for s in stats)
        total_stot = sum(int(s.get('stot', 0) or 0) for s in stats)

        return {
            'current_connections': total_scur,
            'max_connections': total_slim,
            'total_connections': total_stot,
            'connection_rate': info.get('ConnRate', '0'),
            'max_connection_rate': info.get('MaxConnRate', '0'),
            'utilization_pct': (total_scur / total_slim * 100)
                               if total_slim > 0 else 0
        }

    def get_throughput_stats(self) -> Dict[str, int]:
        """Get throughput statistics.

        Returns:
            Dictionary with bytes_in, bytes_out, and requests_total
        """
        stats = self.get_frontend_stats()

        return {
            'bytes_in': sum(int(s.get('bin', 0) or 0) for s in stats),
            'bytes_out': sum(int(s.get('bout', 0) or 0) for s in stats),
            'requests_total': sum(int(s.get('req_tot', 0) or 0) for s in stats)
        }

    def get_error_stats(self) -> Dict[str, int]:
        """Get error statistics.

        Returns:
            Dictionary with various error counts
        """
        frontend_stats = self.get_frontend_stats()
        backend_stats = self.get_backend_stats()
        server_stats = self.get_server_stats()

        return {
            'request_errors': sum(
                int(s.get('ereq', 0) or 0) for s in frontend_stats
            ),
            'denied_requests': sum(
                int(s.get('dreq', 0) or 0) for s in frontend_stats
            ),
            'client_aborts': sum(
                int(s.get('cli_abrt', 0) or 0) for s in backend_stats
            ),
            'server_aborts': sum(
                int(s.get('srv_abrt', 0) or 0) for s in server_stats
            ),
            'connection_errors': sum(
                int(s.get('econ', 0) or 0) for s in server_stats
            ),
            'response_errors': sum(
                int(s.get('eresp', 0) or 0) for s in server_stats
            )
        }

    def get_http_response_codes(self) -> Dict[str, int]:
        """Get HTTP response code counts.

        Returns:
            Dictionary with counts for each HTTP response class
        """
        stats = self.get_frontend_stats()

        return {
            '1xx': sum(int(s.get('hrsp_1xx', 0) or 0) for s in stats),
            '2xx': sum(int(s.get('hrsp_2xx', 0) or 0) for s in stats),
            '3xx': sum(int(s.get('hrsp_3xx', 0) or 0) for s in stats),
            '4xx': sum(int(s.get('hrsp_4xx', 0) or 0) for s in stats),
            '5xx': sum(int(s.get('hrsp_5xx', 0) or 0) for s in stats)
        }

    def collect(self) -> Dict[str, Any]:
        """Collect all metrics in one call.

        Returns:
            Dictionary with all metrics organized by category
        """
        try:
            return {
                'info': self.show_info(),
                'raw_stats': self.show_stat(),
                'connections': self.get_connection_stats(),
                'throughput': self.get_throughput_stats(),
                'errors': self.get_error_stats(),
                'http_codes': self.get_http_response_codes()
            }
        except Exception as e:
            logger.error(f"Failed to collect HAProxy stats: {e}")
            return {'error': str(e)}

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False
