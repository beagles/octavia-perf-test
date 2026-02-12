#!/usr/bin/env python3
"""Main test orchestrator for Octavia performance testing.

This script orchestrates the entire performance test workflow:
1. Validates the test environment
2. Starts metric collectors
3. Executes Locust load tests
4. Collects and aggregates metrics
5. Generates reports

Usage:
    ./run-test.py --config configs/test_profiles/medium_load.yaml
    ./run-test.py --config configs/test_profiles/stress_test.yaml --duration 600
"""

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from collectors.storage import MetricsStorage
from collectors.haproxy_stats import HAProxyStatsCollector
from collectors.amphora_api import AmphoraAPICollector
from collectors.system_metrics import SystemMetricsCollector, MultiHostCollector
from collectors.aggregator import MetricsAggregator, CollectionScheduler
from analysis.bottleneck_detector import BottleneckDetector
from analysis.report_generator import ReportGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('octavia-perf-test')


class TestOrchestrator:
    """Orchestrates the complete performance test workflow."""

    def __init__(self, config_path: str):
        """Initialize the orchestrator.

        Args:
            config_path: Path to the test configuration YAML file
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.storage: Optional[MetricsStorage] = None
        self.run_id: Optional[int] = None
        self.collectors: List[Any] = []
        self.scheduler: Optional[CollectionScheduler] = None
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

    def _load_config(self) -> Dict[str, Any]:
        """Load and validate configuration."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path) as f:
            config = yaml.safe_load(f)

        # Set defaults
        config.setdefault('test', {})
        config['test'].setdefault('name', 'perf-test')
        config['test'].setdefault('duration', 300)  # 5 minutes default

        config.setdefault('locust', {})
        config['locust'].setdefault('users', 50)
        config['locust'].setdefault('spawn_rate', 10)

        config.setdefault('collectors', {})
        config.setdefault('analysis', {'bottleneck_detection': True})
        config.setdefault('report', {'output_dir': './reports', 'formats': ['html']})

        return config

    def validate_environment(self) -> bool:
        """Validate the test environment is ready.

        Checks:
        - Load balancer VIP is reachable
        - Backend servers are responding
        - SSH access to amphorae (if configured)
        """
        logger.info("Validating test environment...")

        # Check VIP reachability
        vip = self.config['locust'].get('host', '')
        if vip:
            import requests
            try:
                response = requests.get(vip, timeout=10)
                logger.info(f"VIP {vip} is reachable (status: {response.status_code})")
            except Exception as e:
                logger.error(f"Cannot reach VIP {vip}: {e}")
                return False

        # Check backend servers if specified
        backends = self.config.get('collectors', {}).get('system_metrics', {}).get('backends', [])
        for backend in backends:
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((backend['ip'], 22))
                sock.close()
                if result == 0:
                    logger.info(f"Backend {backend['id']} is reachable")
                else:
                    logger.warning(f"Backend {backend['id']} SSH not reachable")
            except Exception as e:
                logger.warning(f"Cannot check backend {backend.get('id')}: {e}")

        logger.info("Environment validation complete")
        return True

    def setup_collectors(self):
        """Set up metric collectors based on configuration."""
        logger.info("Setting up metric collectors...")

        # Initialize storage
        db_path = self.config.get('storage', {}).get('path', 'metrics.db')
        self.storage = MetricsStorage(db_path)

        # Create test run
        self.run_id = self.storage.create_test_run(
            name=self.config['test']['name'],
            config=self.config,
            notes=self.config.get('test', {}).get('notes')
        )
        logger.info(f"Created test run with ID: {self.run_id}")

        # Set up collection scheduler
        self.scheduler = CollectionScheduler(self.storage, self.run_id)

        # HAProxy stats collector
        haproxy_config = self.config.get('collectors', {}).get('haproxy_stats', {})
        if haproxy_config.get('enabled', True):
            amphora_ip = haproxy_config.get('amphora_ip')
            lb_id = haproxy_config.get('lb_id')

            if amphora_ip and lb_id:
                collector = HAProxyStatsCollector(
                    amphora_ip=amphora_ip,
                    lb_id=lb_id,
                    ssh_key_path=haproxy_config.get('ssh_key'),
                    ssh_username=haproxy_config.get('ssh_username', 'ubuntu')
                )
                self.collectors.append(collector)

                def store_haproxy(data):
                    if 'error' not in data:
                        self.storage.store_haproxy_stats(
                            self.run_id, amphora_ip, lb_id,
                            data.get('raw_stats', [])
                        )

                self.scheduler.add_collector(
                    name='haproxy',
                    collector=collector,
                    interval=haproxy_config.get('interval', 1),
                    store_func=store_haproxy
                )
                logger.info("HAProxy stats collector configured")

        # Amphora API collector
        amphora_config = self.config.get('collectors', {}).get('amphora_api', {})
        if amphora_config.get('enabled', True):
            amphora_ip = amphora_config.get('amphora_ip')

            if amphora_ip:
                collector = AmphoraAPICollector(
                    amphora_ip=amphora_ip,
                    client_cert_path=amphora_config.get('client_cert'),
                    client_key_path=amphora_config.get('client_key'),
                    server_ca_path=amphora_config.get('server_ca'),
                    verify_ssl=amphora_config.get('verify_ssl', False)
                )
                self.collectors.append(collector)

                def store_amphora(data):
                    if 'error' not in data:
                        self.storage.store_system_metrics(
                            self.run_id, amphora_ip, 'amphora', data
                        )

                self.scheduler.add_collector(
                    name='amphora_api',
                    collector=collector,
                    interval=amphora_config.get('interval', 5),
                    store_func=store_amphora
                )
                logger.info("Amphora API collector configured")

        # System metrics collectors for backends
        system_config = self.config.get('collectors', {}).get('system_metrics', {})
        backends = system_config.get('backends', [])

        for backend in backends:
            collector = SystemMetricsCollector(
                host_ip=backend['ip'],
                host_id=backend['id'],
                ssh_username=backend.get('username', 'vagrant'),
                ssh_key_path=backend.get('ssh_key'),
                ssh_password=backend.get('password')
            )
            self.collectors.append(collector)

            def store_backend(data, host_id=backend['id']):
                if 'error' not in data:
                    self.storage.store_system_metrics(
                        self.run_id, host_id, 'backend', data
                    )

            self.scheduler.add_collector(
                name=f"system_{backend['id']}",
                collector=collector,
                interval=system_config.get('interval', 5),
                store_func=store_backend
            )
            logger.info(f"System metrics collector configured for {backend['id']}")

    def run_locust(self) -> bool:
        """Run Locust load test.

        Returns:
            True if test completed successfully
        """
        logger.info("Starting Locust load test...")

        locust_config = self.config['locust']
        duration = self.config['test']['duration']
        host = locust_config['host']
        users = locust_config['users']
        spawn_rate = locust_config['spawn_rate']

        # Build Locust command
        locust_dir = Path(__file__).parent.parent / 'locust'
        locust_file = locust_dir / 'locustfile.py'

        cmd = [
            'locust',
            '-f', str(locust_file),
            '--host', host,
            '--headless',
            '-u', str(users),
            '-r', str(spawn_rate),
            '-t', f'{duration}s',
            '--csv', f'locust_results_{self.run_id}',
            '--csv-full-history'
        ]

        # Add class picker if specified
        if 'scenarios' in locust_config:
            for scenario in locust_config['scenarios']:
                cmd.extend(['--class-picker', scenario])

        logger.info(f"Running: {' '.join(cmd)}")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Monitor progress
            while process.poll() is None:
                if process.stdout:
                    line = process.stdout.readline()
                    if line:
                        logger.debug(f"Locust: {line.strip()}")
                time.sleep(1)

            # Get final output
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                logger.error(f"Locust failed: {stderr}")
                return False

            logger.info("Locust test completed successfully")
            return True

        except FileNotFoundError:
            logger.error("Locust not found. Install with: pip install locust")
            return False
        except Exception as e:
            logger.error(f"Error running Locust: {e}")
            return False

    def generate_report(self):
        """Generate the final report."""
        logger.info("Generating report...")

        # Get collected data
        haproxy_stats = self.storage.get_haproxy_stats(self.run_id)
        system_metrics = self.storage.get_system_metrics(self.run_id)
        locust_stats = self.storage.get_locust_stats(self.run_id)

        # Generate HTML report
        report_config = self.config.get('report', {})
        output_dir = report_config.get('output_dir', './reports')

        generator = ReportGenerator(output_dir)
        report_path = generator.generate(
            run_name=self.config['test']['name'],
            haproxy_stats=haproxy_stats,
            system_metrics=system_metrics,
            locust_stats=locust_stats,
            config=self.config,
            start_time=self.start_time,
            end_time=self.end_time
        )

        logger.info(f"Report generated: {report_path}")

        # Export raw data to JSON
        if report_config.get('export_json', True):
            json_path = f"{output_dir}/data_{self.run_id}.json"
            self.storage.export_to_json(self.run_id, json_path)
            logger.info(f"Data exported: {json_path}")

        return report_path

    def run(self) -> bool:
        """Run the complete performance test.

        Returns:
            True if test completed successfully
        """
        try:
            # Validate environment
            if not self.validate_environment():
                logger.error("Environment validation failed")
                return False

            # Set up collectors
            self.setup_collectors()

            # Record start time
            self.start_time = datetime.utcnow()
            logger.info(f"Test started at {self.start_time}")

            # Start collectors
            if self.scheduler:
                self.scheduler.start()
                logger.info("Metric collectors started")

            # Run Locust
            success = self.run_locust()

            # Record end time
            self.end_time = datetime.utcnow()
            logger.info(f"Test ended at {self.end_time}")

            # Stop collectors
            if self.scheduler:
                self.scheduler.stop()
                logger.info("Metric collectors stopped")

            # Update test run status
            if self.storage and self.run_id:
                status = 'completed' if success else 'failed'
                self.storage.complete_test_run(self.run_id, status)

            # Generate report
            report_path = self.generate_report()

            logger.info("=" * 60)
            logger.info("PERFORMANCE TEST COMPLETE")
            logger.info(f"Duration: {self.end_time - self.start_time}")
            logger.info(f"Report: {report_path}")
            logger.info("=" * 60)

            return success

        except KeyboardInterrupt:
            logger.info("Test interrupted by user")
            if self.scheduler:
                self.scheduler.stop()
            if self.storage and self.run_id:
                self.storage.complete_test_run(self.run_id, 'interrupted')
            return False

        except Exception as e:
            logger.exception(f"Test failed with error: {e}")
            if self.storage and self.run_id:
                self.storage.complete_test_run(self.run_id, 'error')
            return False

        finally:
            # Clean up collectors
            for collector in self.collectors:
                try:
                    if hasattr(collector, 'disconnect'):
                        collector.disconnect()
                except Exception:
                    pass


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Octavia Amphora Performance Test Runner'
    )
    parser.add_argument(
        '--config', '-c',
        required=True,
        help='Path to test configuration YAML file'
    )
    parser.add_argument(
        '--duration', '-d',
        type=int,
        help='Override test duration in seconds'
    )
    parser.add_argument(
        '--users', '-u',
        type=int,
        help='Override number of concurrent users'
    )
    parser.add_argument(
        '--host',
        help='Override target host URL'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create orchestrator
    orchestrator = TestOrchestrator(args.config)

    # Apply command-line overrides
    if args.duration:
        orchestrator.config['test']['duration'] = args.duration
    if args.users:
        orchestrator.config['locust']['users'] = args.users
    if args.host:
        orchestrator.config['locust']['host'] = args.host

    # Run the test
    success = orchestrator.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
