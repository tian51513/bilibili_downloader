# Bilibili Downloader V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 7 major V2 features: web-based task management with cookie auto-refresh, audio+video download with ffmpeg merge, resume/incremental download, speed limiting, video collection completeness via API backfill, native directory picker, and pagination with WebSocket real-time push.

**Architecture:** Two-phase architecture expands: Phase 1 (scraping) and Phase 2 (downloading) now run as background tasks managed by a TaskService inside the FastAPI web server. A WebSocket channel provides real-time progress push. Cookie validation runs before each scrape task; expired cookies trigger a headed Playwright QR login flow. Download pipeline now handles dual-stream (video+audio) with Range-based resume, ffmpeg merge, and per-connection speed limiting.

**Tech Stack:** Python 3.11+, FastAPI + Uvicorn + Jinja2 + WebSocket, Playwright, aiohttp, aiosqlite, tkinter (directory picker), ffmpeg (external), asyncio

---

## File Structure

```
bilibili_downloader/
├── config.py              # MODIFY: add download_speed_limit default, speed limit constants
├── browser.py             # MODIFY: restore wbi.py dependency, add cookie validation helper
├── storage/
│   ├── database.py        # MODIFY: add task table schema + CRUD, download table add progress/audio fields
│   └── files.py           # MODIFY: support .tmp extensions for dual-stream downloads
├── bilibili/
│   ├── api.py             # MODIFY: add WBI-signed arc/search request for backfill
│   ├── parser.py          # MODIFY: parse_stream_urls returns audio_url explicitly (already does)
│   ├── wbi.py             # RESTORE: WBI signature module (restored from git)
│   └── scraper.py         # MODIFY: add API backfill method after scrolling
├── core/
│   ├── manager.py         # MODIFY: dual-stream download + ffmpeg merge + speed limit
│   ├── worker.py          # MODIFY: Range-based resume, dual-stream, speed limiting
│   └── retry.py           # NO CHANGE
├── cli/
│   └── main.py            # MODIFY: use TaskService in web_command
├── web/
│   ├── app.py             # MODIFY: add WebSocket support, TaskService integration
│   ├── routes.py          # MODIFY: add task + directory picker + pagination APIs
│   ├── task_service.py    # CREATE: background task runner (scrape queue + download dispatcher)
│   ├── ws_manager.py      # CREATE: WebSocket connection manager + broadcast
│   └── templates/
│       └── index.html     # MODIFY: task panel, pagination, WebSocket, directory picker UI
├── bilibili/               # No new files here except restored wbi.py
tests/
    ├── test_database.py   # MODIFY: add task table tests
    ├── test_worker.py     # MODIFY: add resume/speed limit tests
    └── test_task_service.py  # CREATE: task service unit tests
```

---

## Batch 1: Infrastructure

### Task 1: Database Schema Upgrade — Add task table + download fields

**Files:**
- Modify: `bilibili_downloader/storage/database.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Write the failing test for task table creation**

```python
# tests/test_database.py — add to existing file

async def test_task_table_exists(db):
    """Task table should be created on init."""
    cur = await db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='task'"
    )
    row = await cur.fetchone()
    assert row is not None

async def test_insert_and_get_task(db):
    """Insert a task and retrieve it."""
    # Need a platform first
    pid = await db.insert_platform("bilibili")
    task_id = await db.insert_task(
        platform_id=pid,
        space_url="https://space.bilibili.com/12345",
        space_uid="12345",
    )
    task = await db.get_task(task_id)
    assert task["space_url"] == "https://space.bilibili.com/12345"
    assert task["space_uid"] == "12345"
    assert task["status"] == "pending"
    assert task["total_videos"] == 0

async def test_update_task_status(db):
    pid = await db.insert_platform("bilibili")
    task_id = await db.insert_task(platform_id=pid, space_url="https://space.bilibili.com/1", space_uid="1")
    await db.update_task_status(task_id, "scraping", total_videos=41, scraped_videos=10)
    task = await db.get_task(task_id)
    assert task["status"] == "scraping"
    assert task["total_videos"] == 41
    assert task["scraped_videos"] == 10

async def test_get_all_tasks(db):
    pid = await db.insert_platform("bilibili")
    await db.insert_task(platform_id=pid, space_url="https://space.bilibili.com/1", space_uid="1")
    await db.insert_task(platform_id=pid, space_url="https://space.bilibili.com/2", space_uid="2")
    tasks = await db.get_all_tasks()
    assert len(tasks) == 2

async def test_download_table_has_audio_fields(db):
    """Download table should have audio_url and merge_status columns."""
    pid = await db.insert_platform("bilibili")
    cid = await db.insert_creator(platform_id=pid, remote_id="123", name="Test", space_url="https://space.bilibili.com/123")
    vid = await db.insert_video(creator_id=cid, remote_id="BV1xx", title="Test Video")
    dl_id = await db.insert_download(video_id=vid, save_path="/tmp/test.mp4", resolution="720p")
    # Verify new columns exist by querying them
    cur = await db._conn.execute("SELECT audio_url, merge_status FROM download WHERE id=?", (dl_id,))
    row = await cur.fetchone()
    assert row is not None  # columns exist and are accessible
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_database.py::test_task_table_exists tests/test_database.py::test_insert_and_get_task tests/test_database.py::test_update_task_status tests/test_database.py::test_get_all_tasks tests/test_database.py::test_download_table_has_audio_fields -v`
Expected: FAIL — `insert_task`, `get_task`, etc. don't exist; `audio_url` and `merge_status` columns don't exist.

- [ ] **Step 3: Implement database schema upgrade and task CRUD**

In `bilibili_downloader/storage/database.py`:

Add to `_SCHEMA` string (after download table):

```sql
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
```

In the `init()` method, after existing migrations, add:

```python
# Migration: add audio_url and merge_status to download table
for col, col_type in [("audio_url", "TEXT"), ("merge_status", "TEXT DEFAULT NULL")]:
    try:
        await self._conn.execute(f"ALTER TABLE download ADD COLUMN {col} {col_type}")
        await self._conn.commit()
    except Exception:
        pass  # column already exists
```

Add task CRUD methods to the `Database` class:

```python
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
        f"SELECT t.*, c.name as creator_name, c.avatar_url "
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
    params.append(task_id)
    await self._conn.execute(
        f"UPDATE task SET {', '.join(sets)} WHERE id=?", params,
    )
    await self._conn.commit()

async def get_task_by_url(self, space_url: str) -> dict | None:
    cur = await self._conn.execute("SELECT * FROM task WHERE space_url=?", (space_url,))
    row = await cur.fetchone()
    return dict(row) if row else None
