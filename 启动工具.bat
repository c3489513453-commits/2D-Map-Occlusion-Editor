@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [错误] 未找到项目环境 .venv\Scripts\python.exe
  echo 请让 Codex 帮你修复环境后再试。
  pause
  exit /b 1
)
if not exist ".python" (
  echo [错误] 未找到项目自带的 Python 运行环境 .python
  pause
  exit /b 1
)
if not exist "checkpoints\sam2.1_hiera_small.pt" (
  echo [错误] 未找到 SAM2 Small 权重文件。
  pause
  exit /b 1
)
echo 正在启动地图抠图工具，请稍候……
".venv\Scripts\python.exe" -m map_cutout.launcher
if errorlevel 1 (
  echo.
  echo 工具启动失败，请把上面的错误截图发给 Codex。
  pause
)
