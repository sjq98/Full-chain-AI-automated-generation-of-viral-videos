import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


VERSION = "1.0.9"
APP_NAME = "MP4GoldenClipWorkbench"


def bundled_path(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / name


def install_dir():
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return local_app_data / APP_NAME / f"App-{VERSION}"


def install_if_needed(target):
    marker = target / ".bundle-version"
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == VERSION:
        return

    archive = bundled_path("workbench.zip")
    if not archive.exists():
        raise RuntimeError("The bundled desktop application archive is missing.")

    staging = target.with_name(f"{target.name}.staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as package:
            package.extractall(staging)
        (staging / ".bundle-version").write_text(VERSION, encoding="utf-8")
        shutil.rmtree(target, ignore_errors=True)
        staging.replace(target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def find_app_executable(target):
    candidates = sorted(target.glob("*.exe"))
    if not candidates:
        raise RuntimeError("The bundled desktop application executable was not found.")
    return candidates[0]


def main():
    target = install_dir()
    install_if_needed(target)
    executable = find_app_executable(target)
    subprocess.Popen([str(executable)], cwd=str(target), close_fds=True)


if __name__ == "__main__":
    main()
