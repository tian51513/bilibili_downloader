# Bilibili Downloader V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI + Web dashboard bilibili video batch downloader with async high-concurrency download, SQLite state tracking, multi-platform extensible storage.

**Architecture:** Single-process layered architecture. asyncio + aiohttp for concurrent downloads, FastAPI for web dashboard, aiosqlite for async SQLite access. All components share one event loop.

**Tech Stack:** Python 3.11+, asyncio, aiohttp, FastAPI, Jinja2, aiosqlite, argparse

---

## File Map

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Project metadata, dependencies, CLI entry point |
| `bilibili_downloader/__init__.py` | Package init |
| `bilibili_downloader/main.py` | Program entry — dispatch CLI or web mode |
| `bilibili_downloader/config.py` | Global config constants |
| `bilibili_downloader/storage/__init__.py` | Storage subpackage init |
| `bilibili_downloader/storage/database.py` | SQLite init, schema creation, all CRUD operations |
| `bilibili_downloader/storage/files.py` | File naming template, path resolution, file writing |
| `bilibili_downloader/bilibili/__init__.py` | Bilibili subpackage init |
| `bilibili_downloader/bilibili/api.py` | Bilibili public API calls (aiohttp) |
| `bilibili_downloader/bilibili/parser.py` | Parse API responses into data dicts |
| `bilibili_downloader/core/__init__.py` | Core subpackage init |
| `bilibili_downloader/core/retry.py` | Exponential backoff retry decorator |
| `bilibili_downloader/core/worker.py` | Single video download coroutine |
| `bilibili_downloader/core/manager.py` | DownloadManager — queue, worker pool, orchestration |
| `bilibili_downloader/cli/__init__.py` | CLI subpackage init |
| `bilibili_downloader/cli/main.py` | argparse CLI entry, subcommands (download, web) |
| `bilibili_downloader/web/__init__.py` | Web subpackage init |
| `bilibili_downloader/web/app.py` | FastAPI app factory |
| `bilibili_downloader/web/routes.py` | Dashboard routes |
| `bilibili_downloader/web/templates/index.html` | Dashboard HTML template |
| `tests/__init__.py` | Tests package init |
| `tests/conftest.py` | Shared fixtures (tmp SQLite, mock API responses) |
| `tests/test_database.py` | Database CRUD tests |
| `tests/test_files.py` | File naming tests |
| `tests/test_parser.py` | Bilibili response parser tests |
| `tests/test_retry.py` | Retry strategy tests |
| `tests/test_worker.py` | Download worker tests |
| `tests/test_manager.py` | Download manager integration tests |
| `tests/test_cli.py` | CLI argument parsing tests |

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `bilibili_downloader/__init__.py`
- Create: `bilibili_downloader/config.py`
- Create: `bilibili_downloader/main.py`
- Create: `bilibili_downloader/storage/__init__.py`
- Create: `bilibili_downloader/bilibili/__init__.py`
- Create: `bilibili_downloader/core/__init__.py`
- Create: `bilibili_downloader/cli/__init__.py`
- Create: `bilibili_downloader/web/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "bilibili-downloader"
version = "0.1.0"
description = "Bilibili UP主视频批量下载器"
requires-python = ">=3.11"
dependencies = [
    "aiohttp>=3.9",
    "aiosqlite>=0.20",
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "jinja2>=3.1",
]

[project.scripts]
bilibili-dl = "bilibili_downloader.cli.main:main"

[build-system]
requires = ["setuptools>=70"]
build-backend = "setuptools.backends._legacy:_Backend"

[tool.setuptools.packages.find]
include = ["bilibili_downloader*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create all __init__.py files**

Each `__init__.py` is empty:

`bilibili_downloader/__init__.py`
`bilibili_downloader/storage/__init__.py`
`bilibili_downloader/bilibili/__init__.py`
`bilibili_downloader/core/__init__.py`
`bilibili_downloader/cli/__init__.py`
`bilibili_downloader/web/__init__.py`

- [ ] **Step 3: Create config.py**

```python
# bilibili_downloader/config.py

# Download concurrency
MAX_CONCURRENT_DOWNLOADS = 5
MAX_CONCURRENT_API_REQUESTS = 10

# Retry
DOWNLOAD_RETRY_COUNT = 3
RETRY_BACKOFF_BASE = 2  # seconds

# Network
REQUEST_TIMEOUT = 30  # seconds
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Resolution priority (first available wins)
DEFAULT_RESOLUTION_PRIORITY = ["720p", "480p", "1080p", "240p"]

# File naming
DEFAULT_NAME_TEMPLATE = "{title}\u3010{creator}-{section}\u3011"

# Database
DEFAULT_DB_PATH = "bilibili_downloader.db"

# Web
DEFAULT_WEB_PORT = 8080

# Bilibili API base
BILIBILI_API_BASE = "https://api.bilibili.com"
BILIBILI_SPACE_URL_PATTERN = r"https?://space\.bilibili\.com/(\d+)"
```

- [ ] **Step 4: Create main.py (minimal entry)**

```python
# bilibili_downloader/main.py

import sys
from bilibili_downloader.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Install dependencies and verify import**

Run: `pip install -e ".[test]" 2>/dev/null || pip install -e . && pip install pytest pytest-asyncio aioresponses`
Expected: Successfully installed

Run: `python -c "import bilibili_downloader; print(bilibili_downloader.__file__)"`
Expected: path to bilibili_downloader/__init__.py

- [ ] **Step 6: Initialize git and commit**

Run:
```bash
git init
git add pyproject.toml bilibili_downloader/
git commit -m "chore: project scaffolding with pyproject.toml and config"
```

---

### Task 2: Storage Layer — Database

**Files:**
- Create: `bilibili_downloader/storage/database.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_database.py`

- [ ] **Step 1: Write failing tests for database**