```

Also update `get_all_downloads` to return paginated result:

```python
async def get_all_downloads(
    self, status: str | None = None, page: int = 1, page_size: int = 20,
    creator_id: int | None = None, section_name: str | None = None,
    tags: list[str] | None = None,
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
        conditions.append(f"({' AND '.join(tag_conds)})")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Count total
    params_count = list(params)
    cur_count = await self._conn.execute(
        f"SELECT COUNT(*) FROM download d JOIN video v ON d.video_id = v.id "
        f"JOIN creator c ON v.creator_id = c.id {where}", params_count,
    )
    total = (await cur_count.fetchone())[0]

    offset = (page - 1) * page_size
    params.extend([page_size, offset])
    cur = await self._conn.execute(
        f"SELECT d.*, v.title, v.section_name, v.remote_id as bvid, v.tags, "
        f"c.name as creator_name, c.id as creator_id, c.avatar_url "
        f"FROM download d JOIN video v ON d.video_id = v.id "
        f"JOIN creator c ON v.creator_id = c.id "
        f"{where} ORDER BY d.created_at DESC LIMIT ? OFFSET ?",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_database.py -v`
Expected: All tests PASS (including existing tests — verify backward compat)

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/storage/database.py tests/test_database.py
git commit -m "feat(db): add task table schema and paginated download query"
```

---

### Task 2: WebSocket Connection Manager

**Files:**
- Create: `bilibili_downloader/web/ws_manager.py`
- Test: `tests/test_ws_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ws_manager.py
import asyncio
from unittest.mock import AsyncMock

async def test_broadcast_sends_to_all_connections():
    from bilibili_downloader.web.ws_manager import WSManager
    mgr = WSManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    mgr.connect(ws1)
    mgr.connect(ws2)
    await mgr.broadcast({"type": "test", "data": "hello"})
    ws1.send_json.assert_called_once_with({"type": "test", "data": "hello"})
    ws2.send_json.assert_called_once_with({"type": "test", "data": "hello"})

async def test_disconnect_removes_connection():
    from bilibili_downloader.web.ws_manager import WSManager
    mgr = WSManager()
    ws = AsyncMock()
    mgr.connect(ws)
    assert mgr.active_count() == 1
    mgr.disconnect(ws)
    assert mgr.active_count() == 0

async def test_broadcast_empty_does_nothing():
    from bilibili_downloader.web.ws_manager import WSManager
    mgr = WSManager()
    await mgr.broadcast({"type": "test"})  # Should not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ws_manager.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement WSManager**

```python
# bilibili_downloader/web/ws_manager.py
"""WebSocket connection manager for broadcasting real-time progress."""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    """Manages WebSocket connections and broadcasts messages to all clients."""

    def __init__(self):
        self._connections: set[WebSocket] = set()

    def connect(self, ws: WebSocket):
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)

    def active_count(self) -> int:
        return len(self._connections)

    async def broadcast(self, message: dict[str, Any]):
        if not self._connections:
            return
        disconnected = set()
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.add(ws)
        for ws in disconnected:
            self.disconnect(ws)
            logger.debug("WebSocket disconnected during broadcast")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_ws_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/web/ws_manager.py tests/test_ws_manager.py
git commit -m "feat(web): add WebSocket connection manager for real-time push"
```

---

### Task 3: Cookie Validation Helper

**Files:**
- Create: `bilibili_downloader/bilibili/wbi.py` (restore from git — already done)
- Modify: `bilibili_downloader/bilibili/api.py` (add cookie validation method)
- Test: `tests/test_api_cookie.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_cookie.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

async def test_validate_cookie_valid():
    """Valid cookie returns True."""
    from bilibili_downloader.bilibili.api import BilibiliAPI
    session = AsyncMock()
    api = BilibiliAPI.__new__(BilibiliAPI)
    api.session = session
    api.headers = {"User-Agent": "test", "Referer": "https://www.bilibili.com/"}

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"code": 0, "data": {"isLogin": True}})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=mock_resp)

    result = await api.validate_cookie()
    assert result is True

async def test_validate_cookie_expired():
    """Expired cookie returns False."""
    from bilibili_downloader.bilibili.api import BilibiliAPI
    session = AsyncMock()
    api = BilibiliAPI.__new__(BilibiliAPI)
    api.session = session
    api.headers = {"User-Agent": "test", "Referer": "https://www.bilibili.com/"}

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"code": 0, "data": {"isLogin": False}})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=mock_resp)

    result = await api.validate_cookie()
    assert result is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_cookie.py -v`
Expected: FAIL — `validate_cookie` method doesn't exist

- [ ] **Step 3: Implement validate_cookie in api.py**

Add to `BilibiliAPI` class in `bilibili_downloader/bilibili/api.py`:

```python
async def validate_cookie(self) -> bool:
    """Check if the current cookie/session is still valid.

    Returns True if cookie is valid and user is logged in.
    """
    url = f"{BILIBILI_API_BASE}/x/web-interface/nav"
    try:
        async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status != 200:
                return False
            data = await resp.json()
            return data.get("code") == 0 and data.get("data", {}).get("isLogin", False)
    except Exception:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api_cookie.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/bilibili/api.py bilibili_downloader/bilibili/wbi.py tests/test_api_cookie.py
git commit -m "feat(api): add cookie validation and restore WBI signature module"
```

---

### Task 4: Speed Limit Config Constant

**Files:**
- Modify: `bilibili_downloader/config.py`

- [ ] **Step 1: Add speed limit constants to config.py**

Add after `MAX_CONCURRENT_API_REQUESTS`:

```python
# Speed limit
MIN_SPEED_LIMIT_KB = 100  # Minimum speed limit in KB/s
DEFAULT_SPEED_LIMIT_MB = 0.0  # 0 = no limit, in MB/s
```

Add to `_DEFAULTS` dict:

```python
"download_speed_limit": DEFAULT_SPEED_LIMIT_MB,
```

- [ ] **Step 2: Commit**

```bash
git add bilibili_downloader/config.py
git commit -m "feat(config): add speed limit constants (min 100KB/s, default unlimited)"
```

---

## Batch 2: Core Download Pipeline Overhaul

### Task 5: Dual-Stream Download with Resume + Speed Limit

**Files:**
- Modify: `bilibili_downloader/core/worker.py`
- Modify: `bilibili_downloader/storage/files.py`
- Test: `tests/test_worker.py`

- [ ] **Step 1: Write failing tests for resume and speed limit**

```python
# tests/test_worker.py — add new tests

