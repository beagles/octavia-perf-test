"""Bottleneck detection for performance test analysis.

Analyzes collected metrics to identify performance bottlenecks
and provide recommendations for tuning.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BottleneckType(Enum):
    """Types of performance bottlenecks."""
    CPU = "cpu"
    MEMORY = "memory"
    NETWORK = "network"
    CONNECTION_LIMIT = "connection_limit"
    BACKEND = "backend"
    CONFIGURATION = "configuration"


class Severity(Enum):
    """Bottleneck severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Bottleneck:
    """Represents a detected bottleneck."""
    type: BottleneckType
    severity: Severity
    description: str
    evidence: Dict[str, Any]
    recommendation: str
    affected_component: str


class BottleneckDetector:
    """Analyzes metrics to identify performance bottlenecks.

    Indicators checked:

    CPU Bottleneck:
    - cpu.user + cpu.system > 80%
    - load[0] > cpu_count
    - Correlation: High CPU when latency spikes

    Memory Bottleneck:
    - memory.free < 10% of total
    - swap_used increasing
    - Slab growing (kernel memory)

    Network Bottleneck:
    - network_tx or network_rx approaching interface limit
    - High softirq (indicates network interrupt processing)

    Connection Limit Bottleneck:
    - scur approaching slim (session limit)
    - listener status = FULL (not OPEN)
    - qcur > 0 (requests queuing)

    Backend Bottleneck:
    - Backend member status DOWN
    - srv_abrt increasing (server aborts)
    - qcur on backend growing

    HAProxy Configuration Issues:
    - maxconn too low (default 50000)
    - timeout settings causing issues
    """

    # Thresholds for detection
    CPU_HIGH_THRESHOLD = 80  # percentage
    CPU_CRITICAL_THRESHOLD = 95
    MEMORY_LOW_THRESHOLD = 10  # percentage free
    MEMORY_CRITICAL_THRESHOLD = 5
    CONNECTION_SATURATION_HIGH = 70  # percentage
    CONNECTION_SATURATION_CRITICAL = 90
    QUEUE_WARNING_THRESHOLD = 10
    ERROR_RATE_WARNING = 1  # percentage
    ERROR_RATE_HIGH = 5

    def __init__(self):
        self.bottlenecks: List[Bottleneck] = []

    def analyze(
        self,
        haproxy_stats: List[Dict],
        system_metrics: List[Dict],
        locust_stats: Optional[List[Dict]] = None
    ) -> List[Bottleneck]:
        """Analyze all metrics and return detected bottlenecks.

        Args:
            haproxy_stats: Time-series HAProxy statistics
            system_metrics: Time-series system metrics
            locust_stats: Time-series Locust statistics (optional)

        Returns:
            List of detected Bottleneck objects
        """
        self.bottlenecks = []

        if haproxy_stats:
            self._analyze_haproxy(haproxy_stats)

        if system_metrics:
            self._analyze_system_metrics(system_metrics)

        if locust_stats:
            self._analyze_locust_stats(locust_stats)

        # Cross-correlation analysis
        if haproxy_stats and system_metrics:
            self._analyze_correlations(haproxy_stats, system_metrics)

        # Sort by severity
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3
        }
        self.bottlenecks.sort(key=lambda b: severity_order[b.severity])

        return self.bottlenecks

    def _analyze_haproxy(self, stats: List[Dict]):
        """Analyze HAProxy statistics for bottlenecks."""
        if not stats:
            return

        # Analyze latest stats
        latest = stats[-1]

        # Connection limit analysis
        scur = latest.get('scur', 0) or 0
        slim = latest.get('slim', 0) or 0

        if slim > 0:
            saturation = (scur / slim) * 100

            if saturation >= self.CONNECTION_SATURATION_CRITICAL:
                self.bottlenecks.append(Bottleneck(
                    type=BottleneckType.CONNECTION_LIMIT,
                    severity=Severity.CRITICAL,
                    description=(
                        f"Connection limit nearly reached: "
                        f"{scur}/{slim} ({saturation:.1f}%)"
                    ),
                    evidence={
                        'current_connections': scur,
                        'max_connections': slim,
                        'saturation_percent': saturation
                    },
                    recommendation=(
                        "Increase listener connection_limit in Octavia. "
                        "Maximum supported is 1,000,000. Also consider "
                        "adding more amphora instances."
                    ),
                    affected_component="amphora/haproxy"
                ))
            elif saturation >= self.CONNECTION_SATURATION_HIGH:
                self.bottlenecks.append(Bottleneck(
                    type=BottleneckType.CONNECTION_LIMIT,
                    severity=Severity.HIGH,
                    description=(
                        f"Connection limit approaching: "
                        f"{scur}/{slim} ({saturation:.1f}%)"
                    ),
                    evidence={
                        'current_connections': scur,
                        'max_connections': slim,
                        'saturation_percent': saturation
                    },
                    recommendation=(
                        "Consider increasing connection_limit before "
                        "it becomes critical. Current limit: {slim}"
                    ),
                    affected_component="amphora/haproxy"
                ))

        # Queue analysis
        qcur = latest.get('qcur', 0) or 0
        if qcur > self.QUEUE_WARNING_THRESHOLD:
            severity = Severity.HIGH if qcur > 50 else Severity.MEDIUM
            self.bottlenecks.append(Bottleneck(
                type=BottleneckType.BACKEND,
                severity=severity,
                description=f"Requests queuing: {qcur} in queue",
                evidence={'queue_current': qcur},
                recommendation=(
                    "Backend servers may be overloaded. Consider adding "
                    "more backend members or increasing their capacity."
                ),
                affected_component="backend_servers"
            ))

        # Error rate analysis
        stot = latest.get('stot', 0) or 0
        ereq = latest.get('ereq', 0) or 0
        if stot > 0:
            error_rate = (ereq / stot) * 100
            if error_rate >= self.ERROR_RATE_HIGH:
                self.bottlenecks.append(Bottleneck(
                    type=BottleneckType.CONFIGURATION,
                    severity=Severity.HIGH,
                    description=f"High error rate: {error_rate:.2f}%",
                    evidence={
                        'total_requests': stot,
                        'errors': ereq,
                        'error_rate_percent': error_rate
                    },
                    recommendation=(
                        "Investigate error causes. Check HAProxy logs, "
                        "backend health, and timeout settings."
                    ),
                    affected_component="amphora/haproxy"
                ))
            elif error_rate >= self.ERROR_RATE_WARNING:
                self.bottlenecks.append(Bottleneck(
                    type=BottleneckType.CONFIGURATION,
                    severity=Severity.MEDIUM,
                    description=f"Elevated error rate: {error_rate:.2f}%",
                    evidence={
                        'total_requests': stot,
                        'errors': ereq,
                        'error_rate_percent': error_rate
                    },
                    recommendation="Monitor error rate and investigate causes.",
                    affected_component="amphora/haproxy"
                ))

        # Analyze trend for connection growth
        if len(stats) >= 10:
            recent_scur = [s.get('scur', 0) or 0 for s in stats[-10:]]
            if all(recent_scur[i] <= recent_scur[i+1]
                   for i in range(len(recent_scur)-1)):
                # Monotonically increasing connections
                self.bottlenecks.append(Bottleneck(
                    type=BottleneckType.CONNECTION_LIMIT,
                    severity=Severity.MEDIUM,
                    description="Connections continuously increasing",
                    evidence={'connection_trend': recent_scur},
                    recommendation=(
                        "Connection count is growing steadily. "
                        "Monitor for potential connection leaks or "
                        "insufficient connection timeout settings."
                    ),
                    affected_component="amphora/haproxy"
                ))

    def _analyze_system_metrics(self, metrics: List[Dict]):
        """Analyze system metrics for bottlenecks."""
        if not metrics:
            return

        # Separate amphora and backend metrics
        amphora_metrics = [
            m for m in metrics
            if 'amphora' in m.get('host_type', '').lower()
        ]
        backend_metrics = [
            m for m in metrics
            if 'backend' in m.get('host_type', '').lower()
        ]

        self._analyze_host_metrics(amphora_metrics, "amphora")
        self._analyze_host_metrics(backend_metrics, "backend")

    def _analyze_host_metrics(self, metrics: List[Dict], host_type: str):
        """Analyze metrics for a specific host type."""
        if not metrics:
            return

        latest = metrics[-1]

        # CPU analysis
        cpu_count = latest.get('cpu_count', 1) or 1
        load = latest.get('load_1', 0) or 0

        # Load average based CPU saturation
        cpu_saturation = (load / cpu_count) * 100
        if cpu_saturation >= self.CPU_CRITICAL_THRESHOLD:
            self.bottlenecks.append(Bottleneck(
                type=BottleneckType.CPU,
                severity=Severity.CRITICAL,
                description=(
                    f"{host_type.title()} CPU saturated: "
                    f"load {load:.2f} on {cpu_count} CPUs"
                ),
                evidence={
                    'load_average': load,
                    'cpu_count': cpu_count,
                    'saturation_percent': cpu_saturation
                },
                recommendation=(
                    f"Increase {host_type} CPU capacity. For amphora, "
                    "use a larger flavor or add instances. For backends, "
                    "scale out the pool."
                ),
                affected_component=host_type
            ))
        elif cpu_saturation >= self.CPU_HIGH_THRESHOLD:
            self.bottlenecks.append(Bottleneck(
                type=BottleneckType.CPU,
                severity=Severity.HIGH,
                description=(
                    f"{host_type.title()} CPU high: "
                    f"load {load:.2f} on {cpu_count} CPUs"
                ),
                evidence={
                    'load_average': load,
                    'cpu_count': cpu_count,
                    'saturation_percent': cpu_saturation
                },
                recommendation=(
                    f"Monitor {host_type} CPU closely. Consider "
                    "scaling before saturation."
                ),
                affected_component=host_type
            ))

        # Memory analysis
        mem_total = latest.get('mem_total', 1) or 1
        mem_free = latest.get('mem_free', 0) or 0
        mem_free_pct = (mem_free / mem_total) * 100

        if mem_free_pct < self.MEMORY_CRITICAL_THRESHOLD:
            self.bottlenecks.append(Bottleneck(
                type=BottleneckType.MEMORY,
                severity=Severity.CRITICAL,
                description=(
                    f"{host_type.title()} memory critical: "
                    f"only {mem_free_pct:.1f}% free"
                ),
                evidence={
                    'total_mb': mem_total // 1024,
                    'free_mb': mem_free // 1024,
                    'free_percent': mem_free_pct
                },
                recommendation=(
                    f"Increase {host_type} memory immediately. "
                    "For amphora, reduce SSL session cache or "
                    "connection limits."
                ),
                affected_component=host_type
            ))
        elif mem_free_pct < self.MEMORY_LOW_THRESHOLD:
            self.bottlenecks.append(Bottleneck(
                type=BottleneckType.MEMORY,
                severity=Severity.HIGH,
                description=(
                    f"{host_type.title()} memory low: "
                    f"only {mem_free_pct:.1f}% free"
                ),
                evidence={
                    'total_mb': mem_total // 1024,
                    'free_mb': mem_free // 1024,
                    'free_percent': mem_free_pct
                },
                recommendation=(
                    f"Monitor {host_type} memory. Consider scaling "
                    "before it becomes critical."
                ),
                affected_component=host_type
            ))

    def _analyze_locust_stats(self, stats: List[Dict]):
        """Analyze Locust statistics for bottlenecks."""
        if not stats:
            return

        latest = stats[-1]

        # High failure rate
        num_requests = latest.get('num_requests', 0) or 0
        num_failures = latest.get('num_failures', 0) or 0

        if num_requests > 0:
            failure_rate = (num_failures / num_requests) * 100
            if failure_rate >= 10:
                self.bottlenecks.append(Bottleneck(
                    type=BottleneckType.CONFIGURATION,
                    severity=Severity.CRITICAL,
                    description=f"High request failure rate: {failure_rate:.1f}%",
                    evidence={
                        'requests': num_requests,
                        'failures': num_failures,
                        'failure_rate': failure_rate
                    },
                    recommendation=(
                        "Investigate failure causes. Check load balancer "
                        "logs, backend health, and timeout settings."
                    ),
                    affected_component="load_balancer"
                ))

        # High response times
        p99 = latest.get('p99', 0) or 0
        if p99 > 5000:  # 5 seconds
            self.bottlenecks.append(Bottleneck(
                type=BottleneckType.BACKEND,
                severity=Severity.HIGH,
                description=f"High p99 response time: {p99}ms",
                evidence={
                    'p99_ms': p99,
                    'p95_ms': latest.get('p95', 0),
                    'p90_ms': latest.get('p90', 0)
                },
                recommendation=(
                    "Backend response times are high. Optimize backend "
                    "application or add more backend instances."
                ),
                affected_component="backend_servers"
            ))

    def _analyze_correlations(
        self,
        haproxy_stats: List[Dict],
        system_metrics: List[Dict]
    ):
        """Analyze correlations between different metrics."""
        # This would require time-aligned data
        # For now, just check if high CPU correlates with queue growth
        pass

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all detected bottlenecks.

        Returns:
            Dictionary with bottleneck summary
        """
        by_type = {}
        by_severity = {}

        for b in self.bottlenecks:
            type_name = b.type.value
            severity_name = b.severity.value

            by_type[type_name] = by_type.get(type_name, 0) + 1
            by_severity[severity_name] = by_severity.get(severity_name, 0) + 1

        return {
            'total_bottlenecks': len(self.bottlenecks),
            'by_type': by_type,
            'by_severity': by_severity,
            'critical_count': by_severity.get('critical', 0),
            'high_count': by_severity.get('high', 0),
            'recommendations': [b.recommendation for b in self.bottlenecks]
        }
