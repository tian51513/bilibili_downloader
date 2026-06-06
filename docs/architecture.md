# Bilibili Downloader V1 设计文档

> 版本: 1.0 | 日期: 2026-06-06 | 状态: 已实现

---

## 1. 项目概述

B站UP主视频批量下载器。用户输入UP主空间地址，程序异步并发抓取全部视频到本地，支持合集分类命名、分辨率选择、跳过已下载/付费视频、SQLite状态持久化、Web仪表盘实时监控。

### 1.1 设计目标

| 目标 | 实现方式 |
|------|----------|
| 高并发 | asyncio + aiohttp，信号量控制并发数 |
| 高可靠 | 指数退避重试 + 永久错误识别 + SQLite状态持久化 |
| 高扩展 | platform/creator/video分层，extra JSON字段存平台特有数据 |
| 低资源 | 单进程架构，CLI优先，Web仪表盘按需启动 |
| 不影响日常 | 默认5路并发，可调；无后台常驻服务 |

### 1.2 运行形态

- **CLI模式**: `bilibili-dl <URL>` 命令行触发下载
- **Web模式**: `bilibili-dl web` 启动监控仪表盘（只读，下载仍由CLI触发）

---

## 2. 技术架构

### 2.1 架构选型

| 层 | 选型 | 选型理由 |
|----|------|----------|
| 语言 | Python 3.11+ | B站API生态成熟，异步支持好 |
| 异步 | asyncio + aiohttp | IO密集型任务最佳匹配，轻量高效 |
| Web | FastAPI + Jinja2 | 原生async支持，与下载共享事件循环 |
| 数据库 | SQLite (aiosqlite) | 零配置，单文件，异步驱动 |
| CLI | argparse | 标准库，无额外依赖 |

### 2.2 单进程分层架构

```
┌─────────────────────────────────────────────────────┐
│                    CLI Entry Point                   │
│  parse_args → download_command / web_command         │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          │    DownloadManager     │
          │  (core/manager.py)     │
          │  - asyncio.Semaphore   │
          │  - Worker Pool         │
          │  - Queue Building       │
          └────────────┬────────────┘
                       │ asyncio.gather
    ┌──────────────────┼──────────────────┐
    │                  │                  │
┌───┴───┐       ┌────┴────┐        ┌────┴────┐
│Worker│       │ Worker  │        │ Worker  │
│  #1  │       │   #2    │        │   #N    │
└───┬───┘       └────┬────┘        └────┬────┘
    │                │                  │
    │  api_semaphore │ download_semaphore
    │                │                  │
┌───┴────────────────┴──────────────────┴───┐
│              BilibiliAPI                   │
│           (bilibili/api.py)                 │
│  get_space_info / get_all_videos /          │
│  get_sections / get_stream_urls             │
└───────────────────────┬────────────────────┘
                        │
┌───────────────────────┴────────────────────┐
│              SQLite Database                │
│           (storage/database.py)              │
│  platform / creator / video / download      │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│              Web Dashboard (按需启动)        │
│         FastAPI + Jinja2 Templates          │
│    GET / | /api/stats | /api/downloads      │
└────────────────────────────────────────────┘
```

### 2.3 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 单进程 vs 双进程 | 单进程 | FastAPI与Worker共享事件循环，零IPC开销 |
| asyncio vs 多线程 | asyncio | IO密集型，避免GIL，信号量控制简洁 |
| SQLite vs 其他DB | SQLite | 零配置单文件，读性能足够（仪表盘轮询），无需独立服务 |
| Jinja2 vs SPA | Jinja2 | 轻量监控面板，无需前端构建工具链 |
| 信号量 vs 队列 | 信号量 | asyncio.Semaphore原生支持，代码简洁 |

---

## 3. 数据模型

### 3.1 ER关系

```
platform (1) ──→ (N) creator ──→ (N) video ──→ (N) download
                    │              │
                    │              │ section_id, section_name
                    │              │ extra (JSON: 平台特有字段)
                    │
                    └── UNIQUE(platform_id, remote_id)
```

### 3.2 表结构

#### platform 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK AUTOINCREMENT | |
| name | TEXT | UNIQUE NOT NULL | 平台名称（bilibili/youtube） |
| base_url | TEXT | | 平台基础URL |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP | |

#### creator 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK AUTOINCREMENT | |
| platform_id | INTEGER | FK → platform, NOT NULL | 所属平台 |
| remote_id | TEXT | NOT NULL | 平台内用户ID |
| name | TEXT | NOT NULL | 创作者名称 |
| avatar_url | TEXT | | 头像URL |
| space_url | TEXT | NOT NULL | 空间/频道地址 |
| last_sync | DATETIME | | 最后同步时间 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP | |

