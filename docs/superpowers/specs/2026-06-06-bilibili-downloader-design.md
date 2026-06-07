# Bilibili Downloader V2 Design Spec

## 概述

B站UP主视频批量下载器。Playwright 浏览器采集数据（绕过反爬），aiohttp 异步高并发下载视频流。自动扫码登录，Web 仪表盘实时监控。支持双流下载、断点续传、限速下载、视频播放等V2功能。

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python 3.11+ |
| 数据采集 | Playwright (Chromium headless browser) |
| 异步框架 | asyncio + aiohttp |
| Web框架 | FastAPI + Jinja2 + Uvicorn |
| 数据库 | SQLite (aiosqlite) |
| 实时通信 | WebSocket |
| CLI解析 | argparse |
| 包管理 | pip / pyproject.toml |

## 架构：两阶段分离 + Web后台服务

```
CLI入口 → Phase1: Playwright采集 → Phase2: aiohttp下载
         ↓                              ↓
    BilibiliScraper              DownloadManager → Worker池
    (on_response被动读取)         (信号量并发控制)
         ↓                              ↓
    关闭浏览器释放资源           双流下载 + ffmpeg合并
                                        ↓
Web仪表盘(FastAPI) ←── WebSocket ←── Worker广播状态
     ↓
TaskService(后台任务运行器)
  ├── 采集队列(串行)
  ├── API补全(WBI签名)
  └── 下载调度(共享DownloadManager)
```

单进程同时运行FastAPI和下载任务，共享asyncio事件循环和WebSocket连接。

## 模块划分

```
bilibili_downloader/
├── cli/                    # CLI入口与命令解析
│   └── main.py             # argparse命令行入口 + Cookie解析 + QR登录
├── core/                   # 核心下载引擎
│   ├── manager.py          # DownloadManager - 任务调度、队列管理、并发控制
│   ├── worker.py           # download_video - 单视频下载（双流+合并+续传+限速+WS广播）
│   └── retry.py            # retry_async - 指数退避重试
├── bilibili/               # B站API交互层
│   ├── api.py              # BilibiliAPI - 流URL获取 + 视频详情 + API补全 + Cookie验证
│   ├── parser.py           # 纯函数 - 响应解析（空间信息/视频列表(含tag)/合集/DASH流）
│   ├── scraper.py          # BilibiliScraper - Playwright on_response被动采集
│   └── wbi.py              # WBI签名鉴权（arc/search API补全）
├── storage/                # 存储层
│   ├── database.py         # Database - SQLite异步CRUD（五表 + 分页 + 任务状态同步）
│   └── files.py            # 文件命名模板 + 路径解析 + 非法字符过滤（含bvid防重名）
├── web/                    # Web仪表盘
│   ├── app.py              # FastAPI应用工厂 + Jinja2 Environment
│   ├── routes.py           # REST API（30+端点）
│   ├── task_service.py     # TaskService - 后台任务运行（采集队列+API补全+下载调度）
│   ├── ws_manager.py       # WSManager - WebSocket连接管理与广播
│   └── templates/
│       └── index.html      # 仪表盘（任务+下载+播放+设置）
├── browser.py              # PlaywrightBrowser - 浏览器生命周期管理 + Cookie文件I/O
├── config.py               # 全局配置 + 设置持久化（JSON）
└── main.py                 # 程序入口（委托cli.main）
```

## 数据模型

### platform 表

