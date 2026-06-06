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
    bvid = video["remote_id"]
    try:
        await db.update_download_status(download_id, "downloading")

        extra = video.get("extra", {})
        if isinstance(extra, str):
            extra = json.loads(extra)
        cid = extra.get("cid")
        logger.debug(f"[worker] {bvid} extra={extra}, cid={cid}")

        # 1. Get stream URLs (rate-limited by api_semaphore)
        async with api_semaphore:
            if not cid:
                logger.info(f"[worker] {bvid} 缺少cid，通过API获取...")
                video_info = await retry_async(
                    lambda: api.get_video_info(bvid),
                    max_retries=3,
                    backoff_base=2,
                )
                cid = video_info["cid"]
            else:
                video_info = None

            # Fetch tags if video doesn't have them yet
            if video.get("id") and not video.get("tags"):
                try:
                    if not video_info:
                        video_info = await retry_async(
                            lambda: api.get_video_info(bvid),
                            max_retries=2,
                            backoff_base=2,
                        )
                    if video_info and video_info.get("tags"):
                        await db.update_video_tags(video["id"], video_info["tags"])
                except Exception as e:
                    logger.debug(f"[worker] {bvid} 获取标签失败: {e}")
            try:
                stream = await retry_async(
                    lambda: api.get_stream_urls(
                        video["remote_id"], cid, resolution_priority
                    ),
                    max_retries=3,
                    backoff_base=2,
                )
                logger.debug(f"[worker] {bvid} stream: {stream['resolution']}, video_url={stream['video_url'][:80]}...")
            except ValueError as e:
                if "skipped" in str(e) or "62002" in str(e) or "充值" in str(e):
                    await db.update_download_status(download_id, "skipped", str(e))
                    logger.info(f"Skipped {bvid}: {e}")
                    return
                raise

        # 2. Build filename and save path
        filename = build_filename(
            title=video["title"],
            creator=creator_name,
            section=section_name,
            bvid=bvid,
            template=name_template,
        )
        save_path = resolve_save_path(save_dir, filename)

        # 3. Download video stream (rate-limited by download_semaphore)
        total_size = 0
        async with download_semaphore:
            await _download_stream(
                session, stream["video_url"], save_path, download_id, db,
                headers=api.headers,
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
        logger.error(f"Failed {bvid}: {e}", exc_info=True)
        await db.update_download_status(download_id, "failed", str(e))


async def _download_stream(
    session: aiohttp.ClientSession,
    url: str,
    save_path: str,
    download_id: int,
    db,
    headers: dict | None = None,
    chunk_size: int = 1024 * 1024,
):
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    download_headers = headers or {"Referer": "https://www.bilibili.com/"}
    async with session.get(url, headers=download_headers) as resp:
        resp.raise_for_status()
        downloaded = 0
        with open(save_path, "wb") as f:
            async for chunk in resp.content.iter_chunked(chunk_size):
                f.write(chunk)
                downloaded += len(chunk)
                if downloaded % (chunk_size * 10) == 0:
                    await db.update_download_progress(download_id, downloaded)
