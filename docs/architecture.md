# Bilibili Downloader V2 设计文档

> 版本: 2.0 | 日期: 2026-06-07 | 状态: 已发布

---

## 1. 项目概述

B站UP主视频批量下载器。用户输入UP主空间地址，程序自动管理登录态（首次扫码登录并缓存，后续自动读取），通过 Playwright 浏览器被动读取API响应采集UP主信息和视频列表（绕过B站反爬检测），再通过 aiohttp 异步并发下载视频流到本地。支持视频标签提取、分辨率选择、跳过已下载/付费视频、SQLite状态持久化、Web仪表盘实时监控与设置管理。

V2 新增：Web任务管理、API补全采集、双流下载+ffmpeg合并、断点续传、下载限速、视频播放器、WebSocket实时推送。

### 1.1 设计目标

| 目标 | 实现方式 |
|------|----------|
| 零配置登录 | 自动扫码 + 本地缓存，首次扫码后永久有效 |
| 反爬绕过 | Playwright真实浏览器环境，页面JS自动处理WBI签名 |
| 高并发下载 | asyncio + aiohttp，信号量控制并发数 |
| 高可靠 | 指数退避重试 + 永久错误识别 + SQLite状态持久化 |
| 标签管理 | 采集阶段从 arc/search vlist.tag 零额外请求提取 |
| Web管理 | 浏览器端实时监控 + 任务管理 + 视频播放 + 设置面板 |
| 采集完整 | 滚动采集 + API补全（WBI签名arc/search主动分页） |

### 1.2 运行形态

- **CLI模式**: `bilibili-dl <URL>` 命令行触发下载
- **Web模式**: `bilibili-dl web` 或 `start.bat` 启动监控仪表盘 + 任务管理

---

## 2. 技术架构

### 2.1 两阶段分离架构 + 后台任务服务

```
┌─────────────────────────────────────────────────────┐
│                    CLI Entry Point                   │
│  parse_args → _resolve_cookies → download_command    │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          │   Cookie 解析           │
          │  CLI > ENV > 缓存 > 扫码  │
          └────────────┬────────────┘
                       │
          ┌────────────┴────────────┐
          │   Phase 1: 数据采集     │  ← Playwright (on_response)
          │  BilibiliScraper        │
          │  被动读取响应 → 解析 → DB │
          │  + API补全(WBI签名)     │
          └────────────┬────────────┘
                       │ 关闭浏览器
          ┌────────────┴────────────┐
          │   TaskService            │  ← asyncio.Queue 串行
          │  采集队列 + 下载调度     │
          │  Cookie检测 + QR登录    │
          └────────────┬────────────┘
                       │
          ┌────────────┴────────────┐
          │   Phase 2: 下载         │  ← aiohttp
          │  DownloadManager        │
          │  - asyncio.Semaphore    │
          │  - cancel_event        │
          │  - Worker Pool          │
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
│  get_stream_urls + get_video_info          │
│  fetch_videos_by_api (WBI补全)           │
└───────────────────────┬────────────────────┘
                        │
┌───────────────────────┴────────────────────┐
│              SQLite Database                │
│           (storage/database.py)              │
│  platform/creator/video/download/task      │
└─────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│         Web Dashboard + WebSocket          │
│       FastAPI + Jinja2 + 原生JS          │
│  任务管理 + 下载管理 + 视频播放 + 设置     │
│  WebSocket 精确状态推送（无轮询）         │
└────────────────────────────────────────────┘
```

### 2.2 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| on_response vs page.route | 仅 on_response | page.route 的 route.fetch 重复请求被B站拒绝，导致分页丢失 |
| 被动读取 vs 主动拦截 | 被动读取 | 不干扰页面JS行为，WBI签名和分页由页面自行处理 |
| 两阶段 vs 全程浏览器 | 两阶段分离 | 浏览器资源消耗大，下载阶段aiohttp更高效 |
| 滚动 + API补全 | 双重策略 | 滚动可能漏视频，API主动分页补全确保完整 |
| 标签筛选关系 | OR关系 | 多标签筛选时包含任意一个即匹配，更实用 |
| WebSocket vs 轮询 | WebSocket广播 | 精确状态驱动，减少无意义请求，所有状态变化立即刷新 |
| 下载状态广播 | Worker每个状态点广播 | downloading/skipped/failed/completed/merging 全量覆盖 |
| 重置下载策略 | 跳过已完成 | 重置时保留已下载文件，仅补全+重试 |

---

## 3. Cookie与登录设计

### 3.1 4级优先级