```sql
CREATE TABLE platform (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    base_url    TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### creator 表

```sql
CREATE TABLE creator (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id INTEGER NOT NULL REFERENCES platform(id),
    remote_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    avatar_url  TEXT,
    space_url   TEXT NOT NULL,
    last_sync   DATETIME,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(platform_id, remote_id)
);
```

### video 表

```sql
CREATE TABLE video (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id  INTEGER NOT NULL REFERENCES creator(id),
    remote_id   TEXT NOT NULL,
    title       TEXT NOT NULL,
    duration    INTEGER,
    pubdate     DATETIME,
    extra       TEXT,                           -- JSON: 平台特有字段
    tags        TEXT,                           -- JSON: 标签数组 ["标签1","标签2"]
    section_id  TEXT,
    section_name TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(creator_id, remote_id)
);
```

### download 表

```sql
CREATE TABLE download (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    INTEGER NOT NULL REFERENCES video(id),
    save_path   TEXT NOT NULL,
    resolution  TEXT NOT NULL,
    file_size   INTEGER,
    status      TEXT NOT NULL DEFAULT 'pending',
    error_msg   TEXT,
    started_at  DATETIME,
    finished_at DATETIME,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(video_id, resolution)
);
```

status 状态机: `pending → downloading → merging → completed / skipped / failed`

### task 表（V2新增）

```sql
CREATE TABLE task (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    space_url       TEXT NOT NULL,
    space_uid       TEXT,
    creator_id      INTEGER,
    status          TEXT NOT NULL DEFAULT 'init',
    total_videos    INTEGER DEFAULT 0,
    scraped_videos  INTEGER DEFAULT 0,
    downloaded_videos INTEGER DEFAULT 0,
    total_downloads INTEGER DEFAULT 0,
    error_message   TEXT,
    cookie_status   TEXT DEFAULT 'unknown',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

task status 状态机: `init → scraping → pending → downloading → completed / failed / paused`

## 数据采集

### Playwright 被动采集

B站API对非浏览器流量返回反爬错误（-352, -799, 412）。解决方案：
- Playwright 打开真实 Chromium，导航到UP主空间页面
- 通过 `page.on('response')` 被动读取所有API响应（不拦截不干扰页面）
- 页面JS自动处理WBI签名
- 滚动触发分页加载，去重bvid计数避免重叠

### API 补全（V2新增）

滚动采集可能遗漏视频。采集后使用 WBI 签名的 arc/search API 主动分页获取：
- `wbi.py` 实现 mixin_key 计算 + 签名参数生成
- `api.py` 的 `fetch_videos_by_api` 主动分页获取视频列表
- 与采集结果去重后合并

### Cookie机制（4级优先级）

```
CLI参数 (--cookie) → 环境变量 (BILIBILI_SESSDATA) → 缓存文件 → 扫码登录
```

- 缓存文件按平台区分
- `--no-cache` 强制重新扫码
- Web仪表盘支持Cookie状态检测和QR扫码登录

## 下载引擎

### 并发控制

```python
MAX_CONCURRENT_DOWNLOADS = 5      # 同时下载视频数
MAX_CONCURRENT_API_REQUESTS = 10   # 同时API请求数
DOWNLOAD_RETRY_COUNT = 3
RETRY_BACKOFF_BASE = 2            # 秒
REQUEST_TIMEOUT = 30
DEFAULT_RESOLUTION_PRIORITY = ['720p', '480p', '1080p', '240p']
MIN_SPEED_LIMIT_KB = 100          # 最低限速 KB/s
DEFAULT_SPEED_LIMIT_MB = 0.0      # 默认限速（0=不限）
```

### 双流下载 + 合并（V2新增）

1. API获取视频流URL（`/x/player/playurl`，无需WBI签名）
2. 同时下载视频流和音频流（两个独立aiohttp请求）
3. 下载完成后调用 ffmpeg 合并音视频
4. 合并状态: `downloading → merging → completed`
5. 合并后删除临时音视频文件

### 断点续传（V2新增）

- 下载前检查本地文件大小
- 使用 Range 请求头从断点继续下载
- 网络中断后自动恢复，无需从头下载
- 文件大小精确匹配，避免重复下载

### 下载限速（V2新增）

- 单连接速度限制，通过设置项控制
- 默认不限速（`download_speed_limit = 0`）
- 最低限速 100KB/s
- 基于写入间隔的令牌桶实现

### 下载流程

1. API获取视频流URL列表（受 `api_semaphore` 限制）
2. 按优先级选择分辨率
3. 判断可下载性（需充值 → skipped，异常 → failed重试）
4. 双流下载边写磁盘（受 `download_semaphore` 限制）
5. ffmpeg合并音视频
6. 应用命名模板保存文件（含bvid防重名）
7. 更新SQLite状态 + WebSocket广播

### 重试策略

- 指数退避：2s → 4s → 8s
- 网络超时 → 重试
- HTTP 403/404 → 直接标记failed
- 需充值 → 直接标记skipped
- 磁盘写入失败 → 重试，空间不足则failed

### 进度上报

Worker在每个状态变更点通过WebSocket广播，UI实时更新（无轮询）：

```json
{"type": "download_progress", "download_id": 123, "status": "downloading"}
{"type": "download_progress", "download_id": 123, "status": "merging"}
{"type": "download_progress", "download_id": 123, "status": "completed", "file_size": 10485760}
{"type": "download_progress", "download_id": 123, "status": "failed", "error": "timeout"}
```

## CLI 设计

```bash
bilibili-dl https://space.bilibili.com/33676449 -o E:\Video
bilibili-dl https://space.bilibili.com/33676449 https://space.bilibili.com/123456
bilibili-dl https://space.bilibili.com/33676449 -r 1080p
bilibili-dl https://space.bilibili.com/33676449 -n 10
bilibili-dl https://space.bilibili.com/33676449 --dry-run
bilibili-dl https://space.bilibili.com/33676449 --force
bilibili-dl https://space.bilibili.com/33676449 --no-cache
bilibili-dl web --port 8080
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `URL...` | UP主空间地址 | 必填 |
| `-o/--output` | 保存目录 | `./downloads` |
| `-r/--resolution` | 目标分辨率 | 自动选择 |
| `-n/--concurrency` | 并发下载数 | `5` |
| `--dry-run` | 仅分析 | `False` |
| `--force` | 忽略已下载 | `False` |
| `--name-template` | 文件命名模板 | `{title}【{creator}-{section}】` |
| `--headed` | 显示浏览器窗口 | `False` |
| `--no-cache` | 强制重新登录 | `False` |
| `--cookie NAME=VALUE` | B站Cookie | - |
| `web` | 启动仪表盘 | - |
| `--port` | Web端口 | `8080` |

## Web 仪表盘

### REST API（30+端点）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 仪表盘页面 |
| `/ws` | WS | WebSocket实时推送 |
| `/api/stats` | GET | 统计数据 |
| `/api/downloads` | GET | 下载列表（分页+筛选） |
| `/api/downloads/clear` | POST | 清空下载记录 |
| `/api/downloads/start` | POST | 开始下载 |
| `/api/downloads/pause` | POST | 暂停下载 |
| `/api/downloads/batch-start` | POST | 批量下载选中 |
| `/api/downloads/status` | GET | 下载运行状态 |
| `/api/downloads/{id}` | GET | 下载详情 |
| `/api/downloads/{id}/play` | GET | 视频播放 |
| `/api/downloads/{id}/retry` | POST | 重试单个 |
| `/api/downloads/{id}/delete` | DELETE | 删除记录 |
| `/api/creators` | GET | UP主列表 |
| `/api/tags` | GET | 标签列表 |
| `/api/sections` | GET | 合集列表 |
| `/api/settings` | GET/POST | 获取/保存设置 |
| `/api/pick-directory` | POST | 原生目录选择器 |
| `/api/directories` | POST | 列出子目录 |
| `/api/tasks` | GET | 任务列表 |
| `/api/tasks/submit` | POST | 提交任务 |
| `/api/tasks/{id}` | GET | 任务详情 |
| `/api/tasks/{id}/retry` | POST | 重试任务 |
| `/api/tasks/{id}/force` | POST | 强制重抓 |
| `/api/tasks/{id}/pause` | POST | 暂停任务 |
| `/api/tasks/{id}/resume` | POST | 恢复任务 |
| `/api/tasks/{id}/reset-downloads` | POST | 重置下载 |
| `/api/tasks/{id}/url` | POST | 修改URL |
| `/api/tasks/{id}/delete` | POST | 删除任务 |
| `/api/cookie/status` | GET | Cookie状态 |
| `/api/cookie/clear` | POST | 清除Cookie |
| `/api/trigger-login` | POST | 触发扫码登录 |

### 任务管理面板（V2新增）

- 多行提交空间地址（每行一个UP主）
- 任务列表显示：UP主名称、空间视频总数/抓取数、已下载数、文件总大小、状态
- 操作按钮：重试、强制重抓、暂停/恢复、重置下载、修改URL、删除
- 状态机: `init → scraping → pending → downloading → completed/failed/paused`

### 下载管理面板

- 分页显示（20条/页）
- 复选框多选 + 全选
- 单个/批量下载
- 状态Tab页切换
- UP主下拉筛选 + 标签多选筛选（OR关系）
- 标签模糊搜索 + 全选/反选/清除
- 视频标题可点击跳转B站
- 进度条实时显示
- 合并状态显示（merging）

### 视频播放器（V2新增）

- 弹窗播放已下载视频
- 动态播放列表（基于当前筛选条件）
- 上一个/下一个切换
- 自动播放 + 自动连播
- 当前索引/总视频显示

### Cookie管理（V2新增）

- 自动检测Cookie有效性
- 失效时弹出headed浏览器QR扫码登录（120秒超时）
- Web面板显示登录用户名

### WebSocket实时推送（V2新增）

消息类型：
- `task_status` — 任务状态变更
- `scrape_progress` — 采集进度
- `download_progress` — 下载进度/状态变更
- `login_required` — 需要扫码登录
- `login_success` — 登录成功

UI通过WebSocket驱动更新，无轮询定时器。

### 设置面板

| 设置项 | 说明 | 默认值 |
|--------|------|--------|
| max_concurrent_downloads | 并发下载数 | 5 |
| max_concurrent_api | API并发数 | 10 |
| resolution_priority | 分辨率优先级 | 720p,480p,1080p,240p |
| name_template | 文件命名模板 | {title}【{creator}-{section}】 |
| output_dir | 输出目录 | ./downloads |
| web_port | Web端口 | 8080 |
| download_speed_limit | 下载限速 MB/s | 0 |

设置持久化到 `bilibili_settings.json`。

### 日间/夜间双主题

CSS变量驱动，统一按钮系统（`.btn` + 修饰符），全页面主题适配。

## 文件命名

```
模板: {title}【{creator}-{section}】_{bvid}.mp4
无合集: {title}【{creator}】_{bvid}.mp4
示例: 这是什么神仙颜值啊？？？【颜值回忆录-流行】_BV1xx.mp4
```

bvid后缀防止同名覆盖。可用变量: `{title}`, `{creator}`, `{section}`, `{bvid}`。

## 平台扩展

扩展新平台只需：
1. `platform` 表插入记录
2. 新增平台API模块（如 `youtube/api.py`）
3. 实现统一接口协议：获取创作者信息、视频列表、下载链接
