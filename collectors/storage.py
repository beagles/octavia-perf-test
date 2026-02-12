"""Metrics storage using SQLite."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class MetricsStorage:
    """SQLite-based storage for performance test metrics.

    Tables:
    - test_runs: Test run metadata
    - haproxy_stats: Time-series HAProxy metrics
    - system_metrics: Time-series system metrics (amphora and backends)
    - locust_stats: Locust aggregated statistics
    """

    def __init__(self, db_path: str = "metrics.db"):
        self.db_path = Path(db_path)
        self._init_schema()

    @contextmanager
    def _get_connection(self):
        """Get a database connection with context management."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self):
        """Initialize database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Test runs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS test_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    config TEXT,
                    notes TEXT,
                    status TEXT DEFAULT 'running'
                )
            """)

            # HAProxy statistics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS haproxy_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    amphora_id TEXT,
                    lb_id TEXT,
                    proxy_name TEXT,
                    server_name TEXT,
                    scur INTEGER,
                    smax INTEGER,
                    slim INTEGER,
                    stot INTEGER,
                    bin INTEGER,
                    bout INTEGER,
                    dreq INTEGER,
                    ereq INTEGER,
                    status TEXT,
                    weight INTEGER,
                    rate INTEGER,
                    rate_max INTEGER,
                    req_rate INTEGER,
                    req_tot INTEGER,
                    hrsp_1xx INTEGER,
                    hrsp_2xx INTEGER,
                    hrsp_3xx INTEGER,
                    hrsp_4xx INTEGER,
                    hrsp_5xx INTEGER,
                    qcur INTEGER,
                    qmax INTEGER,
                    cli_abrt INTEGER,
                    srv_abrt INTEGER,
                    raw_data TEXT,
                    FOREIGN KEY (run_id) REFERENCES test_runs(id)
                )
            """)

            # System metrics table (for amphora and backend servers)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    host_id TEXT NOT NULL,
                    host_type TEXT NOT NULL,
                    cpu_user INTEGER,
                    cpu_system INTEGER,
                    cpu_softirq INTEGER,
                    cpu_total INTEGER,
                    cpu_count INTEGER,
                    mem_total INTEGER,
                    mem_free INTEGER,
                    mem_buffers INTEGER,
                    mem_cached INTEGER,
                    mem_swap_used INTEGER,
                    disk_used INTEGER,
                    disk_available INTEGER,
                    load_1 REAL,
                    load_5 REAL,
                    load_15 REAL,
                    network_tx INTEGER,
                    network_rx INTEGER,
                    raw_data TEXT,
                    FOREIGN KEY (run_id) REFERENCES test_runs(id)
                )
            """)

            # Locust statistics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS locust_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    name TEXT,
                    method TEXT,
                    num_requests INTEGER,
                    num_failures INTEGER,
                    median_response_time REAL,
                    average_response_time REAL,
                    min_response_time REAL,
                    max_response_time REAL,
                    avg_content_length REAL,
                    requests_per_sec REAL,
                    failures_per_sec REAL,
                    p50 REAL,
                    p90 REAL,
                    p95 REAL,
                    p99 REAL,
                    current_rps REAL,
                    current_fail_per_sec REAL,
                    raw_data TEXT,
                    FOREIGN KEY (run_id) REFERENCES test_runs(id)
                )
            """)

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_haproxy_run_time
                ON haproxy_stats(run_id, timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_system_run_time
                ON system_metrics(run_id, timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_locust_run_time
                ON locust_stats(run_id, timestamp)
            """)

    def create_test_run(
        self,
        name: str,
        config: Optional[Dict] = None,
        notes: Optional[str] = None
    ) -> int:
        """Create a new test run and return its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO test_runs (name, start_time, config, notes)
                VALUES (?, ?, ?, ?)
                """,
                (
                    name,
                    datetime.utcnow().isoformat(),
                    json.dumps(config) if config else None,
                    notes
                )
            )
            return cursor.lastrowid

    def complete_test_run(self, run_id: int, status: str = "completed"):
        """Mark a test run as completed."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE test_runs
                SET end_time = ?, status = ?
                WHERE id = ?
                """,
                (datetime.utcnow().isoformat(), status, run_id)
            )

    def store_haproxy_stats(
        self,
        run_id: int,
        amphora_id: str,
        lb_id: str,
        stats: List[Dict[str, Any]]
    ):
        """Store HAProxy statistics."""
        timestamp = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for stat in stats:
                cursor.execute(
                    """
                    INSERT INTO haproxy_stats (
                        run_id, timestamp, amphora_id, lb_id,
                        proxy_name, server_name, scur, smax, slim, stot,
                        bin, bout, dreq, ereq, status, weight,
                        rate, rate_max, req_rate, req_tot,
                        hrsp_1xx, hrsp_2xx, hrsp_3xx, hrsp_4xx, hrsp_5xx,
                        qcur, qmax, cli_abrt, srv_abrt, raw_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id, timestamp, amphora_id, lb_id,
                        stat.get('pxname'), stat.get('svname'),
                        self._int_or_none(stat.get('scur')),
                        self._int_or_none(stat.get('smax')),
                        self._int_or_none(stat.get('slim')),
                        self._int_or_none(stat.get('stot')),
                        self._int_or_none(stat.get('bin')),
                        self._int_or_none(stat.get('bout')),
                        self._int_or_none(stat.get('dreq')),
                        self._int_or_none(stat.get('ereq')),
                        stat.get('status'),
                        self._int_or_none(stat.get('weight')),
                        self._int_or_none(stat.get('rate')),
                        self._int_or_none(stat.get('rate_max')),
                        self._int_or_none(stat.get('req_rate')),
                        self._int_or_none(stat.get('req_tot')),
                        self._int_or_none(stat.get('hrsp_1xx')),
                        self._int_or_none(stat.get('hrsp_2xx')),
                        self._int_or_none(stat.get('hrsp_3xx')),
                        self._int_or_none(stat.get('hrsp_4xx')),
                        self._int_or_none(stat.get('hrsp_5xx')),
                        self._int_or_none(stat.get('qcur')),
                        self._int_or_none(stat.get('qmax')),
                        self._int_or_none(stat.get('cli_abrt')),
                        self._int_or_none(stat.get('srv_abrt')),
                        json.dumps(stat)
                    )
                )

    def store_system_metrics(
        self,
        run_id: int,
        host_id: str,
        host_type: str,
        metrics: Dict[str, Any]
    ):
        """Store system metrics (CPU, memory, network, etc.)."""
        timestamp = datetime.utcnow().isoformat()

        # Extract CPU metrics
        cpu = metrics.get('cpu', {})
        memory = metrics.get('memory', {})
        disk = metrics.get('disk', {})
        load = metrics.get('load', [0, 0, 0])

        # Sum network tx/rx across all interfaces
        networks = metrics.get('networks', {})
        total_tx = sum(n.get('network_tx', 0) for n in networks.values())
        total_rx = sum(n.get('network_rx', 0) for n in networks.values())

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO system_metrics (
                    run_id, timestamp, host_id, host_type,
                    cpu_user, cpu_system, cpu_softirq, cpu_total, cpu_count,
                    mem_total, mem_free, mem_buffers, mem_cached, mem_swap_used,
                    disk_used, disk_available,
                    load_1, load_5, load_15,
                    network_tx, network_rx, raw_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, timestamp, host_id, host_type,
                    self._int_or_none(cpu.get('user')),
                    self._int_or_none(cpu.get('system')),
                    self._int_or_none(cpu.get('soft_irq')),
                    self._int_or_none(cpu.get('total')),
                    metrics.get('cpu_count'),
                    memory.get('total'),
                    memory.get('free'),
                    memory.get('buffers'),
                    memory.get('cached'),
                    memory.get('swap_used'),
                    disk.get('used'),
                    disk.get('available'),
                    float(load[0]) if load else None,
                    float(load[1]) if len(load) > 1 else None,
                    float(load[2]) if len(load) > 2 else None,
                    total_tx,
                    total_rx,
                    json.dumps(metrics)
                )
            )

    def store_locust_stats(self, run_id: int, stats: Dict[str, Any]):
        """Store Locust statistics."""
        timestamp = datetime.utcnow().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO locust_stats (
                    run_id, timestamp, name, method,
                    num_requests, num_failures,
                    median_response_time, average_response_time,
                    min_response_time, max_response_time,
                    avg_content_length, requests_per_sec, failures_per_sec,
                    p50, p90, p95, p99,
                    current_rps, current_fail_per_sec, raw_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, timestamp,
                    stats.get('name'), stats.get('method'),
                    stats.get('num_requests'), stats.get('num_failures'),
                    stats.get('median_response_time'),
                    stats.get('avg_response_time'),
                    stats.get('min_response_time'),
                    stats.get('max_response_time'),
                    stats.get('avg_content_length'),
                    stats.get('current_rps'),
                    stats.get('current_fail_per_sec'),
                    stats.get('response_times', {}).get('50'),
                    stats.get('response_times', {}).get('90'),
                    stats.get('response_times', {}).get('95'),
                    stats.get('response_times', {}).get('99'),
                    stats.get('current_rps'),
                    stats.get('current_fail_per_sec'),
                    json.dumps(stats)
                )
            )

    def get_haproxy_stats(
        self,
        run_id: int,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> List[Dict]:
        """Get HAProxy stats for a test run."""
        query = "SELECT * FROM haproxy_stats WHERE run_id = ?"
        params = [run_id]

        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)

        query += " ORDER BY timestamp"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_system_metrics(
        self,
        run_id: int,
        host_type: Optional[str] = None
    ) -> List[Dict]:
        """Get system metrics for a test run."""
        query = "SELECT * FROM system_metrics WHERE run_id = ?"
        params = [run_id]

        if host_type:
            query += " AND host_type = ?"
            params.append(host_type)

        query += " ORDER BY timestamp"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_locust_stats(self, run_id: int) -> List[Dict]:
        """Get Locust stats for a test run."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM locust_stats WHERE run_id = ? ORDER BY timestamp",
                (run_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_test_run(self, run_id: int) -> Optional[Dict]:
        """Get test run metadata."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM test_runs WHERE id = ?", (run_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_test_runs(self, limit: int = 20) -> List[Dict]:
        """List recent test runs."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM test_runs ORDER BY start_time DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def export_to_json(self, run_id: int, output_path: str):
        """Export all data for a test run to JSON."""
        data = {
            'test_run': self.get_test_run(run_id),
            'haproxy_stats': self.get_haproxy_stats(run_id),
            'system_metrics': self.get_system_metrics(run_id),
            'locust_stats': self.get_locust_stats(run_id)
        }
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)

    @staticmethod
    def _int_or_none(value) -> Optional[int]:
        """Convert value to int or None."""
        if value is None or value == '':
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
