"""B站 WBI 签名鉴权模块。

自2023年3月起，B站Web端部分接口采用WBI签名鉴权，
需要在请求参数中添加 w_rid 和 wts 字段。
参考 yutto 实现。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import random
import re
import string
import time
from urllib.parse import urlencode

import aiohttp

from platform_video_downloader.config import BILIBILI_API_BASE, USER_AGENT

logger = logging.getLogger(__name__)

# WBI 混淆映射表（重排 img_key + sub_key）
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

_ILLEGAL_CHAR_REMOVER = re.compile(r"[!'\(\)*]")

# dm_img_str 和 dm_cover_img_str 是 B站 Web 端请求时携带的反爬参数
_dm_img_str = base64.b64encode(
    "".join(random.choices(string.printable, k=random.randint(16, 64))).encode()
)[:-2].decode()
_dm_cover_img_str = base64.b64encode(
    "".join(random.choices(string.printable, k=random.randint(32, 128))).encode()
)[:-2].decode()


def _get_mixin_key(raw_key: str) -> str:
    """对 img_key + sub_key 进行字符顺序打乱编码，截取前32位。"""
    return "".join(raw_key[i] for i in _MIXIN_KEY_ENC_TAB)[:32]


def _extract_key(url: str) -> str:
    """从 wbi img_url / sub_url 中提取密钥（文件名去掉扩展名）。"""
    return url.split("/")[-1].split(".")[0]


def encode_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    """为请求参数计算WBI签名，返回添加了 w_rid 和 wts 的参数字典。

    参考 yutto 实现，包含 dm_img_list/dm_img_str/dm_cover_img_str 参数。
    """
    mixin_key = _get_mixin_key(img_key + sub_key)
    wts = str(int(time.time()))

    # 添加 wts 和 dm 参数
    all_params = {
        **params,
        "wts": wts,
        "dm_img_list": "[]",
        "dm_img_str": _dm_img_str,
        "dm_cover_img_str": _dm_cover_img_str,
    }

    # 按 key 排序，过滤非法字符
    filtered = {
        k: _ILLEGAL_CHAR_REMOVER.sub("", str(v))
        for k, v in sorted(all_params.items())
    }

    query = urlencode(filtered)
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()

    return dict(all_params, w_rid=w_rid)


async def get_wbi_keys(session: aiohttp.ClientSession) -> tuple[str, str]:
    """从 nav 接口获取最新的 img_key 和 sub_key。"""
    url = f"{BILIBILI_API_BASE}/x/web-interface/nav"
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"}
    async with session.get(url, headers=headers) as resp:
        resp.raise_for_status()
        data = await resp.json()
    img_url = data["data"]["wbi_img"]["img_url"]
    sub_url = data["data"]["wbi_img"]["sub_url"]
    return _extract_key(img_url), _extract_key(sub_url)


class WbiSigner:
    """WBI 签名器，缓存密钥并签名请求参数。"""

    def __init__(self, img_key: str, sub_key: str):
        self.img_key = img_key
        self.sub_key = sub_key

    def sign(self, params: dict) -> dict:
        """对参数字典进行WBI签名。"""
        return encode_wbi(dict(params), self.img_key, self.sub_key)

    @classmethod
    async def create(cls, session: aiohttp.ClientSession) -> WbiSigner:
        """从B站API获取密钥并创建签名器实例。

        使用传入的 session 获取密钥，确保 cookie 上下文一致。
        """
        img_key, sub_key = await get_wbi_keys(session)
        logger.debug(f"WBI keys acquired: img_key={img_key[:8]}..., sub_key={sub_key[:8]}...")
        return cls(img_key, sub_key)
