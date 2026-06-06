# Bilibili Downloader

B站UP主视频批量下载器，支持多UP主、多分辨率、合集分类、异步高并发下载。

## 功能特性

- 批量下载多个UP主的全部视频
- 自动识别合集分类，文件名体现合集归属
- 异步高并发下载（默认5路并发，可调）
- 分辨率优先级自动选择（720p > 480p > 1080p > 240p）
- SQLite本地数据库记录下载状态，跳过已下载视频
- 需充电视频自动跳过
- 可自定义文件命名模板
- Web仪表盘实时监控下载进度
- 支持dry-run仅分析模式

## 安装

**要求:** Python 3.11+

```bash
# 克隆项目
git clone <repo-url>
cd bilibili_downloader

# 创建虚拟环境并安装
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -e .
```

**依赖:**
- aiohttp >= 3.9
- aiosqlite >= 0.20
- fastapi >= 0.115
- uvicorn >= 0.30
- jinja2 >= 3.1

## 使用方法

### 下载视频

```bash
# 下载单个UP主的视频（保存到 ./downloads）
bilibili-dl https://space.bilibili.com/33676449

# 下载到指定目录
bilibili-dl https://space.bilibili.com/33676449 -o E:\映畫\B

# 同时下载多个UP主
bilibili-dl https://space.bilibili.com/33676449 https://space.bilibili.com/123456 -o E:\映畫\B

# 指定分辨率
bilibili-dl https://space.bilibili.com/33676449 -r 1080p

# 调整并发数（默认5）
bilibili-dl https://space.bilibili.com/33676449 -n 10

# 仅分析不下载（查看有多少新视频）
bilibili-dl https://space.bilibili.com/33676449 --dry-run

# 强制重新下载已完成的视频
bilibili-dl https://space.bilibili.com/33676449 --force

# 自定义文件命名模板
bilibili-dl https://space.bilibili.com/33676449 --name-template "{creator}_{title}"
```

### Web仪表盘

```bash
# 启动仪表盘（默认端口 8080）
bilibili-dl web

# 指定端口
bilibili-dl web --port 9090
```

浏览器打开 `http://localhost:8080` 查看下载状态。页面每3秒自动刷新。

### REST API

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 仪表盘页面 |
| `/api/stats` | GET | 统计数据（JSON） |
| `/api/downloads` | GET | 下载列表（支持 `?status=&limit=&offset=`） |
| `/api/downloads/{id}` | GET | 单个下载详情 |

## 文件命名

默认模板: `{title}【{creator}-{section}】.mp4`

```
有合集: 这是什么神仙颜值啊？？？【颜值回忆录-流行】.mp4
无合集: 独立视频【某UP主】.mp4
```

通过 `--name-template` 自定义，可用变量: `{title}`, `{creator}`, `{section}`

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `URL...` | UP主空间地址（支持多个） | 必填 |
| `-o, --output` | 视频保存目录 | `./downloads` |
| `-r, --resolution` | 目标分辨率 | 按优先级自动选择 |
| `-n, --concurrency` | 并发下载数 | `5` |
| `--dry-run` | 仅分析不下载 | `False` |
| `--force` | 忽略已下载记录 | `False` |
| `--name-template` | 文件命名模板 | `{title}【{creator}-{section}】` |
| `web` | 启动Web仪表盘 | - |
| `--port` | Web服务端口 | `8080` |

## 项目结构

```
bilibili_downloader/
├── config.py          # 全局配置
├── main.py            # 程序入口
├── storage/           # 存储层
│   ├── database.py    # SQLite异步CRUD
│   └── files.py       # 文件命名与路径解析
├── bilibili/          # B站API交互
│   ├── api.py         # 异步HTTP客户端
│   └── parser.py      # 响应解析
├── core/              # 下载引擎
│   ├── manager.py     # 任务调度
│   ├── worker.py      # 单视频下载
│   └── retry.py       # 重试策略
├── cli/               # 命令行
│   └── main.py        # argparse入口
└── web/               # Web仪表盘
    ├── app.py          # FastAPI应用
    ├── routes.py       # 路由定义
    └── templates/      # Jinja2模板
```

## 开发

```bash
# 安装开发依赖
pip install pytest pytest-asyncio aioresponses

# 运行测试
python -m pytest tests/ -v
```

## 技术栈

Python 3.11+ / asyncio / aiohttp / aiosqlite / FastAPI / Jinja2 / Uvicorn

## 许可证

MIT
