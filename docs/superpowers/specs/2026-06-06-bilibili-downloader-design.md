# Bilibili Downloader V1 Design Spec

## 概述

B站UP主视频批量下载器，支持多UP主、多分辨率、合集分类、断点续传，具备本地SQLite数据库记录下载状态，CLI + 轻量Web仪表盘双模式操作。

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python 3.11+ |
| 异步框架 | asyncio + aiohttp |
| Web框架 | FastAPI |
| 前端 | Jinja2 模板 |
| 数据库 | SQLite (aiosqlite) |
| CLI解析 | argparse |
| 包管理 | pip / pyproject.toml |

## 架构：单进程分层

```
CLI入口 → DownloadManager(任务调度) → Worker池(asyncio)
                                        ↓
Web仪表盘(FastAPI) ←── 共享SQLite ←── Worker更新状态
```

单进程同时运行CLI任务和Web服务，FastAPI与下载Worker共享asyncio事件循环。

## 模块划分

```
bilibili_downloader/
├── cli/                    # CLI入口与命令解析
│   └── main.py             # argparse命令行入口
├── core/                   # 核心下载引擎
│   ├── manager.py          # DownloadManager - 任务调度、队列管理、并发控制
│   ├── worker.py           # DownloadWorker - 单个视频下载逻辑
│   └── retry.py            # 重试策略（指数退避）
├── bilibili/               # B站API交互层（平台实现）
│   ├── api.py              # B站公开API封装
│   └── parser.py           # 响应解析（视频流URL、合集信息）
├── storage/                # 存储层
│   ├── database.py         # SQLite操作封装（aiosqlite）
│   ├── models.py           # 数据模型定义
│   └── files.py            # 文件命名与保存逻辑
├── web/                    # Web仪表盘
│   ├── app.py              # FastAPI应用
│   ├── routes.py           # 路由（状态查询、任务管理）
│   └── templates/           # Jinja2 HTML模板
├── config.py               # 全局配置
└── main.py                 # 程序入口
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

status 状态机: `pending → downloading → completed / skipped / failed`

## 下载引擎

### 并发控制

```python
MAX_CONCURRENT_DOWNLOADS = 5      # 同时下载视频数
MAX_CONCURRENT_API_REQUESTS = 10   # 同时API请求数
DOWNLOAD_RETRY_COUNT = 3
RETRY_BACKOFF_BASE = 2            # 秒
REQUEST_TIMEOUT = 30
DEFAULT_RESOLUTION_PRIORITY = ['720p', '480p', '1080p', '240p']
```

### 下载流程

1. API获取视频流URL列表（受 `api_semaphore` 限制）
2. 按优先级选择分辨率（遍历 `DEFAULT_RESOLUTION_PRIORITY`，首个可用即选）
3. 判断可下载性（需充值 → skipped，异常 → failed重试）
4. aiohttp流式下载边写磁盘（受 `download_semaphore` 限制）
5. 应用命名模板保存文件
6. 更新SQLite状态

### 重试策略

- 指数退避：2s → 4s → 8s
- 网络超时 → 重试
- HTTP 403/404 → 直接标记failed
- 需充值 → 直接标记skipped
- 磁盘写入失败 → 重试，空间不足则failed

### 进度上报

Worker定期更新SQLite的 `file_size` 字段，Web仪表盘轮询SQLite获取进度。

## CLI 设计

```bash
# 下载UP主视频
bilibili-dl https://space.bilibili.com/33676449 -o E:\映畫\B

# 多UP主
bilibili-dl https://space.bilibili.com/33676449 https://space.bilibili.com/123456 -o E:\映畫\B

# 指定分辨率
bilibili-dl https://space.bilibili.com/33676449 -r 1080p

# 启动Web仪表盘
bilibili-dl web --port 8080

# 仅分析不下载
bilibili-dl https://space.bilibili.com/33676449 --dry-run

# 强制重新下载
bilibili-dl https://space.bilibili.com/33676449 --force
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
| `web` | 启动仪表盘 | - |
| `--port` | Web端口 | `8080` |

## Web 仪表盘

只读监控面板，下载通过CLI触发。

### 路由

| 路由 | 功能 |
|------|------|
| `GET /` | 仪表盘首页 |
| `GET /api/stats` | JSON统计 |
| `GET /api/downloads` | 下载记录列表（分页、筛选） |
| `GET /api/downloads/{id}` | 单个下载详情 |

### 页面内容

- 顶部统计栏：总UP主、总视频、已下载、下载中、已跳过、失败
- 任务列表：UP主、视频标题、合集、分辨率、状态、进度
- 每3秒自动刷新（JS轮询或meta refresh）

## 文件命名

```
模板: {title}【{creator}-{section}】.mp4
无合集: {title}【{creator}】.mp4
示例: 这是什么神仙颜值啊？？？【颜值回忆录-流行】.mp4
```

模板通过 `--name-template` 参数或 `config.py` 自定义。

## 平台扩展

扩展新平台只需：
1. `platform` 表插入记录
2. 新增平台API模块（如 `youtube/api.py`）
3. 实现统一接口协议：获取创作者信息、视频列表、下载链接
