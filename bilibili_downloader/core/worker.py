import asyncio
import json
import logging
import os
import shutil
import subprocess
import time

import aiohttp

from bilibili_downloader.config import MIN_SPEED_LIMIT_KB
from bilibili_downloader.core.retry import retry_async
from bilibili_downloader.storage.files import build_filename, resolve_save_path

logger = logging.getLogger(__name__)


async def _apply_speed_limit(chunk_size: int, speed_limit_bps: int, elapsed: float):
    """Sleep to enforce speed limit. No-op if speed_limit_bps is 0 (unlimited)."""
    if speed_limit_bps <= 0:
        return
    expected_time = chunk_size / speed_limit_bps
    if elapsed < expected_time:
        await asyncio.sleep(expected_time - elapsed)


async def _download_stream(
    session: aiohttp.ClientSession,
    url: str,
    save_path: str,
    download_id: int,
    db,
    headers: dict | None = None,
    chunk_size: int = 1024 * 1024,
    speed_limit_bps: int = 0,
    existing_size: int = 0,
) -> int:
    """Download a stream with resume support and optional speed limit.

    Returns total bytes downloaded (including existing).
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    download_headers = dict(headers or {"Referer": "https://www.bilibili.com/"})
    if existing_size > 0:
        download_headers["Range"] = f"bytes={existing_size}-"

    async with session.get(url, headers=download_headers) as resp:
        resp.raise_for_status()
        # Determine total size
        content_range = resp.headers.get("Content-Range", "")
        if content_range and "/" in content_range:
            total_size_str = content_range.split("/")[-1]
            total_size = int(total_size_str) if total_size_str != "*" else 0
        else:
            total_size = existing_size + int(resp.headers.get("Content-Length", 0))

        downloaded = existing_size
        mode = "ab" if existing_size > 0 else "wb"
        with open(save_path, mode) as f:
            async for chunk in resp.content.iter_chunked(chunk_size):
                chunk_start = time.monotonic()
                f.write(chunk)
                downloaded += len(chunk)
                chunk_elapsed = time.monotonic() - chunk_start
                await _apply_speed_limit(len(chunk), speed_limit_bps, chunk_elapsed)
                if downloaded % (chunk_size * 10) == 0 or downloaded == total_size:
                    await db.update_download_progress(download_id, downloaded)
        return downloaded


async def _merge_audio_video(
    video_path: str,
    audio_path: str,
    output_path: str,
    download_id: int,
    db,
):
    """Merge video and audio streams using ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("ffmpeg not found, skipping merge. Files saved separately.")
        return False
    try:
        cmd = [
            ffmpeg, "-y",
            "-i", video_path, "-i", audio_path,
            "-c:v", "copy", "-c:a", "copy",
            output_path,
        ]
        logger.info(f"[merge] Running: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"[merge] ffmpeg failed: {stderr.decode()[:500]}")
            return False
        os.remove(video_path)
        os.remove(audio_path)
        logger.info(f"[merge] Merged to {output_path}, removed temp files")
        await db._conn.execute(
            "UPDATE download SET save_path=? WHERE id=?", (output_path, download_id)
        )
        await db._conn.commit()
        return True
    except Exception as e:
        logger.error(f"[merge] Error: {e}")
        return False


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
    speed_limit_bps: int = 0,
    ws_manager=None,
):
    bvid = video["remote_id"]
    try:
        await db.update_download_status(download_id, "downloading")

        extra = video.get("extra", {})
        if isinstance(extra, str):
            extra = json.loads(extra)
        cid = extra.get("cid")
        logger.debug(f"[worker] {bvid} extra={extra}, cid={cid}")

        # 1. Get stream URLs
        stream = None
        async with api_semaphore:
            if not cid:
                logger.info(f"[worker] {bvid} missing cid, fetching via API...")
                video_info = await retry_async(
                    lambda: api.get_video_info(bvid),
                    max_retries=3, backoff_base=2,
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
                            max_retries=2, backoff_base=2,
                        )
                    if video_info and video_info.get("tags"):
                        await db.update_video_tags(video["id"], video_info["tags"])
                except Exception as e:
                    logger.debug(f"[worker] {bvid} tag fetch failed: {e}")

            try:
                stream = await retry_async(
                    lambda: api.get_stream_urls(
                        video["remote_id"], cid, resolution_priority
                    ),
                    max_retries=3, backoff_base=2,
                )
                logger.debug(f"[worker] {bvid} stream: {stream['resolution']}, "
                             f"video={stream['video_url'][:60]}... audio={'yes' if stream.get('audio_url') else 'no'}")
            except ValueError as e:
                if "skipped" in str(e) or "62002" in str(e) or "充值" in str(e):
                    await db.update_download_status(download_id, "skipped", str(e))
                    logger.info(f"Skipped {bvid}: {e}")
                    return
                raise

        # 2. Build filename and paths
        filename = build_filename(
            title=video["title"], creator=creator_name,
            section=section_name, bvid=bvid, template=name_template,
        )
        save_path = resolve_save_path(save_dir, filename)
        video_tmp = save_path + ".video.tmp"
        audio_tmp = save_path + ".audio.tmp"

        # 3. Download video stream with resume + speed limit
        existing_video_size = 0
        if os.path.exists(video_tmp):
            existing_video_size = os.path.getsize(video_tmp)
            logger.info(f"[worker] {bvid} Resuming video from {existing_video_size} bytes")

        async with download_semaphore:
            await _download_stream(
                session, stream["video_url"], video_tmp, download_id, db,
                headers=api.headers, speed_limit_bps=speed_limit_bps,
                existing_size=existing_video_size,
            )

        # 4. Download audio stream with resume + speed limit
        if stream.get("audio_url"):
            existing_audio_size = 0
            if os.path.exists(audio_tmp):
                existing_audio_size = os.path.getsize(audio_tmp)
                logger.info(f"[worker] {bvid} Resuming audio from {existing_audio_size} bytes")
            async with download_semaphore:
                await _download_stream(
                    session, stream["audio_url"], audio_tmp, download_id, db,
                    headers=api.headers, speed_limit_bps=speed_limit_bps,
                    existing_size=existing_audio_size,
                )

        # 5. Merge audio + video with ffmpeg
        if stream.get("audio_url") and os.path.exists(video_tmp) and os.path.exists(audio_tmp):
            merged = await _merge_audio_video(video_tmp, audio_tmp, save_path, download_id, db)
        elif not stream.get("audio_url"):
            os.rename(video_tmp, save_path)

        # 6. Update final status
        if os.path.exists(save_path):
            final_size = os.path.getsize(save_path)
            await db.update_download_progress(download_id, final_size)
            await db.update_download_status(download_id, "completed")
            logger.info(f"Completed {filename} ({stream['resolution']}, {final_size} bytes)")
        else:
            await db.update_download_status(download_id, "failed", "Merge failed, no output file")

    except Exception as e:
        logger.error(f"Failed {bvid}: {e}", exc_info=True)
        await db.update_download_status(download_id, "failed", str(e))
