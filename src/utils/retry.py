"""
Retry logic with exponential backoff for CoreRag.

Handles transient failures in API calls and processing.
"""

import functools
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple, Type, Union

logger = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    initial_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    exponential_base: float = 2.0
    jitter: bool = True  # Add randomness to prevent thundering herd
    jitter_factor: float = 0.1  # ±10% jitter


# Common transient exceptions that should trigger retry
TRANSIENT_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,  # Includes network errors
)


class RetryableError(Exception):
    """Mark an error as retryable."""
    pass


class NonRetryableError(Exception):
    """Mark an error as non-retryable (fail immediately)."""
    pass


def with_retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = TRANSIENT_EXCEPTIONS,
    on_retry: Optional[Callable[[Exception, int], None]] = None
):
    """
    Decorator for adding retry logic to functions.

    Usage:
        @with_retry(max_attempts=3, initial_delay=1.0)
        def call_api():
            return api.request()

        @with_retry(
            max_attempts=5,
            retryable_exceptions=(ConnectionError, TimeoutError)
        )
        async def async_call_api():
            return await api.async_request()
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return retry_with_backoff(
                func,
                args=args,
                kwargs=kwargs,
                max_attempts=max_attempts,
                initial_delay=initial_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                jitter=jitter,
                retryable_exceptions=retryable_exceptions,
                on_retry=on_retry
            )
        return wrapper
    return decorator


def retry_with_backoff(
    func: Callable,
    args: tuple = (),
    kwargs: dict = None,
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = TRANSIENT_EXCEPTIONS,
    on_retry: Optional[Callable[[Exception, int], None]] = None
) -> Any:
    """
    Execute a function with exponential backoff retry.

    Args:
        func: Function to execute
        args: Positional arguments for func
        kwargs: Keyword arguments for func
        max_attempts: Maximum retry attempts
        initial_delay: Initial delay between retries
        max_delay: Maximum delay between retries
        exponential_base: Base for exponential backoff
        jitter: Whether to add randomness to delays
        retryable_exceptions: Exception types that trigger retry
        on_retry: Callback on each retry (exception, attempt_number)

    Returns:
        Result of func

    Raises:
        Last exception if all retries exhausted
    """
    kwargs = kwargs or {}
    last_exception = None

    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)

        except NonRetryableError:
            # Explicitly non-retryable, fail immediately
            raise

        except retryable_exceptions as e:
            last_exception = e

            if attempt == max_attempts:
                logger.error(
                    f"All {max_attempts} attempts failed for {func.__name__}: {e}"
                )
                raise

            # Calculate delay with exponential backoff
            delay = min(
                initial_delay * (exponential_base ** (attempt - 1)),
                max_delay
            )

            # Add jitter
            if jitter:
                jitter_range = delay * 0.1
                delay += random.uniform(-jitter_range, jitter_range)

            logger.warning(
                f"Attempt {attempt}/{max_attempts} failed for {func.__name__}: {e}. "
                f"Retrying in {delay:.1f}s..."
            )

            if on_retry:
                on_retry(e, attempt)

            time.sleep(delay)

        except RetryableError as e:
            # Explicitly marked as retryable
            last_exception = e

            if attempt == max_attempts:
                raise

            delay = min(
                initial_delay * (exponential_base ** (attempt - 1)),
                max_delay
            )

            if jitter:
                jitter_range = delay * 0.1
                delay += random.uniform(-jitter_range, jitter_range)

            logger.warning(f"Retryable error on attempt {attempt}: {e}")

            if on_retry:
                on_retry(e, attempt)

            time.sleep(delay)

    raise last_exception


class RetryBudget:
    """
    Track retry budget to prevent excessive retries system-wide.

    Implements circuit breaker pattern.
    """

    def __init__(
        self,
        max_retries_per_minute: int = 10,
        cooldown_seconds: float = 60.0
    ):
        """
        Initialize retry budget.

        Args:
            max_retries_per_minute: Maximum retries allowed per minute
            cooldown_seconds: Cooldown period when budget exhausted
        """
        self.max_retries = max_retries_per_minute
        self.cooldown = cooldown_seconds
        self._retry_times: list = []
        self._cooldown_until: float = 0

    def can_retry(self) -> bool:
        """Check if retry is allowed."""
        now = time.time()

        # Check cooldown
        if now < self._cooldown_until:
            return False

        # Clean old entries (older than 1 minute)
        self._retry_times = [t for t in self._retry_times if now - t < 60]

        return len(self._retry_times) < self.max_retries

    def record_retry(self) -> None:
        """Record a retry attempt."""
        now = time.time()
        self._retry_times.append(now)

        # Trigger cooldown if budget exhausted
        if len(self._retry_times) >= self.max_retries:
            self._cooldown_until = now + self.cooldown
            logger.warning(f"Retry budget exhausted. Cooling down for {self.cooldown}s")

    def time_until_available(self) -> float:
        """Get seconds until retry is available."""
        now = time.time()

        if now < self._cooldown_until:
            return self._cooldown_until - now

        return 0.0


class CircuitBreaker:
    """
    Circuit breaker for protecting against cascading failures.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Failures exceeded threshold, requests fail immediately
    - HALF_OPEN: Testing if service recovered
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout_seconds: float = 60.0
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Failures before opening circuit
            success_threshold: Successes needed to close from half-open
            timeout_seconds: Time before attempting recovery
        """
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout_seconds

        self._state = self.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0

    @property
    def state(self) -> str:
        """Get current circuit state."""
        if self._state == self.OPEN:
            # Check if timeout expired
            if time.time() - self._last_failure_time >= self.timeout:
                self._state = self.HALF_OPEN
                self._success_count = 0
                logger.info("Circuit breaker: OPEN -> HALF_OPEN")

        return self._state

    def allow_request(self) -> bool:
        """Check if request should be allowed."""
        state = self.state

        if state == self.CLOSED:
            return True
        elif state == self.HALF_OPEN:
            return True  # Allow test requests
        else:  # OPEN
            return False

    def record_success(self) -> None:
        """Record successful request."""
        if self._state == self.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                self._state = self.CLOSED
                self._failure_count = 0
                logger.info("Circuit breaker: HALF_OPEN -> CLOSED")
        else:
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record failed request."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == self.HALF_OPEN:
            # Single failure in half-open reopens
            self._state = self.OPEN
            logger.warning("Circuit breaker: HALF_OPEN -> OPEN")

        elif self._failure_count >= self.failure_threshold:
            self._state = self.OPEN
            logger.warning(
                f"Circuit breaker: CLOSED -> OPEN "
                f"(after {self._failure_count} failures)"
            )

    def __call__(self, func: Callable) -> Callable:
        """Use as decorator."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not self.allow_request():
                raise NonRetryableError(
                    f"Circuit breaker is OPEN for {func.__name__}"
                )

            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure()
                raise

        return wrapper


