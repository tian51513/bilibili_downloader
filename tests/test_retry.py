import pytest
import asyncio
import aiohttp


class TestRetry:
    async def test_success_no_retry(self):
        from platform_video_downloader.core.retry import retry_async

        call_count = 0

        async def success():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_async(success, max_retries=3)
        assert result == "ok"
        assert call_count == 1

    async def test_retry_then_success(self):
        from platform_video_downloader.core.retry import retry_async

        call_count = 0

        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise aiohttp.ClientError("timeout")
            return "ok"

        result = await retry_async(fail_twice, max_retries=3, backoff_base=0)
        assert result == "ok"
        assert call_count == 3

    async def test_exhaust_retries_raises(self):
        from platform_video_downloader.core.retry import retry_async

        async def always_fail():
            raise ConnectionError("dead")

        with pytest.raises(ConnectionError):
            await retry_async(always_fail, max_retries=2, backoff_base=0)

    async def test_no_retry_on_permanent_error(self):
        from platform_video_downloader.core.retry import retry_async

        call_count = 0

        async def fail_404():
            nonlocal call_count
            call_count += 1
            raise ValueError("API error: code=-404, message=视频不可用")

        with pytest.raises(ValueError):
            await retry_async(fail_404, max_retries=3, backoff_base=0)
        assert call_count == 1

    async def test_no_retry_on_skip_error(self):
        from platform_video_downloader.core.retry import retry_async

        call_count = 0

        async def fail_skip():
            nonlocal call_count
            call_count += 1
            raise ValueError("skipped: 需充值")

        with pytest.raises(ValueError, match="skipped"):
            await retry_async(fail_skip, max_retries=3, backoff_base=0)
        assert call_count == 1
