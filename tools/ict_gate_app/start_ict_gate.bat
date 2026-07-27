@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting ICT Gate...
python ict_gate.py
if errorlevel 1 (
  echo.
  echo Python 启动失败。请安装 Python 3.9+ 并勾选 Add to PATH。
  echo 可选：pip install keyboard
  pause
)
