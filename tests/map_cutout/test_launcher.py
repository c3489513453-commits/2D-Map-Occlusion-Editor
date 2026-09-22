from pathlib import Path
import socket

from map_cutout.launcher import choose_address


def test_launcher_uses_loopback_and_next_free_port():
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    port = occupied.getsockname()[1]
    try:
        host, selected = choose_address(port, 3)
        assert host == "127.0.0.1"
        assert selected == port + 1
    finally:
        occupied.close()


def test_batch_file_uses_project_local_python():
    text = Path("启动工具.bat").read_text(encoding="utf-8")
    assert r".venv\Scripts\python.exe" in text
    assert "%APPDATA%" not in text