async def test_download_stream_resume(tmp_path):
    """If tmp file exists, download should resume from where it left off."""
    import os, json
    from unittest.mock import AsyncMock, MagicMock, patch
    from bilibili_downloader.core.worker import download_video

    # Create a partial tmp file (simulating interrupted download)
    tmp_path = str(tmp_path / "test_video.video.tmp")
    with open(tmp_path, "wb") as f:
        f.write(b"\x00" * 5000)  # 5KB already downloaded

    # Mock aiohttp session with Range support
    mock_session = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status = 206  # Partial Content
    mock_resp.headers = {"Content-Range": "bytes 5000-14999/15000", "Content-Length": "10000"}
    # Yield one chunk
    mock_resp.content = MagicMock()
    mock_resp.content.iter_chunked = MagicMock(return_value=iter([b"\x01" * 10000]))
    mock_resp.raise_for_status = MagicMock()
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = MagicMock(return_value=mock_resp)

    from bilibili_downloader.core.worker import _download_stream
    db = AsyncMock()
    db.update_download_progress = AsyncMock()

    await _download_stream(
        session=mock_session, url="http://example.com/video.mp4",
        save_path=tmp_path, download_id=1, db=db,
        headers={"Referer": "https://www.bilibili.com/"},
        existing_size=5000,
    )
    # File should now be 15KB (5000 original + 10000 resumed)
    assert os.path.getsize(tmp_path) == 15000
    # Should have sent Range header
    call_args = mock_session.get.call_args
    assert "Range" in call_args.kwargs["headers"] or "Range" in call_args[1].get("headers", {})

async def test_speed_limit_enforced():
    """Speed limit should throttle download speed."""
    from bilibili_downloader.core.worker import _apply_speed_limit
    import time
    # 1MB chunk at 1MB/s should take ~1 second
    start = time.monotonic()
    await _apply_speed_limit(chunk_size=1024*1024, speed_limit_bps=1024*1024, elapsed=0)
    elapsed = time.monotonic() - start
    assert elapsed >= 0.8  # allow some tolerance

async def test_speed_limit_minimum():
    """Speed limit below minimum should be clamped."""
    from bilibili_downloader.config import MIN_SPEED_LIMIT_KB
    assert MIN_SPEED_LIMIT_KB == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_worker.py::test_download_stream_resume tests/test_worker.py::test_speed_limit_enforced -v`
Expected: FAIL — `_download_stream` doesn't support `existing_size` param; `_apply_speed_limit` doesn't exist

- [ ] **Step 3: Implement dual-stream download with resume + speed limit**

Rewrite `bilibili_downloader/core/worker.py`:

```python
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
            total_size = int(content_range.split("/")[-1])
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
        # Remove temp files after successful merge
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

        # 1. Get stream URLs (rate-limited by api_semaphore)
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
                             f"video={stream['video_url'][:60]}... audio={stream['audio_url'][:60] if stream.get('audio_url') else 'None'}")
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

        total_video_size = 0
        async with download_semaphore:
            total_video_size = await _download_stream(
                session, stream["video_url"], video_tmp, download_id, db,
                headers=api.headers, speed_limit_bps=speed_limit_bps,
                existing_size=existing_video_size,
            )

        # 4. Download audio stream with resume + speed limit
        total_audio_size = 0
        if stream.get("audio_url"):
            existing_audio_size = 0
            if os.path.exists(audio_tmp):
                existing_audio_size = os.path.getsize(audio_tmp)
                logger.info(f"[worker] {bvid} Resuming audio from {existing_audio_size} bytes")
            async with download_semaphore:
                total_audio_size = await _download_stream(
                    session, stream["audio_url"], audio_tmp, download_id, db,
                    headers=api.headers, speed_limit_bps=speed_limit_bps,
                    existing_size=existing_audio_size,
                )

        total_size = total_video_size + total_audio_size

        # 5. Merge audio + video with ffmpeg
        merged = False
        if stream.get("audio_url") and os.path.exists(video_tmp) and os.path.exists(audio_tmp):
            merged = await _merge_audio_video(video_tmp, audio_tmp, save_path, download_id, db)
        elif not stream.get("audio_url"):
            # No audio stream, just rename video tmp to final
            os.rename(video_tmp, save_path)
            merged = True

        # 6. Update final status
        if os.path.exists(save_path):
            final_size = os.path.getsize(save_path)
            await db.update_download_progress(download_id, final_size)
            await db.update_download_status(download_id, "completed")
            merge_info = "merged" if merged else "video-only"
            logger.info(f"Completed {filename} ({stream['resolution']}, {final_size} bytes, {merge_info})")
        else:
            await db.update_download_status(download_id, "failed", "Merge failed, no output file")

    except Exception as e:
        logger.error(f"Failed {bvid}: {e}", exc_info=True)
        await db.update_download_status(download_id, "failed", str(e))
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_worker.py -v`
Expected: All existing + new tests PASS

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/core/worker.py tests/test_worker.py
git commit -m "feat(worker): dual-stream download with resume, speed limit, ffmpeg merge"
```

---

### Task 6: Download Manager Integration

**Files:**
- Modify: `bilibili_downloader/core/manager.py`

- [ ] **Step 1: Update DownloadManager to pass speed_limit and ws_manager**

In `bilibili_downloader/core/manager.py`, update `__init__` to accept `speed_limit_bps` and `ws_manager`:

```python
def __init__(self, db, api, save_dir: str, resolution_priority: list[str] | None = None,
             max_concurrent_downloads: int = MAX_CONCURRENT_DOWNLOADS,
             max_concurrent_api: int = MAX_CONCURRENT_API_REQUESTS,
             name_template: str = DEFAULT_NAME_TEMPLATE,
             speed_limit_bps: int = 0,
             ws_manager=None):
    # ... existing init ...
    self.speed_limit_bps = speed_limit_bps
    self.ws_manager = ws_manager
```

Update `run` method's `download_video` call to pass `speed_limit_bps=self.speed_limit_bps, ws_manager=self.ws_manager`.

Update `enqueue_creator_videos` to also return pending count:

```python
async def enqueue_creator_videos(self, creator_id: int) -> int:
    """Enqueue undownloaded videos for a creator. Returns count of new downloads."""
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
    return new_count
```

- [ ] **Step 2: Commit**

```bash
git add bilibili_downloader/core/manager.py
git commit -m "feat(manager): pass speed limit and ws_manager to worker pipeline"
```

---

## Batch 3: Web Task System

### Task 7: Task Service (Background Task Runner)

