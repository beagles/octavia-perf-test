"""Metrics aggregator for combining and analyzing collected data."""

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from .storage import MetricsStorage

logger = logging.getLogger(__name__)


class MetricsAggregator:
    """Aggregates metrics from multiple collectors and calculates derived metrics.

    Derived metrics:
    - Requests per second (from HAProxy stot delta / interval)
    - Throughput in bytes/sec (from bin/bout deltas)
    - Error rate (ereq / totconns)
    - Connection saturation (scur / slim)
    - CPU utilization trend
    - Memory pressure indicators
    """

    def __init__(
        self,
        storage: MetricsStorage,
        run_id: int
    ):
        """Initialize the aggregator.

        Args:
            storage: MetricsStorage instance for persisting data
            run_id: Test run ID to associate metrics with
        """
        self.storage = storage
        self.run_id = run_id
        self._prev_haproxy_stats: Optional[Dict] = None
        self._prev_timestamp: Optional[float] = None

    def calculate_rates(
        self,
        current: Dict[str, int],
        previous: Dict[str, int],
        interval_seconds: float
    ) -> Dict[str, float]:
        """Calculate rate metrics from deltas.

        Args:
            current: Current counter values
            previous: Previous counter values
            interval_seconds: Time between samples

        Returns:
            Dictionary with rate values (per second)
        """
        if interval_seconds <= 0:
            return {}

        rates = {}
        for key in current:
            if key in previous:
                delta = current[key] - previous[key]
                if delta >= 0:  # Handle counter resets
                    rates[f'{key}_per_sec'] = delta / interval_seconds

        return rates

    def aggregate_haproxy_stats(
        self,
        stats: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Aggregate HAProxy statistics across all proxies.

        Args:
            stats: List of raw HAProxy stats dictionaries

        Returns:
            Aggregated statistics with derived metrics
        """
        now = time.time()

        # Separate by type
        frontends = [s for s in stats if s.get('svname') == 'FRONTEND']
        backends = [s for s in stats if s.get('svname') == 'BACKEND']
        servers = [s for s in stats
                   if s.get('svname') not in ('FRONTEND', 'BACKEND')]

        # Aggregate counters
        current = {
            'scur': sum(int(s.get('scur', 0) or 0) for s in frontends),
            'slim': sum(int(s.get('slim', 0) or 0) for s in frontends),
            'stot': sum(int(s.get('stot', 0) or 0) for s in frontends),
            'bin': sum(int(s.get('bin', 0) or 0) for s in frontends),
            'bout': sum(int(s.get('bout', 0) or 0) for s in frontends),
            'req_tot': sum(int(s.get('req_tot', 0) or 0) for s in frontends),
            'ereq': sum(int(s.get('ereq', 0) or 0) for s in frontends),
            'dreq': sum(int(s.get('dreq', 0) or 0) for s in frontends),
            'hrsp_2xx': sum(int(s.get('hrsp_2xx', 0) or 0) for s in frontends),
            'hrsp_4xx': sum(int(s.get('hrsp_4xx', 0) or 0) for s in frontends),
            'hrsp_5xx': sum(int(s.get('hrsp_5xx', 0) or 0) for s in frontends),
            'qcur': sum(int(s.get('qcur', 0) or 0) for s in backends),
        }

        # Calculate rates if we have previous data
        rates = {}
        if self._prev_haproxy_stats and self._prev_timestamp:
            interval = now - self._prev_timestamp
            rates = self.calculate_rates(
                current, self._prev_haproxy_stats, interval
            )

        self._prev_haproxy_stats = current.copy()
        self._prev_timestamp = now

        # Calculate derived metrics
        saturation = 0
        if current['slim'] > 0:
            saturation = (current['scur'] / current['slim']) * 100

        error_rate = 0
        if current['stot'] > 0:
            error_rate = (current['ereq'] / current['stot']) * 100

        # Count healthy/unhealthy servers
        healthy_servers = sum(
            1 for s in servers if s.get('status') == 'UP'
        )
        total_servers = len(servers)

        return {
            'timestamp': datetime.utcnow().isoformat(),
            'counters': current,
            'rates': rates,
            'derived': {
                'connection_saturation_pct': saturation,
                'error_rate_pct': error_rate,
                'healthy_servers': healthy_servers,
                'total_servers': total_servers,
                'requests_per_sec': rates.get('req_tot_per_sec', 0),
                'throughput_in_bps': rates.get('bin_per_sec', 0),
                'throughput_out_bps': rates.get('bout_per_sec', 0),
            },
            'summary': {
                'frontend_count': len(frontends),
                'backend_count': len(backends),
                'server_count': total_servers,
            }
        }

    def aggregate_system_metrics(
        self,
        metrics: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Aggregate system metrics from multiple hosts.

        Args:
            metrics: Dictionary mapping host_id to metrics

        Returns:
            Aggregated system metrics
        """
        amphora_metrics = {
            k: v for k, v in metrics.items()
            if 'amphora' in k.lower() or 'amp' in k.lower()
        }
        backend_metrics = {
            k: v for k, v in metrics.items()
            if 'backend' in k.lower()
        }

        # Average CPU utilization across amphorae
        amphora_cpu_avg = 0
        amphora_mem_avg = 0
        if amphora_metrics:
            cpu_values = [
                m.get('utilization', {}).get('cpu', 0)
                for m in amphora_metrics.values()
                if m.get('utilization', {}).get('cpu') is not None
            ]
            mem_values = [
                m.get('utilization', {}).get('memory', 0)
                for m in amphora_metrics.values()
                if m.get('utilization', {}).get('memory') is not None
            ]
            if cpu_values:
                amphora_cpu_avg = sum(cpu_values) / len(cpu_values)
            if mem_values:
                amphora_mem_avg = sum(mem_values) / len(mem_values)

        # Average metrics across backends
        backend_cpu_avg = 0
        backend_mem_avg = 0
        if backend_metrics:
            cpu_values = [
                m.get('utilization', {}).get('cpu', 0)
                for m in backend_metrics.values()
                if m.get('utilization', {}).get('cpu') is not None
            ]
            mem_values = [
                m.get('utilization', {}).get('memory', 0)
                for m in backend_metrics.values()
                if m.get('utilization', {}).get('memory') is not None
            ]
            if cpu_values:
                backend_cpu_avg = sum(cpu_values) / len(cpu_values)
            if mem_values:
                backend_mem_avg = sum(mem_values) / len(mem_values)

        return {
            'timestamp': datetime.utcnow().isoformat(),
            'amphora': {
                'count': len(amphora_metrics),
                'avg_cpu_utilization': amphora_cpu_avg,
                'avg_memory_utilization': amphora_mem_avg,
            },
            'backend': {
                'count': len(backend_metrics),
                'avg_cpu_utilization': backend_cpu_avg,
                'avg_memory_utilization': backend_mem_avg,
            },
            'by_host': metrics
        }


class CollectionScheduler:
    """Schedules periodic metric collection from multiple sources."""

    def __init__(
        self,
        storage: MetricsStorage,
        run_id: int
    ):
        """Initialize the scheduler.

        Args:
            storage: MetricsStorage for persisting data
            run_id: Test run ID
        """
        self.storage = storage
        self.run_id = run_id
        self.aggregator = MetricsAggregator(storage, run_id)
        self._collectors: Dict[str, Dict] = {}
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []

    def add_collector(
        self,
        name: str,
        collector: Any,
        interval: float,
        store_func: Callable[[Any], None]
    ):
        """Add a collector to the scheduler.

        Args:
            name: Unique name for this collector
            collector: Collector object with a collect() method
            interval: Collection interval in seconds
            store_func: Function to call with collected data
        """
        self._collectors[name] = {
            'collector': collector,
            'interval': interval,
            'store_func': store_func
        }

    def _collection_loop(self, name: str, config: Dict):
        """Collection loop for a single collector."""
        collector = config['collector']
        interval = config['interval']
        store_func = config['store_func']

        while not self._stop_event.is_set():
            try:
                start_time = time.time()

                # Collect metrics
                data = collector.collect()

                # Store the data
                store_func(data)

                # Sleep for remaining interval time
                elapsed = time.time() - start_time
                sleep_time = max(0, interval - elapsed)
                self._stop_event.wait(sleep_time)

            except Exception as e:
                logger.error(f"Collection error in {name}: {e}")
                self._stop_event.wait(interval)

    def start(self):
        """Start all collection threads."""
        self._stop_event.clear()

        for name, config in self._collectors.items():
            thread = threading.Thread(
                target=self._collection_loop,
                args=(name, config),
                name=f"collector-{name}",
                daemon=True
            )
            thread.start()
            self._threads.append(thread)
            logger.info(f"Started collector: {name}")

    def stop(self, timeout: float = 5.0):
        """Stop all collection threads.

        Args:
            timeout: Maximum time to wait for threads to stop
        """
        self._stop_event.set()

        for thread in self._threads:
            thread.join(timeout=timeout)
            if thread.is_alive():
                logger.warning(f"Thread {thread.name} did not stop cleanly")

        self._threads.clear()
        logger.info("All collectors stopped")

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False
