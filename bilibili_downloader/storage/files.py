import re
from pathlib import Path

from bilibili_downloader.config import DEFAULT_NAME_TEMPLATE

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_ILLEGAL_TRAILING = re.compile(r'[.\s]+$')


def sanitize_filename(name: str) -> str:
    """Remove characters that are illegal in filenames on Windows/Linux/macOS."""
    name = _ILLEGAL_CHARS.sub("", name)
    name = _ILLEGAL_TRAILING.sub("", name)
    return name.strip()


def build_filename(
    title: str,
    creator: str,
    section: str | None,
    bvid: str = "",
    ext: str = "mp4",
    template: str | None = None,
) -> str:
    """Build a filename from metadata fields using the given template.

    When section is None, the template's ``{section}`` placeholder is replaced
    with an empty string and the hyphen dangling inside the bracket decoration
    (if any) is cleaned up.

    bvid is appended as suffix when present to prevent filename collisions.
    """
    template = template or DEFAULT_NAME_TEMPLATE
    title = sanitize_filename(title)
    creator = sanitize_filename(creator)

    if section:
        section = sanitize_filename(section)
        filename = template.format(title=title, creator=creator, section=section)
    else:
        filename = template.format(title=title, creator=creator, section="")
        filename = filename.replace("-】", "】")

    if bvid:
        filename = f"{filename}_{bvid}"

    return f"{filename}.{ext}"


def resolve_save_path(output_dir: str, filename: str) -> str:
    """Return the absolute path for *filename* under *output_dir*."""
    path = Path(output_dir) / filename
    return str(path.resolve())
