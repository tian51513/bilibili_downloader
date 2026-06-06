import asyncio
import json
import logging
import os

import aiohttp

from bilibili_downloader.core.retry import retry_async
from bilibili_downloader.storage.files import build_filename, resolve_save_path

logger = logging.getLogger(__name__)


async def download_video(
    db,
    download_id: int,
    video: dict,
    creator_name: str,
    section_name: str | None,
    save_dir: str,
    api,
    session: aiohttp.ClientSession,
    resolution_priority: list[str],
    name_template: str,
    api_semaphore: asyncio.Semaphore,
    download_semaphore: asyncio.Semaphore,
):
    try:
        await db.update_download_status(download_id, "downloading")

        extra = video.get("extra", {})
        if isinstance(extra, str):
            extra = json.loads(extra)
        cid = extra.get("cid")

        # 1. Get stream URLs (rate-limited by api_semaphore)
        async with api_semaphore:
            try:
                stream = await retry_async(
                    lambda: api.get_stream_urls(
                        video["remote_id"], cid, resolution_priority
                    ),
                    max_retries=3,
                    backoff_base=2,
                )
            except ValueError as e:
                if "skipped" in str(e) or "62002" in str(e) or "充值" in str(e):
                    await db.update_download_status(download_id, "skipped", str(e))
                    logger.info(f"Skipped {video['remote_id']}: {e}")
                    return
                raise

        # 2. Build filename and save path
        filename = build_filename(
            title=video["title"],
            creator=creator_name,
            section=section_name,
            template=name_template,
        )
        save_path = resolve_save_path(save_dir, filename)

        # 3. Download video stream (rate-limited by download_semaphore)
        total_size = 0
        async with download_semaphore:
            await _download_stream(
                session, stream["video_url"], save_path, download_id, db
            )
            if os.path.exists(save_path):
                total_size = os.path.getsize(save_path)
            await db.update_download_progress(download_id, total_size)

        # 4. Update save_path in DB
        await db._conn.execute(
            "UPDATE download SET save_path=? WHERE id=?", (save_path, download_id)
        )
        await db._conn.commit()

        await db.update_download_status(download_id, "completed")
        logger.info(
            f"Completed {filename} ({stream['resolution']}, {total_size} bytes)"
        )

    except Exception as e:
        logger.error(f"Failed {video['remote_id']}: {e}")
        await db.update_download_status(download_id, "failed", str(e))


async def _download_stream(
    session: aiohttp.ClientSession,
    url: str,
    save_path: str,
    download_id: int,
    db,
    chunk_size: int = 1024 * 1024,
):
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    async with session.get(url) as resp:
        resp.raise_for_status()
        downloaded = 0
        with open(save_path, "wb") as f:
            async for chunk in resp.content.iter_chunked(chunk_size):
                f.write(chunk)
                downloaded += len(chunk)
                if downloaded % (chunk_size * 10) == 0:
                    await db.update_download_progress(download_id, downloaded)
