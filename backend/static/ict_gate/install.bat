@echo off
chcp 65001 >nul
echo 正在从 EMS 一键安装 ICT 扫码闸道...
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm http://192.168.2.168:8000/static/ict_gate/install.ps1 | iex"
pause
