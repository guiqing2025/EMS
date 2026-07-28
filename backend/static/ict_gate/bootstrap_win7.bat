@echo off
setlocal
if "%EMS_BASE_URL%"=="" (
  echo 请先设置 EMS_BASE_URL，例如：
  echo   set EMS_BASE_URL=http://当前EMS服务器IP:8000
  pause
  exit /b 1
)
set "EMS=%EMS_BASE_URL%"
set "BAT=%TEMP%\install_win7_ict_gate.bat"
echo Downloading installer from %EMS% ...
certutil -urlcache -split -f "%EMS%/static/ict_gate/install_win7.bat" "%BAT%"
if not exist "%BAT%" (
  echo Download failed
  pause
  exit /b 1
)
call "%BAT%"
endlocal
