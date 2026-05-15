from typing import Callable, TypeVar
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

T = TypeVar("T")


def with_retry(
    *,
    attempts: int = 3,
    wait_seconds: float = 1.0,
    max_wait: float = 8.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=wait_seconds, max=max_wait, jitter=0.5),
        reraise=True,
    )
