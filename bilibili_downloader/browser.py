import json
import logging
import os

from bilibili_downloader.config import USER_AGENT

logger = logging.getLogger(__name__)

BILIBILI_COOKIE_DOMAIN = ".bilibili.com"


def build_cookies_from_env() -> list[dict]:
    """从环境变量构建B站 cookies。"""
    sessdata = os.environ.get("BILIBILI_SESSDATA", "")
    bili_jct = os.environ.get("BILIBILI_BILI_JCT", "")
    cookies = []
    if sessdata:
        cookies.append({
            "name": "SESSDATA",
            "value": sessdata,
            "domain": BILIBILI_COOKIE_DOMAIN,
            "path": "/",
        })
    if bili_jct:
        cookies.append({
            "name": "bili_jct",
            "value": bili_jct,
            "domain": BILIBILI_COOKIE_DOMAIN,
            "path": "/",
        })
    return cookies


def load_cookies_from_file(path: str) -> list[dict] | None:
    """从本地 JSON 文件加载缓存的 cookies。"""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return None
        logger.info(f"从缓存加载了 {len(data)} 个 cookies: {path}")
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"cookie 缓存文件读取失败: {e}")
        return None


def save_cookies_to_file(cookies: list[dict], path: str):
    """将 cookies 保存到本地 JSON 缓存文件。"""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    logger.info(f"已保存 {len(cookies)} 个 cookies 到缓存: {path}")


class PlaywrightBrowser:
    """管理 Playwright Chromium 浏览器实例的生命周期。

    用法:
        browser = PlaywrightBrowser()
        await browser.start()
        # 使用 browser.page 进行页面操作
        await browser.close()
    """

    def __init__(self, headless: bool = True, cookies: list[dict] | None = None):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._headless = headless
        self._cookies = cookies

    async def start(self):
        """启动浏览器，创建上下文和页面，导航到 bilibili.com 建立会话。"""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
        )

        # 注入 cookies（如果提供）
        cookies_to_add = self._cookies or build_cookies_from_env()
        if cookies_to_add:
            await self._context.add_cookies(cookies_to_add)
            logger.info(f"已注入 {len(cookies_to_add)} 个 cookies")

        self._page = await self._context.new_page()
        await self._page.goto(
            "https://www.bilibili.com",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        await self._page.wait_for_timeout(3000)
        logger.info("浏览器已启动并导航到 bilibili.com")

    @property
    def page(self):
        """当前 Playwright Page 实例。"""
        if self._page is None:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        return self._page

    async def get_context_cookies(self) -> list[dict]:
        """获取当前浏览器上下文的所有 cookies。"""
        if self._context is None:
            raise RuntimeError("浏览器未启动")
        return await self._context.cookies()

    async def close(self):
        """关闭浏览器并释放所有资源。"""
        if self._page:
            await self._page.close()
            self._page = None
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("浏览器已关闭")
