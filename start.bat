@echo off
setlocal
cd /d "%~dp0"
set PORT=8767
set LOCAL_WHISPER_DEVICE=cpu
set LOCAL_WHISPER_COMPUTE_TYPE=int8
set LOCAL_WHISPER_MODEL=base
set LOCAL_WHISPER_BEAM_SIZE=1
set LOCAL_WHISPER_LANGUAGE=zh
set LOCAL_WHISPER_INITIAL_PROMPT=Mandarin Chinese speech. Output simplified Chinese text.

echo MP4 Golden Clip Workbench
echo URL: http://127.0.0.1:%PORT%
echo.
python -c "import faster_whisper, opencc" >nul 2>nul
if errorlevel 1 (
  echo Missing Python dependencies for local transcription.
  echo Run install-deps.bat first, then start again.
  echo.
)
python app.py
pause
