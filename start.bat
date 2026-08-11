@echo off
setlocal
cd /d "%~dp0"
set PORT=8767

echo MP4 Golden Clip Workbench
echo URL: http://127.0.0.1:%PORT%
echo.
python -c "import tos" >nul 2>nul
if errorlevel 1 (
  echo Missing Python dependency: tos
  echo Run install-deps.bat first, then start again.
  echo.
)
python app.py
pause
