@echo off
setlocal
cd /d "%~dp0"
set "PYTHON_EXE="

for %%P in (
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%LocalAppData%\Programs\Python\Python310\python.exe"
) do (
  if not defined PYTHON_EXE if exist "%%~fP" set "PYTHON_EXE=%%~fP"
)

if not defined PYTHON_EXE set "PYTHON_EXE=python"

echo Installing MP4 Golden Clip Workbench Python dependencies...
echo Python:
"%PYTHON_EXE%" -c "import sys; print(sys.executable)"
echo.
"%PYTHON_EXE%" -m pip install --upgrade pip
"%PYTHON_EXE%" -m pip install -r requirements.txt
echo.
echo Done. Run start.bat to open the workbench.
pause
