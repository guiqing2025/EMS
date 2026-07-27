@echo off
setlocal EnableExtensions
title ICT Gate Install Win7

set "EMS=http://192.168.2.168:8000"
set "ROOT=C:\EMS\ict_gate_app"
set "ZIP=%TEMP%\ict_gate_app.zip"
set "APIKEY=ems-ict-gate-2026-dx"
if "%ICT_MACHINE_ID%"=="" set "ICT_MACHINE_ID=ict-pilot"

echo EMS=%EMS%
echo ROOT=%ROOT%
echo MACHINE=%ICT_MACHINE_ID%
echo.

echo [1/5] download zip
if exist "%ZIP%" del /f /q "%ZIP%"
certutil -urlcache -split -f "%EMS%/static/ict_gate/ict_gate_app.zip" "%ZIP%"
if not exist "%ZIP%" (
  echo ERROR download zip failed
  pause
  exit /b 1
)

echo [2/5] unzip
if exist "%ROOT%" rd /s /q "%ROOT%"
if not exist "C:\EMS" mkdir "C:\EMS"
powershell -NoProfile -ExecutionPolicy Bypass -Command " $z='%ZIP%'; $d='C:\EMS'; $s=New-Object -ComObject Shell.Application; $ns=$s.NameSpace($z); $nd=$s.NameSpace($d); foreach($i in $ns.Items()){ $nd.CopyHere($i,16) }; Start-Sleep 3 "
if not exist "%ROOT%\ict_gate.py" (
  echo ERROR unzip failed
  pause
  exit /b 1
)

echo [3/5] write config
> "%ROOT%\ict_gate_config.json" echo {
>> "%ROOT%\ict_gate_config.json" echo   "ems_base_url": "%EMS%",
>> "%ROOT%\ict_gate_config.json" echo   "api_key": "%APIKEY%",
>> "%ROOT%\ict_gate_config.json" echo   "machine_id": "%ICT_MACHINE_ID%",
>> "%ROOT%\ict_gate_config.json" echo   "append_enter": true,
>> "%ROOT%\ict_gate_config.json" echo   "focus_delay_ms": 80,
>> "%ROOT%\ict_gate_config.json" echo   "play_sound": true
>> "%ROOT%\ict_gate_config.json" echo }

echo [4/5] find python
set "PY="
where py >nul 2>&1 && set "PY=py"
if "%PY%"=="" where python >nul 2>&1 && set "PY=python"
if "%PY%"=="" (
  echo.
  echo Python NOT found.
  echo 1. Install Python 3.8+ and CHECK Add to PATH
  echo 2. Close cmd, open new cmd, run this bat again
  echo.
  start "" "%EMS%/static/ict_gate/"
  pause
  exit /b 1
)
echo PY=%PY%
%PY% -m pip install keyboard

echo @echo off> "%ROOT%\start_ict_gate.bat"
echo cd /d "%ROOT%">> "%ROOT%\start_ict_gate.bat"
echo %PY% ict_gate.py>> "%ROOT%\start_ict_gate.bat"
echo if errorlevel 1 pause>> "%ROOT%\start_ict_gate.bat"

echo [5/5] test api
powershell -NoProfile -ExecutionPolicy Bypass -Command "try{$w=New-Object Net.WebClient;$w.Headers.Add('X-Api-Key','%APIKEY%');Write-Host $w.DownloadString('%EMS%/api/ict-gate/health')}catch{Write-Host $_.Exception.Message}"

echo.
echo DONE. Start: %ROOT%\start_ict_gate.bat
echo.
set /p YN=Start now Y/N?
if /i "%YN%"=="Y" start "" "%ROOT%\start_ict_gate.bat"
pause
endlocal
