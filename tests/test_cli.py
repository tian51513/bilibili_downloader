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
        args = parse_args(["https://space.bilibili.com/33676449", "https://space.bilibili.com/123456"])
        assert len(args.urls) == 2

    def test_parse_output_dir(self):
        from bilibili_downloader.cli.main import parse_args
        args = parse_args(["https://space.bilibili.com/33676449", "-o", r"E:\映畫\B"])
        assert args.output == r"E:\映畫\B"

    def test_parse_resolution(self):
        from bilibili_downloader.cli.main import parse_args
        args = parse_args(["https://space.bilibili.com/33676449", "-r", "1080p"])
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