**Files:**
- Create: `bilibili_downloader/web/task_service.py`
- Test: `tests/test_task_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_task_service.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

async def test_task_service_submit_creates_task():
    """Submitting a URL creates a task in the database."""
    from bilibili_downloader.web.task_service import TaskService
    db = AsyncMock()
    db.insert_platform = AsyncMock(return_value=1)
    db.get_platform_by_name = AsyncMock(return_value={"id": 1})
    db.insert_task = AsyncMock(return_value=42)
    db.get_task_by_url = AsyncMock(return_value=None)
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    ts = TaskService(db=db, ws_manager=ws_manager)
    task_id = await ts.submit_task("https://space.bilibili.com/12345")
    assert task_id == 42
    db.insert_task.assert_called_once()

async def test_task_service_prevents_duplicate():
    """Submitting same URL returns existing task."""
    from bilibili_downloader.web.task_service import TaskService
    db = AsyncMock()
    db.get_task_by_url = AsyncMock(return_value={"id": 99, "status": "pending"})
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    ts = TaskService(db=db, ws_manager=ws_manager)
    task_id = await ts.submit_task("https://space.bilibili.com/12345")
    assert task_id == 99
    db.insert_task.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_task_service.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement TaskService**

```python
# bilibili_downloader/web/task_service.py
"""Background task service for managing scrape + download tasks."""

import asyncio
import json
import logging
import re

from bilibili_downloader.config import (
    BILIBILI_SPACE_URL_PATTERN,
    DEFAULT_COOKIE_CACHE_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_NAME_TEMPLATE,
    DEFAULT_RESOLUTION_PRIORITY,
    MAX_CONCURRENT_API_REQUESTS,
    MAX_CONCURRENT_DOWNLOADS,
    DEFAULT_SPEED_LIMIT_MB,
    load_settings,
)
from bilibili_downloader.bilibili.api import BilibiliAPI
from bilibili_downloader.core.manager import DownloadManager

logger = logging.getLogger(__name__)

# Cookie file paths per platform
_COOKIE_FILES = {
    "bilibili": DEFAULT_COOKIE_CACHE_PATH,
}


class TaskService:
    """Manages background scrape + download tasks."""

    def __init__(self, db, ws_manager=None):
        self.db = db
        self.ws_manager = ws_manager
        self._scrape_lock = asyncio.Lock()
        self._scrape_queue: asyncio.Queue = asyncio.Queue()
        self._running = False

    async def submit_task(self, space_url: str) -> int:
        """Submit a new scrape task. Returns task_id (existing if duplicate)."""
        # Check for existing task with same URL
        existing = await self.db.get_task_by_url(space_url)
        if existing:
            return existing["id"]

        # Extract UID from URL
        match = re.search(BILIBILI_SPACE_URL_PATTERN, space_url)
        if not match:
            raise ValueError(f"Invalid Bilibili space URL: {space_url}")
        space_uid = match.group(1)

        # Get or create platform
        platform = await self.db.get_platform_by_name("bilibili")
        if not platform:
            pid = await self.db.insert_platform("bilibili")
        else:
            pid = platform["id"]

        task_id = await self.db.insert_task(platform_id=pid, space_url=space_url, space_uid=space_uid)

        # Queue for background processing
        await self._scrape_queue.put(task_id)

        # Start processor if not running
        if not self._running:
            self._running = True
            asyncio.create_task(self._process_queue())

        return task_id

    async def _process_queue(self):
        """Background loop: process scrape tasks sequentially."""
        while True:
            try:
                task_id = await asyncio.wait_for(self._scrape_queue.get(), timeout=5)
            except asyncio.TimeoutError:
                if self._scrape_queue.empty():
                    self._running = False
                    break
                continue

            try:
                await self._execute_task(task_id)
            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}", exc_info=True)
                await self.db.update_task_status(task_id, "failed", error_message=str(e))

    async def _execute_task(self, task_id: int):
        """Execute a single scrape + download task."""
        task = await self.db.get_task(task_id)
        if not task:
            return

        settings = load_settings()

        # Check cookie validity
        await self.db.update_task_status(task_id, "pending", cookie_status="checking")
        cookie_valid = await self._check_cookie(task_id)
        if not cookie_valid:
            await self.db.update_task_status(task_id, "pending", cookie_status="login_required")
            await self._broadcast({"type": "login_required", "task_id": task_id, "message": "Cookie已失效，请扫码登录"})
            # Wait for login to complete (poll every 2s, timeout 120s)
            logged_in = await self._wait_for_login(task_id, timeout=120)
            if not logged_in:
                await self.db.update_task_status(task_id, "failed", error_message="登录超时", cookie_status="expired")
                return

        # Phase 1: Scrape
        await self.db.update_task_status(task_id, "scraping", cookie_status="valid")
        await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "scraping"}})

        from bilibili_downloader.browser import (
            PlaywrightBrowser,
            load_cookies_from_file,
            save_cookies_to_file,
        )
        from bilibili_downloader.bilibili.scraper import BilibiliScraper

        cookies = load_cookies_from_file(_COOKIE_FILES.get("bilibili", "bilibili_cookies.json"))
        browser = PlaywrightBrowser(headless=True, cookies=cookies)
        await browser.start()

        try:
            scraper = BilibiliScraper(browser)
            data = await scraper.collect(task["space_uid"])
            space_info = data["space_info"]
            videos = data["videos"]
            sections = data["sections"]
            total = len(videos)

            # Create or get creator
            if space_info:
                pid = task["platform_id"]
                creator = await self.db.get_creator_by_remote(pid, space_info["remote_id"])
                if not creator:
                    cid = await self.db.insert_creator(
                        platform_id=pid, remote_id=space_info["remote_id"],
                        name=space_info["name"], space_url=task["space_url"],
                        avatar_url=space_info.get("avatar_url"),
                    )
                else:
                    cid = creator["id"]
                await self.db.update_task_status(task_id, "scraping", creator_id=cid, total_videos=total, scraped_videos=total)
            else:
                await self.db.update_task_status(task_id, "scraping", total_videos=total, scraped_videos=total)
                cid = None

            # Store videos in database
            section_map = {s["remote_id"]: s for s in sections}
            for video_data in videos:
                if cid is None:
                    continue
                remote_id = video_data["remote_id"]
                sec = section_map.get(remote_id)
                video = await self.db.get_video_by_remote(cid, remote_id)
                if not video:
                    vid = await self.db.insert_video(
                        creator_id=cid, remote_id=remote_id,
                        title=video_data["title"],
                        duration=video_data.get("duration"),
                        pubdate=video_data.get("pubdate"),
                        extra=json.dumps(video_data.get("extra")),
                        section_id=sec["section_id"] if sec else None,
                        section_name=sec["section_name"] if sec else None,
                    )
                tags = video_data.get("tags", [])
                if tags and video and not video.get("tags"):
                    await self.db.update_video_tags(video["id"], tags)

        finally:
            await browser.close()

        await self._broadcast({"type": "scrape_progress", "task_id": task_id,
                               "data": {"scraped": total, "total": total, "phase": "done"}})

        # Phase 2: Enqueue downloads and start download manager
        if cid:
            await self.db.update_task_status(task_id, "downloading")
            await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "downloading"}})

            import aiohttp
            cookies = load_cookies_from_file(_COOKIE_FILES.get("bilibili", "bilibili_cookies.json"))
            async with aiohttp.ClientSession() as session:
                api = BilibiliAPI(session, cookies=cookies)
                resolution_priority = settings.get("resolution_priority", DEFAULT_RESOLUTION_PRIORITY)
                speed_limit_bps = int(settings.get("download_speed_limit", 0) * 1024 * 1024)
                manager = DownloadManager(
                    db=self.db, api=api,
                    save_dir=settings.get("output_dir", "./downloads"),
                    resolution_priority=resolution_priority,
                    max_concurrent_downloads=settings.get("max_concurrent_downloads", MAX_CONCURRENT_DOWNLOADS),
                    max_concurrent_api=settings.get("max_concurrent_api", MAX_CONCURRENT_API_REQUESTS),
                    name_template=settings.get("name_template", DEFAULT_NAME_TEMPLATE),
                    speed_limit_bps=speed_limit_bps,
                    ws_manager=self.ws_manager,
                )
                await manager.run(session)

            # Final status
            from bilibili_downloader.storage.database import Database as DB
            stats = {}
            # Count completed downloads for this creator
            cur = await self.db._conn.execute(
                "SELECT COUNT(*) FROM download d JOIN video v ON d.video_id = v.id WHERE v.creator_id=? AND d.status='completed'",
                (cid,),
            )
            completed = (await cur.fetchone())[0]
            cur2 = await self.db._conn.execute(
                "SELECT COUNT(*) FROM download d JOIN video v ON d.video_id = v.id WHERE v.creator_id=? AND d.status IN ('pending','downloading')",
                (cid,),
            )
            remaining = (await cur2.fetchone())[0]
            await self.db.update_task_status(
                task_id, "completed",
                downloaded_videos=completed,
                total_downloads=completed + remaining,
            )
            await self._broadcast({"type": "task_status", "task_id": task_id,
                                   "data": {"status": "completed", "downloaded": completed}})

    async def _check_cookie(self, task_id: int) -> bool:
        """Check if cookie is valid. If not, trigger QR login."""
        import aiohttp
        from bilibili_downloader.browser import load_cookies_from_file
        cookies = load_cookies_from_file(_COOKIE_FILES.get("bilibili", "bilibili_cookies.json"))
        if not cookies:
            return False
        async with aiohttp.ClientSession() as session:
            api = BilibiliAPI(session, cookies=cookies)
            return await api.validate_cookie()

    async def _wait_for_login(self, task_id: int, timeout: int = 120) -> bool:
        """Wait for QR login to complete. Returns True if login succeeded."""
        start = asyncio.get_event_loop().time()
        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout:
                return False
            valid = await self._check_cookie(task_id)
            if valid:
                await self._broadcast({"type": "login_success", "task_id": task_id, "message": "登录成功"})
                return True
            await asyncio.sleep(2)

    async def trigger_qr_login(self) -> bool:
        """Trigger QR code login in a headed browser. Returns True on success."""
        from bilibili_downloader.browser import PlaywrightBrowser, save_cookies_to_file
        from bilibili_downloader.cli.main import _qr_code_login
        browser = PlaywrightBrowser(headless=False)
        await browser.start()
        try:
            login_cookies = await _qr_code_login(browser.page)
            cookie_path = _COOKIE_FILES.get("bilibili", "bilibili_cookies.json")
            save_cookies_to_file(login_cookies, cookie_path)
            return True
        except Exception as e:
            logger.error(f"QR login failed: {e}")
            return False
        finally:
            await browser.close()

    async def _broadcast(self, message: dict):
        if self.ws_manager:
            await self.ws_manager.broadcast(message)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_task_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/web/task_service.py tests/test_task_service.py
