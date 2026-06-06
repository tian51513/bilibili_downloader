# Bilibili Downloader V1 设计文档

> 版本: 1.0 | 日期: 2026-06-06 | 状态: 已发布

---

## 1. 项目概述

B站UP主视频批量下载器。用户输入UP主空间地址，程序自动管理登录态（首次扫码登录并缓存，后续自动读取），通过 Playwright 浏览器被动读取API响应采集UP主信息和视频列表（绕过B站反爬检测），再通过 aiohttp 异步并发下载视频流到本地。支持视频标签提取、合集分类命名、分辨率选择、跳过已下载/付费视频、SQLite状态持久化、Web仪表盘实时监控与设置管理。

### 1.1 设计目标

| 目标 | 实现方式 |
|------|----------|
| 零配置登录 | 自动扫码 + 本地缓存，首次扫码后永久有效 |
| 反爬绕过 | Playwright真实浏览器环境，页面JS自动处理WBI签名 |
| 高并发下载 | asyncio + aiohttp，信号量控制并发数 |
| 高可靠 | 指数退避重试 + 永久错误识别 + SQLite状态持久化 |
| 标签管理 | 采集阶段从 arc/search vlist.tag 零额外请求提取 |
| Web管理 | 浏览器端实时监控 + 筛选 + 设置面板，JSON持久化 |

### 1.2 运行形态

- **CLI模式**: `bilibili-dl <URL>` 命令行触发下载
- **Web模式**: `bilibili-dl web` 或 `start.bat` 启动监控仪表盘 + 设置管理

---

## 2. 技术架构

### 2.1 两阶段分离架构

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
          └────────────┬────────────┘
                       │ 关闭浏览器
          ┌────────────┴────────────┐
          │   Phase 2: 下载         │  ← aiohttp
          │  DownloadManager        │
          │  - asyncio.Semaphore    │
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
└───────────────────────┬────────────────────┘
                        │
┌───────────────────────┴────────────────────┐
│              SQLite Database                │
│           (storage/database.py)              │
│  platform / creator / video(download+tags)  │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│              Web Dashboard (按需启动)        │
│       FastAPI + Jinja2 + 原生JS          │
│  统计 + Tab + 筛选 + 标签 + 进度 + 设置  │
└────────────────────────────────────────────┘
```

### 2.2 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| on_response vs page.route | 仅 on_response | page.route 的 route.fetch 重复请求被B站拒绝，导致分页丢失 |
| 被动读取 vs 主动拦截 | 被动读取 | 不干扰页面JS行为，WBI签名和分页由页面自行处理 |
| 两阶段 vs 全程浏览器 | 两阶段分离 | 浏览器资源消耗大，下载阶段aiohttp更高效 |
| 标签获取时机 | 采集阶段为主 | arc/search vlist.tag 零额外请求；下载阶段 get_video_info 补充 |
| Web设置存储 | JSON文件 | 简单人类可读，load_settings 合并文件+默认值 |
| Jinja2 集成 | 直接用 jinja2.Environment | Starlette Jinja2Templates 与 Jinja2 3.1.x 不兼容 |

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

---

## 4. 数据采集设计（Phase 1）

### 4.1 on_response 被动读取

```python
async def on_response(response):
    # 读取 UP主信息
    if '/x/space/wbi/acc/info' in url:
        data = await response.json()
    # 读取合集信息
    elif '/x/space/section/index' in url:
        data = await response.json()
    # 读取视频列表（含标签）
    elif '/arc/search' in url and 'mid' in url:
        data = await response.json()
