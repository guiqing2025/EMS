@echo off
REM Step1 only: download zip to Desktop (Win7 cmd safe)
setlocal
if "%EMS_BASE_URL%"=="" (
  echo 请先设置 EMS_BASE_URL，例如：
  echo   set EMS_BASE_URL=http://当前EMS服务器IP:8000
  pause
  exit /b 1
)
set "EMS=%EMS_BASE_URL%"
set "OUT=%USERPROFILE%\Desktop\ict_gate_app.zip"
echo Downloading to %OUT% from %EMS%
certutil -urlcache -split -f "%EMS%/static/ict_gate/ict_gate_app.zip" "%OUT%"
if exist "%OUT%" (
  echo OK. Now unzip to C:\EMS\ict_gate_app then run start_ict_gate.bat
) else (
  echo FAIL
)
pause
endlocal
