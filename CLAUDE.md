# Bilibili Downloader - Claude Code 项目上下文

## 项目概述

B站UP主视频批量下载器，CLI + 轻量Web仪表盘双模式。Python asyncio异步高并发下载，SQLite本地状态追踪，多平台可扩展架构。

## 技术栈

- **语言**: Python 3.11+（开发环境 3.12）
- **异步框架**: asyncio + aiohttp
- **Web框架**: FastAPI + Jinja2 + Uvicorn
- **数据库**: SQLite（aiosqlite 异步驱动）
- **CLI**: argparse（入口 `bilibili-dl`）
- **构建**: setuptools + pyproject.toml
- **测试**: pytest + pytest-asyncio（asyncio_mode=auto）
- **包管理**: uv（虚拟环境 `.venv/`）

## 架构

单进程分层架构，FastAPI与下载Worker共享asyncio事件循环：

```
CLI入口 (cli/main.py)
    ↓
download_command: 获取UP主信息 → 同步视频列表 → 构建下载队列 → 启动DownloadManager
    ↓
DownloadManager (core/manager.py): 信号量控制并发 → asyncio.gather调度Worker池
    ↓
DownloadWorker (core/worker.py): 获取流URL(retry_async) → 流式下载 → 更新SQLite状态
    ↑
Web仪表盘 (web/): 轮询SQLite → Jinja2渲染统计+任务列表（只读监控，3秒自动刷新）
```

## 模块结构

```
bilibili_downloader/
├── config.py          # 全局配置常量（并发数、超时、分辨率优先级、命名模板、API地址）
├── main.py            # 程序入口（委托cli.main）
├── storage/
│   ├── database.py    # Database类 — SQLite异步CRUD（platform/creator/video/download四表）
│   └── files.py       # 文件命名模板 + 路径解析 + 非法字符过滤
├── bilibili/
│   ├── api.py         # BilibiliAPI类 — B站公开API异步封装
│   └── parser.py      # 纯函数 — 解析API响应（空间信息/视频列表/合集/DASH流）
├── core/
│   ├── manager.py     # DownloadManager类 — 队列构建、Worker池调度、并发信号量
│   ├── worker.py      # download_video协程 — 单视频下载全流程 + 状态更新
│   └── retry.py       # retry_async — 指数退避重试，自动识别永久错误
├── cli/
│   └── main.py        # argparse命令解析 + download/web子命令 + main()入口
└── web/
    ├── app.py          # FastAPI应用工厂 + Jinja2 filesizeformat过滤器
    ├── routes.py       # 4个路由（/ + /api/stats + /api/downloads + /api/downloads/{id}）
    └── templates/
        └── index.html  # 仪表盘HTML（统计卡片 + 下载列表 + 3秒自动刷新）
```

## 数据模型

- **platform** — 视频平台（bilibili、youtube...），支持多平台扩展
- **creator** — 创作者，UNIQUE(platform_id, remote_id)
- **video** — 视频，UNIQUE(creator_id, remote_id)，extra字段存平台特有数据JSON
- **download** — 下载记录，UNIQUE(video_id, resolution)，状态机: pending → downloading → completed/skipped/failed

## 关键配置 (config.py)

| 常量 | 默认值 | 说明 |
|------|--------|------|
| MAX_CONCURRENT_DOWNLOADS | 5 | 同时下载视频数 |
| MAX_CONCURRENT_API_REQUESTS | 10 | 同时API请求数 |
| DOWNLOAD_RETRY_COUNT | 3 | 下载重试次数 |
| RETRY_BACKOFF_BASE | 2 | 重试退避基数(秒) |
| REQUEST_TIMEOUT | 30 | 请求超时(秒) |
| DEFAULT_RESOLUTION_PRIORITY | ["720p","480p","1080p","240p"] | 分辨率优先级 |
| DEFAULT_NAME_TEMPLATE | {title}【{creator}-{section}】 | 文件命名模板 |
| DEFAULT_DB_PATH | bilibili_downloader.db | SQLite数据库路径 |
| DEFAULT_WEB_PORT | 8080 | Web仪表盘端口 |

## CLI用法

```bash
bilibili-dl <URL...> [options]          # 下载UP主视频
bilibili-dl web [--port 8080]           # 启动Web仪表盘

选项:
  -o, --output DIR       保存目录 (默认: ./downloads)
  -r, --resolution RES   目标分辨率 (默认: 按优先级自动选择)
  -n, --concurrency N    并发下载数 (默认: 5)
  --dry-run               仅分析不下载
  --force                 忽略已下载记录
  --name-template TPL     自定义文件命名模板
```

## 开发指南

### 环境搭建

```bash
uv venv && source .venv/Scripts/activate  # Windows
pip install -e .
pip install pytest pytest-asyncio aioresponses
```

### 运行测试

```bash
python -m pytest tests/ -v
```

### 代码规范

- 全部使用async/await，同步代码仅限parse_args和纯函数
- Database类所有方法以async def开头
- 错误处理：网络错误重试，永久错误(code=-404/62002)直接标记skipped/failed
- 类型标注使用Python 3.10+风格（`str | None`而非`Optional[str]`）

## 当前版本状态 (V1)

已完成:
- 多UP主批量下载，自动分页获取全部视频
- 合集信息提取，文件命名体现合集归属
- 异步高并发下载（信号量控制API/下载并发数）
- 指数退避重试 + 永久错误识别
- SQLite状态追踪，跳过已下载/已跳过视频
- CLI（download/web子命令，--dry-run/--force等）
- Web仪表盘（统计概览 + 下载列表 + REST API）

V2待做:
- 断点续传下载
- 音视频合并（ffmpeg mux，当前仅下载视频流）
- 更多平台支持（YouTube等）
- 下载速度限速
