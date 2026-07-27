@echo off
REM Step1 only: download zip to Desktop (Win7 cmd safe)
setlocal
set "EMS=http://192.168.2.168:8000"
set "OUT=%USERPROFILE%\Desktop\ict_gate_app.zip"
echo Downloading to %OUT%
certutil -urlcache -split -f "%EMS%/static/ict_gate/ict_gate_app.zip" "%OUT%"
if exist "%OUT%" (
  echo OK. Now unzip to C:\EMS\ict_gate_app then run start_ict_gate.bat
) else (
  echo FAIL
)
pause
endlocal
