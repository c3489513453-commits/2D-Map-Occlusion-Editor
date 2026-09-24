from __future__ import annotations

import argparse
from dataclasses import replace
import socket
from threading import Timer
import webbrowser

import uvicorn

from .config import AppConfig
from .web_app import create_app


def choose_address(start_port: int = 7860, attempts: int = 20) -> tuple[str, int]:
    host = "127.0.0.1"
    for port in range(start_port, start_port + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, port))
            except OSError:
                continue
        return host, port
    raise RuntimeError(f"端口 {start_port} 到 {start_port + attempts - 1} 都被占用")


def main(argv=None):
    parser = argparse.ArgumentParser(description="启动 2D 地图遮挡与行走区域编辑器")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    host, port = choose_address(args.port)
    config = replace(AppConfig(), host=host, port=port)
    app = create_app(config)
    url = f"http://{host}:{port}"
    print(f"2D 地图遮挡与行走区域编辑器已启动：{url}")
    print("关闭此窗口即可停止工具。")
    if not args.no_browser:
        Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
