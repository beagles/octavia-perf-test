"""Main Locust entry point for Octavia performance testing.

This file serves as the main entry point for Locust load tests.
Import and combine scenarios as needed, or run specific scenarios
using Locust's --class-picker option.

Usage:
    # Run with web UI
    locust -f locustfile.py --host http://VIP_ADDRESS

    # Run headless
    locust -f locustfile.py --host http://VIP_ADDRESS \
           --headless -u 100 -r 10 -t 5m

    # Run specific scenario
    locust -f locustfile.py --host http://VIP_ADDRESS \
           --class-picker BasicHTTPUser
"""

# Import all scenarios for easy access
from scenarios.basic_http import BasicHTTPUser, HealthCheckUser
from scenarios.variable_payload import (
    SmallPayloadUser,
    LargeDownloadUser,
    LargeUploadUser,
    MixedPayloadUser
)
from scenarios.connection_patterns import (
    ConnectionReuseUser,
    NewConnectionUser,
    KeepAliveStressUser
)
from scenarios.ramp_patterns import (
    StepLoadShape,
    SpikeLoadShape,
    SoakLoadShape
)

# Default user class when running without specifying a class
# This provides a balanced mix of request types
from locust import HttpUser, task, between


class DefaultUser(HttpUser):
    """Default balanced user for general performance testing.

    Combines common request patterns:
    - Simple GET requests (high frequency)
    - Health checks (medium frequency)
    - POST requests (lower frequency)
    """

    wait_time = between(0.5, 2.0)

    @task(10)
    def get_root(self):
        """Simple GET request to root."""
        self.client.get("/")

    @task(5)
    def get_health(self):
        """Health check endpoint."""
        self.client.get("/health/")

    @task(3)
    def post_data(self):
        """POST request with JSON payload."""
        self.client.post(
            "/api/data",
            json={"test": "data", "timestamp": "now"}
        )

    @task(2)
    def get_small_file(self):
        """Download a small file."""
        self.client.get("/file_10k")

    @task(1)
    def get_large_file(self):
        """Download a larger file."""
        self.client.get("/file_100k")
