_QID_TO_LABEL = {
    16: "360p",
    32: "240p",
    64: "480p",
    80: "720p",
    112: "1080p",
    116: "1080p60",
    120: "4k",
}
_LABEL_TO_QID = {v: k for k, v in _QID_TO_LABEL.items()}


def parse_space_info(raw: dict) -> dict:
    d = raw.get("data")
    if not d or "mid" not in d:
        code = raw.get("code", "unknown")
        msg = raw.get("message", "unknown error")
        raise ValueError(f"Invalid space info response: code={code}, message={msg}")
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
        # tag 字段是逗号分隔的字符串，如 "可爱,纯欲,甜妹"
        tag_str = v.get("tag", "")
        tags = [t.strip() for t in tag_str.split(",") if t.strip()] if tag_str else []
        videos.append(
            {
                "remote_id": v["bvid"],
                "title": v["title"],
                "duration": duration,
                "pubdate": v.get("created"),
                "extra": {"cid": v.get("cid"), "aid": v.get("aid")},
                "tags": tags,
            }
        )
    return videos


def parse_sections(raw: dict) -> list[dict]:
    sections_raw = raw.get("data", {}).get("sections", [])
    result = []
    for sec in sections_raw:
        sid = str(sec["id"])
        sname = sec["title"]
        for ep in sec.get("episodes", []):
            result.append(
                {
                    "remote_id": ep["bvid"],
                    "section_id": sid,
                    "section_name": sname,
                }
            )
    return result


def parse_stream_urls(raw: dict, priority: list[str] | None = None) -> dict:
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
        selected = max(videos, key=lambda x: x.get("bandwidth", 0))
        selected_label = _QID_TO_LABEL.get(selected["id"], f"qid_{selected['id']}")

    audio_url = audios[0]["baseUrl"] if audios else None

    return {
        "video_url": selected["baseUrl"],
        "audio_url": audio_url,
        "resolution": selected_label,
    }