约束: UNIQUE(platform_id, remote_id)

#### video 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK AUTOINCREMENT | |
| creator_id | INTEGER | FK → creator, NOT NULL | 所属创作者 |
| remote_id | TEXT | NOT NULL | 平台内视频标识（BV号） |
| title | TEXT | NOT NULL | 视频标题 |
| duration | INTEGER | | 时长(秒) |
| pubdate | DATETIME | | 发布时间 |
| extra | TEXT | | JSON: 平台特有字段 |
| section_id | TEXT | | 合集/播放列表ID |
| section_name | TEXT | | 合集/播放列表名称 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP | |

约束: UNIQUE(creator_id, remote_id)

extra字段示例（B站）: `{"cid": 456, "aid": 67890}`

#### download 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK AUTOINCREMENT | |
| video_id | INTEGER | FK → video, NOT NULL | 关联视频 |
| save_path | TEXT | NOT NULL | 保存文件路径 |
| resolution | TEXT | NOT NULL | 分辨率标签（720p/1080p等） |
| file_size | INTEGER | | 已下载/最终文件大小(字节) |
| status | TEXT | NOT NULL DEFAULT 'pending' | 状态 |
| error_msg | TEXT | | 失败原因 |
| started_at | DATETIME | | 开始下载时间 |
| finished_at | DATETIME | | 完成/失败时间 |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP | |

约束: UNIQUE(video_id, resolution)

### 3.3 状态机

```
              ┌─────────────────────────┐
              │                         │
    ┌─────────┴───┐               ┌─────▼─────┐
    │   pending   │───download──→│downloading │
    └─────────────┘               └─────┬─────┘
                                        │
                     ┌──────────────────┼──────────────┐
                     │                  │              │
              ┌──────▼──────┐   ┌──────▼──────┐  ┌────▼─────┐
              │  completed  │   │   skipped   │  │  failed   │
              └─────────────┘   └─────────────┘  └──────────┘
```

状态转换规则:
- `pending → downloading`: Worker开始下载
- `downloading → completed`: 文件下载完成
- `downloading → skipped`: API返回需充值(code=62002)或付费标记
- `downloading → failed`: 重试耗尽或遇到永久错误(code=-404)
- `pending`状态记录也会被`get_existing_downloads`视为已存在，避免重复入队

---

## 4. 核心模块设计

### 4.1 下载引擎

#### 并发控制

```python
api_semaphore = asyncio.Semaphore(MAX_CONCURRENT_API_REQUESTS)    # 默认10
download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)  # 默认5
```

API请求和文件下载使用独立信号量，避免互相阻塞。Worker获取流URL时受api_semaphore限制，下载文件时受download_semaphore限制。

#### 单视频下载流程 (download_video)

```
1. 更新状态: downloading
2. 解析extra字段获取cid
3. async with api_semaphore:
   4. retry_async调用API获取流URL
      - 成功: 返回 {video_url, audio_url, resolution}
      - 需充值(62002/充值): 标记skipped, return
      - 永久错误(-404): retry_async直接抛出, 标记failed
      - 网络超时: 指数退避重试(2s→4s→8s)
5. build_filename生成文件名
6. resolve_save_path解析保存路径
7. async with download_semaphore:
   8. _download_stream: 流式下载，1MB chunk写磁盘
   9. 每10MB更新一次DB进度(file_size)
10. 更新save_path到DB
11. 更新状态: completed
```

#### 重试策略 (retry_async)

| 错误类型 | 行为 |
|----------|------|
| aiohttp.ClientError / ConnectionError / TimeoutError / OSError | 指数退避重试 |
| ValueError 含 "code=-404" / "code=62002" / "skipped:" | 立即抛出，不重试 |
| 其他ValueError | 指数退避重试 |

退避公式: `delay = backoff_base ** attempt`（默认: 2^1=2s, 2^2=4s, 2^3=8s）

### 4.2 任务管理 (DownloadManager)

```
run(session):
  1. 查询所有pending状态的download记录
  2. 对每条记录:
     a. 查关联video和creator信息
     b. 创建download_video协程
  3. asyncio.gather(*tasks) 并发执行
```

`enqueue_creator_videos(creator_id)` 用于为UP主的所有新视频创建pending下载记录。

### 4.3 B站API层

#### API端点

