import asyncio
import logging

from bilibili_downloader.config import DEFAULT_NAME_TEMPLATE, MAX_CONCURRENT_DOWNLOADS, MAX_CONCURRENT_API_REQUESTS
from bilibili_downloader.core.worker import download_video
from bilibili_downloader.storage.files import build_filename, resolve_save_path

logger = logging.getLogger(__name__)


class DownloadManager:
    def __init__(self, db, api, save_dir: str, resolution_priority: list[str] | None = None,
                 max_concurrent_downloads: int = MAX_CONCURRENT_DOWNLOADS,
                 max_concurrent_api: int = MAX_CONCURRENT_API_REQUESTS,
                 name_template: str = DEFAULT_NAME_TEMPLATE):
        self.db = db
        self.api = api
        self.save_dir = save_dir
        self.resolution_priority = resolution_priority or ["720p", "480p", "1080p", "240p"]
        self.max_concurrent_downloads = max_concurrent_downloads
        self.max_concurrent_api = max_concurrent_api
        self.name_template = name_template
        self.api_semaphore = asyncio.Semaphore(max_concurrent_api)
        self.download_semaphore = asyncio.Semaphore(max_concurrent_downloads)

    async def _build_queue(self, creator_id: int) -> list[dict]:
        videos = await self.db.get_videos_by_creator(creator_id)
        existing = await self.db.get_existing_downloads(creator_id)
        queue = []
        for video in videos:
            if (video["remote_id"], self.resolution_priority[0]) not in existing:
                queue.append(video)
        return queue

    async def run(self, session):
        # Auto-discover: enqueue un-downloaded videos for all creators
        creators = await self.db.get_all_creators()
        for creator in creators:
            queue = await self._build_queue(creator["id"])
            for video in queue:
                filename = build_filename(
                    title=video["title"], creator=creator["name"],
                    section=video.get("section_name"), bvid=video.get("remote_id", ""),
                    template=self.name_template,
                )
                save_path = resolve_save_path(self.save_dir, filename)
                await self.db.insert_download(
                    video_id=video["id"], save_path=save_path,
                    resolution=self.resolution_priority[0],
                )

        # Process all pending downloads
        pending = await self.db.get_all_downloads(status="pending")
        if not pending:
            logger.info("No pending downloads")
            return

        tasks = []
        for dl in pending:
            video = await self.db.get_video(dl["video_id"])
            if not video:
                logger.warning(f"download id={dl['id']} 关联的 video_id={dl['video_id']} 不存在，跳过")
                continue
            creator_name = dl.get("creator_name")
            if not creator_name:
                cur = await self.db._conn.execute(
                    "SELECT c.name FROM creator c JOIN video v ON v.creator_id = c.id WHERE v.id=?",
                    (dl["video_id"],),
                )
                row = await cur.fetchone()
                if not row:
                    logger.warning(f"download id={dl['id']} video_id={dl['video_id']} 找不到对应创作者，跳过")
                    continue
                creator_name = row[0]

            logger.info(f"开始下载: {video['title']} (bvid={video['remote_id']})")
            tasks.append(download_video(
                db=self.db, download_id=dl["id"], video=video,
                creator_name=creator_name, section_name=video.get("section_name"),
                save_dir=self.save_dir, api=self.api, session=session,
                resolution_priority=self.resolution_priority,
                name_template=self.name_template,
                api_semaphore=self.api_semaphore,
                download_semaphore=self.download_semaphore,
            ))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def enqueue_creator_videos(self, creator_id: int):
        videos = await self.db.get_videos_by_creator(creator_id)
        existing = await self.db.get_existing_downloads(creator_id)
        new_count = 0
        for video in videos:
            if (video["remote_id"], self.resolution_priority[0]) not in existing:
                creator = await self.db.get_creator(creator_id)
                filename = build_filename(
                    title=video["title"], creator=creator["name"],
                    section=video.get("section_name"), bvid=video.get("remote_id", ""),
                    template=self.name_template,
                )
                save_path = resolve_save_path(self.save_dir, filename)
                await self.db.insert_download(video_id=video["id"], save_path=save_path, resolution=self.resolution_priority[0])
                new_count += 1
        logger.info(f"Enqueued {new_count} new downloads for creator {creator_id}")
        return new_count
