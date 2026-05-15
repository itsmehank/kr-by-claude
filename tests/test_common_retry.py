import pytest

from kr_pipeline.common.retry import with_retry


def test_retry_succeeds_on_third_attempt():
    attempts = []

    @with_retry(attempts=3, wait_seconds=0)
    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient")
        return "ok"

    assert flaky() == "ok"
    assert len(attempts) == 3


def test_retry_gives_up_after_max_attempts():
    attempts = []

    @with_retry(attempts=2, wait_seconds=0)
    def always_fails():
        attempts.append(1)
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError, match="permanent"):
        always_fails()
    assert len(attempts) == 2
