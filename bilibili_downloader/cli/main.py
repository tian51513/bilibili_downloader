import argparse
import asyncio
import logging
import re
import sys

import aiohttp

from bilibili_downloader.config import (
    BILIBILI_SPACE_URL_PATTERN,
    DEFAULT_DB_PATH,
    DEFAULT_NAME_TEMPLATE,
    DEFAULT_RESOLUTION_PRIORITY,
    DEFAULT_WEB_PORT,
    MAX_CONCURRENT_DOWNLOADS,
)
from bilibili_downloader.bilibili.api import BilibiliAPI
from bilibili_downloader.core.manager import DownloadManager
from bilibili_downloader.storage.database import Database
from bilibili_downloader.storage.files import build_filename, resolve_save_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="bilibili-dl", description="B站UP主视频批量下载器")
    subparsers = parser.add_subparsers(dest="command")

    dl_parser = subparsers.add_parser("download", help="下载UP主视频")
    dl_parser.add_argument("urls", nargs="+", help="UP主空间地址")
    dl_parser.add_argument("-o", "--output", default="./downloads", help="保存目录")
    dl_parser.add_argument("-r", "--resolution", default=None, help="目标分辨率")
    dl_parser.add_argument("-n", "--concurrency", type=int, default=MAX_CONCURRENT_DOWNLOADS, help="并发下载数")
    dl_parser.add_argument("--dry-run", action="store_true", help="仅分析不下载")
    dl_parser.add_argument("--force", action="store_true", help="忽略已下载记录")
    dl_parser.add_argument("--name-template", default=None, help="文件命名模板")

    web_parser = subparsers.add_parser("web", help="启动Web仪表盘")
    web_parser.add_argument("--port", type=int, default=DEFAULT_WEB_PORT, help="Web服务端口")

    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv[0] not in ("download", "web"):
        argv = ["download"] + argv
    args = parser.parse_args(argv)
    return args


def extract_mid(url: str) -> str:
    match = re.search(BILIBILI_SPACE_URL_PATTERN, url)
    if not match:
        raise ValueError(f"Invalid Bilibili space URL: {url}")
    return match.group(1)


async def download_command(args):
    db = Database(DEFAULT_DB_PATH)
    await db.init()

    async with aiohttp.ClientSession() as session:
        api = BilibiliAPI(session)
        resolution_priority = [args.resolution] if args.resolution else DEFAULT_RESOLUTION_PRIORITY

        for url in args.urls:
            mid = extract_mid(url)
            logger.info(f"Processing UP主: {url} (mid={mid})")

            platform = await db.get_platform_by_name("bilibili")
            pid = platform["id"] if platform else await db.insert_platform(name="bilibili", base_url="https://www.bilibili.com")

            creator = await db.get_creator_by_remote(pid, mid)
            if not creator:
                info = await api.get_space_info(mid)
                cid = await db.insert_creator(platform_id=pid, remote_id=mid, name=info["name"], space_url=url, avatar_url=info.get("avatar_url"))
            else:
                cid = creator["id"]

            videos = await api.get_all_videos(mid)
            sections = await api.get_sections(mid)
            section_map = {s["remote_id"]: s for s in sections}

            existing = set()
            if not args.force:
                existing = await db.get_existing_downloads(cid)

            new_videos = 0
            for video_data in videos:
                remote_id = video_data["remote_id"]
                sec = section_map.get(remote_id)
                video = await db.get_video_by_remote(cid, remote_id)
                if not video:
                    vid = await db.insert_video(
                        creator_id=cid, remote_id=remote_id, title=video_data["title"],
                        duration=video_data.get("duration"), pubdate=video_data.get("pubdate"),
                        extra=str(video_data.get("extra")),
                        section_id=sec["section_id"] if sec else None,
                        section_name=sec["section_name"] if sec else None,
                    )
                    video = await db.get_video(vid)

                if not args.force and (remote_id, resolution_priority[0]) in existing:
                    continue

                creator_info = await db.get_creator(cid)
                filename = build_filename(
                    title=video_data["title"], creator=creator_info["name"],
                    section=sec["section_name"] if sec else None,
                    template=args.name_template or DEFAULT_NAME_TEMPLATE,
                )
                save_path = resolve_save_path(args.output, filename)
                await db.insert_download(video_id=video["id"], save_path=save_path, resolution=resolution_priority[0])
                new_videos += 1

            await db.update_creator_sync(cid)
            logger.info(f"Found {len(videos)} videos, {new_videos} new downloads queued")

        if args.dry_run:
            stats = await db.get_stats()
            logger.info(f"Dry run complete: {stats}")
            await db.close()
            return

        manager = DownloadManager(
            db=db, api=api, save_dir=args.output,
            resolution_priority=resolution_priority,
            max_concurrent_downloads=args.concurrency,
            name_template=args.name_template or DEFAULT_NAME_TEMPLATE,
        )
        await manager.run(session)

    stats = await db.get_stats()
    logger.info(f"Done: {stats}")
    await db.close()


async def web_command(args):
    import uvicorn
    from bilibili_downloader.web.app import create_app
    db = Database(DEFAULT_DB_PATH)
    await db.init()
    app = create_app(db)
    logger.info(f"Web dashboard starting on http://localhost:{args.port}")
    await uvicorn.serve(app, host="0.0.0.0", port=args.port, log_level="info")
    await db.close()


def main(argv=None):
    args = parse_args(argv)
    if args.command == "web":
        asyncio.run(web_command(args))
    else:
        asyncio.run(download_command(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
