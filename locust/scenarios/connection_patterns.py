"""Connection pattern test scenarios.

These scenarios test different TCP connection behaviors to identify
connection-related bottlenecks and tune HAProxy settings.
"""

import requests
from locust import HttpUser, task, between, constant, events


class ConnectionReuseUser(HttpUser):
    """User that maximizes HTTP keep-alive connection reuse.

    Tests sustained connection performance. HAProxy settings:
    - option http-keep-alive
    - timeout http-keep-alive

    This is the default behavior and tests connection pooling
    efficiency.
    """

    wait_time = between(0.1, 0.3)

    @task
    def multiple_requests_same_connection(self):
        """Send multiple requests using connection reuse."""
        # Requests library uses connection pooling by default
        for _ in range(10):
            with self.client.get("/", catch_response=True) as response:
                # Check for Connection header
                conn_header = response.headers.get('Connection', '')
                if conn_header.lower() == 'close':
                    response.failure("Connection closed unexpectedly")
                    break


class NewConnectionUser(HttpUser):
    """User that creates new connections for each request.

    Forces new TCP connections to test connection establishment
    overhead. Useful for identifying connection limit issues.

    This stresses:
    - TCP handshake
    - SSL handshake (if HTTPS)
    - HAProxy connection tracking
    """

    wait_time = between(0.1, 0.5)

    def on_start(self):
        """Configure session to not reuse connections."""
        # Create a new session for each user that doesn't pool
        self.client.pool_connections = 1
        self.client.pool_maxsize = 1

    @task
    def new_connection_request(self):
        """Make request with explicit connection close."""
        headers = {"Connection": "close"}
        with self.client.get(
            "/",
            headers=headers,
            catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"Status: {response.status_code}")


class KeepAliveStressUser(HttpUser):
    """User that tests keep-alive connection limits.

    Maintains long-lived connections with periodic requests
    to test connection aging and timeout behavior.

    HAProxy settings tested:
    - timeout client (client inactivity)
    - timeout http-keep-alive
    - maxconn (connection limits)
    """

    wait_time = between(5, 15)  # Long waits between requests

    @task
    def periodic_keepalive(self):
        """Send periodic requests to maintain connection."""
        self.client.get("/health/")


class ConcurrentConnectionUser(HttpUser):
    """User that opens multiple concurrent connections.

    Tests HAProxy's ability to handle multiple simultaneous
    connections from the same source.
    """

    wait_time = between(0.5, 1.0)

    @task
    def concurrent_requests(self):
        """Make multiple concurrent requests."""
        import concurrent.futures

        def make_request():
            try:
                return self.client.get("/", timeout=5)
            except Exception as e:
                return None

        # Use ThreadPoolExecutor for concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(5)]
            results = [f.result() for f in futures]

            # Count successful responses
            success_count = sum(
                1 for r in results
                if r is not None and r.status_code == 200
            )
            if success_count < 4:
                # Log as a failure if less than 80% succeeded
                self.environment.events.request.fire(
                    request_type="CONCURRENT",
                    name="5_parallel_requests",
                    response_time=0,
                    response_length=0,
                    exception=f"Only {success_count}/5 succeeded"
                )


class SlowClientUser(HttpUser):
    """User that simulates slow client behavior.

    Tests HAProxy's handling of slow clients that take time
    to send requests or receive responses.

    HAProxy settings tested:
    - timeout client
    - timeout http-request
    """

    wait_time = between(0.1, 0.3)

    @task
    def slow_receive(self):
        """Slowly receive a response."""
        with self.client.get(
            "/file_100k",
            stream=True,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                # Simulate slow client by reading slowly
                import time
                for chunk in response.iter_content(chunk_size=1024):
                    time.sleep(0.01)  # 10ms delay per KB


class ConnectionErrorUser(HttpUser):
    """User that tests error handling paths.

    Makes requests that may fail to test error handling
    and recovery behavior.
    """

    wait_time = between(1.0, 2.0)

    @task(5)
    def normal_request(self):
        """Normal successful request."""
        self.client.get("/")

    @task(2)
    def not_found(self):
        """Request non-existent resource."""
        with self.client.get(
            "/nonexistent_path_12345",
            catch_response=True
        ) as response:
            if response.status_code == 404:
                # Expected - mark as success
                response.success()
            else:
                response.failure(f"Expected 404, got {response.status_code}")

    @task(1)
    def timeout_request(self):
        """Request with short timeout."""
        try:
            self.client.get("/", timeout=0.001)
        except requests.exceptions.Timeout:
            # Expected timeout - this is fine
            pass


class PipelinedRequestUser(HttpUser):
    """User that simulates HTTP pipelining behavior.

    While HTTP/1.1 pipelining is rarely used, this tests
    rapid sequential requests on the same connection.
    """

    wait_time = constant(0)  # No wait between bursts

    @task
    def pipelined_burst(self):
        """Send a burst of rapid requests."""
        for _ in range(20):
            self.client.get("/")
        # Then wait before next burst
        import time
        time.sleep(1)
