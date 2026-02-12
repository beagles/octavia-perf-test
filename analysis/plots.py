"""Visualization utilities for performance test data.

Generates matplotlib charts for metrics visualization.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logger.warning("matplotlib not available, plotting disabled")


def ensure_matplotlib():
    """Check if matplotlib is available."""
    if not MATPLOTLIB_AVAILABLE:
        raise ImportError(
            "matplotlib is required for plotting. "
            "Install with: pip install matplotlib"
        )


class MetricsPlotter:
    """Creates visualizations for performance metrics."""

    def __init__(
        self,
        output_dir: str = "./reports/plots",
        figsize: Tuple[int, int] = (12, 6),
        dpi: int = 100
    ):
        """Initialize the plotter.

        Args:
            output_dir: Directory to save plot images
            figsize: Default figure size (width, height)
            dpi: Resolution for saved images
        """
        ensure_matplotlib()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.figsize = figsize
        self.dpi = dpi

        # Set style
        plt.style.use('seaborn-v0_8-whitegrid')

    def plot_connections_over_time(
        self,
        haproxy_stats: List[Dict],
        filename: str = "connections.png"
    ) -> str:
        """Plot connection metrics over time.

        Args:
            haproxy_stats: Time-series HAProxy statistics
            filename: Output filename

        Returns:
            Path to saved plot
        """
        if not haproxy_stats:
            return ""

        fig, ax = plt.subplots(figsize=self.figsize)

        # Extract data
        timestamps = [
            datetime.fromisoformat(s['timestamp'])
            for s in haproxy_stats
            if 'timestamp' in s
        ]
        current = [s.get('scur', 0) or 0 for s in haproxy_stats]
        limit = [s.get('slim', 0) or 0 for s in haproxy_stats]

        if not timestamps:
            # Use index as x-axis
            x = range(len(current))
            ax.plot(x, current, label='Current Connections', linewidth=2)
            if any(limit):
                ax.plot(x, limit, '--', label='Connection Limit',
                        linewidth=1, alpha=0.7)
            ax.set_xlabel('Sample')
        else:
            ax.plot(timestamps, current, label='Current Connections',
                    linewidth=2)
            if any(limit):
                ax.plot(timestamps, limit, '--', label='Connection Limit',
                        linewidth=1, alpha=0.7)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
            plt.xticks(rotation=45)

        ax.set_ylabel('Connections')
        ax.set_title('Connection Count Over Time')
        ax.legend()

        # Save
        filepath = self.output_dir / filename
        plt.tight_layout()
        plt.savefig(filepath, dpi=self.dpi)
        plt.close()

        return str(filepath)

    def plot_throughput(
        self,
        haproxy_stats: List[Dict],
        filename: str = "throughput.png"
    ) -> str:
        """Plot throughput metrics over time.

        Args:
            haproxy_stats: Time-series HAProxy statistics
            filename: Output filename

        Returns:
            Path to saved plot
        """
        if not haproxy_stats:
            return ""

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(self.figsize[0], 10))

        # Bytes
        bytes_in = [s.get('bin', 0) or 0 for s in haproxy_stats]
        bytes_out = [s.get('bout', 0) or 0 for s in haproxy_stats]
        x = range(len(bytes_in))

        ax1.plot(x, [b / 1024 / 1024 for b in bytes_in],
                 label='Bytes In (MB)', linewidth=2)
        ax1.plot(x, [b / 1024 / 1024 for b in bytes_out],
                 label='Bytes Out (MB)', linewidth=2)
        ax1.set_ylabel('Cumulative MB')
        ax1.set_title('Data Transfer')
        ax1.legend()

        # Requests
        requests = [s.get('req_tot', 0) or 0 for s in haproxy_stats]
        ax2.plot(x, requests, label='Total Requests',
                 linewidth=2, color='green')
        ax2.set_ylabel('Requests')
        ax2.set_xlabel('Sample')
        ax2.set_title('Request Count')
        ax2.legend()

        filepath = self.output_dir / filename
        plt.tight_layout()
        plt.savefig(filepath, dpi=self.dpi)
        plt.close()

        return str(filepath)

    def plot_system_utilization(
        self,
        system_metrics: List[Dict],
        host_type: str = "amphora",
        filename: str = "system_util.png"
    ) -> str:
        """Plot system utilization metrics.

        Args:
            system_metrics: Time-series system metrics
            host_type: Type of host to plot
            filename: Output filename

        Returns:
            Path to saved plot
        """
        if not system_metrics:
            return ""

        # Filter by host type
        metrics = [
            m for m in system_metrics
            if host_type.lower() in m.get('host_type', '').lower()
        ]

        if not metrics:
            return ""

        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(self.figsize[0], 12))

        x = range(len(metrics))

        # CPU (using load average as proxy)
        cpu_count = metrics[0].get('cpu_count', 1) or 1
        load = [m.get('load_1', 0) or 0 for m in metrics]
        cpu_util = [(l / cpu_count) * 100 for l in load]

        ax1.plot(x, cpu_util, label='CPU Utilization %', linewidth=2)
        ax1.axhline(y=80, color='orange', linestyle='--',
                    label='Warning (80%)', alpha=0.7)
        ax1.axhline(y=95, color='red', linestyle='--',
                    label='Critical (95%)', alpha=0.7)
        ax1.set_ylabel('CPU %')
        ax1.set_title(f'{host_type.title()} CPU Utilization')
        ax1.legend()
        ax1.set_ylim(0, 120)

        # Memory
        mem_total = [m.get('mem_total', 1) or 1 for m in metrics]
        mem_free = [m.get('mem_free', 0) or 0 for m in metrics]
        mem_util = [
            ((t - f) / t) * 100
            for t, f in zip(mem_total, mem_free)
        ]

        ax2.plot(x, mem_util, label='Memory Utilization %',
                 linewidth=2, color='purple')
        ax2.axhline(y=90, color='orange', linestyle='--',
                    label='Warning (90%)', alpha=0.7)
        ax2.set_ylabel('Memory %')
        ax2.set_title(f'{host_type.title()} Memory Utilization')
        ax2.legend()
        ax2.set_ylim(0, 100)

        # Load average
        ax3.plot(x, load, label='Load Average (1min)', linewidth=2)
        ax3.axhline(y=cpu_count, color='orange', linestyle='--',
                    label=f'CPU Count ({cpu_count})', alpha=0.7)
        ax3.set_ylabel('Load')
        ax3.set_xlabel('Sample')
        ax3.set_title(f'{host_type.title()} Load Average')
        ax3.legend()

        filepath = self.output_dir / filename
        plt.tight_layout()
        plt.savefig(filepath, dpi=self.dpi)
        plt.close()

        return str(filepath)

    def plot_response_times(
        self,
        locust_stats: List[Dict],
        filename: str = "response_times.png"
    ) -> str:
        """Plot response time percentiles over time.

        Args:
            locust_stats: Time-series Locust statistics
            filename: Output filename

        Returns:
            Path to saved plot
        """
        if not locust_stats:
            return ""

        fig, ax = plt.subplots(figsize=self.figsize)

        x = range(len(locust_stats))
        p50 = [s.get('p50', 0) or 0 for s in locust_stats]
        p90 = [s.get('p90', 0) or 0 for s in locust_stats]
        p95 = [s.get('p95', 0) or 0 for s in locust_stats]
        p99 = [s.get('p99', 0) or 0 for s in locust_stats]

        ax.plot(x, p50, label='p50', linewidth=2)
        ax.plot(x, p90, label='p90', linewidth=2)
        ax.plot(x, p95, label='p95', linewidth=2)
        ax.plot(x, p99, label='p99', linewidth=2)

        ax.set_ylabel('Response Time (ms)')
        ax.set_xlabel('Sample')
        ax.set_title('Response Time Percentiles Over Time')
        ax.legend()

        filepath = self.output_dir / filename
        plt.tight_layout()
        plt.savefig(filepath, dpi=self.dpi)
        plt.close()

        return str(filepath)

    def plot_error_rates(
        self,
        haproxy_stats: List[Dict],
        filename: str = "errors.png"
    ) -> str:
        """Plot error rates over time.

        Args:
            haproxy_stats: Time-series HAProxy statistics
            filename: Output filename

        Returns:
            Path to saved plot
        """
        if not haproxy_stats:
            return ""

        fig, ax = plt.subplots(figsize=self.figsize)

        x = range(len(haproxy_stats))
        errors = [s.get('ereq', 0) or 0 for s in haproxy_stats]
        total = [s.get('stot', 1) or 1 for s in haproxy_stats]
        error_rate = [(e / t) * 100 if t > 0 else 0
                      for e, t in zip(errors, total)]

        ax.plot(x, error_rate, label='Error Rate %',
                linewidth=2, color='red')
        ax.axhline(y=1, color='orange', linestyle='--',
                   label='Warning (1%)', alpha=0.7)
        ax.axhline(y=5, color='red', linestyle='--',
                   label='Critical (5%)', alpha=0.7)

        ax.set_ylabel('Error Rate %')
        ax.set_xlabel('Sample')
        ax.set_title('Request Error Rate Over Time')
        ax.legend()

        filepath = self.output_dir / filename
        plt.tight_layout()
        plt.savefig(filepath, dpi=self.dpi)
        plt.close()

        return str(filepath)

    def generate_all_plots(
        self,
        haproxy_stats: List[Dict],
        system_metrics: List[Dict],
        locust_stats: Optional[List[Dict]] = None,
        prefix: str = ""
    ) -> Dict[str, str]:
        """Generate all available plots.

        Args:
            haproxy_stats: HAProxy statistics
            system_metrics: System metrics
            locust_stats: Locust statistics (optional)
            prefix: Filename prefix

        Returns:
            Dictionary mapping plot name to file path
        """
        plots = {}

        if haproxy_stats:
            plots['connections'] = self.plot_connections_over_time(
                haproxy_stats, f"{prefix}connections.png"
            )
            plots['throughput'] = self.plot_throughput(
                haproxy_stats, f"{prefix}throughput.png"
            )
            plots['errors'] = self.plot_error_rates(
                haproxy_stats, f"{prefix}errors.png"
            )

        if system_metrics:
            plots['amphora_util'] = self.plot_system_utilization(
                system_metrics, "amphora", f"{prefix}amphora_util.png"
            )
            plots['backend_util'] = self.plot_system_utilization(
                system_metrics, "backend", f"{prefix}backend_util.png"
            )

        if locust_stats:
            plots['response_times'] = self.plot_response_times(
                locust_stats, f"{prefix}response_times.png"
            )

        return plots
