@echo off
setlocal
cd /d "%~dp0"
echo Python executable:
python -c "import sys; print(sys.executable)"
echo.
echo Checking packages...
python -c "import faster_whisper; print('faster-whisper OK')"
python -c "import opencc; print('opencc OK')"
echo.
echo Checking FFmpeg...
ffmpeg -version
pause
