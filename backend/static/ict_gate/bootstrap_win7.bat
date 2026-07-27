@echo off
setlocal
set "EMS=http://192.168.2.168:8000"
set "BAT=%TEMP%\install_win7_ict_gate.bat"
echo Downloading installer...
certutil -urlcache -split -f "%EMS%/static/ict_gate/install_win7.bat" "%BAT%"
if not exist "%BAT%" (
  echo Download failed
  pause
  exit /b 1
)
call "%BAT%"
endlocal
