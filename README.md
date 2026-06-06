# Bilibili Downloader

B站UP主视频批量下载器。Playwright 浏览器采集数据（绕过反爬），aiohttp 异步高并发下载视频流。自动扫码登录，Web 仪表盘实时监控。支持双流下载、断点续传、限速下载、视频播放等V2功能。

## 功能特性

### 下载引擎
- 双流下载（视频+音频）+ ffmpeg合并
- 断点续传（Range请求，网络中断后自动恢复）
- 下载限速（可设置MB/s，最低100KB/s）
- 异步高并发下载（API/下载信号量分别控制）
- 分辨率优先级自动选择
- 指数退避重试 + 永久错误自动识别

### 数据采集
- Playwright 浏览器采集，绕过B站反爬检测（-352/-799/412）
- API补全（WBI签名arc/search主动分页，解决滚动加载不全问题）
- 自动扫码登录，Cookie 4级优先级（CLI > 环境变量 > 缓存 > 扫码）
- 视频标签提取，合集分类自动提取
- 文件名含 bvid 防止同名覆盖

### Web仪表盘
- 任务管理面板（多行提交/进度/重试/暂停/强制重抓/编辑URL/删除）
- 下载管理（单个/批量下载，复选框全选，状态实时刷新）
- 视频播放器（自动播放 + 动态播放列表 + 上/下一个 + 自动连播）
- 标签筛选（OR关系，搜索/全选/反选/清除）
- WebSocket实时推送（精确状态驱动，无轮询）
- 统一UI系统（日间/夜间双主题）
- 分页显示、目录选择器、设置持久化

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
- **ffmpeg**：用于合并视频流和音频流
  - Windows: 从 [ffmpeg官网](https://ffmpeg.org/download.html) 下载并添加到PATH
  - Linux: `sudo apt install ffmpeg`
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

功能：任务管理、下载管理、视频播放、状态筛选、项目设置。

## REST API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 仪表盘页面 |
| `/ws` | WS | WebSocket实时推送 |
| `/api/stats` | GET | 统计数据 |
| `/api/downloads` | GET | 下载列表（分页+筛选） |
| `/api/downloads/start` | POST | 开始下载 |
| `/api/downloads/pause` | POST | 暂停下载 |
| `/api/downloads/batch-start` | POST | 批量下载选中 |
| `/api/downloads/{id}` | GET | 下载详情 |
| `/api/downloads/{id}/play` | GET | 视频文件播放 |
| `/api/downloads/{id}/retry` | POST | 重试单个 |
| `/api/downloads/{id}/delete` | DELETE | 删除记录 |
| `/api/tasks` | GET | 任务列表 |
| `/api/tasks/submit` | POST | 提交任务 |
| `/api/tasks/{id}/retry` | POST | 重试任务 |
| `/api/tasks/{id}/force` | POST | 强制重抓 |
| `/api/tasks/{id}/pause` | POST | 暂停任务 |
| `/api/tasks/{id}/resume` | POST | 恢复任务 |
| `/api/tasks/{id}/reset-downloads` | POST | 重置下载 |
| `/api/tasks/{id}/url` | POST | 修改URL |
| `/api/tasks/{id}/delete` | POST | 删除任务 |
| `/api/creators` | GET | UP主列表 |
| `/api/sections` | GET | 合集列表 |
| `/api/tags` | GET | 标签列表 |
| `/api/settings` | GET/POST | 获取/保存设置 |
| `/api/cookie/status` | GET | Cookie状态 |
| `/api/cookie/clear` | POST | 清除Cookie |
| `/api/trigger-login` | POST | 触发扫码登录 |

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
│   ├── database.py    # SQLite异步CRUD（五表 + 分页 + 任务状态同步）
│   └── files.py       # 文件命名与路径解析
├── bilibili/          # B站交互层
│   ├── api.py         # 流URL获取 + 视频详情 + API补全 + Cookie验证
│   ├── parser.py      # 响应解析
│   ├── scraper.py     # Playwright数据采集
│   └── wbi.py         # WBI签名鉴权
├── core/              # 下载引擎
│   ├── manager.py     # 任务调度 + 取消事件
│   ├── worker.py      # 单视频下载（双流+合并+续传+限速+WS广播）
│   └── retry.py       # 重试策略
├── cli/               # 命令行
│   └── main.py        # argparse + Cookie + QR登录
└── web/               # Web仪表盘
    ├── app.py          # FastAPI应用 + WebSocket
    ├── routes.py       # REST API（30+端点）
    ├── task_service.py # 后台任务服务（采集队列+API补全+下载调度）
    ├── ws_manager.py   # WebSocket连接管理
    └── templates/
        └── index.html   # 仪表盘（任务+下载+播放+设置）
start.bat              # Windows一键启动
```

## 技术架构

两阶段分离：

1. **数据采集**（Playwright）：Chromium → 注入Cookie → 导航空间页 → on_response读取API → 滚动加载 → API补全遗漏 → 解析去重 → 关闭浏览器
2. **视频下载**（aiohttp）：获取流URL → 双流下载 → ffmpeg合并 → SQLite状态更新 → WebSocket广播

任务状态机：`init → scraping → pending → downloading → completed/paused/failed`

## 许可证

MIT
