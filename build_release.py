"""Build self-contained backend tools for the Electron release package.

Run this from a Python environment that has ``PyInstaller``, ``tos``,
``yt-dlp``, Playwright, Node.js, and MediaCrawler's dependencies installed.
The script packages code and runtime binaries, but never copies local settings,
jobs, exports, browser profiles, cookies, or search data into the release.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
from importlib import metadata
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DESKTOP_BACKEND_DIR = ROOT / "desktop" / "resources" / "backend"
MEDIA_CRAWLER_DIR = ROOT / "vendor" / "MediaCrawler"
PUBLISHERS_DIR = ROOT / "vendor" / "publishers"
FFMPEG_PATH = ROOT / "bin" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
BACKEND_MANIFEST = DESKTOP_BACKEND_DIR / "backend-manifest.json"


def data_arg(source: Path, target: str) -> str:
    return f"{source}{';' if sys.platform == 'win32' else ':'}{target}"


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(f'"{part}"' if " " in part else part for part in command))
    subprocess.run(command, cwd=cwd, check=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_build_dependency(module_name: str, package_name: str) -> str:
    try:
        importlib.import_module(module_name)
        return metadata.version(package_name)
    except Exception as exc:
        raise RuntimeError(
            f"The packaging Python environment is missing {package_name}. "
            f"Install it before building the desktop release: {exc}"
        ) from exc


def publisher_runtime_tree(destination: Path) -> Path:
    """Copy adapter runtime files while excluding every local browser/session artifact."""
    if not PUBLISHERS_DIR.is_dir():
        raise RuntimeError(f"Missing publisher source directory: {PUBLISHERS_DIR}")

    def ignore(_directory: str, names: list[str]) -> set[str]:
        excluded = {
            ".git", ".upstream-git", "__pycache__", ".pytest_cache",
            "browser_data", "cookies", "logs", "screenshots", ".vscode", ".idea",
        }
        return {
            name for name in names
            if name in excluded
            or name.endswith((".pyc", ".pyo", ".log"))
            or name in {"douyin_state.json", "xhs-state.json"}
        }

    shutil.copytree(PUBLISHERS_DIR, destination, ignore=ignore)
    return destination


def bundled_node_executable() -> Path:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to package the bundled 小红书发布器")
    path = Path(node)
    if not path.is_file():
        raise RuntimeError(f"Node.js executable does not exist: {path}")
    return path


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
    if not (PUBLISHERS_DIR / "xhs-mcp" / "dist" / "index.js").is_file():
        raise RuntimeError("xhs-mcp is not built. Run npm install and npm run build in vendor/publishers/xhs-mcp first.")
    if not (PUBLISHERS_DIR / "xhs-mcp" / "node_modules").is_dir():
        raise RuntimeError("xhs-mcp dependencies are missing. Run npm install in vendor/publishers/xhs-mcp first.")
    require_build_dependency("PyInstaller", "pyinstaller")
    tos_version = require_build_dependency("tos", "tos")
    require_build_dependency("yt_dlp", "yt-dlp")
    require_build_dependency("playwright", "playwright")
    node = bundled_node_executable()

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
        publishers = publisher_runtime_tree(temp_root / "publishers")

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
            console=False,
        )
        downloader = build_onefile(
            runner,
            "yt-dlp",
            dist_dir,
            work_root,
            ["--collect-all", "yt_dlp"],
        )
        publisher_args = ["--paths", str(PUBLISHERS_DIR), "--collect-all", "playwright"]
        douyin_publisher = build_onefile(
            PUBLISHERS_DIR / "douyin-auto-publish" / "scripts" / "dy_video_publish.py",
            "douyin-publisher",
            dist_dir,
            work_root,
            publisher_args,
            cwd=PUBLISHERS_DIR / "douyin-auto-publish",
        )
        channels_publisher = build_onefile(
            PUBLISHERS_DIR / "auto-weixin-video" / "scripts" / "publish.py",
            "channels-publisher",
            dist_dir,
            work_root,
            publisher_args,
            cwd=PUBLISHERS_DIR / "auto-weixin-video",
        )
        channels_login = build_onefile(
            PUBLISHERS_DIR / "auto-weixin-video" / "scripts" / "get_cookie.py",
            "channels-login",
            dist_dir,
            work_root,
            publisher_args,
            cwd=PUBLISHERS_DIR / "auto-weixin-video",
        )
        backend = build_onefile(
            ROOT / "app.py",
            "app",
            dist_dir,
            work_root,
            [
                "--add-data",
                data_arg(ROOT / "static", "static"),
                "--add-data",
                data_arg(MEDIA_CRAWLER_DIR / "libs", "mediacrawler-libs"),
                "--add-data",
                data_arg(publishers, "vendor/publishers"),
                "--add-data",
                data_arg(publishers, "vendor/publishers"),
                "--add-binary",
                data_arg(FFMPEG_PATH, "bin"),
                "--add-binary",
                data_arg(crawler, "bin"),
                "--add-binary",
                data_arg(downloader, "bin"),
                "--add-binary",
                data_arg(douyin_publisher, "bin"),
                "--add-binary",
                data_arg(channels_publisher, "bin"),
                "--add-binary",
                data_arg(channels_login, "bin"),
                "--add-binary",
                data_arg(node, "bin"),
                "--collect-all",
                "tos",
                "--collect-all",
                "playwright",
            ],
            console=False,
        )

        shutil.rmtree(DESKTOP_BACKEND_DIR, ignore_errors=True)
        DESKTOP_BACKEND_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backend, DESKTOP_BACKEND_DIR / backend.name)

    BACKEND_MANIFEST.write_text(
        json.dumps(
            {
                "schema": 1,
                "built_at": datetime.now(timezone.utc).isoformat(),
                "platform": sys.platform,
                "machine": platform.machine(),
                "python_version": sys.version.split()[0],
                "backend": backend.name,
                "sources": {"app.py": sha256_file(ROOT / "app.py")},
                "capabilities": {
                    "volcengine_tos_sdk": {"available": True, "version": tos_version},
                    "publisher_adapters": {"available": True, "platforms": ["douyin", "channels", "xiaohongshu"]},
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

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