```python
# tests/__init__.py
# empty

# tests/conftest.py
import pytest
import aiosqlite
import os

@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    from bilibili_downloader.storage.database import Database
    database = Database(str(db_path))
    await database.init()
    yield database
    await database.close()

# tests/test_database.py
import pytest
from datetime import datetime

class TestDatabase:
    async def test_init_creates_tables(self, db):
        async with db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ) as cursor:
            tables = {row[0] for row in await cursor.fetchall()}
        assert tables == {"platform", "creator", "video", "download"}

    async def test_insert_and_get_platform(self, db):
        pid = await db.insert_platform(name="bilibili", base_url="https://www.bilibili.com")
        assert pid == 1
        platform = await db.get_platform(pid)
        assert platform["name"] == "bilibili"

    async def test_insert_duplicate_platform_raises(self, db):
        await db.insert_platform(name="bilibili")
        with pytest.raises(Exception):
            await db.insert_platform(name="bilibili")

    async def test_insert_and_get_creator(self, db):
        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="33676449",
            name="TestUP", space_url="https://space.bilibili.com/33676449"
        )
        creator = await db.get_creator(cid)
        assert creator["name"] == "TestUP"
        assert creator["remote_id"] == "33676449"

    async def test_insert_and_get_video(self, db):
        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="123", name="UP", space_url="https://x.com"
        )
        vid = await db.insert_video(
            creator_id=cid, remote_id="BV1xx", title="Test Video",
            duration=120, extra='{"cid": 456}', section_id="s1", section_name="合集A"
        )
        video = await db.get_video(vid)
        assert video["title"] == "Test Video"
        assert video["section_name"] == "合集A"

    async def test_insert_download_and_get(self, db):
        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="123", name="UP", space_url="https://x.com"
        )
        vid = await db.insert_video(
            creator_id=cid, remote_id="BV1xx", title="V", duration=60
        )
        did = await db.insert_download(
            video_id=vid, save_path="/tmp/v.mp4", resolution="720p"
        )
        dl = await db.get_download(did)
        assert dl["status"] == "pending"
        assert dl["resolution"] == "720p"

    async def test_update_download_status(self, db):
        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="123", name="UP", space_url="https://x.com"
        )
        vid = await db.insert_video(
            creator_id=cid, remote_id="BV1xx", title="V", duration=60
        )
        did = await db.insert_download(
            video_id=vid, save_path="/tmp/v.mp4", resolution="720p"
        )
        await db.update_download_status(did, "downloading")
        dl = await db.get_download(did)
        assert dl["status"] == "downloading"

    async def test_get_existing_downloads(self, db):
        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="123", name="UP", space_url="https://x.com"
        )
        vid1 = await db.insert_video(
            creator_id=cid, remote_id="BV1a", title="VA", duration=60
        )
        vid2 = await db.insert_video(
            creator_id=cid, remote_id="BV1b", title="VB", duration=60
        )
        await db.insert_download(video_id=vid1, save_path="/a.mp4", resolution="720p")
        await db.insert_download(video_id=vid2, save_path="/b.mp4", resolution="720p")
        await db.update_download_status(
            (await db.insert_download(video_id=vid2, save_path="/b2.mp4", resolution="480p")),
            "completed"
        )
        existing = await db.get_existing_downloads(cid)
        assert ("BV1a", "720p") in existing
        assert ("BV1b", "720p") in existing
        assert ("BV1b", "480p") in existing
        assert len(existing) == 3

    async def test_get_stats(self, db):
        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="123", name="UP", space_url="https://x.com"
        )
        vid = await db.insert_video(
            creator_id=cid, remote_id="BV1xx", title="V", duration=60
        )
        d1 = await db.insert_download(video_id=vid, save_path="/a.mp4", resolution="720p")
        d2 = await db.insert_download(video_id=vid, save_path="/b.mp4", resolution="480p")
        await db.update_download_status(d1, "completed")
        await db.update_download_status(d2, "skipped")
        stats = await db.get_stats()
        assert stats["total_creators"] == 1
        assert stats["total_videos"] == 1
        assert stats["completed"] == 1
        assert stats["skipped"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_database.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bilibili_downloader.storage.database'`

- [ ] **Step 3: Write database.py implementation**

```python
# bilibili_downloader/storage/database.py

import aiosqlite
import json
from datetime import datetime, timezone

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
        cur = await self._conn.execute("SELECT * FROM platform WHERE id=?", (platform_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_platform_by_name(self, name: str) -> dict:
        cur = await self._conn.execute("SELECT * FROM platform WHERE name=?", (name,))
        row = await cur.fetchone()
        return dict(row) if row else None

    # --- Creator ---

    async def insert_creator(
        self, platform_id: int, remote_id: str, name: str,
        space_url: str, avatar_url: str | None = None
    ) -> int:
        cur = await self._conn.execute(
            "INSERT INTO creator (platform_id, remote_id, name, space_url, avatar_url) VALUES (?, ?, ?, ?, ?)",
            (platform_id, remote_id, name, space_url, avatar_url),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_creator(self, creator_id: int) -> dict:
        cur = await self._conn.execute("SELECT * FROM creator WHERE id=?", (creator_id,))
        row = await cur.fetchone()
        return dict(row) if row else None

    async def get_creator_by_remote(
        self, platform_id: int, remote_id: str
    ) -> dict:
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
        self, creator_id: int, remote_id: str, title: str,
        duration: int | None = None, pubdate: str | None = None,
        extra: str | None = None, section_id: str | None = None,
        section_name: str | None = None
    ) -> int:
        cur = await self._conn.execute(
            "INSERT INTO video (creator_id, remote_id, title, duration, pubdate, extra, section_id, section_name) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (creator_id, remote_id, title, duration, pubdate, extra, section_id, section_name),
        )
        await self._conn.commit()
        return cur.lastrowid

    async def get_video(self, video_id: int) -> dict:
        cur = await self._conn.execute("SELECT * FROM video WHERE id=?", (video_id,))
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

    # --- Download ---

    async def insert_download(
        self, video_id: int, save_path: str, resolution: str
    ) -> int:
        cur = await self._conn.execute(
            "INSERT OR IGNORE INTO download (video_id, save_path, resolution) VALUES (?, ?, ?)",
            (video_id, save_path, resolution),
        )
        await self._conn.commit()
        if cur.lastrowid == 0:
            cur = await self._conn.execute(
                "SELECT id FROM download WHERE video_id=? AND resolution=?",
                (video_id, resolution),
            )
            row = await cur.fetchone()
            return dict(row)["id"]
        return cur.lastrowid

    async def get_download(self, download_id: int) -> dict:
        cur = await self._conn.execute("SELECT * FROM download WHERE id=?", (download_id,))
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
                "UPDATE download SET status=? WHERE id=?", (status, download_id)
            )
        await self._conn.commit()

    async def update_download_progress(self, download_id: int, file_size: int):
        await self._conn.execute(
            "UPDATE download SET file_size=? WHERE id=?", (file_size, download_id)
        )
        await self._conn.commit()

    async def get_existing_downloads(self, creator_id: int) -> set:
        cur = await self._conn.execute(
            "SELECT v.remote_id, d.resolution FROM download d "
            "JOIN video v ON d.video_id = v.id "
            "JOIN creator c ON v.creator_id = c.id "
            "WHERE c.id=? AND d.status IN ('completed', 'skipped', 'downloading')",
            (creator_id,),
        )
        rows = await cur.fetchall()
        return {(row[0], row[1]) for row in rows}

    async def get_all_downloads(self, status: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        if status:
            cur = await self._conn.execute(
                "SELECT d.*, v.title, v.section_name, c.name as creator_name "
                "FROM download d "
                "JOIN video v ON d.video_id = v.id "
                "JOIN creator c ON v.creator_id = c.id "
                "WHERE d.status=? ORDER BY d.created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        else:
            cur = await self._conn.execute(
                "SELECT d.*, v.title, v.section_name, c.name as creator_name "
                "FROM download d "
                "JOIN video v ON d.video_id = v.id "
                "JOIN creator c ON v.creator_id = c.id "
                "ORDER BY d.created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_database.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/storage/ tests/
git commit -m "feat: add storage layer with SQLite database and CRUD operations"
```