```
1. --cookie CLI参数（最高优先级）
2. 环境变量 BILIBILI_SESSDATA / BILIBILI_BILI_JCT
3. 缓存文件 bilibili_cookies.json
4. 浏览器内QR码扫码登录（最低优先级，触发后自动缓存）
```

### 3.2 QR码扫码登录流程

```
1. 启动headed浏览器（--headed 或需要扫码时）
2. 导航到B站页面 → 点击登录按钮/导航登录页
3. 终端打印提示"请扫描二维码"
4. 每2秒轮询 context.cookies() 检测 SESSDATA
5. 检测到SESSDATA → 登录成功 → 缓存cookie
6. 超时120秒抛出 TimeoutError
```

### 3.3 自动Cookie检测

TaskService 在每次任务执行前自动检测Cookie有效性：
1. 检测到Cookie失效 → 广播 `login_required` → 前端弹窗提示
2. 用户点击扫码 → 调用 `POST /api/trigger-login` → 弹出headed浏览器
3. 登录成功 → 广播 `login_success` → 前端关闭弹窗
4. 等待最多120秒

---

## 4. 数据采集设计（Phase 1）

### 4.1 on_response 被动读取

```python
async def on_response(response):
    if '/x/space/wbi/acc/info' in url:    # UP主信息
        data = await response.json()
    elif '/x/space/section/index' in url: # 合集信息
        data = await response.json()
    elif '/arc/search' in url and 'mid' in url:  # 视频列表(含标签)
        data = await response.json()
```

### 4.2 滚动加载 + API补全

1. 导航到空间页 → 等3秒初始加载 → 滚动加载分页
2. 滚动结束后，用 aiohttp + WBI签名调用 `arc/search` API 主动分页
3. `fetch_videos_by_api` 按 `ps=30` 分页获取，去重后合并
4. API补全失败不阻塞任务，使用滚动采集数据

### 4.3 标签提取

arc/search 的 vlist 中每个视频包含 `tag` 字段（逗号分隔字符串），解析为 tags 列表存入 video.tags。

### 4. WBI签名

`bilibili/wbi.py` 实现 B站 WBI 签名鉴权：
- 从 `/x/web-interface/nav` 获取 img_key + sub_key
- 混淆映射表重排 → 截取前32位
- MD5签名生成 w_rid

---

## 5. 下载引擎设计（Phase 2）

### 5.1 单视频下载流程

```
1. 广播 downloading 状态
2. 解析extra获取cid（缺失则调用 get_video_info）
3. 获取标签（缺失则通过 get_video_info 补充）
4. async with api_semaphore: 获取流URL（retry 3次）
5. build_filename（含bvid防重名）
6. 双流下载：video流(.video.tmp) + audio流(.audio.tmp)
7. 检查已有临时文件 → Range请求断点续传
8. 速度限制：chunk写入后计算耗时，不足则sleep补足
9. ffmpeg合并 → 输出最终文件 → 删除临时文件
10. 广播 completed/failed/skipped 状态
```

### 5. 状态广播覆盖

Worker 在以下状态变化点通过 WebSocket 广播：

| 状态变化 | 广播消息 |
|----------|----------|
| 开始下载 | `{type: "download_progress", status: "downloading"}` |
| 进度更新 | `{type: "download_progress", download_id, file_size, total_size}` |
| 开始合并 | `{type: "download_progress", status: "merging"}` |
| 下载完成 | `{type: "download_progress", status: "completed", file_size}` |
| 跳过 | `{type: "download_progress", status: "skipped"}` |
| 失败 | `{type: "download_progress", status: "failed"}` |

### 5. 断点续传

- 检测 `.video.tmp` / `.audio.tmp` 临时文件
- 获取已有文件大小作为 Range 请求起点
- Content-Range 响应解析总大小
- append 模式写入（existing_size > 0 时用 "ab"）

### 5. 下载限速

- `speed_limit_bps` 参数传入 Worker（单位：bytes/s）
- 每个 chunk 写入后：`expected_time = chunk_size / speed_limit_bps`
- 若实际耗时 < expected_time，sleep 补足差值
- 最低限速 100KB/s（config.py 常量保护）

---

## 6. 任务管理系统

### 6.1 TaskService

后台任务服务，管理采集队列和下载调度：

- `submit_task(space_url)` — 提交/重新提交任务，去重
- `_process_queue()` — 串行处理采集队列（asyncio.Queue + asyncio.create_task）
- `_execute_task(task_id)` — 单个任务完整流程：Cookie检测 → 采集 → API补全 → 创建下载记录
- `start_downloads()` — 启动下载（cancel_event 控制优雅停止）
- `pause_downloads()` — 通过 cancel_event 中断下载
- `trigger_qr_login()` — 弹出headed浏览器QR登录

