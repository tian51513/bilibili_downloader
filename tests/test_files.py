import pytest
from pathlib import Path


class TestFileName:
    def test_default_template_with_section(self):
        from platform_video_downloader.storage.files import build_filename
        result = build_filename(
            title="这是什么神仙颜值啊？？？", creator="颜值回忆录", section="流行", ext="mp4"
        )
        assert result == "这是什么神仙颜值啊？？？【颜值回忆录-流行】.mp4"

    def test_default_template_without_section(self):
        from platform_video_downloader.storage.files import build_filename
        result = build_filename(title="独立视频", creator="某UP主", section=None, ext="mp4")
        assert result == "独立视频【某UP主】.mp4"

    def test_custom_template(self):
        from platform_video_downloader.storage.files import build_filename
        result = build_filename(title="V", creator="C", section="S", ext="mp4", template="{creator}_{section}_{title}")
        assert result == "C_S_V.mp4"

    def test_custom_template_no_section(self):
        from platform_video_downloader.storage.files import build_filename
        result = build_filename(title="V", creator="C", section=None, ext="mp4", template="{creator}_{title}")
        assert result == "C_V.mp4"

    def test_sanitize_filename(self):
        from platform_video_downloader.storage.files import build_filename
        result = build_filename(title='file/with<bad>|chars', creator="UP", section=None, ext="mp4")
        assert "/" not in result
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result
        assert result.endswith(".mp4")


class TestResolveSavePath:
    def test_resolve_basic(self, tmp_path):
        from platform_video_downloader.storage.files import resolve_save_path
        result = resolve_save_path(str(tmp_path), "video.mp4")
        assert result == str(tmp_path / "video.mp4")

    def test_resolve_creates_parent(self, tmp_path):
        from platform_video_downloader.storage.files import resolve_save_path
        result = resolve_save_path(str(tmp_path), "subdir/video.mp4")
        assert result == str(tmp_path / "subdir" / "video.mp4")