---

### Task 3: File Naming and Saving

**Files:**
- Create: `bilibili_downloader/storage/files.py`
- Create: `tests/test_files.py`

- [ ] **Step 1: Write failing tests for file naming**

```python
# tests/test_files.py
import pytest
import os
from pathlib import Path


class TestFileName:
    def test_default_template_with_section(self):
        from bilibili_downloader.storage.files import build_filename
        result = build_filename(
            title="这是什么神仙颜值啊？？？",
            creator="颜值回忆录",
            section="流行",
            ext="mp4",
        )
        assert result == "这是什么神仙颜值啊？？？【颜值回忆录-流行】.mp4"

    def test_default_template_without_section(self):
        from bilibili_downloader.storage.files import build_filename
        result = build_filename(
            title="独立视频",
            creator="某UP主",
            section=None,
            ext="mp4",
        )
        assert result == "独立视频【某UP主】.mp4"

    def test_custom_template(self):
        from bilibili_downloader.storage.files import build_filename
        result = build_filename(
            title="V",
            creator="C",
            section="S",
            ext="mp4",
            template="{creator}_{section}_{title}",
        )
        assert result == "C_S_V.mp4"

    def test_custom_template_no_section(self):
        from bilibili_downloader.storage.files import build_filename
        result = build_filename(
            title="V",
            creator="C",
            section=None,
            ext="mp4",
            template="{creator}_{title}",
        )
        assert result == "C_V.mp4"

    def test_sanitize_filename(self):
        from bilibili_downloader.storage.files import build_filename
        result = build_filename(
            title='file/with<bad>|chars',
            creator="UP",
            section=None,
            ext="mp4",
        )
        assert "/" not in result
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result
        assert result.endswith(".mp4")


class TestResolveSavePath:
    def test_resolve_basic(self, tmp_path):
        from bilibili_downloader.storage.files import resolve_save_path
        result = resolve_save_path(str(tmp_path), "video.mp4")
        assert result == str(tmp_path / "video.mp4")

    def test_resolve_creates_parent(self, tmp_path):
        from bilibili_downloader.storage.files import resolve_save_path
        result = resolve_save_path(str(tmp_path), "subdir/video.mp4")
        assert result == str(tmp_path / "subdir" / "video.mp4")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_files.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write files.py implementation**

```python
# bilibili_downloader/storage/files.py

import os
import re
from pathlib import Path

from bilibili_downloader.config import DEFAULT_NAME_TEMPLATE

# Characters illegal in Windows/Mac/Linux filenames
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_ILLEGAL_TRAILING = re.compile(r'[.\s]+$')


def sanitize_filename(name: str) -> str:
    name = _ILLEGAL_CHARS.sub("", name)
    name = _ILLEGAL_TRAILING.sub("", name)
    return name.strip()


def build_filename(
    title: str,
    creator: str,
    section: str | None,
    ext: str = "mp4",
    template: str | None = None,
) -> str:
    template = template or DEFAULT_NAME_TEMPLATE
    title = sanitize_filename(title)
    creator = sanitize_filename(creator)
    if section:
        section = sanitize_filename(section)
        filename = template.format(title=title, creator=creator, section=section)
    else:
        filename = template.format(title=title, creator=creator, section="")
        filename = filename.replace("【-】", "】")
        filename = filename.replace("【-】", "】")
    return f"{filename}.{ext}"


def resolve_save_path(output_dir: str, filename: str) -> str:
    path = Path(output_dir) / filename
    return str(path.resolve())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_files.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/storage/files.py tests/test_files.py
git commit -m "feat: add file naming template and path resolution"
```

---

### Task 4: Bilibili API Layer

**Files:**
- Create: `bilibili_downloader/bilibili/parser.py`
- Create: `bilibili_downloader/bilibili/api.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Write failing tests for parser**

```python
# tests/test_parser.py
import pytest


class TestParseSpaceInfo:
    def test_parse_mid_and_name(self):
        from bilibili_downloader.bilibili.parser import parse_space_info
        data = {
            "data": {
                "mid": 33676449,
                "name": "TestUP",
                "face": "https://example.com/face.jpg",
            }
        }
        result = parse_space_info(data)
        assert result["remote_id"] == "33676449"
        assert result["name"] == "TestUP"
        assert result["avatar_url"] == "https://example.com/face.jpg"


class TestParseVideoList:
    def test_parse_videos_basic(self):
        from bilibili_downloader.bilibili.parser import parse_video_list
        data = {
            "data": {
                "list": {
                    "vlist": [
                        {
                            "bvid": "BV1xx",
                            "title": "Video A",
                            "length": "3:45",
                            "created": 1700000000,
                            "cid": 12345,
                            "aid": 67890,
                        },
                        {
                            "bvid": "BV1yy",
                            "title": "Video B",
                            "length": "10:00",
                            "created": 1700001000,
                            "cid": 11111,
                            "aid": 22222,
                        },
                    ]
                }
            }
        }
        videos = parse_video_list(data)
        assert len(videos) == 2
        assert videos[0]["remote_id"] == "BV1xx"
        assert videos[0]["duration"] == 225  # 3*60+45
        assert videos[0]["extra"]["cid"] == 12345
        assert videos[1]["duration"] == 600

    def test_parse_videos_empty(self):
        from bilibili_downloader.bilibili.parser import parse_video_list
        data = {"data": {"list": {"vlist": []}}}
        videos = parse_video_list(data)
        assert videos == []


class TestParseSections:
    def test_parse_sections(self):
        from bilibili_downloader.bilibili.parser import parse_sections
        data = {
            "data": {
                "sections": [
                    {
                        "id": 123,
                        "title": "合集A",
                        "episodes": [
                            {"bvid": "BV1xx", "title": "Ep1", "arc": {"aid": 111}},
                            {"bvid": "BV1yy", "title": "Ep2", "arc": {"aid": 222}},
                        ],
                    },
                    {
                        "id": 456,
                        "title": "合集B",
                        "episodes": [
                            {"bvid": "BV1zz", "title": "Ep3", "arc": {"aid": 333}},
                        ],
                    },
                ]
            }
        }
        sections = parse_sections(data)
        assert len(sections) == 3
        assert sections[0]["remote_id"] == "BV1xx"
        assert sections[0]["section_id"] == "123"
        assert sections[0]["section_name"] == "合集A"
        assert sections[2]["section_name"] == "合集B"


class TestParseStreamURLs:
    def test_parse_selects_best_resolution(self):
        from bilibili_downloader.bilibili.parser import parse_stream_urls
        data = {
            "data": {
                "dash": {
                    "video": [
                        {"id": 32, "bandwidth": 1000000, "baseUrl": "http://a/240p"},
                        {"id": 64, "bandwidth": 2000000, "baseUrl": "http://a/480p"},
                        {"id": 80, "bandwidth": 3000000, "baseUrl": "http://a/720p"},
                    ],
                    "audio": [
                        {"id": 30280, "bandwidth": 500000, "baseUrl": "http://a/audio"},
                    ],
                }
            }
        }
        urls = parse_stream_urls(data, priority=["720p", "480p", "240p"])
        assert urls["video_url"] == "http://a/720p"
        assert urls["audio_url"] == "http://a/audio"

    def test_parse_fallback_resolution(self):
        from bilibili_downloader.bilibili.parser import parse_stream_urls
        data = {
            "data": {
                "dash": {
                    "video": [
                        {"id": 32, "bandwidth": 1000000, "baseUrl": "http://a/240p"},
                        {"id": 80, "bandwidth": 3000000, "baseUrl": "http://a/720p"},
                    ],
                    "audio": [
                        {"id": 30280, "bandwidth": 500000, "baseUrl": "http://a/audio"},
                    ],
                }
            }
        }
        urls = parse_stream_urls(data, priority=["480p", "720p", "240p"])
        assert urls["video_url"] == "http://a/720p"

    def test_parse_no_streams_raises(self):
        from bilibili_downloader.bilibili.parser import parse_stream_urls
        data = {"data": {"dash": {"video": [], "audio": []}}}
        with pytest.raises(ValueError, match="No video streams"):
            parse_stream_urls(data, priority=["720p"])

    def test_parse_returns_resolution_label(self):
        from bilibili_downloader.bilibili.parser import parse_stream_urls
        data = {
            "data": {
                "dash": {
                    "video": [
                        {"id": 32, "bandwidth": 1000000, "baseUrl": "http://a/240p"},
                        {"id": 80, "bandwidth": 3000000, "baseUrl": "http://a/720p"},
                    ],
                    "audio": [
                        {"id": 30280, "bandwidth": 500000, "baseUrl": "http://a/audio"},
                    ],
                }
            }
        }
        urls = parse_stream_urls(data, priority=["720p"])
        assert urls["resolution"] == "720p"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write parser.py implementation**

```python
# bilibili_downloader/bilibili/parser.py

