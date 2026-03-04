"""
Unit tests for the retry decorator.

Tests retry behavior including successful execution, exhausted attempts,
specific exception filtering, and backoff delays.
"""

import asyncio
import pytest
from utils.retry import retry


class TestRetryDecorator:
    """Test suite for the async retry decorator."""

    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        """Function that succeeds immediately should not retry."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_success_after_retries(self):
        """Function that fails then succeeds should retry correctly."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, jitter=False)
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient error")
            return "ok"

        result = await fail_then_succeed()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_all_attempts_exhausted(self):
        """Should raise after all attempts are exhausted."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, jitter=False)
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("permanent failure")

        with pytest.raises(RuntimeError, match="permanent failure"):
            await always_fail()

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_specific_exception_types(self):
        """Should only retry on specified exception types."""
        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, exceptions=(ValueError,), jitter=False)
        async def raise_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            await raise_type_error()

        # Should not retry because TypeError is not in the exceptions list
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_matching_exception(self):
        """Should retry when the matching exception type is raised."""
        call_count = 0

        @retry(max_attempts=2, base_delay=0.01, exceptions=(ValueError,), jitter=False)
        async def raise_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("retryable")

        with pytest.raises(ValueError):
            await raise_value_error()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_preserves_return_value(self):
        """Should preserve the return value of the wrapped function."""

        @retry(max_attempts=1, base_delay=0.01)
        async def return_dict():
            return {"key": "value", "count": 42}

        result = await return_dict()
        assert result == {"key": "value", "count": 42}
