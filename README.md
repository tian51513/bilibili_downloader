# Bilibili Downloader

B站UP主视频批量下载器。Playwright 浏览器采集数据（绕过反爬），aiohttp 异步高并发下载视频流。自动扫码登录，Web 仪表盘实时监控。支持双流下载、断点续传、限速下载等V2新功能。

## 功能特性

### V1功能
- 批量下载多个UP主的全部视频
- Playwright 浏览器采集，绕过B站反爬检测（-352/-799/412）
- **自动扫码登录**：无cookie时弹出浏览器，手机B站APP扫码，登录后自动缓存
- **Cookie 4级优先级**：CLI参数 > 环境变量 > 缓存文件 > 扫码登录
- 视频标签提取（可爱/纯欲/萌妹等），Web端多选标签筛选
- 合集分类自动提取，文件名体现合集归属
- 文件名含 bvid 防止同名视频覆盖
- 异步高并发下载（可调并发数）
- 分辨率优先级自动选择
- SQLite状态持久化，跳过已下载视频，--force 可重置
- Web仪表盘（统计/筛选/标签/进度条/设置面板）
- `start.bat` 一键启动

### V2新增功能
- **双流下载**：同时下载视频流和音频流，使用ffmpeg合并成完整视频
- **断点续传**：支持断点续传，网络中断后可从断点继续下载
- **下载限速**：支持设置下载速度下限（最低100KB/s）
- **实时进度**：WebSocket实时推送下载进度和状态更新
- **任务管理**：Web任务管理面板，支持发布任务、查看进度、重试失败任务
- **分页显示**：下载列表和任务列表都支持分页浏览
- **目录选择器**：原生tkinter目录选择器，方便选择保存路径
- **多平台Cookie**：支持多平台的Cookie文件存储

## 快速开始

```bash
# 安装
pip install -e .
playwright install chromium

# 首次运行（自动扫码登录）
bilibili-dl https://space.bilibili.com/33676449 --dry-run

# 正式下载
bilibili-dl https://space.bilibili.com/33676449 -o ./downloads

# Web仪表盘（双击 start.bat 或命令行）
bilibili-dl web
```

## 安装

**要求:** Python 3.11+

```bash
git clone <repo-url>
cd bilibili_downloader

uv venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -e .
playwright install chromium
```

### 依赖说明

- **基础依赖**：通过 `pip install -e .` 自动安装
- **Playwright**：需要手动安装 Chromium 浏览器
- **ffmpeg**（V2新增）：用于合并视频流和音频流，请确保系统已安装
  - Windows: 从 [ffmpeg官网](https://ffmpeg.org/download.html) 下载并添加到PATH
  - Linux: `sudo apt install ffmpeg` 或 `sudo yum install ffmpeg`
  - Mac: `brew install ffmpeg`

## Cookie机制

```
CLI参数 (--cookie) → 环境变量 (BILIBILI_SESSDATA) → 缓存文件 → 扫码登录
```

| 方式 | 说明 |
|------|------|
| 自动（默认） | 首次运行弹出浏览器扫码，登录后缓存到 `bilibili_cookies.json` |
| 手动Cookie | `--cookie SESSDATA=xxx` |
| 环境变量 | `export BILIBILI_SESSDATA=xxx` |
| 强制重新登录 | `--no-cache` 忽略缓存，重新扫码 |

## 使用方法

### 下载视频

```bash
bilibili-dl https://space.bilibili.com/33676449                          # 最简用法
bilibili-dl https://space.bilibili.com/33676449 -o E:\Video               # 指定目录
bilibili-dl https://space.bilibili.com/33676449 https://space.bilibili.com/123456  # 多UP主
bilibili-dl https://space.bilibili.com/33676449 -r 1080p                     # 指定分辨率
bilibili-dl https://space.bilibili.com/33676449 -n 10                         # 10路并发
bilibili-dl https://space.bilibili.com/33676449 --dry-run                    # 仅分析
bilibili-dl https://space.bilibili.com/33676449 --force                       # 重置已下载
bilibili-dl https://space.bilibili.com/33676449 --no-cache                   # 重新扫码
```

### Web仪表盘

```bash
bilibili-dl web                # 默认 http://localhost:8080
bilibili-dl web --port 9090  # 自定义端口
start.bat                   # Windows 一键启动（自动激活venv+打开浏览器）
```

功能：状态Tab切换、UP主/合集/标签筛选、下载进度条、项目设置。

### REST API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 仪表盘页面 |
| `/api/stats` | GET | 统计数据 |
| `/api/downloads` | GET | 下载列表（`?status=&creator_id=&section_name=&tags=`） |
| `/api/downloads/{id}` | GET | 单个下载详情 |
| `/api/creators` | GET | UP主列表 |
| `/api/sections` | GET | 合集列表 |
| `/api/tags` | GET | 标签列表 |
| `/api/settings` | GET/POST | 获取/保存设置 |

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `URL...` | UP主空间地址 | 必填 |
| `-o, --output` | 保存目录 | `./downloads` |
| `-r, --resolution` | 目标分辨率 | 按优先级自动 |
| `-n, --concurrency` | 并发下载数 | `5` |
| `--dry-run` | 仅分析 | `False` |
| `--force` | 重置已下载 | `False` |
| `--name-template` | 命名模板 | `{title}【{creator}-{section}】` |
| `--headed` | 显示浏览器窗口 | `False` |
| `--no-cache` | 强制重新登录 | `False` |
| `--cookie NAME=VALUE` | B站Cookie | - |
| `web` | 启动仪表盘 | - |
| `--port` | Web端口 | `8080` |

### V2新增选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `--download-speed-limit` | 下载速度限制（MB/s） | 0（不限速） |

## 文件命名

默认模板: `{title}【{creator}-{section}】_{bvid}.mp4`

```
有合集: 这是什么神仙颜值啊？？？【颜值回忆录-流行】_BV1xx.mp4
无合集: 独立视频【某UP主】_BV1yy.mp4
```

可用变量: `{title}`, `{creator}`, `{section}`, `{bvid}`

## 项目结构

```
bilibili_downloader/
├── config.py          # 配置常量 + 设置持久化
├── main.py            # 程序入口
├── browser.py         # Playwright浏览器 + Cookie缓存
├── storage/           # 存储层
│   ├── database.py    # SQLite异步CRUD
│   └── files.py       # 文件命名与路径解析
├── bilibili/          # B站交互层
│   ├── api.py         # 流URL获取 + 视频详情(含标签)
│   ├── parser.py      # 响应解析
│   └── scraper.py     # Playwright数据采集
├── core/              # 下载引擎
│   ├── manager.py     # 任务调度
│   ├── worker.py      # 单视频下载
│   └── retry.py       # 重试策略
├── cli/               # 命令行
│   └── main.py        # argparse + Cookie + QR登录
└── web/               # Web仪表盘
    ├── app.py          # FastAPI应用
    ├── routes.py       # REST API
    └── templates/      # Jinja2模板
start.bat              # Windows一键启动
```

## 技术架构

两阶段分离：

1. **数据采集**（Playwright）：Chromium → 注入Cookie → 导航空间页 → on_response读取API响应 → 滚动加载全部分页 → 解析去重 → 关闭浏览器
2. **视频下载**（aiohttp）：获取流URL → 信号量并发控制 → CDN流式下载 → SQLite状态更新

## 许可证

MIT
