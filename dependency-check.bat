@echo off
setlocal
cd /d "%~dp0"
echo Python executable:
python -c "import sys; print(sys.executable)"
echo.
echo Checking packages...
python -c "import tos; print('tos OK')"
echo.
echo Checking FFmpeg...
ffmpeg -version
echo.
echo Checking FFprobe...
ffprobe -version
pause
