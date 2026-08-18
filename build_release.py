"""Build self-contained backend tools for the Electron release package.

Run this from a Python environment that has ``PyInstaller``, ``tos``,
``yt-dlp``, and MediaCrawler's dependencies installed. The script deliberately
packages only code, static files, and runtime binaries. It never copies local
settings, jobs, exports, or search data into the desktop release.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DESKTOP_BACKEND_DIR = ROOT / "desktop" / "resources" / "backend"
MEDIA_CRAWLER_DIR = ROOT / "vendor" / "MediaCrawler"
FFMPEG_PATH = ROOT / "bin" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")


def data_arg(source: Path, target: str) -> str:
    return f"{source}{';' if sys.platform == 'win32' else ':'}{target}"


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(f'"{part}"' if " " in part else part for part in command))
    subprocess.run(command, cwd=cwd, check=True)


def build_onefile(
    entry: Path,
    name: str,
    dist_dir: Path,
    work_root: Path,
    extra_args: list[str] | None = None,
    cwd: Path | None = None,
    console: bool = True,
) -> Path:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_root / name / "work"),
        "--specpath",
        str(work_root / name / "spec"),
    ]
    if not console:
        command.append("--noconsole")
    command.extend(extra_args or [])
    command.append(str(entry))
    run(command, cwd=cwd)
    binary = dist_dir / (f"{name}.exe" if sys.platform == "win32" else name)
    if not binary.exists():
        raise RuntimeError(f"PyInstaller did not create {binary}")
    return binary


def build_release() -> None:
    if not FFMPEG_PATH.exists():
        raise RuntimeError(f"Missing bundled FFmpeg: {FFMPEG_PATH}")
    if not (MEDIA_CRAWLER_DIR / "main.py").exists():
        raise RuntimeError("Missing vendor/MediaCrawler/main.py")

    with tempfile.TemporaryDirectory(prefix="mp4-golden-release-") as temp:
        temp_root = Path(temp)
        dist_dir = temp_root / "dist"
        work_root = temp_root / "build"
        runner = temp_root / "yt_dlp_runner.py"
        runner.write_text(
            "from yt_dlp import main\n\n"
            "if __name__ == '__main__':\n"
            "    raise SystemExit(main())\n",
            encoding="utf-8",
        )

        crawler = build_onefile(
            MEDIA_CRAWLER_DIR / "main.py",
            "mediacrawler",
            dist_dir,
            work_root,
            [
                "--paths",
                str(MEDIA_CRAWLER_DIR),
                "--collect-all",
                "media_platform",
                "--collect-all",
                "config",
                "--collect-all",
                "database",
                "--collect-all",
                "store",
                "--collect-all",
                "tools",
            ],
            cwd=MEDIA_CRAWLER_DIR,
        )
        downloader = build_onefile(
            runner,
            "yt-dlp",
            dist_dir,
            work_root,
            ["--collect-all", "yt_dlp"],
        )
        backend = build_onefile(
            ROOT / "app.py",
            "app",
            dist_dir,
            work_root,
            [
                "--add-data",
                data_arg(ROOT / "static", "static"),
                "--add-binary",
                data_arg(FFMPEG_PATH, "bin"),
                "--add-binary",
                data_arg(crawler, "bin"),
                "--add-binary",
                data_arg(downloader, "bin"),
                "--collect-all",
                "tos",
            ],
            console=False,
        )

        shutil.rmtree(DESKTOP_BACKEND_DIR, ignore_errors=True)
        DESKTOP_BACKEND_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backend, DESKTOP_BACKEND_DIR / backend.name)

    forbidden = ["user-settings.json", "data", "outputs", "trends", "tasks"]
    bundled_names = {path.name.casefold() for path in DESKTOP_BACKEND_DIR.rglob("*")}
    unexpected = [name for name in forbidden if name.casefold() in bundled_names]
    if unexpected:
        raise RuntimeError(f"Release resources contain prohibited local data: {', '.join(unexpected)}")
    print(f"Release backend resources ready: {DESKTOP_BACKEND_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build desktop backend release resources")
    parser.parse_args()
    build_release()
