"""Variable payload size test scenarios.

These scenarios test load balancer behavior with different
request and response sizes to identify bandwidth vs connection
bottlenecks.
"""

import random
import string

from locust import HttpUser, task, between


def generate_payload(size_bytes: int) -> str:
    """Generate a random string payload of specified size."""
    return ''.join(
        random.choices(string.ascii_letters + string.digits, k=size_bytes)
    )


class SmallPayloadUser(HttpUser):
    """User with small request/response payloads.

    Tests connection establishment overhead with minimal
    data transfer. Good for testing connection limits.
    """

    wait_time = between(0.1, 0.3)

    @task
    def small_request(self):
        """Small request and response (~1KB)."""
        payload = {"data": generate_payload(100)}
        self.client.post("/api/data", json=payload)


class LargeDownloadUser(HttpUser):
    """User that downloads large responses.

    Tests download throughput - identifies egress bandwidth
    bottlenecks and HAProxy buffer settings.
    """

    wait_time = between(0.5, 1.5)

    @task(5)
    def download_100k(self):
        """Download 100KB file."""
        self.client.get("/file_100k")

    @task(3)
    def download_1m(self):
        """Download 1MB file."""
        self.client.get("/large_file")

    @task(1)
    def download_with_timing(self):
        """Download with explicit timing measurement."""
        with self.client.get(
            "/large_file",
            catch_response=True,
            name="/large_file (timed)"
        ) as response:
            if response.status_code == 200:
                # Response time is automatically measured
                content_length = len(response.content)
                if content_length < 900000:  # Expecting ~1MB
                    response.failure(
                        f"Short response: {content_length} bytes"
                    )


class LargeUploadUser(HttpUser):
    """User that uploads large request payloads.

    Tests upload throughput - identifies ingress bandwidth
    bottlenecks and request buffer settings.
    """

    wait_time = between(0.5, 2.0)

    def on_start(self):
        """Generate payloads once at start."""
        self.payload_10k = generate_payload(10 * 1024)
        self.payload_100k = generate_payload(100 * 1024)
        self.payload_1m = generate_payload(1024 * 1024)

    @task(5)
    def upload_10k(self):
        """Upload 10KB payload."""
        self.client.post(
            "/api/data",
            data=self.payload_10k,
            headers={"Content-Type": "application/octet-stream"}
        )

    @task(3)
    def upload_100k(self):
        """Upload 100KB payload."""
        self.client.post(
            "/api/data",
            data=self.payload_100k,
            headers={"Content-Type": "application/octet-stream"}
        )

    @task(1)
    def upload_1m(self):
        """Upload 1MB payload."""
        self.client.post(
            "/api/data",
            data=self.payload_1m,
            headers={"Content-Type": "application/octet-stream"}
        )


class MixedPayloadUser(HttpUser):
    """User with mixed payload sizes.

    Simulates realistic traffic with varying request/response
    sizes. Tests load balancer buffer management.
    """

    wait_time = between(0.3, 1.0)

    def on_start(self):
        """Prepare payloads."""
        self.small_payload = generate_payload(100)
        self.medium_payload = generate_payload(10 * 1024)
        self.large_payload = generate_payload(100 * 1024)

    @task(10)
    def small_both(self):
        """Small request, small response."""
        self.client.post("/api/data", json={"data": self.small_payload})

    @task(5)
    def small_request_large_response(self):
        """Small request, large response (download)."""
        self.client.get("/file_100k")

    @task(3)
    def large_request_small_response(self):
        """Large request, small response (upload)."""
        self.client.post(
            "/api/data",
            data=self.medium_payload,
            headers={"Content-Type": "application/octet-stream"}
        )

    @task(1)
    def large_both(self):
        """Large request and response."""
        self.client.post(
            "/api/data",
            data=self.large_payload,
            headers={"Content-Type": "application/octet-stream"}
        )


class StreamingUser(HttpUser):
    """User that tests streaming/chunked responses.

    Tests HAProxy's handling of chunked transfer encoding
    and streaming responses.
    """

    wait_time = between(1.0, 3.0)

    @task
    def streaming_download(self):
        """Download with streaming enabled."""
        with self.client.get(
            "/large_file",
            stream=True,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                # Consume the stream
                total_bytes = 0
                for chunk in response.iter_content(chunk_size=8192):
                    total_bytes += len(chunk)

                if total_bytes < 900000:
                    response.failure(f"Short stream: {total_bytes} bytes")
            else:
                response.failure(f"Status: {response.status_code}")
