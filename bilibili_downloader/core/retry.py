import asyncio
import logging
import aiohttp

logger = logging.getLogger(__name__)

_NO_RETRY_KEYWORDS = ("code=-404", "code=62002", "skipped:")


async def retry_async(func, max_retries: int = 3, backoff_base: float = 2):
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            return await func()
        except (ValueError, TypeError) as exc:
            error_msg = str(exc)
            if any(kw in error_msg for kw in _NO_RETRY_KEYWORDS):
                raise
            last_exc = exc
            if attempt < max_retries:
                delay = backoff_base ** attempt
                logger.warning(f"Retry {attempt}/{max_retries} after {delay}s: {exc}")
                await asyncio.sleep(delay)
        except (aiohttp.ClientError, ConnectionError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = backoff_base ** attempt
                logger.warning(f"Retry {attempt}/{max_retries} after {delay}s: {exc}")
                await asyncio.sleep(delay)
    raise last_exc
