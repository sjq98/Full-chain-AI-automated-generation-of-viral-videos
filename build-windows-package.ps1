param(
    [string]$PythonPath = "$PSScriptRoot\vendor\MediaCrawler\.venv\Scripts\python.exe",
    [string]$PnpmPath = "pnpm"
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$desktopRoot = Join-Path $projectRoot "desktop"

if (-not (Test-Path $PythonPath)) {
    throw "未找到构建 Python：$PythonPath"
}

Push-Location $projectRoot
try {
    & $PythonPath -m pip install --upgrade pyinstaller tos yt-dlp
    & $PythonPath build_release.py

    Push-Location $desktopRoot
    try {
        & $PnpmPath install --lockfile=false
        $env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
        & $PnpmPath exec electron-builder --win nsis
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}

Write-Host "Windows installer: $desktopRoot\dist\MP4-Golden-Clip-Workbench-1.0.9.exe"
