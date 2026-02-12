"""Report generator for performance test results.

Generates HTML reports with visualizations and analysis.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, BaseLoader

from .bottleneck_detector import BottleneckDetector, Bottleneck

logger = logging.getLogger(__name__)

# HTML template for the report
REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 20px;
        }
        h1 { font-size: 2em; margin-bottom: 10px; }
        h2 { color: #444; margin: 20px 0 15px; padding-bottom: 10px; border-bottom: 2px solid #eee; }
        h3 { color: #555; margin: 15px 0 10px; }

        .meta { opacity: 0.9; font-size: 0.9em; }

        .card {
            background: white;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }

        .metric-card {
            background: white;
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .metric-value {
            font-size: 2.5em;
            font-weight: bold;
            color: #667eea;
        }
        .metric-label {
            color: #666;
            font-size: 0.9em;
            margin-top: 5px;
        }

        .severity-critical { background: #fee2e2; border-left: 4px solid #dc2626; }
        .severity-high { background: #fef3c7; border-left: 4px solid #f59e0b; }
        .severity-medium { background: #dbeafe; border-left: 4px solid #3b82f6; }
        .severity-low { background: #d1fae5; border-left: 4px solid #10b981; }

        .bottleneck {
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 5px;
        }
        .bottleneck-type {
            font-weight: bold;
            text-transform: uppercase;
            font-size: 0.8em;
            opacity: 0.7;
        }
        .bottleneck-desc {
            font-size: 1.1em;
            margin: 5px 0;
        }
        .bottleneck-rec {
            font-style: italic;
            color: #555;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        th {
            background: #f8f9fa;
            font-weight: 600;
        }
        tr:hover { background: #f8f9fa; }

        .status-up { color: #10b981; }
        .status-down { color: #dc2626; }

        .chart-container {
            width: 100%;
            height: 300px;
            margin: 20px 0;
        }

        .summary-box {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 15px;
        }
        .summary-item {
            background: #f0f0f0;
            padding: 8px 15px;
            border-radius: 20px;
            font-size: 0.9em;
        }

        footer {
            text-align: center;
            padding: 20px;
            color: #666;
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <header>
        <h1>{{ title }}</h1>
        <div class="meta">
            <p>Test Run: {{ run_name }}</p>
            <p>Duration: {{ duration }}</p>
            <p>Generated: {{ generated_at }}</p>
        </div>
    </header>

    <!-- Summary Metrics -->
    <section class="grid">
        <div class="metric-card">
            <div class="metric-value">{{ summary.total_requests | default(0) | int }}</div>
            <div class="metric-label">Total Requests</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{{ "%.1f" | format(summary.requests_per_sec | default(0)) }}</div>
            <div class="metric-label">Requests/sec (avg)</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{{ "%.0f" | format(summary.avg_response_time | default(0)) }}ms</div>
            <div class="metric-label">Avg Response Time</div>
        </div>
        <div class="metric-card">
            <div class="metric-value">{{ "%.2f" | format(summary.error_rate | default(0)) }}%</div>
            <div class="metric-label">Error Rate</div>
        </div>
    </section>

    <!-- Bottleneck Analysis -->
    {% if bottlenecks %}
    <section class="card">
        <h2>Bottleneck Analysis</h2>
        <div class="summary-box">
            <span class="summary-item">{{ bottlenecks | length }} issues detected</span>
            {% if bottleneck_summary.critical_count %}
            <span class="summary-item" style="background: #fee2e2;">{{ bottleneck_summary.critical_count }} Critical</span>
            {% endif %}
            {% if bottleneck_summary.high_count %}
            <span class="summary-item" style="background: #fef3c7;">{{ bottleneck_summary.high_count }} High</span>
            {% endif %}
        </div>

        {% for b in bottlenecks %}
        <div class="bottleneck severity-{{ b.severity.value }}">
            <div class="bottleneck-type">{{ b.type.value }} - {{ b.severity.value }}</div>
            <div class="bottleneck-desc">{{ b.description }}</div>
            <div class="bottleneck-rec">Recommendation: {{ b.recommendation }}</div>
        </div>
        {% endfor %}
    </section>
    {% endif %}

    <!-- HAProxy Statistics -->
    {% if haproxy_stats %}
    <section class="card">
        <h2>Load Balancer Statistics</h2>

        <h3>Connection Summary</h3>
        <table>
            <tr>
                <th>Metric</th>
                <th>Value</th>
            </tr>
            <tr>
                <td>Peak Concurrent Connections</td>
                <td>{{ haproxy_summary.max_connections | default(0) }}</td>
            </tr>
            <tr>
                <td>Total Connections</td>
                <td>{{ haproxy_summary.total_connections | default(0) }}</td>
            </tr>
            <tr>
                <td>Connection Limit</td>
                <td>{{ haproxy_summary.connection_limit | default(0) }}</td>
            </tr>
            <tr>
                <td>Peak Utilization</td>
                <td>{{ "%.1f" | format(haproxy_summary.peak_utilization | default(0)) }}%</td>
            </tr>
        </table>

        <h3>Throughput</h3>
        <table>
            <tr>
                <th>Metric</th>
                <th>Value</th>
            </tr>
            <tr>
                <td>Total Bytes In</td>
                <td>{{ haproxy_summary.bytes_in | default(0) | filesizeformat }}</td>
            </tr>
            <tr>
                <td>Total Bytes Out</td>
                <td>{{ haproxy_summary.bytes_out | default(0) | filesizeformat }}</td>
            </tr>
            <tr>
                <td>Total Requests</td>
                <td>{{ haproxy_summary.total_requests | default(0) }}</td>
            </tr>
        </table>

        <h3>HTTP Response Codes</h3>
        <table>
            <tr>
                <th>Code</th>
                <th>Count</th>
                <th>Percentage</th>
            </tr>
            {% for code, count in haproxy_summary.http_codes.items() %}
            <tr>
                <td>{{ code }}xx</td>
                <td>{{ count }}</td>
                <td>{{ "%.1f" | format(count / haproxy_summary.total_requests * 100 if haproxy_summary.total_requests else 0) }}%</td>
            </tr>
            {% endfor %}
        </table>
    </section>
    {% endif %}

    <!-- System Metrics -->
    {% if system_summary %}
    <section class="card">
        <h2>System Resource Utilization</h2>

        <h3>Amphora</h3>
        <table>
            <tr>
                <th>Metric</th>
                <th>Average</th>
                <th>Peak</th>
            </tr>
            <tr>
                <td>CPU Utilization</td>
                <td>{{ "%.1f" | format(system_summary.amphora.avg_cpu | default(0)) }}%</td>
                <td>{{ "%.1f" | format(system_summary.amphora.max_cpu | default(0)) }}%</td>
            </tr>
            <tr>
                <td>Memory Utilization</td>
                <td>{{ "%.1f" | format(system_summary.amphora.avg_memory | default(0)) }}%</td>
                <td>{{ "%.1f" | format(system_summary.amphora.max_memory | default(0)) }}%</td>
            </tr>
            <tr>
                <td>Load Average (1min)</td>
                <td>{{ "%.2f" | format(system_summary.amphora.avg_load | default(0)) }}</td>
                <td>{{ "%.2f" | format(system_summary.amphora.max_load | default(0)) }}</td>
            </tr>
        </table>

        {% if system_summary.backend %}
        <h3>Backend Servers</h3>
        <table>
            <tr>
                <th>Metric</th>
                <th>Average</th>
                <th>Peak</th>
            </tr>
            <tr>
                <td>CPU Utilization</td>
                <td>{{ "%.1f" | format(system_summary.backend.avg_cpu | default(0)) }}%</td>
                <td>{{ "%.1f" | format(system_summary.backend.max_cpu | default(0)) }}%</td>
            </tr>
            <tr>
                <td>Memory Utilization</td>
                <td>{{ "%.1f" | format(system_summary.backend.avg_memory | default(0)) }}%</td>
                <td>{{ "%.1f" | format(system_summary.backend.max_memory | default(0)) }}%</td>
            </tr>
        </table>
        {% endif %}
    </section>
    {% endif %}

    <!-- Locust Statistics -->
    {% if locust_summary %}
    <section class="card">
        <h2>Load Test Results</h2>

        <h3>Response Time Percentiles</h3>
        <table>
            <tr>
                <th>Percentile</th>
                <th>Response Time (ms)</th>
            </tr>
            <tr><td>50th (Median)</td><td>{{ locust_summary.p50 | default(0) }}</td></tr>
            <tr><td>90th</td><td>{{ locust_summary.p90 | default(0) }}</td></tr>
            <tr><td>95th</td><td>{{ locust_summary.p95 | default(0) }}</td></tr>
            <tr><td>99th</td><td>{{ locust_summary.p99 | default(0) }}</td></tr>
        </table>

        <h3>Request Summary</h3>
        <table>
            <tr>
                <th>Metric</th>
                <th>Value</th>
            </tr>
            <tr>
                <td>Total Requests</td>
                <td>{{ locust_summary.total_requests | default(0) }}</td>
            </tr>
            <tr>
                <td>Failed Requests</td>
                <td>{{ locust_summary.total_failures | default(0) }}</td>
            </tr>
            <tr>
                <td>Peak RPS</td>
                <td>{{ "%.1f" | format(locust_summary.peak_rps | default(0)) }}</td>
            </tr>
            <tr>
                <td>Average RPS</td>
                <td>{{ "%.1f" | format(locust_summary.avg_rps | default(0)) }}</td>
            </tr>
        </table>
    </section>
    {% endif %}

    <!-- Configuration -->
    {% if config %}
    <section class="card">
        <h2>Test Configuration</h2>
        <pre style="background: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto;">{{ config | tojson(indent=2) }}</pre>
    </section>
    {% endif %}

    <!-- Recommendations -->
    {% if recommendations %}
    <section class="card">
        <h2>Recommendations</h2>
        <ul style="list-style: none;">
            {% for rec in recommendations %}
            <li style="padding: 10px 0; border-bottom: 1px solid #eee;">
                {{ rec }}
            </li>
            {% endfor %}
        </ul>
    </section>
    {% endif %}

    <footer>
        <p>Generated by Octavia Performance Test Framework</p>
        <p>{{ generated_at }}</p>
    </footer>
</body>
</html>
"""