### 6.2 任务状态机

```
init → scraping → pending → downloading → completed
                  ↓           ↓
               paused      failed
```

- **init**: 任务已入队，等待Cookie检测
- **scraping**: 正在采集视频列表（含API补全）
- **pending**: 视频已采集，等待下载
- **downloading**: 下载进行中
- **completed**: 全部视频已下载
- **failed**: 任务执行失败（Cookie过期超时等）
- **paused**: 用户暂停

### 6.3 任务状态自动同步

`sync_task_status_from_downloads(task_id)` 从子下载记录聚合推导任务状态：
- 有 downloading → downloading
- 全部 pending → pending
- 全部 failed → failed
- 全部 completed/skipped → completed
- 混合状态 → downloading

### 6.4 重置下载策略

`reset_task_downloads(creator_id)`:
- 仅重置 failed/skipped 状态的下载记录
- **跳过 completed 记录**（保留已下载文件）
- API补全新增的视频自动创建 pending 下载记录

---

## 7. Web仪表盘设计

### 7.1 技术栈

FastAPI + Jinja2 + 原生JS + WebSocket

### 7.2 功能

| 功能 | 实现方式 |
|------|----------|
| 任务管理 | 多行提交/列表/进度/重试/暂停/强制重抓/编辑URL/删除 |
| 任务状态显示 | init/scraping/pending/downloading/completed/paused/failed |
| 文件大小 | 每个任务显示已完成视频的文件总大小（子查询SUM） |
| 下载管理 | 单个/批量下载（复选框+全选）/状态实时刷新 |
| 视频播放 | 模态播放器（自动播放+动态播放列表+上/下一个+自动连播） |
| 视频跳转 | 标题链接到B站视频页（新标签页） |
| 统计卡片 | 6个stat-card（总数/各状态数） |
| 状态Tab | 6个tab（全部/下载中/已完成/等待/已跳过/失败） |
| UP主筛选 | 下拉框，显示 已下载/总数 |
| 标签筛选 | OR关系，搜索/全选/反选/清除 |
| 下载进度 | downloading行高亮 + 进度条 + merging状态 |
| 合并状态 | 紫色标签显示"合并中" |
| 按钮系统 | .btn修饰符（primary/success/warning/danger/ghost），日间/夜间双主题 |
| 设置面板 | 居中布局（下载设置/界面设置/Cookie管理分组） |
| WebSocket | 精确状态驱动（所有download_progress/task_status触发UI刷新，无轮询） |
| 分页 | 下载列表20条/页 + 任务列表50条/页 |
| 目录选择器 | tkinter 原生目录选择器 |
| Cookie管理 | 自动检测状态 + 扫码登录 + 清除 |

### 7.3 REST API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/ws` | WS | WebSocket实时推送 |
| `/api/stats` | GET | 统计数据 |
| `/api/downloads` | GET | 下载列表（分页+筛选） |
| `/api/downloads/start` | POST | 开始下载 |
| `/api/downloads/pause` | POST | 暂停下载 |
| `/api/downloads/batch-start` | POST | 批量下载选中 |
| `/api/downloads/{id}` | GET | 下载详情 |
| `/api/downloads/{id}/play` | GET | 视频文件播放（FileResponse） |
| `/api/downloads/{id}/retry` | POST | 重试单个 |
| `/api/downloads/{id}/delete` | DELETE | 删除记录 |
| `/api/downloads/clear` | POST | 清空全部 |
| `/api/tasks` | GET | 任务列表 |
| `/api/tasks/submit` | POST | 提交任务 |
| `/api/tasks/{id}` | GET | 任务详情 |
| `/api/tasks/{id}/retry` | POST | 重试任务 |
| `/api/tasks/{id}/force` | POST | 强制重抓 |
| `/api/tasks/{id}/pause` | POST | 暂停 |
| `/api/tasks/{id}/resume` | POST | 恢复 |
| `/api/tasks/{id}/reset-downloads` | POST | 重置下载 |
| `/api/tasks/{id}/url` | POST | 修改URL |
| `/api/tasks/{id}/delete` | POST | 删除任务 |
| `/api/creators` | GET | UP主列表 |
| `/api/tags` | GET | 标签列表及计数 |
| `/api/settings` | GET/POST | 设置读写 |
| `/api/cookie/status` | GET | Cookie状态 |
| `/api/cookie/clear` | POST | 清除Cookie |
| `/api/trigger-login` | POST | 触发扫码登录 |
| `/api/pick-directory` | POST | 目录选择器 |
| `/api/directories` | POST | 目录列表 |