from bilibili_downloader.config import USER_AGENT, BILIBILI_API_BASE

# B站视频流 quality id → 分辨率标签
_QID_TO_LABEL = {
    16: "360p",
    32: "240p",  # actually 360p in bilibili mapping, but spec uses 240p
    64: "480p",
    80: "720p",
    112: "1080p",
    116: "1080p60",
    120: "4k",
}

# 分辨率标签 → quality id (用于匹配优先级)
_LABEL_TO_QID = {v: k for k, v in _QID_TO_LABEL.items()}


def parse_space_info(raw: dict) -> dict:
    d = raw["data"]
    return {
        "remote_id": str(d["mid"]),
        "name": d["name"],
        "avatar_url": d.get("face"),
    }


def parse_video_list(raw: dict) -> list[dict]:
    vlist = raw.get("data", {}).get("list", {}).get("vlist", [])
    videos = []
    for v in vlist:
        duration = 0
        length = v.get("length", "")
        if ":" in length:
            parts = length.split(":")
            if len(parts) == 2:
                duration = int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        videos.append({
            "remote_id": v["bvid"],
            "title": v["title"],
            "duration": duration,
            "pubdate": v.get("created"),
            "extra": {
                "cid": v.get("cid"),
                "aid": v.get("aid"),
            },
        })
    return videos


def parse_sections(raw: dict) -> list[dict]:
    sections_raw = raw.get("data", {}).get("sections", [])
    result = []
    for sec in sections_raw:
        sid = str(sec["id"])
        sname = sec["title"]
        for ep in sec.get("episodes", []):
            result.append({
                "remote_id": ep["bvid"],
                "section_id": sid,
                "section_name": sname,
            })
    return result