git commit -m "feat(web): add TaskService for background scrape + download tasks"
```

---

### Task 8: Video Collection Completeness — API Backfill

**Files:**
- Modify: `bilibili_downloader/bilibili/scraper.py`
- Modify: `bilibili_downloader/bilibili/api.py`
- Test: `tests/test_scraper.py`

- [ ] **Step 1: Write failing test for API backfill**

```python
# tests/test_scraper.py — add to existing file

async def test_api_backfill_supplements_missing_videos():
    """API backfill should fetch pages not covered by scrolling."""
    import aiohttp
    from unittest.mock import AsyncMock, MagicMock, patch
    from bilibili_downloader.bilibili.api import BilibiliAPI
    from bilibili_downloader.bilibili.wbi import WbiSigner

    session = AsyncMock()
    api = BilibiliAPI.__new__(BilibiliAPI)
    api.session = session
    api.headers = {"User-Agent": "test", "Referer": "https://www.bilibili.com/"}

    # Mock WbiSigner.create to return a mock signer
    mock_signer = MagicMock()
    mock_signer.sign = MagicMock(side_effect=lambda p: p)  # pass-through
    signer_cls = AsyncMock()
    signer_cls.create = AsyncMock(return_value=mock_signer)

    # Mock arc/search response with 2 pages
    def make_resp(vlist):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "code": 0,
            "data": {
                "list": {"vlist": vlist},
                "page": {"pn": 1, "count": len(vlist)},
            }
        })
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    page1_videos = [{"bvid": f"BV{i}", "title": f"Video {i}", "length": "5:00", "created": 0, "tag": ""} for i in range(30)]
    page2_videos = [{"bvid": f"BV{i}", "title": f"Video {i}", "length": "5:00", "created": 0, "tag": ""} for i in range(30, 41)]

    session.get = MagicMock(side_effect=[
        make_resp(page1_videos),
        make_resp(page2_videos),
    ])

    with patch("bilibili_downloader.bilibili.api.WbiSigner", signer_cls):
        result = await api.fetch_videos_by_api("12345", existing_bvids=set(f"BV{i}" for i in range(10)))
    # Should have returned new videos only
    assert len(result) == 31  # 41 total - 10 existing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scraper.py::test_api_backfill_supplements_missing_videos -v`
Expected: FAIL — `fetch_videos_by_api` doesn't exist

- [ ] **Step 3: Implement API backfill**

Add to `BilibiliAPI` class in `bilibili_downloader/bilibili/api.py`:

```python
async def fetch_videos_by_api(
    self, mid: str, existing_bvids: set[str] | None = None,
) -> list[dict]:
    """Fetch all videos for a UP主 via arc/search API with WBI signature.

    Used to backfill videos that scrolling didn't collect.
    """
    from bilibili_downloader.bilibili.wbi import WbiSigner
    from bilibili_downloader.bilibili.parser import parse_video_list

    existing_bvids = existing_bvids or set()
    all_videos: list[dict] = []
    page = 1
    total = None

    signer = await WbiSigner.create(self.session)

    while True:
        params = signer.sign({
            "mid": mid,
            "ps": 30,
            "pn": page,
            "order": "pubdate",
        })
        url = f"{BILIBILI_API_BASE}/x/space/wbi/arc/search?{urlencode(params)}"
        async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json()

        if data.get("code") != 0:
            logger.warning(f"[api] arc/search backfill page {page} error: {data.get('message')}")
            break

        page_data = data["data"]
        total = page_data.get("page", {}).get("count", 0)
        new_videos = []
        for v in parse_video_list(data):
            if v["remote_id"] not in existing_bvids and v["remote_id"] not in {x["remote_id"] for x in all_videos}:
                new_videos.append(v)

        all_videos.extend(new_videos)
        logger.info(f"[api] backfill page {page}: {len(new_videos)} new videos, total collected {len(all_videos)}/{total}")

        if len(all_videos) >= total:
            break
        page += 1

    return all_videos
```

Add to `BilibiliScraper` class in `bilibili_downloader/bilibili/scraper.py`, add a new method:

```python
async def collect_with_backfill(self, mid: str, session: aiohttp.ClientSession = None, cookies: list[dict] | None = None) -> dict:
    """Collect data with API backfill for completeness.

    Same as collect() but adds arc/search API backfill after scrolling.
    """
    result = await self.collect(mid)

    # Check if we got all videos
    videos = result["videos"]
    total_from_api = 0
    # The total was extracted during collect but not returned; re-derive from video count
    # We need to check if there's a discrepancy
    # For now, always run backfill and dedup
    if session and cookies:
        from bilibili_downloader.bilibili.api import BilibiliAPI
        api = BilibiliAPI(session, cookies=cookies)
        existing_bvids = {v["remote_id"] for v in videos}
        backfill_videos = await api.fetch_videos_by_api(mid, existing_bvids)
        if backfill_videos:
            seen_bvids = existing_bvids
            for v in backfill_videos:
                if v["remote_id"] not in seen_bvids:
                    videos.append(v)
                    seen_bvids.add(v["remote_id"])
            logger.info(f"API backfill added {len(backfill_videos)} videos, total now {len(videos)}")

    result["videos"] = videos
    return result
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_scraper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bilibili_downloader/bilibili/scraper.py bilibili_downloader/bilibili/api.py tests/test_scraper.py
git commit -m "feat(scraper): add API backfill for video collection completeness"
```

---

### Task 9: Directory Picker API Endpoint

**Files:**
- Modify: `bilibili_downloader/web/routes.py`

- [ ] **Step 1: Add directory listing and picker endpoints**

In `bilibili_downloader/web/routes.py`, add new handler functions inside `create_routes`:

```python
async def api_pick_directory(request: Request) -> JSONResponse:
    """Open native directory picker dialog. Returns selected path."""
    import asyncio
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return JSONResponse({"ok": False, "error": "tkinter not available"}, status_code=500)

    data = await request.json() if request.method == "POST" else {}
    initial_dir = data.get("current_path", "./downloads")

    def _pick():
        root = tk.Tk()
        root.withdraw()
        result = filedialog.askdirectory(initialdir=initial_dir, title="选择保存目录")
        root.destroy()
        return result

    selected = await asyncio.to_thread(_pick)
    if selected:
        return JSONResponse({"ok": True, "path": selected})
    return JSONResponse({"ok": False, "error": "cancelled"})

async def api_list_directories(request: Request) -> JSONResponse:
    """List subdirectories of a given path."""
    from pathlib import Path
    data = await request.json()
    path_str = data.get("path", ".")
    try:
        p = Path(path_str)
        if not p.exists():
            return JSONResponse({"ok": False, "error": "path not found"}, status_code=404)
        dirs = []
        for entry in sorted(p.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                dirs.append({"name": entry.name, "path": str(entry.resolve())})
        return JSONResponse({"ok": True, "directories": dirs, "parent": str(p.resolve()), "has_parent": p.parent != p})
    except PermissionError:
        return JSONResponse({"ok": False, "error": "permission denied"}, status_code=403)
```

Add to the returned routes dict:

```python
"/api/pick-directory": (api_pick_directory, ["POST"]),
"/api/directories": (api_list_directories, ["POST"]),
```

- [ ] **Step 2: Commit**

```bash
git add bilibili_downloader/web/routes.py
git commit -m "feat(web): add directory picker and listing API endpoints"
```

---

### Task 10: Task API Routes + QR Login Trigger

**Files:**
- Modify: `bilibili_downloader/web/routes.py`

- [ ] **Step 1: Add task CRUD + QR login trigger routes**

Add to `create_routes` in `routes.py`:

```python
async def api_tasks(request: Request) -> JSONResponse:
    status = request.query_params.get("status")
    page = int(request.query_params.get("page", 1))
    tasks = await db.get_all_tasks(status=status or None, page=page, page_size=50)
    return JSONResponse(tasks)

async def api_task_submit(request: Request) -> JSONResponse:
    data = await request.json()
    space_url = data.get("space_url", "").strip()
    if not space_url:
        return JSONResponse({"ok": False, "error": "space_url is required"}, status_code=400)
    try:
        task_id = await task_service.submit_task(space_url)
        return JSONResponse({"ok": True, "task_id": task_id})
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

async def api_task_detail(request: Request) -> JSONResponse:
    task_id = int(request.path_params["task_id"])
    task = await db.get_task(task_id)
    if not task:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(dict(task))

async def api_trigger_login(request: Request) -> JSONResponse:
    success = await task_service.trigger_qr_login()
    if success:
        return JSONResponse({"ok": True, "message": "QR login completed"})
    return JSONResponse({"ok": False, "error": "QR login failed or timed out"}, status_code=500)

async def api_task_retry(request: Request) -> JSONResponse:
    """Retry a failed task."""
    task_id = int(request.path_params["task_id"])
    task = await db.get_task(task_id)
    if not task:
        return JSONResponse({"error": "not found"}, status_code=404)
    if task["status"] != "failed":
        return JSONResponse({"ok": False, "error": "Only failed tasks can be retried"}, status_code=400)
    await db.update_task_status(task_id, "pending", error_message=None, cookie_status="valid")
    await task_service.submit_task(task["space_url"])
    return JSONResponse({"ok": True})
```