| 方法 | API端点 | 功能 |
|------|---------|------|
| get_space_info | /x/space/wbi/acc/info?mid={mid} | 获取UP主信息 |
| get_video_list | /x/space/arc/search?mid={mid}&ps=50&pn={page} | 分页获取视频列表 |
| get_all_videos | (自动分页) | 获取全部视频 |
| get_sections | /x/space/section/index?mid={mid} | 获取合集列表 |
| get_stream_urls | /x/player/playurl?bvid={}&cid={}&fnval=16&fourk=1 | 获取DASH流URL |

#### 分辨率映射

| quality_id | 标签 |
|------------|------|
| 32 | 240p |
| 64 | 480p |
| 80 | 720p |
| 112 | 1080p |
| 116 | 1080p60 |
| 120 | 4k |

选择逻辑: 按 `DEFAULT_RESOLUTION_PRIORITY` 顺序匹配，首个可用即选。无匹配则fallback到最高带宽流。

### 4.4 文件命名

```
sanitize_filename: 移除 <>:"/\\|?* 控制字符，移除末尾./空格
build_filename: 应用模板，处理section为None时的模板清理
resolve_save_path: Path.resolve()返回绝对路径
```

模板变量: `{title}`, `{creator}`, `{section}`

### 4.5 Web仪表盘

- 只读监控面板，不触发下载操作
- Jinja2服务端渲染，无前端构建
- `<script>setTimeout(location.reload, 3000)</script>` 自动刷新
- 自定义Jinja2过滤器 `filesizeformat`（B→KB→MB→GB→TB）
- REST API返回JSON，支持分页和状态筛选

---

## 5. CLI设计

### 5.1 命令结构

```
bilibili-dl [download] <URL...> [OPTIONS]   # 下载模式（默认）
bilibili-dl web [--port PORT]               # 仪表盘模式
```

当直接传入URL（无显式子命令）时，自动识别为download命令。

### 5.2 download流程

```
1. 解析URL列表，提取mid
2. 对每个UP主:
   a. 获取/创建platform记录
   b. 获取/创建creator记录
   c. API获取全部视频列表 + 合集信息
   d. 合并合集信息到视频数据
   e. 查询已存在下载记录（--force跳过此步）
   f. 为新视频创建download记录
   g. 更新creator.last_sync
3. 如果--dry-run: 输出统计，结束
4. 创建DownloadManager，执行run()
```

---

## 6. 多平台扩展设计

当前V1仅实现B站。架构预留了多平台扩展点：

### 6.1 扩展新平台步骤

1. `platform`表插入新记录（如name="youtube"）
2. 新建 `bilibili_downloader/youtube/` 包
3. 实现与 `bilibili/api.py` 相同接口的API类：
   - `get_space_info(remote_id) → dict`
   - `get_all_videos(remote_id) → list[dict]`
   - `get_sections(remote_id) → list[dict]`
   - `get_stream_urls(remote_id, ...) → dict`
4. CLI入口根据URL pattern选择对应API模块

### 6.2 平台无关设计要素

- `platform`表隔离不同平台
- `creator.remote_id`为TEXT类型，兼容不同平台ID格式
- `video.extra`为JSON字段，存平台特有数据
- `download.resolution`为TEXT类型，兼容不同分辨率命名
- `video.section_id/section_name`兼容不同平台的播放列表概念

---

## 7. 环境需求

### 7.1 运行时依赖

```
Python >= 3.11
aiohttp >= 3.9
aiosqlite >= 0.20
fastapi >= 0.115
uvicorn >= 0.30
jinja2 >= 3.1
```

### 7.2 开发依赖

```
pytest >= 8.0
pytest-asyncio >= 0.23
aioresponses >= 0.7
```

### 7.3 运行时产物

| 文件 | 说明 |
|------|------|
| bilibili_downloader.db | SQLite数据库文件（默认在项目根目录） |
| ./downloads/ | 默认视频保存目录 |

---

## 8. 测试覆盖

42个测试，覆盖：

| 模块 | 测试数 | 覆盖内容 |
|------|--------|----------|
| test_database.py | 9 | 四表CRUD、唯一约束、状态更新、去重查询、统计聚合 |
| test_files.py | 7 | 默认模板、无合集模板、自定义模板、非法字符过滤、路径解析 |
| test_parser.py | 8 | 空间信息解析、视频列表（含时长转换）、合集解析、流URL选择/回退/异常 |
| test_retry.py | 5 | 成功无重试、重试后成功、重试耗尽、永久错误不重试、跳过错误不重试 |
| test_worker.py | 2 | 下载成功（mock流）、付费视频跳过 |
| test_manager.py | 2 | 队列处理完成、跳过已存在 |
| test_cli.py | 9 | 各参数解析、裸URL自动识别、子命令、默认值 |