# Pre-configured retry strategies for common use cases
class RetryStrategies:
    """Pre-built retry strategies for common scenarios."""

    @staticmethod
    def api_call() -> dict:
        """Strategy for API calls."""
        return {
            "max_attempts": 3,
            "initial_delay": 1.0,
            "max_delay": 30.0,
            "exponential_base": 2.0,
            "jitter": True,
            "retryable_exceptions": (
                ConnectionError,
                TimeoutError,
                OSError,
            )
        }

    @staticmethod
    def file_operation() -> dict:
        """Strategy for file operations."""
        return {
            "max_attempts": 3,
            "initial_delay": 0.5,
            "max_delay": 5.0,
            "exponential_base": 2.0,
            "jitter": False,
            "retryable_exceptions": (
                OSError,
                IOError,
                PermissionError,
            )
        }

    @staticmethod
    def embedding_api() -> dict:
        """Strategy for embedding API calls."""
        return {
            "max_attempts": 5,
            "initial_delay": 2.0,
            "max_delay": 60.0,
            "exponential_base": 2.0,
            "jitter": True,
            "retryable_exceptions": (
                ConnectionError,
                TimeoutError,
                OSError,
            )
        }

    @staticmethod
    def database_operation() -> dict:
        """Strategy for database operations."""
        return {
            "max_attempts": 3,
            "initial_delay": 0.1,
            "max_delay": 2.0,
            "exponential_base": 2.0,
            "jitter": True,
            "retryable_exceptions": (
                OSError,
                IOError,
            )
        }