def parse_stream_urls(
    raw: dict, priority: list[str] | None = None
) -> dict:
    dash = raw.get("data", {}).get("dash", {})
    videos = dash.get("video", [])
    audios = dash.get("audio", [])

    if not videos:
        raise ValueError("No video streams available")

    priority = priority or ["720p", "480p", "1080p", "240p"]

    selected = None
    selected_label = None
    for label in priority:
        qid = _LABEL_TO_QID.get(label)
        if qid is None:
            continue
        for v in videos:
            if v["id"] == qid:
                selected = v
                selected_label = label
                break
        if selected:
            break

    if selected is None:
        # fallback: pick highest bandwidth
        selected = max(videos, key=lambda x: x.get("bandwidth", 0))
        selected_label = _QID_TO_LABEL.get(selected["id"], f"qid_{selected['id']}")

    audio_url = audios[0]["baseUrl"] if audios else None

    return {
        "video_url": selected["baseUrl"],
        "audio_url": audio_url,
        "resolution": selected_label,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_parser.py -v`
Expected: All PASS

- [ ] **Step 5: Write api.py (no tests — thin HTTP layer, tested via integration)**

```python
# bilibili_downloader/bilibili/api.py

import aiohttp

from bilibili_downloader.config import (
    BILIBILI_API_BASE,
    REQUEST_TIMEOUT,
    USER_AGENT,
)
from bilibili_downloader.bilibili.parser import (
    parse_space_info,
    parse_video_list,
    parse_sections,
    parse_stream_urls,
)


class BilibiliAPI:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.headers = {"User-Agent": USER_AGENT}

    async def get_space_info(self, mid: str) -> dict:
        url = f"{BILIBILI_API_BASE}/x/space/wbi/acc/info?mid={mid}"
        async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            return parse_space_info(await resp.json())

    async def get_video_list(self, mid: str, page: int = 1, page_size: int = 50) -> dict:
        url = (
            f"{BILIBILI_API_BASE}/x/space/arc/search"
            f"?mid={mid}&ps={page_size}&pn={page}&order=pubdate"
        )
        async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json()
            videos = parse_video_list(data)
            total = data.get("data", {}).get("page", {}).get("count", 0)
            return {"videos": videos, "total": total}

    async def get_all_videos(self, mid: str) -> list[dict]:
        all_videos = []
        page = 1
        while True:
            result = await self.get_video_list(mid, page=page)
            all_videos.extend(result["videos"])
            if len(all_videos) >= result["total"] or not result["videos"]:
                break
            page += 1
        return all_videos

    async def get_sections(self, mid: str) -> list[dict]:
        url = f"{BILIBILI_API_BASE}/x/polymer/web-dynamic/v1/opus/detail"
        # B站合集API
        url = f"{BILIBILI_API_BASE}/x/space/section/index?mid={mid}"
        async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status == 404:
                return []
            resp.raise_for_status()
            data = await resp.json()
            return parse_sections(data)

    async def get_stream_urls(self, bvid: str, cid: int, priority: list[str] | None = None) -> dict:
        url = (
            f"{BILIBILI_API_BASE}/x/player/playurl"
            f"?bvid={bvid}&cid={cid}&qn=80&fnval=16&fourk=1"
        )
        async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json()
            code = data.get("code", -1)
            if code != 0:
                raise ValueError(f"API error: code={code}, message={data.get('message')}")
            return parse_stream_urls(data, priority)
```

- [ ] **Step 6: Commit**

```bash
git add bilibili_downloader/bilibili/ tests/test_parser.py
git commit -m "feat: add bilibili API layer and response parser"
```

---

### Task 5: Retry Strategy

**Files:**
- Create: `bilibili_downloader/core/retry.py`
- Create: `tests/test_retry.py`

- [ ] **Step 1: Write failing tests for retry**

```python
# tests/test_retry.py
import pytest
import asyncio


class TestRetry:
    async def test_success_no_retry(self):
        from bilibili_downloader.core.retry import retry_async

        call_count = 0

        async def success():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_async(success, max_retries=3)
        assert result == "ok"
        assert call_count == 1

    async def test_retry_then_success(self):
        from bilibili_downloader.core.retry import retry_async

        call_count = 0

        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise aiohttp.ClientError("timeout")
            return "ok"

        import aiohttp
        result = await retry_async(fail_twice, max_retries=3, backoff_base=0)
        assert result == "ok"
        assert call_count == 3

    async def test_exhaust_retries_raises(self):
        from bilibili_downloader.core.retry import retry_async

        async def always_fail():
            raise ConnectionError("dead")

        with pytest.raises(ConnectionError):
            await retry_async(always_fail, max_retries=2, backoff_base=0)

    async def test_no_retry_on_permanent_error(self):
        from bilibili_downloader.core.retry import retry_async

        call_count = 0

        async def fail_404():
            nonlocal call_count
            call_count += 1
            raise ValueError("API error: code=-404, message=视频不可用")

        with pytest.raises(ValueError):
            await retry_async(fail_404, max_retries=3, backoff_base=0)
        assert call_count == 1  # no retry

    async def test_no_retry_on_skip_error(self):
        from bilibili_downloader.core.retry import retry_async

        call_count = 0

        async def fail_skip():
            nonlocal call_count
            call_count += 1
            raise ValueError("skipped: 需充值")

        with pytest.raises(ValueError, match="skipped"):
            await retry_async(fail_skip, max_retries=3, backoff_base=0)
        assert call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_retry.py -v`
Expected: FAIL

- [ ] **Step 3: Write retry.py implementation**

```python
# bilibili_downloader/core/retry.py

import asyncio
import logging

import aiohttp

logger = logging.getLogger(__name__)

# Errors that should NOT be retried (permanent)
_NO_RETRY_KEYWORDS = ("code=-404", "code=62002", "skipped:")


async def retry_async(
    func,
    max_retries: int = 3,
    backoff_base: float = 2,
):
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_retry.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/core/retry.py tests/test_retry.py
git commit -m "feat: add exponential backoff retry with permanent error detection"
```

---

### Task 6: Download Worker

**Files:**
- Create: `bilibili_downloader/core/worker.py`
- Create: `tests/test_worker.py`

- [ ] **Step 1: Write failing tests for worker**

```python
# tests/test_worker.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path


class TestDownloadWorker:
    async def test_download_success(self, tmp_path, db):
        from bilibili_downloader.core.worker import download_video
        from bilibili_downloader.config import DEFAULT_NAME_TEMPLATE

        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="123", name="TestUP",
            space_url="https://space.bilibili.com/123"
        )
        vid = await db.insert_video(
            creator_id=cid, remote_id="BV1xx", title="Test Video", duration=60,
            extra='{"cid": 456}'
        )
        did = await db.insert_download(
            video_id=vid, save_path=str(tmp_path / "test.mp4"), resolution="720p"
        )

        mock_api = AsyncMock()
        mock_api.get_stream_urls.return_value = {
            "video_url": "http://example.com/video.mp4",
            "audio_url": "http://example.com/audio.mp4",
            "resolution": "720p",
        }

        mock_session = MagicMock()
        # Mock streaming response for video
        video_resp = AsyncMock()
        video_resp.status = 200
        video_resp.headers = {"Content-Length": "1000"}
        video_resp.content.iter_chunked = AsyncMock(return_value=[b"v" * 1000])

        audio_resp = AsyncMock()
        audio_resp.status = 200
        audio_resp.headers = {"Content-Length": "500"}
        audio_resp.content.iter_chunked = AsyncMock(return_value=[b"a" * 500])

        mock_session.get = MagicMock(side_effect=[
            AsyncMock(__aenter__=AsyncMock(return_value=video_resp),
                      __aexit__=AsyncMock(return_value=False)),
            AsyncMock(__aenter__=AsyncMock(return_value=audio_resp),
                      __aexit__=AsyncMock(return_value=False)),
        ])

        await download_video(
            db=db,
            download_id=did,
            video={"id": vid, "remote_id": "BV1xx", "extra": {"cid": 456}},
            creator_name="TestUP",
            section_name=None,
            save_dir=str(tmp_path),
            api=mock_api,
            session=mock_session,
            resolution_priority=["720p"],
            name_template=DEFAULT_NAME_TEMPLATE,
            api_semaphore=AsyncMock(),
            download_semaphore=AsyncMock(),
        )

        dl = await db.get_download(did)
        assert dl["status"] == "completed"
        assert dl["file_size"] == 1000

    async def test_download_skipped_on_paid(self, tmp_path, db):
        from bilibili_downloader.core.worker import download_video
        from bilibili_downloader.config import DEFAULT_NAME_TEMPLATE

        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="123", name="TestUP",
            space_url="https://space.bilibili.com/123"
        )
        vid = await db.insert_video(
            creator_id=cid, remote_id="BV1xx", title="Paid Video", duration=60,
            extra='{"cid": 456}'
        )
        did = await db.insert_download(
            video_id=vid, save_path=str(tmp_path / "paid.mp4"), resolution="720p"
        )

        mock_api = AsyncMock()
        mock_api.get_stream_urls.side_effect = ValueError("code=62002, message=需要充值")

        mock_session = MagicMock()

        await download_video(
            db=db,
            download_id=did,
            video={"id": vid, "remote_id": "BV1xx", "extra": {"cid": 456}},
            creator_name="TestUP",
            section_name=None,
            save_dir=str(tmp_path),
            api=mock_api,
            session=mock_session,
            resolution_priority=["720p"],
            name_template=DEFAULT_NAME_TEMPLATE,
            api_semaphore=AsyncMock(),
            download_semaphore=AsyncMock(),
        )

        dl = await db.get_download(did)
        assert dl["status"] == "skipped"
        assert "充值" in dl["error_msg"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_worker.py -v`
Expected: FAIL

- [ ] **Step 3: Write worker.py implementation**

```python
# bilibili_downloader/core/worker.py

import logging
from contextlib import asynccontextmanager

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
    """Download a single video. Updates db status throughout."""
    import asyncio

    try:
        await db.update_download_status(download_id, "downloading")

        # 1. Get stream URLs
        extra = video.get("extra", {})
        if isinstance(extra, str):
            import json
            extra = json.loads(extra)
        cid = extra.get("cid")

        async with api_semaphore:
            try:
                stream = await retry_async(
                    lambda: api.get_stream_urls(video["remote_id"], cid, resolution_priority),
                    max_retries=3,
                    backoff_base=2,
                )
            except ValueError as e:
                if "skipped" in str(e) or "62002" in str(e) or "充值" in str(e):
                    await db.update_download_status(download_id, "skipped", str(e))
                    logger.info(f"Skipped {video['remote_id']}: {e}")
                    return
                raise

        # 2. Download video stream
        video_url = stream["video_url"]
        actual_resolution = stream["resolution"]
        filename = build_filename(
            title=video["title"],
            creator=creator_name,
            section=section_name,
            template=name_template,
        )
        save_path = resolve_save_path(save_dir, filename)

        total_size = 0

        async with download_semaphore:
            await _download_stream(session, video_url, save_path, download_id, db)

            # Check actual file size
            import os
            total_size = os.path.getsize(save_path) if os.path.exists(save_path) else 0

            await db.update_download_progress(download_id, total_size)

        # 3. Update save_path with actual resolution
        await db._conn.execute(
            "UPDATE download SET save_path=? WHERE id=?",
            (save_path, download_id),
        )
        await db._conn.commit()

        await db.update_download_status(download_id, "completed")
        logger.info(f"Completed {filename} ({actual_resolution}, {total_size} bytes)")

    except Exception as e:
        logger.error(f"Failed {video['remote_id']}: {e}")
        await db.update_download_status(download_id, "failed", str(e))


async def _download_stream(
    session: aiohttp.ClientSession,
    url: str,
    save_path: str,
    download_id: int,
    db,
    chunk_size: int = 1024 * 1024,  # 1MB chunks
):
    """Stream download a file, writing chunks to disk."""
    import os
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_worker.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/core/worker.py tests/test_worker.py
git commit -m "feat: add download worker with stream writing and status tracking"
```

---

### Task 7: Download Manager

**Files:**
- Create: `bilibili_downloader/core/manager.py`
- Create: `tests/test_manager.py`

- [ ] **Step 1: Write failing tests for manager**

```python
# tests/test_manager.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDownloadManager:
    async def test_manager_processes_queue(self, tmp_path, db):
        from bilibili_downloader.core.manager import DownloadManager
        from bilibili_downloader.bilibili.api import BilibiliAPI

        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="123", name="TestUP",
            space_url="https://space.bilibili.com/123"
        )
        await db.insert_video(
            creator_id=cid, remote_id="BV1aa", title="Video A", duration=60,
            extra='{"cid": 111}'
        )
        await db.insert_video(
            creator_id=cid, remote_id="BV1bb", title="Video B", duration=60,
            extra='{"cid": 222}'
        )

        mock_api = AsyncMock(spec=BilibiliAPI)

        manager = DownloadManager(
            db=db,
            api=mock_api,
            save_dir=str(tmp_path),
            resolution_priority=["720p"],
            max_concurrent_downloads=2,
        )

        mock_session = MagicMock()

        # Patch the download_video function to avoid real network calls
        async def fake_download(**kwargs):
            await kwargs["db"].update_download_status(kwargs["download_id"], "completed")
            await kwargs["db"].update_download_progress(kwargs["download_id"], 1000)

        with patch("bilibili_downloader.core.manager.download_video", side_effect=fake_download):
            await manager.run(mock_session)

        stats = await db.get_stats()
        assert stats["completed"] == 2
        assert stats["pending"] == 0

    async def test_manager_skips_existing(self, tmp_path, db):
        from bilibili_downloader.core.manager import DownloadManager
        from bilibili_downloader.bilibili.api import BilibiliAPI

        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="123", name="TestUP",
            space_url="https://space.bilibili.com/123"
        )
        vid = await db.insert_video(
            creator_id=cid, remote_id="BV1aa", title="Video A", duration=60,
            extra='{"cid": 111}'
        )
        did = await db.insert_download(
            video_id=vid, save_path="/old/a.mp4", resolution="720p"
        )
        await db.update_download_status(did, "completed")

        mock_api = AsyncMock(spec=BilibiliAPI)
        manager = DownloadManager(
            db=db,
            api=mock_api,
            save_dir=str(tmp_path),
            resolution_priority=["720p"],
            max_concurrent_downloads=2,
        )

        results = await manager._build_queue(cid)
        assert len(results) == 0  # should skip already completed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_manager.py -v`