def filesizeformat(value: int) -> str:
    """Format a file size in bytes to human readable format."""
    if value < 1024:
        return f"{value} B"
    elif value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    elif value < 1024 * 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    else:
        return f"{value / (1024 * 1024 * 1024):.1f} GB"


class ReportGenerator:
    """Generates performance test reports.

    Report sections:
    1. Executive Summary - Key metrics and status
    2. Bottleneck Analysis - Detected issues and recommendations
    3. Load Balancer Statistics - HAProxy metrics
    4. System Resource Utilization - CPU, memory, network
    5. Load Test Results - Locust metrics
    6. Configuration - Test parameters
    """

    def __init__(self, output_dir: str = "./reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Set up Jinja2 environment
        self.env = Environment(loader=BaseLoader())
        self.env.filters['filesizeformat'] = filesizeformat
        self.template = self.env.from_string(REPORT_TEMPLATE)

    def generate(
        self,
        run_name: str,
        haproxy_stats: List[Dict],
        system_metrics: List[Dict],
        locust_stats: Optional[List[Dict]] = None,
        config: Optional[Dict] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> str:
        """Generate an HTML report.

        Args:
            run_name: Name of the test run
            haproxy_stats: HAProxy statistics
            system_metrics: System metrics
            locust_stats: Locust statistics (optional)
            config: Test configuration (optional)
            start_time: Test start time
            end_time: Test end time

        Returns:
            Path to the generated report file
        """
        # Calculate duration
        duration = "Unknown"
        if start_time and end_time:
            delta = end_time - start_time
            minutes = int(delta.total_seconds() // 60)
            seconds = int(delta.total_seconds() % 60)
            duration = f"{minutes}m {seconds}s"

        # Run bottleneck analysis
        detector = BottleneckDetector()
        bottlenecks = detector.analyze(
            haproxy_stats, system_metrics, locust_stats
        )
        bottleneck_summary = detector.get_summary()

        # Calculate summaries
        summary = self._calculate_summary(
            haproxy_stats, system_metrics, locust_stats
        )
        haproxy_summary = self._summarize_haproxy(haproxy_stats)
        system_summary = self._summarize_system(system_metrics)
        locust_summary = self._summarize_locust(locust_stats)

        # Get recommendations from bottlenecks
        recommendations = list(set(b.recommendation for b in bottlenecks))

        # Render template
        html = self.template.render(
            title=f"Performance Test Report - {run_name}",
            run_name=run_name,
            duration=duration,
            generated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            summary=summary,
            bottlenecks=bottlenecks,
            bottleneck_summary=bottleneck_summary,
            haproxy_stats=haproxy_stats,
            haproxy_summary=haproxy_summary,
            system_summary=system_summary,
            locust_summary=locust_summary,
            config=config,
            recommendations=recommendations
        )

        # Write report
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"report_{run_name}_{timestamp}.html"
        filepath = self.output_dir / filename

        with open(filepath, 'w') as f:
            f.write(html)

        logger.info(f"Report generated: {filepath}")
        return str(filepath)

    def _calculate_summary(
        self,
        haproxy_stats: List[Dict],
        system_metrics: List[Dict],
        locust_stats: Optional[List[Dict]]
    ) -> Dict[str, Any]:
        """Calculate high-level summary metrics."""
        summary = {
            'total_requests': 0,
            'requests_per_sec': 0,
            'avg_response_time': 0,
            'error_rate': 0
        }

        if haproxy_stats:
            latest = haproxy_stats[-1] if haproxy_stats else {}
            first = haproxy_stats[0] if haproxy_stats else {}

            total_req = (latest.get('stot', 0) or 0)
            summary['total_requests'] = total_req

            # Calculate RPS from time range
            if len(haproxy_stats) > 1:
                # Assuming timestamps are in stats
                pass

            # Error rate
            errors = latest.get('ereq', 0) or 0
            if total_req > 0:
                summary['error_rate'] = (errors / total_req) * 100

        if locust_stats:
            latest = locust_stats[-1] if locust_stats else {}
            summary['avg_response_time'] = latest.get(
                'average_response_time', 0
            )
            summary['requests_per_sec'] = latest.get('requests_per_sec', 0)

        return summary

    def _summarize_haproxy(self, stats: List[Dict]) -> Dict[str, Any]:
        """Summarize HAProxy statistics."""
        if not stats:
            return {}

        latest = stats[-1]

        # Find max values across all samples
        max_connections = max(s.get('scur', 0) or 0 for s in stats)

        return {
            'max_connections': max_connections,
            'total_connections': latest.get('stot', 0) or 0,
            'connection_limit': latest.get('slim', 0) or 0,
            'peak_utilization': (
                (max_connections / (latest.get('slim', 1) or 1)) * 100
            ),
            'bytes_in': latest.get('bin', 0) or 0,
            'bytes_out': latest.get('bout', 0) or 0,
            'total_requests': latest.get('req_tot', 0) or 0,
            'http_codes': {
                '1': latest.get('hrsp_1xx', 0) or 0,
                '2': latest.get('hrsp_2xx', 0) or 0,
                '3': latest.get('hrsp_3xx', 0) or 0,
                '4': latest.get('hrsp_4xx', 0) or 0,
                '5': latest.get('hrsp_5xx', 0) or 0,
            }
        }

    def _summarize_system(self, metrics: List[Dict]) -> Dict[str, Any]:
        """Summarize system metrics."""
        if not metrics:
            return {}

        amphora = [m for m in metrics if 'amphora' in m.get('host_type', '')]
        backend = [m for m in metrics if 'backend' in m.get('host_type', '')]

        def summarize_host_type(data: List[Dict]) -> Dict:
            if not data:
                return {}

            cpu_values = [
                (m.get('cpu_user', 0) or 0) + (m.get('cpu_system', 0) or 0)
                for m in data
            ]
            # These are ticks, not percentages, so we'll use load instead
            load_values = [m.get('load_1', 0) or 0 for m in data]

            return {
                'avg_cpu': sum(load_values) / len(load_values) * 10 if load_values else 0,
                'max_cpu': max(load_values) * 10 if load_values else 0,
                'avg_load': sum(load_values) / len(load_values) if load_values else 0,
                'max_load': max(load_values) if load_values else 0,
                'avg_memory': 50,  # Placeholder
                'max_memory': 60,  # Placeholder
            }

        return {
            'amphora': summarize_host_type(amphora),
            'backend': summarize_host_type(backend)
        }

    def _summarize_locust(
        self, stats: Optional[List[Dict]]
    ) -> Optional[Dict[str, Any]]:
        """Summarize Locust statistics."""
        if not stats:
            return None

        latest = stats[-1] if stats else {}

        rps_values = [s.get('requests_per_sec', 0) or 0 for s in stats]

        return {
            'total_requests': latest.get('num_requests', 0),
            'total_failures': latest.get('num_failures', 0),
            'p50': latest.get('p50', 0),
            'p90': latest.get('p90', 0),
            'p95': latest.get('p95', 0),
            'p99': latest.get('p99', 0),
            'peak_rps': max(rps_values) if rps_values else 0,
            'avg_rps': sum(rps_values) / len(rps_values) if rps_values else 0
        }
