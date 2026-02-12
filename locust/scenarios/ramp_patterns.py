"""Custom load shape patterns for performance testing.

These load shapes control how users are spawned over time,
enabling different testing patterns for bottleneck identification.

Usage:
    locust -f locustfile.py --host http://VIP \
           --class-picker BasicHTTPUser \
           --headless

    # The load shape is automatically used when included
"""

import math
from locust import LoadTestShape


class StepLoadShape(LoadTestShape):
    """Step function load pattern.

    Increases load in discrete steps, holding each level
    for a period before stepping up. Useful for identifying
    the breaking point.

    Pattern:
        Step 1: 10 users for 60 seconds
        Step 2: 25 users for 60 seconds
        Step 3: 50 users for 60 seconds
        Step 4: 75 users for 60 seconds
        Step 5: 100 users for 60 seconds
    """

    steps = [
        {"duration": 60, "users": 10, "spawn_rate": 5},
        {"duration": 60, "users": 25, "spawn_rate": 5},
        {"duration": 60, "users": 50, "spawn_rate": 10},
        {"duration": 60, "users": 75, "spawn_rate": 10},
        {"duration": 60, "users": 100, "spawn_rate": 10},
    ]

    def tick(self):
        """Calculate current user target based on elapsed time."""
        run_time = self.get_run_time()

        cumulative_time = 0
        for step in self.steps:
            cumulative_time += step["duration"]
            if run_time < cumulative_time:
                return (step["users"], step["spawn_rate"])

        # Test complete
        return None


class LinearRampShape(LoadTestShape):
    """Linear ramp-up load pattern.

    Gradually increases users at a constant rate up to a
    maximum, then holds steady. Good for finding the point
    where performance degrades.

    Parameters (can be overridden):
        ramp_time: Time in seconds to reach max users (default: 300)
        max_users: Maximum number of users (default: 100)
        steady_time: Time to hold at max after ramp (default: 300)
    """

    ramp_time = 300  # 5 minutes to ramp up
    max_users = 100
    steady_time = 300  # 5 minutes at steady state

    def tick(self):
        """Calculate current user target."""
        run_time = self.get_run_time()

        if run_time < self.ramp_time:
            # Ramping up
            current_users = int(
                (run_time / self.ramp_time) * self.max_users
            )
            spawn_rate = max(1, self.max_users // self.ramp_time)
            return (max(1, current_users), spawn_rate)

        elif run_time < self.ramp_time + self.steady_time:
            # Steady state
            return (self.max_users, 1)

        # Test complete
        return None


class SpikeLoadShape(LoadTestShape):
    """Spike load pattern.

    Maintains a baseline load with periodic spikes.
    Tests load balancer response to sudden traffic bursts.

    Pattern:
        - Baseline: 20 users
        - Spike: 100 users for 30 seconds
        - Spike interval: every 2 minutes
    """

    baseline_users = 20
    spike_users = 100
    spike_duration = 30  # seconds
    spike_interval = 120  # seconds (2 minutes)
    total_duration = 600  # 10 minutes total

    def tick(self):
        """Calculate current user target."""
        run_time = self.get_run_time()

        if run_time > self.total_duration:
            return None

        # Check if we're in a spike period
        cycle_time = run_time % self.spike_interval
        in_spike = cycle_time < self.spike_duration

        if in_spike:
            return (self.spike_users, 50)  # Fast spawn during spike
        else:
            return (self.baseline_users, 10)


class SoakLoadShape(LoadTestShape):
    """Soak test load pattern.

    Maintains constant load for an extended period to
    identify memory leaks, connection leaks, or gradual
    degradation.

    Parameters:
        users: Number of concurrent users (default: 50)
        duration: Test duration in seconds (default: 3600 = 1 hour)
    """

    users = 50
    duration = 3600  # 1 hour

    def tick(self):
        """Calculate current user target."""
        run_time = self.get_run_time()

        if run_time < self.duration:
            return (self.users, 10)

        return None


class DoubleLoadShape(LoadTestShape):
    """Double the load pattern.

    Doubles the user count at regular intervals to find
    breaking point quickly.

    Pattern: 1 -> 2 -> 4 -> 8 -> 16 -> 32 -> 64 -> 128
    Each level held for 30 seconds.
    """

    base_users = 1
    max_users = 128
    step_duration = 30  # seconds per level

    def tick(self):
        """Calculate current user target."""
        run_time = self.get_run_time()

        # Calculate which step we're on
        step = int(run_time // self.step_duration)

        # Calculate users (powers of 2)
        users = self.base_users * (2 ** step)

        if users > self.max_users:
            return None

        spawn_rate = max(10, users // 5)
        return (users, spawn_rate)


class SineWaveShape(LoadTestShape):
    """Sine wave load pattern.

    Oscillates load in a sine wave pattern to test
    auto-scaling and adaptive behavior.

    Parameters:
        min_users: Minimum users at wave trough
        max_users: Maximum users at wave peak
        period: Wave period in seconds
        duration: Total test duration
    """

    min_users = 10
    max_users = 100
    period = 120  # 2 minute wave
    duration = 600  # 10 minutes

    def tick(self):
        """Calculate current user target."""
        run_time = self.get_run_time()

        if run_time > self.duration:
            return None

        # Calculate sine wave value (0 to 1)
        wave = (math.sin(2 * math.pi * run_time / self.period) + 1) / 2

        # Scale to user range
        user_range = self.max_users - self.min_users
        users = int(self.min_users + (wave * user_range))

        return (users, 10)


class BreakingPointShape(LoadTestShape):
    """Breaking point finder pattern.

    Keeps increasing load until response times exceed threshold,
    then backs off. Useful for automated capacity testing.

    This is a more aggressive version of step load that
    continues until performance degrades.
    """

    initial_users = 10
    user_increment = 10
    increment_interval = 30  # seconds
    max_users = 500

    def tick(self):
        """Calculate current user target."""
        run_time = self.get_run_time()

        # Calculate current step
        step = int(run_time // self.increment_interval)
        users = self.initial_users + (step * self.user_increment)

        if users > self.max_users:
            return None

        spawn_rate = max(5, self.user_increment)
        return (users, spawn_rate)
