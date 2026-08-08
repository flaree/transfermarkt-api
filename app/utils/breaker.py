import threading
import time
from typing import Callable

from app.settings import settings


class CircuitBreaker:
    """
    Trips open after repeated bot challenges and stops outbound requests for a cooldown period.

    Retrying into an active block tends to deepen it, and every blocked attempt still costs a full
    network round trip. Once the breaker is open, requests fail immediately so the caller can fall
    back to stale cached data without waiting on an upstream that is not going to answer.

    Args:
        threshold (int): Consecutive challenges required to open the circuit.
        cooldown (float): Seconds the circuit stays open before allowing a trial request.
        clock (Callable[[], float]): Monotonic time source, injectable for tests.
    """

    def __init__(
        self,
        threshold: int = None,
        cooldown: float = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the CircuitBreaker."""
        self._threshold = settings.BOT_BREAKER_THRESHOLD if threshold is None else threshold
        self._cooldown = settings.BOT_BREAKER_COOLDOWN if cooldown is None else cooldown
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = None

    def allow(self) -> bool:
        """
        Check whether an outbound request may be attempted.

        Returns:
            bool: True if the circuit is closed, or open but past its cooldown (a trial request).
        """
        if not settings.BOT_BREAKER_ENABLE:
            return True

        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at >= self._cooldown:
                # Let a single trial request through; success closes the circuit, failure re-opens it.
                self._opened_at = None
                self._failures = self._threshold - 1
                return True
            return False

    def record_success(self) -> None:
        """Reset the failure count and close the circuit."""
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        """Count a bot challenge, opening the circuit once the threshold is reached."""
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._opened_at = self._clock()

    @property
    def is_open(self) -> bool:
        """
        Report whether the circuit is currently open.

        Returns:
            bool: True if outbound requests are being suppressed.
        """
        with self._lock:
            return self._opened_at is not None

    @property
    def retry_after(self) -> int:
        """
        Report how long a client should wait before retrying.

        Returns:
            int: Seconds remaining on the cooldown, or 0 if the circuit is closed.
        """
        with self._lock:
            if self._opened_at is None:
                return 0
            remaining = self._cooldown - (self._clock() - self._opened_at)
            return max(1, int(remaining + 0.5)) if remaining > 0 else 0

    def reset(self) -> None:
        """Return the breaker to its initial closed state (used by tests)."""
        with self._lock:
            self._failures = 0
            self._opened_at = None


bot_breaker = CircuitBreaker()