Expected: FAIL

- [ ] **Step 3: Write manager.py implementation**

```python
# bilibili_downloader/core/manager.py

import asyncio
import logging

from bilibili_downloader.config import (
    DEFAULT_NAME_TEMPLATE,
    MAX_CONCURRENT_DOWNLOADS,
    MAX_CONCURRENT_API_REQUESTS,
)
from bilibili_downloader.core.worker import download_video

logger = logging.getLogger(__name__)


class DownloadManager:
    def __init__(
        self,
        db,
        api,
        save_dir: str,
        resolution_priority: list[str] | None = None,
        max_concurrent_downloads: int = MAX_CONCURRENT_DOWNLOADS,
        max_concurrent_api: int = MAX_CONCURRENT_API_REQUESTS,
        name_template: str = DEFAULT_NAME_TEMPLATE,
    ):
        self.db = db
        self.api = api
        self.save_dir = save_dir
        self.resolution_priority = resolution_priority or ["720p", "480p", "1080p", "240p"]
        self.max_concurrent_downloads = max_concurrent_downloads
        self.max_concurrent_api = max_concurrent_api
        self.name_template = name_template

        self.api_semaphore = asyncio.Semaphore(max_concurrent_api)
        self.download_semaphore = asyncio.Semaphore(max_concurrent_downloads)

    async def run(self, session):
        """Build queue from pending downloads and process them."""
        pending = await self.db.get_all_downloads(status="pending")
        if not pending:
            logger.info("No pending downloads")
            return

        tasks = []
        for dl in pending:
            video = await self.db.get_video(dl["video_id"])
            creator = await self.db.get_creator(
                (await self.db._conn.execute(
                    "SELECT creator_id FROM video WHERE id=?", (dl["video_id"],)
                )) # fetch creator via video
            )
            # Get creator info
            cur = await self.db._conn.execute(
                "SELECT c.name, c.id FROM creator c "
                "JOIN video v ON v.creator_id = c.id WHERE v.id=?",
                (dl["video_id"],),
            )
            row = await cur.fetchone()
            if not row:
                continue
            creator_name = row[0]

            tasks.append(
                download_video(
                    db=self.db,
                    download_id=dl["id"],
                    video=video,
                    creator_name=creator_name,
                    section_name=video.get("section_name"),
                    save_dir=self.save_dir,
                    api=self.api,
                    session=session,
                    resolution_priority=self.resolution_priority,
                    name_template=self.name_template,
                    api_semaphore=self.api_semaphore,
                    download_semaphore=self.download_semaphore,
                )
            )

        await asyncio.gather(*tasks, return_exceptions=True)

    async def enqueue_creator_videos(self, creator_id: int):
        """Insert pending download records for new videos of a creator."""
        videos = await self.db.get_videos_by_creator(creator_id)
        existing = await self.db.get_existing_downloads(creator_id)

        new_count = 0
        for video in videos:
            remote_id = video["remote_id"]
            if (remote_id, self.resolution_priority[0]) not in existing:
                from bilibili_downloader.storage.files import build_filename, resolve_save_path
                creator = await self.db.get_creator(creator_id)
                filename = build_filename(
                    title=video["title"],
                    creator=creator["name"],
                    section=video.get("section_name"),
                    template=self.name_template,
                )
                save_path = resolve_save_path(self.save_dir, filename)
                await self.db.insert_download(
                    video_id=video["id"],
                    save_path=save_path,
                    resolution=self.resolution_priority[0],
                )
                new_count += 1

        logger.info(f"Enqueued {new_count} new downloads for creator {creator_id}")
        return new_count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_manager.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/core/manager.py tests/test_manager.py
git commit -m "feat: add DownloadManager with queue building and worker pool orchestration"
```