### 7.4 视频播放器

- 点击已完成视频的"播放"按钮 → 打开模态框
- 后端 `GET /api/downloads/{id}/play` 返回 FileResponse（video/mp4）
- 自动根据当前筛选条件（UP主/标签）动态构建播放列表
- 播放器 autoplay 自动播放，ended 事件自动切换下一个
- 播放列表显示当前项高亮，点击列表项可跳转
- ◀◀上一个 / ▶▶下一个 / 关闭按钮，首尾按钮 disabled

---

## 8. 数据模型

### 8.1 表结构

#### platform 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| name | TEXT | UNIQUE NOT NULL | 平台名称 |
| base_url | TEXT | | 基础URL |
| created_at | DATETIME | | |

#### creator 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| platform_id | INTEGER | FK, NOT NULL | |
| remote_id | TEXT | NOT NULL | 平台用户ID |
| name | TEXT | NOT NULL | 创作者名称 |
| avatar_url | TEXT | | 头像URL |
| space_url | TEXT | NOT NULL | 空间地址 |
| last_sync | DATETIME | | 最后同步时间 |
| created_at | DATETIME | | |

UNIQUE(platform_id, remote_id)

#### video 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| creator_id | INTEGER | FK, NOT NULL | |
| remote_id | TEXT | NOT NULL | BV号 |
| title | TEXT | NOT NULL | 视频标题 |
| duration | INTEGER | | 时长(秒) |
| pubdate | DATETIME | | 发布时间 |
| extra | TEXT | | JSON: cid, aid |
| section_id | TEXT | | 合集ID |
| section_name | TEXT | 合集名称 |
| **tags** | TEXT | | JSON数组: ["可爱","纯欲"] |
| created_at | DATETIME | | |

UNIQUE(creator_id, remote_id)

#### download 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| video_id | INTEGER | FK, NOT NULL | |
| save_path | TEXT | NOT NULL | 文件路径 |
| resolution | TEXT | NOT NULL | 分辨率 |
| file_size | INTEGER | | 文件大小 |
| total_size | INTEGER | | 总大小 |
| status | TEXT | DEFAULT 'pending' | 状态 |
| error_msg | TEXT | 失败原因 |
| started_at | DATETIME | 开始时间 |
| finished_at | DATETIME | 完成时间 |
| created_at | DATETIME | |

UNIQUE(video_id, resolution)

#### task 表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PK | |
| platform_id | INTEGER | FK | |
| creator_id | INTEGER | FK | NULLABLE |
| space_url | TEXT | NOT NULL | 空间地址 |
| space_uid | TEXT | | 平台用户ID |
| display_name | TEXT | | 显示名称 |
| status | TEXT | DEFAULT 'pending' | 状态 |
| cookie_status | TEXT | DEFAULT 'valid' | Cookie状态 |
| total_videos | INTEGER | DEFAULT 0 | 视频总数 |
| scraped_videos | INTEGER | DEFAULT 0 | 已采集数 |
| downloaded_videos | INTEGER | DEFAULT 0 | 已下载数 |
| total_downloads | INTEGER | DEFAULT 0 | 下载记录总数 |
| error_message | TEXT | NULL | 错误信息 |
| created_at | DATETIME | | |
| updated_at | DATETIME | | |

### 8.2 状态机

```
download: pending → downloading → merging → completed
                                   ↓
                          skipped / failed

task: init → scraping → pending → downloading → completed
                   ↓           ↓
                paused      failed
```

---

## 9. 测试覆盖

54个测试（V1），覆盖：

| 模块 | 测试数 | 覆盖内容 |
|------|--------|----------|
| test_browser.py | 12 | Cookie文件I/O、环境变量、解析优先级 |
| test_cli.py | 9 | 参数解析、子命令、默认值 |
| test_database.py | 9 | CRUD、唯一约束、状态更新、聚合查询 |
| test_files.py | 7 | 命名模板、非法字符、路径解析 |
| test_parser.py | 8 | 各类解析、时长转换、流URL选择 |
| test_retry.py | 5 | 退避重试、永久错误、跳过错误 |
| test_worker.py | 2 | 下载成功mock、付费视频跳过 |
| test_manager.py | 2 | 队列处理、跳过已存在 |

---

## 10. 运行时产物

| 文件 | 说明 |
|------|------|
| bilibili_downloader.db | SQLite数据库 |
| bilibili_cookies.json | Cookie缓存（自动生成） |
| bilibili_settings.json | 用户设置（Web面板修改后生成） |
| ./downloads/ | 默认下载目录 |
| start.bat | Windows快捷启动脚本 |