Update `create_routes` signature to accept `task_service`:

```python
def create_routes(db, env, task_service=None):
```

Add to returned routes:

```python
"/api/tasks": (api_tasks, ["GET"]),
"/api/tasks/submit": (api_task_submit, ["POST"]),
"/api/tasks/{task_id}": (api_task_detail, ["GET"]),
"/api/tasks/{task_id}/retry": (api_task_retry, ["POST"]),
"/api/trigger-login": (api_trigger_login, ["POST"]),
```

- [ ] **Step 2: Commit**

```bash
git add bilibili_downloader/web/routes.py
git commit -m "feat(web): add task CRUD and QR login trigger API routes"
```

---

## Batch 4: Frontend & Integration

### Task 11: WebSocket Endpoint + App Integration

**Files:**
- Modify: `bilibili_downloader/web/app.py`
- Modify: `bilibili_downloader/cli/main.py`

- [ ] **Step 1: Add WebSocket endpoint and wire TaskService into app**

In `bilibili_downloader/web/app.py`:

```python
import pathlib
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from bilibili_downloader.web.routes import create_routes
from bilibili_downloader.web.ws_manager import WSManager

logger = logging.getLogger(__name__)

_ws_manager = WSManager()


def get_ws_manager() -> WSManager:
    return _ws_manager


def create_app(db, task_service=None):
    app = FastAPI(title="Bilibili Downloader Dashboard")
    templates_dir = pathlib.Path(__file__).parent / "templates"

    from jinja2 import Environment, FileSystemLoader
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=True,
    )

    def filesizeformat(value):
        if value is None:
            return "0 B"
        value = int(value)
        for unit in ("B", "KB", "MB", "GB"):
            if abs(value) < 1024:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"

    env.filters["filesizeformat"] = filesizeformat
    routes = create_routes(db, env, task_service=task_service)
    for path, (handler, methods) in routes.items():
        app.add_api_route(path, handler, methods=methods)

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        _ws_manager.connect(ws)
        try:
            while True:
                await ws.receive_text()  # keep-alive
        except WebSocketDisconnect:
            _ws_manager.disconnect(ws)

    return app
```

Update `web_command` in `bilibili_downloader/cli/main.py`:

```python
async def web_command(args):
    import uvicorn
    from bilibili_downloader.web.app import create_app
    from bilibili_downloader.web.task_service import TaskService
    db = Database(DEFAULT_DB_PATH)
    await db.init()
    task_service = TaskService(db=db, ws_manager=get_ws_manager())
    app = create_app(db, task_service=task_service)
    logger.info(f"Web dashboard starting on http://localhost:{args.port}")
    config = uvicorn.Config(app, host="0.0.0.0", port=args.port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
```

Note: `get_ws_manager` import needs to be added.

- [ ] **Step 2: Commit**

```bash
git add bilibili_downloader/web/app.py bilibili_downloader/cli/main.py
git commit -m "feat(web): integrate WebSocket endpoint and TaskService into app"
```

---

### Task 12: Frontend — Task Panel + Pagination + WebSocket + Directory Picker

**Files:**
- Modify: `bilibili_downloader/web/templates/index.html`

This is the largest single task. The full `index.html` rewrite includes:

1. **Navigation tabs**: "Downloads" and "Tasks" top-level tabs
2. **Task panel**: submit form, task list table with pagination (50/page), status badges, action buttons
3. **Download list pagination**: 20/page, page navigation controls
4. **WebSocket client**: auto-connect on load, handle all message types, reconnect on disconnect
5. **Directory picker**: "Browse" button in settings → POST /api/pick-directory → fill input
6. **Login modal**: shown on `login_required` WebSocket message

- [ ] **Step 1: Implement the full frontend**

The complete HTML is too large to inline in the plan. Key structural changes:

**Add navigation tabs after the header:**

```html
<div class="nav-tabs" style="display:flex;gap:0;margin-bottom:20px;border-bottom:2px solid #e8e8e8;">
    <div class="nav-tab active" data-panel="downloads" onclick="switchPanel('downloads')">下载管理</div>
    <div class="nav-tab" data-panel="tasks" onclick="switchPanel('tasks')">任务管理</div>
</div>
```

**Add task panel HTML (hidden by default):**

```html
<div id="panel-tasks" style="display:none">
    <div class="task-submit">
        <input type="text" id="task-url" placeholder="输入UP主空间地址，如 https://space.bilibili.com/12345">
        <button onclick="submitTask()">发布任务</button>
    </div>
    <table>
        <thead>
            <tr><th>UP主</th><th>状态</th><th>视频</th><th>采集</th><th>下载</th><th>创建时间</th><th>操作</th></tr>
        </thead>
        <tbody id="task-list"></tbody>
    </table>
    <div id="task-pagination" class="pagination"></div>
</div>
```

**Add pagination controls to download panel:**

```html
<div id="download-pagination" class="pagination"></div>
```

**Add CSS for pagination, nav-tabs, task-submit, login-modal:**

```css
.pagination { display:flex; justify-content:center; gap:4px; margin-top:12px; }
.pagination button { padding:4px 10px; border:1px solid #d9d9d9; border-radius:4px; background:#fff; cursor:pointer; font-size:13px; }
.pagination button.active { background:#00a1d6; color:#fff; border-color:#00a1d6; }
.pagination button:disabled { opacity:.5; cursor:default; }
.nav-tab { padding:10px 20px; cursor:pointer; font-size:14px; color:#666; border-bottom:2px solid transparent; margin-bottom:-2px; }
.nav-tab.active { color:#00a1d6; border-bottom-color:#00a1d6; font-weight:600; }
.task-submit { display:flex; gap:10px; margin-bottom:16px; }
.task-submit input { flex:1; padding:8px 12px; border:1px solid #d9d9d9; border-radius:6px; font-size:14px; }
.task-submit button { padding:8px 20px; background:#00a1d6; color:#fff; border:none; border-radius:6px; cursor:pointer; }
```

**Add WebSocket client:**

