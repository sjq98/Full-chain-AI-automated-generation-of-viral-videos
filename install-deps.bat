@echo off
setlocal
cd /d "%~dp0"
echo Installing MP4 Golden Clip Workbench Python dependencies...
echo Python:
python -c "import sys; print(sys.executable)"
echo.
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo Done. Run start.bat to open the workbench.
pause