```

关键：不拦截请求，仅被动读取页面JS已收到的响应。页面JS自行处理WBI签名和分页。

### 4.2 滚动加载

算法：
1. 导航到空间页 + 等待3秒初始加载
2. 统计去重后bvid数 vs API返回的total
3. 若 loaded < total：`window.scrollTo(0, document.body.scrollHeight)` → 等2秒 → 重计
4. 用**去重bvid计数**（非原始vlist总数）避免分页重叠误判
5. 连续5轮无新增则停止
6. 最大轮数：`(total // 10) + 20`

### 4.3 标签提取

arc/search 的 vlist 中每个视频包含 `tag` 字段（逗号分隔字符串）：
```json
{"bvid": "BV1xx", "title": "视频标题", "tag": "可爱,纯欲,甜妹", ...}
```

parse_video_list 解析为 tags 列表，存入 video.tags 字段（JSON数组）。

### 4.4 合集视频补充

section/index 响应中的视频可能与投稿列表重叠。对合集视频中未出现在投稿列表的进行补充，标题待下载阶段通过API补充。

---

## 5. 下载引擎设计（Phase 2）

### 5.1 BilibiliAPI

```python
class BilibiliAPI:
    def __init__(self, session, cookies=None)  # 支持cookie注入
    async def get_cid(bvid) -> int                   # 获取cid（备用）
    async def get_video_info(bvid) -> dict           # 获取cid+tags
    async def get_stream_urls(bvid, cid, priority) -> dict  # 获取流URL
```

### 5.2 单视频下载流程

```
1. 更新状态: downloading
2. 解析extra获取cid（缺失则调用 get_video_info）
3. 获取标签（缺失则通过 get_video_info 补充，存入DB）
4. async with api_semaphore: 获取流URL（retry 3次）
5. build_filename（含bvid防重名）
6. async with download_semaphore: CDN流式下载（带cookie header）
7. 更新状态: completed / skipped / failed
```

---

## 6. Web仪表盘设计

### 6.1 技术栈

FastAPI + Jinja2（直接 Environment，绕过 Starlette 兼容问题）+ 原生JS（无构建工具）

### 6.2 功能

| 功能 | 实现方式 |
|------|----------|
| 统计卡片 | 6个stat-card（总数/各状态数），点击过滤 |
| 状态Tab | 6个tab（全部/下载中/已完成/等待/已跳过/失败） |
| UP主筛选 | 下拉框，显示视频计数 |
| 合集筛选 | 下拉框 |
| 标签筛选 | 多选下拉框，AND关系，显示视频计数 |
| 下载进度 | downloading 行蓝色高亮 + 进度条 |
| 设置面板 | 右侧抽屉（并发数/分辨率/模板/目录/端口） |
| 设置持久化 | POST /api/settings → bilibili_settings.json |
| 自动刷新 | 3秒轮询（stats + downloads） |

### 6.3 REST API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 仪表盘页面 |
| `/api/stats` | GET | 统计数据 |
| `/api/downloads` | GET | 下载列表（支持 status/creator_id/section_name/tags 筛选） |
| `/api/downloads/{id}` | GET | 下载详情 |
| `/api/creators` | GET | UP主列表 |
| `/api/sections` | GET | 合集列表 |
| `/api/tags` | GET | 标签列表及计数 |
| `/api/settings` | GET/POST | 设置读写 |

### 6.4 标签筛选实现

- GET `/api/tags` 返回所有标签及视频计数（聚合 video.tags JSON数组）
- 前端多选标签 → 逗号拼接 → `?tags=tag1,tag2`
- 后端 `LIKE '%"tag1"%' AND LIKE '%"tag2"'` 过滤（SQLite兼容）

---

## 7. 数据模型

### 7. 表结构

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
| section_name | TEXT | | 合集名称 |
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
| status | TEXT | DEFAULT 'pending' | 状态 |
| error_msg | TEXT | | 失败原因 |
| started_at | DATETIME | | 开始时间 |
| finished_at | DATETIME | | 完成时间 |
| created_at | DATETIME | | |

UNIQUE(video_id, resolution)

### 7.2 状态机

```
         pending ──download──→ downloading
                                   │
                    ┌──────────┼──────────┐
                    │          │          │
              completed    skipped     failed
```

---

## 8. 测试覆盖

54个测试，覆盖：

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

## 9. 运行时产物

| 文件 | 说明 |
|------|------|
| bilibili_downloader.db | SQLite数据库 |
| bilibili_cookies.json | Cookie缓存（自动生成） |
| bilibili_settings.json | 用户设置（Web面板修改后生成） |
| ./downloads/ | 默认下载目录 |
| start.bat | Windows快捷启动脚本 |