---

### Task 8: CLI Entry Point

**Files:**
- Create: `bilibili_downloader/cli/main.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for CLI parsing**

```python
# tests/test_cli.py
import pytest
from unittest.mock import patch, MagicMock


class TestCLIParsing:
    def test_parse_download_command(self):
        from bilibili_downloader.cli.main import parse_args
        args = parse_args(["https://space.bilibili.com/33676449"])
        assert args.command == "download"
        assert args.urls == ["https://space.bilibili.com/33676449"]
        assert args.output == "./downloads"

    def test_parse_multiple_urls(self):
        from bilibili_downloader.cli.main import parse_args
        args = parse_args([
            "https://space.bilibili.com/33676449",
            "https://space.bilibili.com/123456",
        ])
        assert len(args.urls) == 2

    def test_parse_output_dir(self):
        from bilibili_downloader.cli.main import parse_args
        args = parse_args([
            "https://space.bilibili.com/33676449",
            "-o", r"E:\映畫\B",
        ])
        assert args.output == r"E:\映畫\B"

    def test_parse_resolution(self):
        from bilibili_downloader.cli.main import parse_args
        args = parse_args([
            "https://space.bilibili.com/33676449",
            "-r", "1080p",
        ])
        assert args.resolution == "1080p"

    def test_parse_dry_run(self):
        from bilibili_downloader.cli.main import parse_args
        args = parse_args(["https://space.bilibili.com/33676449", "--dry-run"])
        assert args.dry_run is True

    def test_parse_force(self):
        from bilibili_downloader.cli.main import parse_args
        args = parse_args(["https://space.bilibili.com/33676449", "--force"])
        assert args.force is True

    def test_parse_web_command(self):
        from bilibili_downloader.cli.main import parse_args
        args = parse_args(["web", "--port", "9090"])
        assert args.command == "web"
        assert args.port == 9090

    def test_parse_web_default_port(self):
        from bilibili_downloader.cli.main import parse_args
        args = parse_args(["web"])
        assert args.port == 8080

    def test_parse_concurrency(self):
        from bilibili_downloader.cli.main import parse_args
        args = parse_args(["https://space.bilibili.com/33676449", "-n", "10"])
        assert args.concurrency == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL

- [ ] **Step 3: Write cli/main.py implementation**

```python
# bilibili_downloader/cli/main.py

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="bilibili-dl",
        description="B站UP主视频批量下载器",
    )
    subparsers = parser.add_subparsers(dest="command")

    # download subcommand (default)
    dl_parser = subparsers.add_parser("download", help="下载UP主视频")
    dl_parser.add_argument("urls", nargs="+", help="UP主空间地址")
    dl_parser.add_argument("-o", "--output", default="./downloads", help="保存目录")
    dl_parser.add_argument("-r", "--resolution", default=None, help="目标分辨率")
    dl_parser.add_argument("-n", "--concurrency", type=int, default=MAX_CONCURRENT_DOWNLOADS, help="并发下载数")
    dl_parser.add_argument("--dry-run", action="store_true", help="仅分析不下载")
    dl_parser.add_argument("--force", action="store_true", help="忽略已下载记录")
    dl_parser.add_argument("--name-template", default=None, help="文件命名模板")

    # web subcommand
    web_parser = subparsers.add_parser("web", help="启动Web仪表盘")
    web_parser.add_argument("--port", type=int, default=DEFAULT_WEB_PORT, help="Web服务端口")

    # If no subcommand, treat first positional args as download URLs
    args = parser.parse_args(argv)
    if args.command is None:
        # Re-parse as download command
        args = parser.parse_args(argv + ["download"] if argv else ["download"])

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

            # Get or create platform
            platform = await db.get_platform_by_name("bilibili")
            if not platform:
                pid = await db.insert_platform(name="bilibili", base_url="https://www.bilibili.com")
            else:
                pid = platform["id"]

            # Get or create creator
            creator = await db.get_creator_by_remote(pid, mid)
            if not creator:
                info = await api.get_space_info(mid)
                cid = await db.insert_creator(
                    platform_id=pid,
                    remote_id=mid,
                    name=info["name"],
                    space_url=url,
                    avatar_url=info.get("avatar_url"),
                )
            else:
                cid = creator["id"]

            # Sync videos
            videos = await api.get_all_videos(mid)
            sections = await api.get_sections(mid)

            # Build section map
            section_map = {s["remote_id"]: s for s in sections}

            existing = set()
            if not args.force:
                existing = await db.get_existing_downloads(cid)

            new_videos = 0
            for video_data in videos:
                remote_id = video_data["remote_id"]

                # Merge section info
                sec = section_map.get(remote_id)
                section_id = sec["section_id"] if sec else None
                section_name = sec["section_name"] if sec else None

                # Upsert video
                video = await db.get_video_by_remote(cid, remote_id)
                if not video:
                    vid = await db.insert_video(
                        creator_id=cid,
                        remote_id=remote_id,
                        title=video_data["title"],
                        duration=video_data.get("duration"),
                        pubdate=video_data.get("pubdate"),
                        extra=str(video_data.get("extra")),
                        section_id=section_id,
                        section_name=section_name,
                    )
                    video = await db.get_video(vid)

                # Check if already downloaded
                if not args.force and (remote_id, resolution_priority[0]) in existing:
                    continue

                # Create download record
                from bilibili_downloader.storage.files import build_filename, resolve_save_path
                creator_info = await db.get_creator(cid)
                filename = build_filename(
                    title=video_data["title"],
                    creator=creator_info["name"],
                    section=section_name,
                    template=args.name_template or DEFAULT_NAME_TEMPLATE,
                )
                save_path = resolve_save_path(args.output, filename)
                await db.insert_download(
                    video_id=video["id"],
                    save_path=save_path,
                    resolution=resolution_priority[0],
                )
                new_videos += 1

            await db.update_creator_sync(cid)
            logger.info(f"Found {len(videos)} videos, {new_videos} new downloads queued")

        if args.dry_run:
            stats = await db.get_stats()
            logger.info(f"Dry run complete: {stats}")
            await db.close()
            return

        # Run downloads
        manager = DownloadManager(
            db=db,
            api=api,
            save_dir=args.output,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/cli/main.py tests/test_cli.py bilibili_downloader/main.py
git commit -m "feat: add CLI entry point with download and web subcommands"
```

