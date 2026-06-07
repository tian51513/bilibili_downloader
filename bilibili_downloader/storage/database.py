import json
import logging
import re

import aiosqlite
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    base_url    TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS creator (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id INTEGER NOT NULL REFERENCES platform(id),
    remote_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    avatar_url  TEXT,
    space_url   TEXT NOT NULL,
    last_sync   DATETIME,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(platform_id, remote_id)
);

CREATE TABLE IF NOT EXISTS video (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id  INTEGER NOT NULL REFERENCES creator(id),
    remote_id   TEXT NOT NULL,
    title       TEXT NOT NULL,
    duration    INTEGER,
    pubdate     DATETIME,
    extra       TEXT,
    section_id  TEXT,
    section_name TEXT,
    tags        TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(creator_id, remote_id)
);

CREATE TABLE IF NOT EXISTS download (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    INTEGER NOT NULL REFERENCES video(id),
    save_path   TEXT NOT NULL,
    resolution  TEXT NOT NULL,
    file_size   INTEGER,
    status      TEXT NOT NULL DEFAULT 'pending',
    error_msg   TEXT,
    started_at  DATETIME,
    finished_at DATETIME,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(video_id, resolution)
);

CREATE TABLE IF NOT EXISTS task (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id         INTEGER NOT NULL REFERENCES platform(id),
    creator_id          INTEGER,
    space_url           TEXT NOT NULL,
    space_uid           TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    total_videos        INTEGER DEFAULT 0,
    scraped_videos      INTEGER DEFAULT 0,
    downloaded_videos   INTEGER DEFAULT 0,
    total_downloads     INTEGER DEFAULT 0,
    error_message       TEXT,
    cookie_status       TEXT DEFAULT 'valid',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def init(self):
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        # Migration: add tags column if missing
        try:
            await self._conn.execute("ALTER TABLE video ADD COLUMN tags TEXT")
            await self._conn.commit()
        except Exception:
            pass  # column already exists
        # Migration: add audio_url and merge_status to download table
        for col, col_type in [("audio_url", "TEXT"), ("merge_status", "TEXT DEFAULT NULL")]:
            try:
                await self._conn.execute(f"ALTER TABLE download ADD COLUMN {col} {col_type}")
                await self._conn.commit()
            except Exception:
                pass  # column already exists
        # Migration: add total_size to download table
        try:
            await self._conn.execute("ALTER TABLE download ADD COLUMN total_size INTEGER")
            await self._conn.commit()
        except Exception:
            pass  # column already exists
        # Migration: add display_name to task table
        try:
            await self._conn.execute("ALTER TABLE task ADD COLUMN display_name TEXT")
            await self._conn.commit()
        except Exception:
            pass  # column already exists

    async def close(self):
        if self._conn:
            await self._conn.close()

    # --- Platform ---

    async def insert_platform(self, name: str, base_url: str | None = None) -> int:
        cur = await self._conn.execute(
            "INSERT INTO platform (name, base_url) VALUES (?, ?)", (name, base_url)
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_platform(self, platform_id: int) -> dict:
        cur = await self._conn.execute(
            "SELECT * FROM platform WHERE id=?", (platform_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_platform_by_name(self, name: str) -> dict:
        cur = await self._conn.execute(
            "SELECT * FROM platform WHERE name=?", (name,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    # --- Creator ---

    async def insert_creator(
        self,
        platform_id: int,
        remote_id: str,
        name: str,
        space_url: str,
        avatar_url: str | None = None,
    ) -> int:
        cur = await self._conn.execute(
            "INSERT INTO creator (platform_id, remote_id, name, space_url, avatar_url) "
            "VALUES (?, ?, ?, ?, ?)",
            (platform_id, remote_id, name, space_url, avatar_url),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_creator(self, creator_id: int) -> dict:
        cur = await self._conn.execute(
            "SELECT * FROM creator WHERE id=?", (creator_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_creator_by_remote(self, platform_id: int, remote_id: str) -> dict:
        cur = await self._conn.execute(
            "SELECT * FROM creator WHERE platform_id=? AND remote_id=?",
            (platform_id, remote_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def update_creator_sync(self, creator_id: int):
        now = datetime.now(timezone.utc).isoformat()
        await self._conn.execute(
            "UPDATE creator SET last_sync=? WHERE id=?", (now, creator_id)
        )
        await self._conn.commit()

    # --- Video ---

    async def insert_video(
        self,
        creator_id: int,
        remote_id: str,
        title: str,
        duration: int | None = None,
        pubdate: str | None = None,
        extra: str | None = None,
        section_id: str | None = None,
        section_name: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        tags_json = json.dumps(tags, ensure_ascii=False) if tags else None
        cur = await self._conn.execute(
            "INSERT INTO video "
            "(creator_id, remote_id, title, duration, pubdate, extra, section_id, section_name, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                creator_id,
                remote_id,
                title,
                duration,
                pubdate,
                extra,
                section_id,
                section_name,
                tags_json,
            ),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_video(self, video_id: int) -> dict:
        cur = await self._conn.execute(
            "SELECT * FROM video WHERE id=?", (video_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_video_by_remote(self, creator_id: int, remote_id: str) -> dict:
        cur = await self._conn.execute(
            "SELECT * FROM video WHERE creator_id=? AND remote_id=?",
            (creator_id, remote_id),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_videos_by_creator(self, creator_id: int) -> list[dict]:
        cur = await self._conn.execute(
            "SELECT * FROM video WHERE creator_id=?", (creator_id,)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_video_tags(self, video_id: int, tags: list[str]):
        tags_json = json.dumps(tags, ensure_ascii=False)
        await self._conn.execute(
            "UPDATE video SET tags=? WHERE id=?", (tags_json, video_id)
        )
        await self._conn.commit()

    async def get_tags(self) -> list[dict]:
        cur = await self._conn.execute(
            "SELECT v.tags, COUNT(*) as video_count "
            "FROM video v WHERE v.tags IS NOT NULL AND v.tags != '' "
            "GROUP BY v.tags ORDER BY video_count DESC"
        )
        rows = await cur.fetchall()
        tag_counts: dict[str, int] = {}
        for row in rows:
            try:
                for tag in json.loads(row[0]):
                    tag_counts[tag] = tag_counts.get(tag, 0) + row[1]
            except (json.JSONDecodeError, TypeError):
                continue
        return [{"name": tag, "count": count} for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])]

    # --- Download ---

    async def insert_download(
        self, video_id: int, save_path: str, resolution: str
    ) -> int:
        cur = await self._conn.execute(
            "INSERT OR IGNORE INTO download (video_id, save_path, resolution) "
            "VALUES (?, ?, ?)",
            (video_id, save_path, resolution),
        )
        await self._conn.commit()
        if cur.lastrowid == 0:
            # Record exists — if it's in a terminal state, reset to pending
            cur2 = await self._conn.execute(
                "SELECT status FROM download WHERE video_id=? AND resolution=?",
                (video_id, resolution),
            )
            old_row = await cur2.fetchone()
            await self._conn.execute(
                "UPDATE download SET status='pending', save_path=?, error_msg=NULL, "
                "started_at=NULL, finished_at=NULL, file_size=NULL, total_size=NULL "
                "WHERE video_id=? AND resolution=? AND status IN ('failed', 'skipped')",
                (save_path, video_id, resolution),
            )
            await self._conn.commit()
            if old_row and old_row[0] != "pending":
                logger.info(f"重置下载 video_id={video_id} 分辨率={resolution}: {old_row[0]} → pending")
            cur = await self._conn.execute(
                "SELECT id FROM download WHERE video_id=? AND resolution=?",
                (video_id, resolution),
            )
            row = await cur.fetchone()
            return dict(row)["id"]
        return cur.lastrowid

    async def get_download(self, download_id: int) -> dict:
        cur = await self._conn.execute(
            "SELECT * FROM download WHERE id=?", (download_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def update_download_status(
        self, download_id: int, status: str, error_msg: str | None = None
    ):
        now = datetime.now(timezone.utc).isoformat()
        if status == "downloading":
            await self._conn.execute(
                "UPDATE download SET status=?, started_at=? WHERE id=?",
                (status, now, download_id),
            )
        elif status in ("completed", "skipped", "failed"):
            await self._conn.execute(
                "UPDATE download SET status=?, finished_at=?, error_msg=? WHERE id=?",
                (status, now, error_msg, download_id),
            )
        else:
            await self._conn.execute(
                "UPDATE download SET status=?, error_msg=NULL, started_at=NULL, finished_at=NULL, file_size=NULL WHERE id=?",
                (status, download_id),
            )
        await self._conn.commit()

    async def update_download_progress(self, download_id: int, file_size: int, resolution: str | None = None):
        if resolution:
            await self._conn.execute(
                "UPDATE download SET file_size=?, resolution=? WHERE id=?",
                (file_size, resolution, download_id),
            )
        else:
            await self._conn.execute(
                "UPDATE download SET file_size=? WHERE id=?",
                (file_size, download_id),
            )
        await self._conn.commit()

    async def get_all_creators(self) -> list[dict]:
        cur = await self._conn.execute("SELECT * FROM creator")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_existing_downloads(self, creator_id: int) -> set:
        cur = await self._conn.execute(
            "SELECT v.remote_id, d.resolution FROM download d "
            "JOIN video v ON d.video_id = v.id "
            "JOIN creator c ON v.creator_id = c.id "
            "WHERE c.id=? AND d.status IN ('completed', 'skipped', 'downloading', 'pending')",
            (creator_id,),
        )
        rows = await cur.fetchall()
        return {(row[0], row[1]) for row in rows}

    async def get_all_downloads(
        self, status: str | None = None, page: int = 1, page_size: int = 20,
        creator_id: int | None = None, section_name: str | None = None,
        tags: list[str] | None = None, sort_by: str = "created_at", sort_order: str = "desc",
    ) -> dict:
        conditions = []
        params = []
        if status:
            conditions.append("d.status=?")
            params.append(status)
        if creator_id:
            conditions.append("c.id=?")
            params.append(creator_id)
        if section_name:
            conditions.append("v.section_name=?")
            params.append(section_name)
        if tags:
            tag_conds = []
            for tag in tags:
                tag_conds.append("v.tags LIKE ?")
                params.append(f'%"{tag}"%')
            conditions.append(f"({' OR '.join(tag_conds)})")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size
        # Sort mapping
        sort_map = {
            "title": "v.title",
            "duration": "v.duration",
            "resolution": "d.resolution",
            "file_size": "d.file_size",
            "created_at": "d.created_at",
        }
        sort_col = sort_map.get(sort_by, "d.created_at")
        sort_dir = "DESC" if sort_order.lower() == "desc" else "ASC"
        order_by = f"ORDER BY {sort_col} IS NULL, {sort_col} {sort_dir}"
        # Count total
        params_count = params[:]
        cur_count = await self._conn.execute(
            f"SELECT COUNT(*) FROM download d "
            f"JOIN video v ON d.video_id = v.id "
            f"JOIN creator c ON v.creator_id = c.id "
            f"{where}", params_count,
        )
        total = (await cur_count.fetchone())[0]
        # Fetch page
        params.extend([page_size, offset])
        cur = await self._conn.execute(
            f"SELECT d.*, v.title, v.section_name, v.remote_id as bvid, v.tags, v.duration, "
            f"c.name as creator_name, c.id as creator_id "
            f"FROM download d JOIN video v ON d.video_id = v.id "
            f"JOIN creator c ON v.creator_id = c.id "
            f"{where} {order_by} LIMIT ? OFFSET ?",
            params,
        )
        rows = await cur.fetchall()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    async def get_creators_with_stats(self) -> list[dict]:
        cur = await self._conn.execute(
            "SELECT c.id, c.name, c.avatar_url, "
            "COUNT(v.id) as video_count, "
            "COUNT(CASE WHEN d.status='completed' THEN 1 END) as completed, "
            "COUNT(CASE WHEN d.status='failed' THEN 1 END) as failed, "
            "COUNT(CASE WHEN d.status='downloading' OR d.status='pending' THEN 1 END) as active "
            "FROM creator c "
            "LEFT JOIN video v ON v.creator_id = c.id "
            "LEFT JOIN download d ON d.video_id = v.id "
            "GROUP BY c.id ORDER BY c.name"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_sections(self) -> list[dict]:
        cur = await self._conn.execute(
            "SELECT DISTINCT v.section_name, c.name as creator_name, c.id as creator_id "
            "FROM video v JOIN creator c ON v.creator_id = c.id "
            "WHERE v.section_name IS NOT NULL AND v.section_name != '' "
            "ORDER BY v.section_name"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_stats(self) -> dict:
        result = {}
        cur = await self._conn.execute("SELECT COUNT(*) FROM creator")
        result["total_creators"] = (await cur.fetchone())[0]
        cur = await self._conn.execute("SELECT COUNT(*) FROM video")
        result["total_videos"] = (await cur.fetchone())[0]
        for status in ("pending", "downloading", "completed", "skipped", "failed"):
            cur = await self._conn.execute(
                "SELECT COUNT(*) FROM download WHERE status=?", (status,)
            )
            result[status] = (await cur.fetchone())[0]
        return result

    # --- Task ---

    async def insert_task(
        self, platform_id: int, space_url: str, space_uid: str | None = None,
    ) -> int:
        cur = await self._conn.execute(
            "INSERT INTO task (platform_id, space_url, space_uid) VALUES (?, ?, ?)",
            (platform_id, space_url, space_uid),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_task(self, task_id: int) -> dict | None:
        cur = await self._conn.execute("SELECT * FROM task WHERE id=?", (task_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_all_tasks(
        self, status: str | None = None, page: int = 1, page_size: int = 50,
    ) -> dict:
        conditions = []
        params = []
        if status:
            conditions.append("t.status=?")
            params.append(status)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size
        params_count = params[:]
        cur_count = await self._conn.execute(
            f"SELECT COUNT(*) FROM task t {where}", params_count,
        )
        total = (await cur_count.fetchone())[0]
        params.extend([page_size, offset])
        cur = await self._conn.execute(
            f"SELECT t.*, c.name as creator_name, c.avatar_url, t.display_name, "
            f"(SELECT COALESCE(SUM(d.file_size), 0) FROM download d "
            f"JOIN video v ON d.video_id = v.id WHERE v.creator_id = t.creator_id AND d.status = 'completed') as total_file_size "
            f"FROM task t LEFT JOIN creator c ON t.creator_id = c.id "
            f"{where} ORDER BY t.created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cur.fetchall()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    async def update_task_status(
        self, task_id: int, status: str,
        total_videos: int | None = None, scraped_videos: int | None = None,
        downloaded_videos: int | None = None, total_downloads: int | None = None,
        error_message: str | None = None, creator_id: int | None = None,
        display_name: str | None = None,
        cookie_status: str | None = None,
    ):
        sets = ["status=?"]
        params: list = [status]
        now = datetime.now(timezone.utc).isoformat()
        sets.append("updated_at=?")
        params.append(now)
        if total_videos is not None:
            sets.append("total_videos=?")
            params.append(total_videos)
        if scraped_videos is not None:
            sets.append("scraped_videos=?")
            params.append(scraped_videos)
        if downloaded_videos is not None:
            sets.append("downloaded_videos=?")
            params.append(downloaded_videos)
        if total_downloads is not None:
            sets.append("total_downloads=?")
            params.append(total_downloads)
        if error_message is not None:
            sets.append("error_message=?")
            params.append(error_message)
        if creator_id is not None:
            sets.append("creator_id=?")
            params.append(creator_id)
        if cookie_status is not None:
            sets.append("cookie_status=?")
            params.append(cookie_status)
        if display_name is not None:
            sets.append("display_name=?")
            params.append(display_name)
        params.append(task_id)
        await self._conn.execute(
            f"UPDATE task SET {', '.join(sets)} WHERE id=?", params,
        )
        await self._conn.commit()

    async def get_task_by_url(self, space_url: str) -> dict | None:
        cur = await self._conn.execute("SELECT * FROM task WHERE space_url=?", (space_url,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def update_task_url(self, task_id: int, space_url: str, space_uid: str | None = None):
        if not space_uid:
            match = re.search(r"https?://space\.bilibili\.com/(\d+)", space_url)
            space_uid = match.group(1) if match else None
        await self._conn.execute(
            "UPDATE task SET space_url=?, space_uid=?, status='pending', error_message=NULL, "
            "cookie_status='valid', total_videos=0, scraped_videos=0, downloaded_videos=0, total_downloads=0 WHERE id=?",
            (space_url, space_uid, task_id),
        )
        await self._conn.commit()

    async def cleanup_stale_downloads(self):
        """Clean up downloads stuck in 'downloading' after process kill.
        Check file existence: if file exists → completed, else → failed.
        Never resets to 'pending' to avoid unexpected re-downloads.
        """
        import os
        cur = await self._conn.execute(
            "SELECT id, save_path FROM download WHERE status='downloading'"
        )
        rows = await cur.fetchall()
        completed = 0
        failed = 0
        for row in rows:
            dl_id, save_path = row["id"], row["save_path"]
            if save_path and os.path.exists(save_path):
                await self._conn.execute(
                    "UPDATE download SET status='completed', finished_at=datetime('now'), "
                    "error_msg=NULL WHERE id=?", (dl_id,)
                )
                completed += 1
            else:
                await self._conn.execute(
                    "UPDATE download SET status='failed', error_msg='进程中断，下载未完成', "
                    "started_at=NULL WHERE id=?", (dl_id,)
                )
                failed += 1
        await self._conn.commit()
        if completed or failed:
            logger.info(f"清理卡死下载: {completed} 个已完成(文件存在), {failed} 个标记失败")
        return completed, failed

    async def check_storage(self, new_output_dir: str) -> dict:
        """Check completed downloads' save_path validity against filesystem.
        If old path invalid, try new_output_dir + filename.
        Returns {moved, missing, total_checked}.
        """
        import os
        new_output_dir = os.path.normpath(new_output_dir)
        cur = await self._conn.execute(
            "SELECT id, save_path FROM download WHERE status='completed'"
        )
        rows = await cur.fetchall()
        moved = 0
        missing = 0
        for row in rows:
            dl_id, save_path = row["id"], row["save_path"]
            if os.path.exists(save_path):
                # Also backfill file_size if NULL
                await self._conn.execute(
                    "UPDATE download SET file_size=COALESCE(file_size, ?) WHERE id=? AND file_size IS NULL",
                    (os.path.getsize(save_path), dl_id),
                )
                continue
            # Old path invalid, try new directory
            filename = os.path.basename(save_path)
            new_path = os.path.join(new_output_dir, filename)
            if os.path.exists(new_path):
                size = os.path.getsize(new_path)
                await self._conn.execute(
                    "UPDATE download SET save_path=?, file_size=COALESCE(file_size, ?) WHERE id=?",
                    (new_path, size, dl_id),
                )
                moved += 1
            else:
                await self._conn.execute(
                    "UPDATE download SET status='pending', error_msg='文件不存在', "
                    "started_at=NULL, finished_at=NULL, file_size=NULL WHERE id=?", (dl_id,)
                )
                missing += 1
        await self._conn.commit()
        if moved or missing:
            logger.info(f"存储检测: {moved} 个路径已更新, {missing} 个标记为待下载")
        return {"moved": moved, "missing": missing, "total_checked": len(rows)}

    async def reset_task_downloads(self, creator_id: int):
        """Reset non-completed downloads for a creator to pending status (skip completed)."""
        await self._conn.execute(
            "UPDATE download SET status='pending', error_msg=NULL, started_at=NULL, finished_at=NULL, file_size=NULL "
            "WHERE video_id IN (SELECT id FROM video WHERE creator_id=?) AND status != 'completed'",
            (creator_id,),
        )
        await self._conn.commit()

    async def delete_task(self, task_id: int):
        """Delete a task and cascade delete its downloads and videos."""
        await self._conn.execute("DELETE FROM download WHERE video_id IN "
                                 "(SELECT id FROM video WHERE creator_id = "
                                 "(SELECT creator_id FROM task WHERE id = ? AND creator_id IS NOT NULL))", (task_id,))
        await self._conn.execute("DELETE FROM video WHERE creator_id = "
                                 "(SELECT creator_id FROM task WHERE id = ? AND creator_id IS NOT NULL)", (task_id,))
        await self._conn.execute("DELETE FROM task WHERE id = ?", (task_id,))
        await self._conn.commit()

    async def delete_download(self, download_id: int):
        """Delete a single download record."""
        await self._conn.execute("DELETE FROM download WHERE id=?", (download_id,))
        await self._conn.commit()

    async def sync_task_status_from_downloads(self, task_id: int):
        """根据下载状态同步任务状态。"""
        task = await self.get_task(task_id)
        if not task or not task.get("creator_id"):
            return
        cid = task["creator_id"]
        # 统计该 creator 下所有 download 的状态
        cur = await self._conn.execute(
            "SELECT status, COUNT(*) as cnt FROM download d "
            "JOIN video v ON d.video_id = v.id WHERE v.creator_id=? GROUP BY d.status",
            (cid,),
        )
        rows = await cur.fetchall()
        counts = {row[0]: row[1] for row in rows}
        total = sum(counts.values())
        if total == 0:
            return
        downloading = counts.get("downloading", 0)
        completed = counts.get("completed", 0)
        skipped = counts.get("skipped", 0)
        failed = counts.get("failed", 0)
        pending = counts.get("pending", 0)

        if downloading > 0:
            new_status = "downloading"
        elif pending == total:
            new_status = "pending"
        elif failed == total:
            new_status = "failed"
        elif completed + skipped == total:
            new_status = "completed"
        elif completed + skipped + failed == total:
            new_status = "completed"
        else:
            new_status = "downloading"

        if new_status != task["status"]:
            error_msg = None if new_status in ("pending", "downloading") else task.get("error_message")
            await self.update_task_status(
                task_id, new_status,
                downloaded_videos=completed,
                total_downloads=total,
                error_message=error_msg,
            )

    async def clear_all_downloads(self):
        """Delete all downloads, videos, creators, and tasks."""
        await self._conn.execute("DELETE FROM download")
        await self._conn.execute("DELETE FROM video")
        await self._conn.execute("DELETE FROM creator")
        await self._conn.execute("DELETE FROM task")
        await self._conn.commit()