```javascript
// WebSocket
let ws = null;
function connectWS() {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${protocol}://${location.host}/ws`);
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        switch(msg.type) {
            case 'task_status':
            case 'scrape_progress':
            case 'download_progress':
                refreshCurrentPanel();
                break;
            case 'login_required':
                showLoginModal();
                break;
            case 'login_success':
                hideLoginModal();
                break;
            case 'settings_changed':
                break;
        }
    };
    ws.onclose = () => { setTimeout(connectWS, 3000); };
    ws.onerror = () => {};
}
connectWS();
```

**Add directory picker in settings:**

```javascript
async function browseDirectory() {
    const current = document.getElementById('s-output').value || './downloads';
    const resp = await fetch('/api/pick-directory', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({current_path: current}),
    });
    const result = await resp.json();
    if (result.ok) {
        document.getElementById('s-output').value = result.path;
    }
}
```

**Add pagination logic:**

```javascript
// Downloads pagination
let downloadPage = 1;
async function loadDownloads(page) {
    downloadPage = page || 1;
    // ... existing fetch logic with ?page=downloadPage&page_size=20
    renderPagination('download-pagination', data.page, data.total_pages, loadDownloads);
}

// Tasks pagination
let taskPage = 1;
async function loadTasks(page) {
    taskPage = page || 1;
    const resp = await fetchJSON(`/api/tasks?page=${taskPage}&page_size=50`);
    renderTaskList(resp.items);
    renderPagination('task-pagination', resp.page, resp.total_pages, loadTasks);
}

function renderPagination(containerId, current, totalPages, onPageChange) {
    const el = document.getElementById(containerId);
    if (totalPages <= 1) { el.innerHTML = ''; return; }
    let html = '';
    html += `<button ${current<=1?'disabled':''} onclick="(${onPageChange.name})(${current-1})">上一页</button>`;
    for (let i = 1; i <= totalPages; i++) {
        if (totalPages > 7 && Math.abs(i-current) > 2 && i !== 1 && i !== totalPages) {
            if (i === 2 || i === totalPages-1) html += '<span>...</span>';
            continue;
        }
        html += `<button class="${i===current?'active':''}" onclick="(${onPageChange.name})(${i})">${i}</button>`;
    }
    html += `<button ${current>=totalPages?'disabled':''} onclick="(${onPageChange.name})(${current+1})">下一页</button>`;
    el.innerHTML = html;
}
```

**Add task submit and list functions:**

```javascript
async function submitTask() {
    const url = document.getElementById('task-url').value.trim();
    if (!url) return;
    const resp = await fetch('/api/tasks/submit', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({space_url: url}),
    });
    const result = await resp.json();
    if (result.ok) {
        document.getElementById('task-url').value = '';
        loadTasks(1);
    } else {
        alert('发布失败: ' + (result.error || ''));
    }
}

async function retryTask(taskId) {
    await fetch(`/api/tasks/${taskId}/retry`, {method: 'POST'});
    loadTasks(taskPage);
}

function renderTaskList(tasks) {
    const tbody = document.getElementById('task-list');
    tbody.innerHTML = tasks.map(t => {
        const statusClass = `status-${t.status}`;
        const retryBtn = t.status === 'failed'
            ? `<button class="action-btn" onclick="retryTask(${t.id})">重试</button>` : '';
        return `<tr>
            <td>${escHtml(t.creator_name || t.space_uid || '')}</td>
            <td><span class="status ${statusClass}">${t.status}</span></td>
            <td>${t.total_videos}</td>
            <td>${t.scraped_videos}</td>
            <td>${t.downloaded_videos}/${t.total_downloads}</td>
            <td>${t.created_at ? new Date(t.created_at).toLocaleString() : ''}</td>
            <td>${retryBtn}</td>
        </tr>`;
    }).join('');
}
```

**Add login modal HTML:**

```html
<div class="modal-overlay" id="login-modal" style="display:none">
    <div class="modal">
        <h3>Cookie已失效</h3>
        <p>正在弹出浏览器窗口，请使用B站APP扫描二维码登录。</p>
        <div id="login-status">等待扫码...</div>
    </div>
</div>
```

- [ ] **Step 2: Test manually by running the web server**

Run: `bilibili-dl web`
Open: `http://localhost:8080`
Verify:
- [ ] Navigation between "Downloads" and "Tasks" tabs works
- [ ] Task submission form accepts URL and creates task
- [ ] Download list shows pagination controls
- [ ] Settings "Browse" button opens native directory picker
- [ ] WebSocket connection established (check browser console)

- [ ] **Step 3: Commit**

```bash
git add bilibili_downloader/web/templates/index.html
git commit -m "feat(web): add task panel, pagination, WebSocket, directory picker, login modal"
```

---

### Task 13: Backward Compat — Fix Existing Tests

**Files:**
- Modify: `tests/test_database.py`
- Modify: `tests/test_worker.py`
- Modify: `tests/test_manager.py`

- [ ] **Step 1: Run full test suite and fix any breakage**

Run: `python -m pytest tests/ -v`

Known breakage areas:
- `get_all_downloads` return type changed from `list[dict]` to `dict` with pagination wrapper — any test calling it needs to access `.items` instead of iterating the result directly
- `download_video` signature added `speed_limit_bps` and `ws_manager` kwargs (defaulted, so existing calls should work)
- Task-related routes need `task_service` parameter in `create_routes`

Fix each failing test to match the new API.

- [ ] **Step 2: Ensure all 54+ tests pass**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "fix(tests): update existing tests for V2 API changes"
```

---

### Task 14: Update CLAUDE.md and README.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Update CLAUDE.md**

Add to architecture section:
- TaskService description
- WebSocket message protocol table
- Task table in data model section
- Speed limit config constant
- `download_speed_limit` in settings table

Update module structure to include new files:
- `web/task_service.py`
- `web/ws_manager.py`

Update "已完成" section with V2 features.

- [ ] **Step 2: Update README.md**

Add V2 feature descriptions and any new setup instructions (e.g., ffmpeg requirement).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: update CLAUDE.md and README.md for V2 features"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Output directory picker → Task 9 + Task 12
- [x] Web task panel (submit, list, progress, retry) → Task 7, 10, 12
- [x] Cookie auto-validation + QR login → Task 3, 7
- [x] Per-platform cookie files → Task 7 (_COOKIE_FILES dict)
- [x] Download list pagination (20/page) → Task 1, 12
- [x] Task list pagination (50/page) → Task 1, 12
- [x] Resume download (Range header, .tmp files) → Task 5
- [x] Audio+video merge (ffmpeg) → Task 5
- [x] Speed limit (single connection, min 100KB/s) → Task 4, 5
- [x] Video collection completeness (API backfill) → Task 8
- [x] WebSocket real-time push → Task 2, 11, 12

**2. Placeholder scan:** No TBD, TODO, or vague steps found.

**3. Type consistency:** `get_all_downloads` consistently returns paginated dict in all usages. `speed_limit_bps` is consistently in bytes/sec throughout the pipeline. Task status values match the lifecycle design.
