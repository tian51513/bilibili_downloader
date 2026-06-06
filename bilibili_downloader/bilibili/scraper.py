"""B站数据爬虫模块，通过 Playwright 响应拦截获取数据。

导航到UP主空间页面，拦截页面JS发出的API响应。
页面自己的JavaScript会正确处理WBI签名，我们只需被动读取响应数据。

策略：不拦截 arc/search 请求（避免 route.fetch 重复请求被B站拒绝），
仅通过 on_response 读取页面JS已接收的响应。页面JS自行处理分页加载。
"""

import json
import logging

import aiohttp

from bilibili_downloader.bilibili.parser import (
    parse_sections,
    parse_space_info,
    parse_video_list,
)

logger = logging.getLogger(__name__)


class BilibiliScraper:
    """通过 Playwright 响应拦截抓取B站数据。

    导航到UP主空间页面，被动读取页面JS发出的API响应。
    """

    def __init__(self, browser):
        self._browser = browser
        self._collected: dict[str, dict] = {}

    async def collect(self, mid: str) -> dict:
        """采集一个UP主的全部数据（空间信息 + 视频列表 + 合集）。

        Returns:
            {'space_info': dict | None, 'videos': list[dict], 'sections': list[dict]}
        """
        if mid in self._collected:
            return self._collected[mid]

        page = self._browser.page
        space_info_raw = None
        video_responses: list[dict] = []
        section_raw = None
        video_error_code = None
        video_error_msg = None

        async def on_response(response):
            nonlocal space_info_raw, section_raw, video_error_code, video_error_msg
            url = response.url
            try:
                if '/x/space/wbi/acc/info' in url and response.status == 200:
                    data = await response.json()
                    if data.get('code') == 0:
                        space_info_raw = data

                elif '/x/space/section/index' in url and response.status == 200:
                    try:
                        data = await response.json()
                        if data.get('code') == 0:
                            section_raw = data
                    except Exception:
                        pass

                elif '/arc/search' in url and 'mid' in url and response.status == 200:
                    try:
                        data = await response.json()
                        code = data.get('code', -1)
                        if code == 0:
                            video_responses.append(data)
                            vlist_len = len(data.get('data', {}).get('list', {}).get('vlist', []))
                            pn = data.get('data', {}).get('page', {}).get('pn', '?')
                            total = data.get('data', {}).get('page', {}).get('count', '?')
                            logger.debug(f"[response] arc/search pn={pn} vlist={vlist_len} total={total}")
                        else:
                            video_error_code = code
                            video_error_msg = data.get('message', '')
                            logger.warning(f"[response] arc/search error: code={code} msg={data.get('message')}")
                    except Exception as e:
                        logger.debug(f"[response] arc/search 解析失败: {e}")
            except Exception as e:
                logger.debug(f"响应处理异常: {url[:80]}... error={e}")

        # 只注册 on_response 监听器，不拦截请求
        page.on('response', on_response)
        try:
            await page.goto(
                f'https://space.bilibili.com/{mid}',
                wait_until='networkidle',
                timeout=30000,
            )

            # 检查是否触发了人机验证
            title = await page.title()
            if '验证' in title:
                raise ValueError("B站要求人机验证，请使用 --headed 模式手动完成验证后重试")

            # 等待初始数据加载
            await page.wait_for_timeout(3000)

            if not space_info_raw:
                logger.warning(f"未拦截到UP主信息: mid={mid}")

            # 用去重后的bvid计数
            def _deduped_count():
                bvids: set[str] = set()
                for r in video_responses:
                    for v in r.get('data', {}).get('list', {}).get('vlist', []):
                        bvids.add(v.get('bvid', ''))
                return len(bvids)

            # 计算总视频数
            total = 0
            for resp in video_responses:
                t = resp.get('data', {}).get('page', {}).get('count', 0)
                if t > total:
                    total = t

            loaded = _deduped_count()
            logger.info(f"初始加载: 去重后 {loaded}/{total}, 拦截到 {len(video_responses)} 个arc/search响应")

            if total > 0 and loaded < total:
                logger.info(f"滚动加载视频: 去重后 {loaded}/{total}")
                max_rounds = min((total // 10) + 20, 200)
                last_loaded = loaded
                stale_count = 0
                for round_num in range(max_rounds):
                    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await page.wait_for_timeout(2000)
                    loaded = _deduped_count()

                    if loaded == last_loaded:
                        stale_count += 1
                        if stale_count >= 5:
                            logger.info(f"滚动停止: 连续{stale_count}次无新视频，去重后 {loaded}/{total}")
                            break
                    else:
                        stale_count = 0
                        logger.info(f"滚动加载视频: 去重后 {loaded}/{total}, 响应数={len(video_responses)}")
                    last_loaded = loaded
                    if loaded >= total:
                        break

            if loaded < total:
                logger.warning(f"视频采集不完整: 去重后 {loaded}/{total}")
            else:
                logger.info(f"视频采集完成: 去重后 {loaded}/{total}")

            if not video_responses:
                if video_error_code == -403:
                    raise ValueError(
                        "视频列表接口返回 -403（账号权限不足）。"
                        "请提供B站登录 cookie：\n"
                        "  方式1: --cookie SESSDATA=你的SESSDATA\n"
                        "  方式2: 环境变量 BILIBILI_SESSDATA=你的SESSDATA\n"
                        "  方式3: 不提供cookie，程序会自动弹出浏览器扫码登录\n"
                        "如果cookie已过期，使用 --no-cache 重新登录"
                    )
                logger.warning(f"未拦截到视频列表: mid={mid}")
        finally:
            page.remove_listener('response', on_response)

        # 解析数据并去重
        seen_bvids: set[str] = set()
        videos: list[dict] = []
        for resp in video_responses:
            for v in parse_video_list(resp):
                if v['remote_id'] not in seen_bvids:
                    seen_bvids.add(v['remote_id'])
                    videos.append(v)

        # 将合集视频中尚未出现在投稿列表里的也加入
        sections = parse_sections(section_raw) if section_raw else []
        new_from_sections = 0
        for s in sections:
            if s['remote_id'] not in seen_bvids:
                videos.append({
                    'remote_id': s['remote_id'],
                    'title': f"合集视频 {s['remote_id']}",
                    'duration': 0,
                    'pubdate': None,
                    'extra': {},
                })
                seen_bvids.add(s['remote_id'])
                new_from_sections += 1

        if new_from_sections:
            logger.info(f"从合集补充 {new_from_sections} 个视频（标题待API补充）")

        result = {
            'space_info': parse_space_info(space_info_raw) if space_info_raw else None,
            'videos': videos,
            'sections': sections,
        }

        self._collected[mid] = result
        return result

    async def collect_with_backfill(self, mid: str, session=None, cookies=None) -> dict:
        """Collect data with API backfill for completeness."""
        result = await self.collect(mid)
        videos = result["videos"]

        if session and cookies:
            from bilibili_downloader.bilibili.api import BilibiliAPI

            api = BilibiliAPI(session, cookies=cookies)
            existing_bvids = {v["remote_id"] for v in videos}
            backfill_videos = await api.fetch_videos_by_api(mid, existing_bvids)
            if backfill_videos:
                for v in backfill_videos:
                    if v["remote_id"] not in existing_bvids:
                        videos.append(v)
                        existing_bvids.add(v["remote_id"])
                logger.info(f"API backfill added {len(backfill_videos)} videos, total now {len(videos)}")

        result["videos"] = videos
        return result
