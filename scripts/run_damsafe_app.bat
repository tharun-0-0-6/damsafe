@echo off
setlocal
cd /d "%~dp0"

REM Run the DamSafe app: pipeline + QGIS or built-in map window
python run_damsafe_app.py %*
if errorlevel 1 pause
endlocal
