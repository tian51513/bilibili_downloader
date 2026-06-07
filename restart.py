"""重启脚本 - 关闭旧浏览器标签页 → 杀掉旧进程和终端 → 启动新服务"""
import subprocess
import sys
import time
import os
import urllib.request


def kill_port_process(port: int):
    """杀掉监听指定端口的进程及其父终端窗口"""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, encoding="gbk", errors="replace"
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                if not pid.isdigit():
                    continue
                # 杀掉服务进程
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                print(f"  已终止服务进程 PID={pid}")
                # 杀掉父终端窗口（cmd.exe / powershell.exe / python.exe）
                try:
                    parent_result = subprocess.run(
                        ["wmic", "process", "where", f"ProcessId={pid}",
                         "get", "ParentProcessId", "/FORMAT:CSV", "/NH"],
                        capture_output=True, text=True, timeout=5,
                    )
                    for p_line in parent_result.stdout.strip().splitlines():
                        p_line = p_line.strip().strip('"')
                        parts = [p.strip().strip('"') for p in p_line.split(",")]
                        if len(parts) >= 2:
                            ppid = parts[0]
                            if ppid.isdigit() and int(ppid) != pid:
                                name_result = subprocess.run(
                                    ["tasklist", "/FI", f"PID eq {ppid}", "/FO", "CSV", "/NH"],
                                    capture_output=True, text=True, timeout=3,
                                )
                                proc_name = ""
                                for nl in name_result.stdout.strip().splitlines():
                                    nl = nl.strip().strip('"')
                                    if nl.startswith('"'):
                                        proc_name = nl.split('"')[1]
                                        break
                                if proc_name.lower() in ("cmd.exe", "powershell.exe", "python.exe"):
                                    subprocess.run(
                                        ["taskkill", "/F", "/PID", ppid],
                                        capture_output=True, timeout=5,
                                    )
                                    print(f"  已关闭终端窗口 PID={ppid} ({proc_name})")
                except Exception:
                    pass
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

    # 2. 杀掉旧服务进程及其终端窗口
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

    # 启动新服务进程，restart.py 随后退出
    venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        venv_python = sys.executable
    subprocess.Popen([venv_python, "-m", "platform_video_downloader.cli.main", "web"])


if __name__ == "__main__":
    main()
