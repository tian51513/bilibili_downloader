import pytest


@pytest.fixture
async def db(tmp_path):
    db_path = tmp_path / "test.db"
    from platform_video_downloader.storage.database import Database

    database = Database(str(db_path))
    await database.init()
    yield database
    await database.close()
