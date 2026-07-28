@echo off
chcp 65001 >nul
if "%EMS_BASE_URL%"=="" (
  echo 请先设置 EMS_BASE_URL，例如：
  echo   set EMS_BASE_URL=http://当前EMS服务器IP:8000
  pause
  exit /b 1
)
echo 正在从 %EMS_BASE_URL% 一键安装 ICT 扫码闸道...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:EMS_BASE_URL='%EMS_BASE_URL%'; irm ($env:EMS_BASE_URL.TrimEnd('/') + '/static/ict_gate/install.ps1') | iex"
pause
