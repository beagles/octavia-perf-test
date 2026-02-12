"""Basic HTTP load test scenarios.

These scenarios provide fundamental HTTP workload patterns for
baseline performance testing of the load balancer.
"""

from locust import HttpUser, task, between, constant


class BasicHTTPUser(HttpUser):
    """Basic HTTP user for simple GET/POST testing.

    Tests basic load balancer functionality with standard
    HTTP requests. Good for establishing baseline metrics.

    Endpoints tested:
    - GET / : Root page
    - GET /health/ : Health check endpoint
    - POST /api/data : JSON POST endpoint
    """

    wait_time = between(0.1, 0.5)

    @task(10)
    def get_root(self):
        """Simple GET request to root page."""
        with self.client.get("/", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"Got status {response.status_code}")
            elif "Backend Server" not in response.text:
                response.failure("Unexpected response content")

    @task(5)
    def get_health(self):
        """GET health check endpoint."""
        with self.client.get("/health/", catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"Got status {response.status_code}")
            # Health endpoint should return JSON
            try:
                data = response.json()
                if data.get("status") != "healthy":
                    response.failure("Health check returned unhealthy")
            except Exception:
                # Not JSON, might be HTML - that's okay
                pass

    @task(3)
    def post_data(self):
        """POST JSON data to API endpoint."""
        payload = {
            "key": "test_value",
            "numbers": [1, 2, 3, 4, 5],
            "nested": {"a": 1, "b": 2}
        }
        with self.client.post(
            "/api/data",
            json=payload,
            catch_response=True
        ) as response:
            if response.status_code not in (200, 201):
                response.failure(f"POST failed: {response.status_code}")


class HealthCheckUser(HttpUser):
    """User that only performs health checks.

    Useful for testing health monitor behavior and
    minimal load scenarios.
    """

    wait_time = constant(1)  # Fixed 1 second between requests

    @task
    def health_check(self):
        """Perform health check."""
        self.client.get("/health/")


class HighFrequencyUser(HttpUser):
    """User that makes requests as fast as possible.

    No wait time between requests - useful for stress testing
    connection limits and maximum throughput.

    WARNING: Use with caution, can generate very high load.
    """

    wait_time = constant(0)

    @task
    def rapid_get(self):
        """Rapid GET requests."""
        self.client.get("/")


class ReadWriteMixUser(HttpUser):
    """User with configurable read/write ratio.

    Simulates realistic application workloads with a mix
    of read (GET) and write (POST) operations.
    """

    wait_time = between(0.2, 1.0)

    # Default 80/20 read/write ratio
    read_weight = 80
    write_weight = 20

    @task(80)
    def read_operation(self):
        """Read operation (GET)."""
        self.client.get("/")

    @task(20)
    def write_operation(self):
        """Write operation (POST)."""
        self.client.post("/api/data", json={"operation": "write"})


class StaticContentUser(HttpUser):
    """User that requests static content of various sizes.

    Tests throughput with different content sizes.
    """

    wait_time = between(0.5, 1.5)

    @task(5)
    def get_1k(self):
        """Get 1KB file."""
        self.client.get("/file_1k")

    @task(3)
    def get_10k(self):
        """Get 10KB file."""
        self.client.get("/file_10k")

    @task(2)
    def get_100k(self):
        """Get 100KB file."""
        self.client.get("/file_100k")

    @task(1)
    def get_1m(self):
        """Get 1MB file."""
        self.client.get("/large_file")
