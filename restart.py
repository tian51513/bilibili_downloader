"""重启脚本 - 关闭旧浏览器标签页 → 杀掉旧进程 → 启动新服务"""
import subprocess
import sys
import time
import os
import urllib.request


def kill_port_process(port: int):
    """杀掉监听指定端口的进程"""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, encoding="gbk", errors="replace"
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                if pid.isdigit():
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True)
                    print(f"  已终止进程 PID={pid}")
                    return True
    except Exception as e:
        print(f"  查找进程失败: {e}")
    return False


def is_port_listening(port: int) -> bool:
    """检查指定端口是否有进程在监听"""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, encoding="gbk", errors="replace"
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                return True
    except Exception:
        pass
    return False


def close_browser_tabs(port: int):
    """通过 /close-tab 端点通知浏览器标签页关闭自身。"""
    url = f"http://localhost:{port}/close-tab"
    try:
        urllib.request.urlopen(url, timeout=3)
        print("  已通知浏览器关闭旧标签页")
        time.sleep(1)
    except Exception:
        pass


def wait_port_free(port: int, timeout: int = 15):
    """等待端口释放"""
    for i in range(timeout):
        if not is_port_listening(port):
            return True
        if i > 0:
            print(f"  等待端口释放... ({i}s)")
        time.sleep(1)
    return False


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    port = 8080

    print(f"正在重启服务 (端口 {port})...")

    # 1. 先通知浏览器关闭旧标签页（服务还活着）
    close_browser_tabs(port)
    time.sleep(1)

    # 2. 杀掉旧服务进程
    print("正在关闭旧服务...")
    killed = False
    for _ in range(3):
        if kill_port_process(port):
            killed = True
            break
        time.sleep(1)

    if killed:
        print("旧服务已关闭")
    else:
        print("未发现运行中的旧服务")

    if not wait_port_free(port):
        print(f"错误: 端口 {port} 无法释放，请手动关闭旧窗口后重试")
        sys.exit(1)

    print("正在启动服务...")

    import threading
    import webbrowser
    import urllib.request

    def wait_and_open():
        for i in range(30):
            time.sleep(1)
            try:
                urllib.request.urlopen(f"http://localhost:{port}/", timeout=2)
                webbrowser.open(f"http://localhost:{port}")
                return
            except Exception:
                pass

    threading.Thread(target=wait_and_open, daemon=True).start()

    from bilibili_downloader.cli.main import main as cli_main
    sys.exit(cli_main(["web"]))


if __name__ == "__main__":
    main()
