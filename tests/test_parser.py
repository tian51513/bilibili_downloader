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
        assert videos[0]["duration"] == 225
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
                        {"id": 30280, "bandwidth": 500000, "baseUrl": "http://a/audio"}
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
                        {"id": 30280, "bandwidth": 500000, "baseUrl": "http://a/audio"}
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
                        {"id": 30280, "bandwidth": 500000, "baseUrl": "http://a/audio"}
                    ],
                }
            }
        }
        urls = parse_stream_urls(data, priority=["720p"])
        assert urls["resolution"] == "720p"
