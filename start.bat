@echo off
setlocal
cd /d "%~dp0"
set "PORT=8789"
set "PYTHON_EXE="

for %%P in (
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%LocalAppData%\Programs\Python\Python310\python.exe"
) do (
  if not defined PYTHON_EXE if exist "%%~fP" set "PYTHON_EXE=%%~fP"
)

if not defined PYTHON_EXE set "PYTHON_EXE=python"

echo MP4 Golden Clip Workbench
echo URL: http://127.0.0.1:%PORT%
echo.

netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo Port %PORT% is already in use.
  echo Close the program already using this address, then run start.bat again.
  echo.
  pause
  exit /b 1
)

"%PYTHON_EXE%" -c "import cgi, tos" >nul 2>nul
if errorlevel 1 (
  echo Python 3.10-3.12 and the tos dependency are required.
  echo Run install-deps.bat with Python 3.10-3.12, then start again.
  echo.
  pause
  exit /b 1
)
start "" /b "%PYTHON_EXE%" app.py
timeout /t 2 /nobreak >nul

powershell -NoProfile -Command "try { $page = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 'http://127.0.0.1:%PORT%/').Content; if ($page -notmatch 'workbenchTabs') { exit 2 } } catch { exit 1 }"
if errorlevel 1 (
  echo The new source server did not start correctly.
  echo Check this window for errors, then run start.bat again.
  echo.
  pause
  exit /b 1
)

start "" "http://127.0.0.1:%PORT%/"
echo New source server is running. Close this window to stop it.
pause