---

### Task 9: Web Dashboard

**Files:**
- Create: `bilibili_downloader/web/app.py`
- Create: `bilibili_downloader/web/routes.py`
- Create: `bilibili_downloader/web/templates/index.html`

- [ ] **Step 1: Create index.html template**

```html
<!-- bilibili_downloader/web/templates/index.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bilibili Downloader Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f5f5f5; color: #333; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        h1 { margin-bottom: 20px; color: #00a1d6; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .stat-card { background: #fff; border-radius: 8px; padding: 15px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .stat-card .label { font-size: 14px; color: #999; }
        .stat-card .value { font-size: 28px; font-weight: bold; margin-top: 5px; }
        .stat-card.downloading .value { color: #00a1d6; }
        .stat-card.completed .value { color: #52c41a; }
        .stat-card.skipped .value { color: #faad14; }
        .stat-card.failed .value { color: #f5222d; }
        table { width: 100%; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #fafafa; font-weight: 600; }
        .status { padding: 3px 8px; border-radius: 4px; font-size: 12px; }
        .status-pending { background: #f0f0f0; color: #999; }
        .status-downloading { background: #e6f7ff; color: #00a1d6; }
        .status-completed { background: #f6ffed; color: #52c41a; }
        .status-skipped { background: #fffbe6; color: #faad14; }
        .status-failed { background: #fff2f0; color: #f5222d; }
        .auto-refresh { margin-top: 10px; color: #999; font-size: 13px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Bilibili Downloader</h1>
        <div class="stats">
            <div class="stat-card">
                <div class="label">UP主</div>
                <div class="value">{{ stats.total_creators }}</div>
            </div>
            <div class="stat-card">
                <div class="label">视频总数</div>
                <div class="value">{{ stats.total_videos }}</div>
            </div>
            <div class="stat-card downloading">
                <div class="label">下载中</div>
                <div class="value">{{ stats.downloading }}</div>
            </div>
            <div class="stat-card completed">
                <div class="label">已完成</div>
                <div class="value">{{ stats.completed }}</div>
            </div>
            <div class="stat-card skipped">
                <div class="label">已跳过</div>
                <div class="value">{{ stats.skipped }}</div>
            </div>
            <div class="stat-card failed">
                <div class="label">失败</div>
                <div class="value">{{ stats.failed }}</div>
            </div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>UP主</th>
                    <th>视频标题</th>
                    <th>合集</th>
                    <th>分辨率</th>
                    <th>状态</th>
                    <th>大小</th>
                </tr>
            </thead>
            <tbody>
                {% for dl in downloads %}
                <tr>
                    <td>{{ dl.creator_name }}</td>
                    <td>{{ dl.title }}</td>
                    <td>{{ dl.section_name or '-' }}</td>
                    <td>{{ dl.resolution }}</td>
                    <td><span class="status status-{{ dl.status }}">{{ dl.status }}</span></td>
                    <td>{{ (dl.file_size or 0) | filesizeformat }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        <div class="auto-refresh">页面每3秒自动刷新</div>
    </div>
    <script>
        setTimeout(function() { location.reload(); }, 3000);
    </script>
</body>
</html>
```

- [ ] **Step 2: Create routes.py**

```python
# bilibili_downloader/web/routes.py

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates


def create_routes(db, templates: Jinja2Templates):
    async def index(request: Request) -> HTMLResponse:
        stats = await db.get_stats()
        downloads = await db.get_all_downloads(limit=200)
        return templates.TemplateResponse("index.html", {
            "request": request,
            "stats": stats,
            "downloads": downloads,
        })

    async def api_stats(request: Request) -> JSONResponse:
        stats = await db.get_stats()
        return JSONResponse(stats)

    async def api_downloads(request: Request) -> JSONResponse:
        status = request.query_params.get("status")
        limit = int(request.query_params.get("limit", 100))
        offset = int(request.query_params.get("offset", 0))
        downloads = await db.get_all_downloads(status=status, limit=limit, offset=offset)
        return JSONResponse(downloads)

    async def api_download_detail(request: Request) -> JSONResponse:
        download_id = int(request.path_params["download_id"])
        dl = await db.get_download(download_id)
        if not dl:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(dict(dl))

    return {
        "/": (index, ["GET"]),
        "/api/stats": (api_stats, ["GET"]),
        "/api/downloads": (api_downloads, ["GET"]),
        "/api/downloads/{download_id}": (api_download_detail, ["GET"]),
    }
```

- [ ] **Step 3: Create app.py**

```python
# bilibili_downloader/web/app.py

import pathlib

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from bilibili_downloader.web.routes import create_routes


def create_app(db):
    app = FastAPI(title="Bilibili Downloader Dashboard")

    templates_dir = pathlib.Path(__file__).parent / "templates"
    templates = Jinja2Templates(directory=str(templates_dir))

    # Register Jinja2 filter for file size formatting
    def filesizeformat(value):
        if value is None:
            return "0 B"
        value = int(value)
        for unit in ("B", "KB", "MB", "GB"):
            if abs(value) < 1024:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"

    templates.env.filters["filesizeformat"] = filesizeformat

    routes = create_routes(db, templates)
    for path, (handler, methods) in routes.items():
        app.add_api_route(path, handler, methods=methods)

    return app
```

- [ ] **Step 4: Verify web app starts**

Run: `python -c "from bilibili_downloader.web.app import create_app; print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/web/
git commit -m "feat: add web dashboard with stats and download list"
```

---

### Task 10: Integration Test & Final Wiring

**Files:**
- Modify: `bilibili_downloader/main.py` (already done in Task 1)
- Verify: all tests pass end-to-end

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify CLI help output**

Run: `python -m bilibili_downloader.cli.main --help`
Expected: help text with subcommands

- [ ] **Step 3: Verify dry-run against real Bilibili API**

Run: `python -m bilibili_downloader.cli.main https://space.bilibili.com/33676449 --dry-run -o /tmp/test_dl`
Expected: Log output showing UP主 info, video count, no actual downloads

- [ ] **Step 4: Verify web dashboard starts**

Run: `python -m bilibili_downloader.cli.main web --port 8080 &` then `curl http://localhost:8080/`
Expected: HTML dashboard page returned

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete V1 bilibili downloader with CLI and web dashboard"
```
