from pathlib import Path

from map_cutout.launcher import choose_address


def test_launcher_uses_loopback_and_next_free_port(monkeypatch):
    attempts = []

    class FakeSocket:
        def __init__(self, *args): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, address):
            attempts.append(address)
            if address[1] == 7860:
                raise OSError("occupied")

    monkeypatch.setattr("map_cutout.launcher.socket.socket", FakeSocket)
    host, selected = choose_address(7860, 3)
    assert host == "127.0.0.1"
    assert selected == 7861
    assert attempts == [("127.0.0.1", 7860), ("127.0.0.1", 7861)]


def test_batch_file_uses_project_local_python():
    text = Path("启动工具.bat").read_text(encoding="utf-8")
    assert r".venv\Scripts\python.exe" in text
    assert "%APPDATA%" not in text
