import json
import logging

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
    ) -> int:
        cur = await self._conn.execute(
            "INSERT INTO video "
            "(creator_id, remote_id, title, duration, pubdate, extra, section_id, section_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                creator_id,
                remote_id,
                title,
                duration,
                pubdate,
                extra,
                section_id,
                section_name,
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
                "started_at=NULL, finished_at=NULL "
                "WHERE video_id=? AND resolution=? AND status IN ('failed', 'completed', 'skipped')",
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
                "UPDATE download SET status=? WHERE id=?",
                (status, download_id),
            )
        await self._conn.commit()

    async def update_download_progress(self, download_id: int, file_size: int):
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
        self, status: str | None = None, limit: int = 100, offset: int = 0,
        creator_id: int | None = None, section_name: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict]:
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
            conditions.append(f"({' AND '.join(tag_conds)})")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])
        cur = await self._conn.execute(
            f"SELECT d.*, v.title, v.section_name, v.remote_id as bvid, v.tags, "
            f"c.name as creator_name, c.id as creator_id "
            f"FROM download d JOIN video v ON d.video_id = v.id "
            f"JOIN creator c ON v.creator_id = c.id "
            f"{where} ORDER BY d.created_at DESC LIMIT ? OFFSET ?",
            params,
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

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
