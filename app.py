import cgi
import hashlib
import html
import json
import math
import mimetypes
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree
from html.parser import HTMLParser

try:
    import certifi
except ImportError:  # pragma: no cover - the release build installs certifi explicitly
    certifi = None


# Network routing is intentionally direct-only. The app never reads or changes
# Windows proxy settings; child processes also inherit a cleaned environment.
PROXY_ENVIRONMENT_KEYS = (
    "APP_PROXY", "PUBLISHER_PROXY_SERVER",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
)
for _proxy_var in PROXY_ENVIRONMENT_KEYS:
    os.environ.pop(_proxy_var, None)

# 打包成 exe 后（PyInstaller onefile），__file__ 指向临时解压目录，
# 用户数据/配置必须放到 %APPDATA% 下持久保存；静态资源和 bin 从解压目录读取。
IS_FROZEN = bool(getattr(sys, "frozen", False))
if IS_FROZEN:
    if sys.platform == "darwin":
        data_base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        data_base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        data_base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    APP_DATA_DIR = data_base / "MP4GoldenClipWorkbench"
    RES_ROOT = Path(getattr(sys, "_MEIPASS", APP_DATA_DIR))
    ROOT = APP_DATA_DIR
    STATIC_DIR = RES_ROOT / "static"
    BIN_DIR = RES_ROOT / "bin"
else:
    ROOT = Path(__file__).resolve().parent
    STATIC_DIR = ROOT / "static"
    BIN_DIR = ROOT / "bin"
DATA_DIR = ROOT / "data"
JOBS_DIR = DATA_DIR / "jobs"
OUTPUTS_DIR = DATA_DIR / "outputs"
RUNTIME_DIR = DATA_DIR / "runtime"
TRENDS_DIR = DATA_DIR / "trends"
TREND_ARTICLE_CACHE_DIR = TRENDS_DIR / "article-cache"
TREND_KNOWLEDGE_PATH = TRENDS_DIR / "taste-knowledge.json"
MEDIA_CRAWLER_DIR = ROOT / "vendor" / "MediaCrawler"
MEDIA_CRAWLER_VENV_DIR = MEDIA_CRAWLER_DIR / ".venv"
MEDIA_CRAWLER_RUNTIME_DIR = RUNTIME_DIR / "mediacrawler"
MEDIA_CRAWLER_BUNDLED_LIBS_DIR = (
    RES_ROOT / "mediacrawler-libs" if IS_FROZEN else MEDIA_CRAWLER_DIR / "libs"
)
PUBLISHERS_DIR = RES_ROOT / "vendor" / "publishers" if IS_FROZEN else ROOT / "vendor" / "publishers"
PUBLISHER_RUNTIME_DIR = RUNTIME_DIR / "publishers"
PUBLISH_CHROME_PROFILE_DIR = PUBLISHER_RUNTIME_DIR / "chrome"
PUBLISH_LOCAL_ASSETS_DIR = RUNTIME_DIR / "publish-assets"
YTDLP_PACKAGE_DIR = (RES_ROOT / "tools" / "yt-dlp") if IS_FROZEN else (ROOT.parent / ".tools" / "yt-dlp")
SETTINGS_PATH = ROOT / "user-settings.json"
PACKAGED_PROFILE_MARKER = ROOT / ".profile-initialized-v3"
TASKS_PATH = RUNTIME_DIR / "tasks.json"
PUBLISH_TASKS_PATH = RUNTIME_DIR / "publish_tasks.json"
PUBLISH_LOGIN_TASKS_PATH = RUNTIME_DIR / "publish_login_tasks.json"
PUBLISH_LOCAL_ASSETS_PATH = RUNTIME_DIR / "publish_local_assets.json"
PUBLISH_DIAGNOSTICS_PATH = RUNTIME_DIR / "publish-diagnostics.jsonl"
NETWORK_SETTINGS_PATH = RUNTIME_DIR / "network-settings.json"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8789"))
MEDIA_CRAWLER_TIMEOUT = max(60, int(os.environ.get("MEDIA_CRAWLER_TIMEOUT", "300")))

JOB_LOCK = threading.Lock()
JOBS = {}
UPLOAD_LOCK = threading.Lock()
CLIP_TASK_LOCK = threading.Lock()
CLIP_TASKS = {}
TASK_PERSIST_LAST = 0.0
TASK_PERSIST_MIN_INTERVAL = 0.75
TREND_TASK_LOCK = threading.Lock()
TREND_TASKS = {}
TREND_DISCOVERY_LOCK = threading.Lock()
ACTIVE_TREND_DISCOVERY_TASK_ID = None
TREND_HOTSPOT_LOCK = threading.Lock()
ACTIVE_TREND_HOTSPOT_TASK_ID = None
BROLL_TASK_LOCK = threading.Lock()
BROLL_TASKS = {}
BROLL_SEARCH_LOCK = threading.Lock()
ACTIVE_BROLL_SEARCH_TASK_ID = None
PUBLISH_TASK_LOCK = threading.Lock()
PUBLISH_TASKS = {}
PUBLISH_LOGIN_LOCK = threading.Lock()
PUBLISH_LOGIN_TASKS = {}
PUBLISH_LOGIN_WORKERS = {}
PUBLISH_LOGIN_CANCEL_EVENTS = {}
PUBLISH_BROWSER_LOCK = threading.Lock()
PUBLISHER_USER_CLOSED_WINDOW_MARKER = "PUBLISHER_USER_CLOSED_WINDOW"
PUBLISH_MANUAL_TASK_PROBE_LAST = 0.0
PUBLISH_MANUAL_TASK_PROBE_INTERVAL = 2.0

PUBLISH_PLATFORMS = {
    "douyin": {
        "id": "douyin", "name": "抖音", "status": "local_adapter_ready",
        "label": "douyin-auto-publish · Google Chrome 直接启动", "supports_video": True,
        "supports_metadata": True, "requires_oauth": True,
        "adapter": "douyin-auto-publish", "ai_used": False,
    },
    "xiaohongshu": {
        "id": "xiaohongshu", "name": "小红书", "status": "local_adapter_ready",
        "label": "xhs-mcp · MCP HTTP", "supports_video": True,
        "supports_metadata": True, "requires_oauth": True,
        "adapter": "xhs-mcp", "ai_used": False,
    },
    "channels": {
        "id": "channels", "name": "视频号", "status": "local_adapter_ready",
        "label": "auto-weixin-video · Google Chrome 直接启动", "supports_video": True,
        "supports_metadata": True, "requires_oauth": True,
        "adapter": "auto-weixin-video", "ai_used": False,
    },
}
class PublishWindowClosedByUser(RuntimeError):
    """The user closed the visible platform window before the task completed."""


def _publisher_window_closed_by_user(detail):
    text = str(detail or "")
    return (
        PUBLISHER_USER_CLOSED_WINDOW_MARKER in text
        or "TargetClosedError" in text
        or "Target page, context or browser has been closed" in text
        or "登录窗口已关闭" in text
        or "用户已关闭" in text
    )


def _publish_window_closed_message(platform):
    name = PUBLISH_PLATFORMS.get(platform, {}).get("name") or "平台"
    return f"用户已关闭{name}发布窗口，任务已停止，未发布。"


def _login_window_closed_message(platform):
    name = PUBLISH_PLATFORMS.get(platform, {}).get("name") or "平台"
    return f"用户已关闭{name}登录窗口，登录准备已停止。"


def record_publish_diagnostic(platform, event, cause, resolution, detail=""):
    """Append a sanitized publisher diagnosis for later troubleshooting."""
    PUBLISH_DIAGNOSTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "platform": str(platform or ""),
        "event": str(event or ""),
        "cause": str(cause or "")[:500],
        "resolution": str(resolution or "")[:500],
        "detail": str(detail or "")[-1500:],
    }
    try:
        with PUBLISH_DIAGNOSTICS_PATH.open("a", encoding="utf-8") as output:
            output.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass





def ensure_dirs():
    initialize_frozen_profile()
    for path in (STATIC_DIR, JOBS_DIR, OUTPUTS_DIR, RUNTIME_DIR, TRENDS_DIR, PUBLISHER_RUNTIME_DIR, PUBLISH_CHROME_PROFILE_DIR, PUBLISH_LOCAL_ASSETS_DIR):
        path.mkdir(parents=True, exist_ok=True)
    ensure_media_crawler_resources()


def ensure_media_crawler_resources():
    """Deploy MediaCrawler's runtime JavaScript assets beside its working directory.

    MediaCrawler imports several platform modules at process startup. Those modules
    read files such as ``libs/douyin.js`` using paths relative to the process cwd,
    so PyInstaller's ``_MEIPASS`` resource directory is not visible to them. The
    packaged backend therefore copies the read-only bundled assets into the
    writable runtime directory used as MediaCrawler's cwd.
    """
    if not IS_FROZEN:
        return
    source_dir = MEDIA_CRAWLER_BUNDLED_LIBS_DIR
    if not source_dir.is_dir():
        raise RuntimeError(
            "打包资源缺少 MediaCrawler 脚本目录，请重新构建桌面后端"
        )
    target_dir = MEDIA_CRAWLER_RUNTIME_DIR / "libs"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        for source in source_dir.iterdir():
            if not source.is_file():
                continue
            target = target_dir / source.name
            if (
                not target.exists()
                or target.stat().st_size != source.stat().st_size
                or target.stat().st_mtime_ns < source.stat().st_mtime_ns
            ):
                shutil.copy2(source, target)
    except OSError as exc:
        raise RuntimeError(f"MediaCrawler 脚本资源部署失败：{exc}") from exc


def initialize_frozen_profile():
    """Start packaged builds with an empty, private user profile.

    A development ``user-settings.json`` must never be carried into an exe.
    Jobs, cached search results, and exports also start empty. The marker is
    created only in the per-user APPDATA directory, so everything the user
    creates in the packaged app remains available on later starts.
    """
    if not IS_FROZEN or PACKAGED_PROFILE_MARKER.exists():
        return
    # Do not migrate or copy settings or task data from bundled application
    # files. This one-time reset also clears APPDATA left by older builds that
    # displayed development providers, task history, or storage entries.
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    write_json(SETTINGS_PATH, {})
    PACKAGED_PROFILE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    PACKAGED_PROFILE_MARKER.write_text("3\n", encoding="utf-8")


def json_response(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    # Task and publish state changes frequently; never let a browser cache an old snapshot.
    handler.send_header("Cache-Control", "no-store, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Expires", "0")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


_NO_PROXY_OPENER = None
_HTTPS_SSL_CONTEXT = None
class ExternalNetworkError(RuntimeError):
    """External network failure with a message suitable for any provider."""


def public_proxy_url():
    """Compatibility API for diagnostics; request routing remains direct-only."""
    return _windows_system_proxy_url()


def _windows_system_proxy_url():
    """Legacy compatibility hook; Windows proxy settings are never consulted."""
    return ""


def remember_public_proxy_candidate():
    """Remove a legacy proxy cache left by earlier versions of the app."""
    settings = read_json(NETWORK_SETTINGS_PATH, {})
    if isinstance(settings, dict) and settings.pop("app_proxy", None) is not None:
        write_json(NETWORK_SETTINGS_PATH, settings)


def strip_proxy_environment(environment):
    """Return a child-process environment that cannot configure a proxy."""
    for key in PROXY_ENVIRONMENT_KEYS:
        environment.pop(key, None)
    return environment


def https_ssl_context():
    """Return a verified context with both system and certifi trust roots."""
    global _HTTPS_SSL_CONTEXT
    if _HTTPS_SSL_CONTEXT is None:
        context = ssl.create_default_context()
        if certifi is not None:
            # PyInstaller does not always discover certifi's PEM data through
            # import analysis alone, so the build explicitly bundles it below.
            context.load_verify_locations(cafile=certifi.where())
        _HTTPS_SSL_CONTEXT = context
    return _HTTPS_SSL_CONTEXT


def http_opener():
    """Return the direct-only opener used for local and fallback requests."""
    global _NO_PROXY_OPENER
    if _NO_PROXY_OPENER is None:
        _NO_PROXY_OPENER = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=https_ssl_context()),
        )
    return _NO_PROXY_OPENER


def proxy_http_opener():
    """Compatibility API retained for callers; proxy routing is disabled."""
    return None


def public_proxy_is_available(target_url):
    return False


def http_openers():
    # ``proxy_http_opener`` is a no-op in production. Keeping the optional
    # slot makes old diagnostics/tests that inject a custom opener harmless,
    # while Windows settings can never create one.
    proxy_opener = proxy_http_opener()
    return (proxy_opener, http_opener()) if proxy_opener is not None else (http_opener(),)


def open_public_request(request, timeout):
    """Open a public request through the direct-only urllib opener."""
    errors = []
    openers = http_openers()
    for index, opener in enumerate(openers):
        try:
            return opener.open(request, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError) as exc:
            errors.append(("直连", exc))
    last_route, last_error = errors[-1] if errors else ("直连", RuntimeError("unknown network error"))
    reason = getattr(last_error, "reason", last_error)
    if getattr(reason, "winerror", None) == 10013 or getattr(last_error, "winerror", None) == 10013:
        raise ExternalNetworkError(
            f"外部网络连接（{last_route}）被系统拒绝（WinError 10013）。请检查 Windows 防火墙、网络或安全软件。"
        ) from last_error
    if getattr(reason, "winerror", None) == 10061 or getattr(last_error, "winerror", None) == 10061:
        routes = "；".join(f"{route}: {getattr(err, 'reason', err)}" for route, err in errors)
        raise ExternalNetworkError(f"无法连接外部服务（WinError 10061）：{routes}") from last_error
    raise ExternalNetworkError(f"无法连接外部服务：{reason}") from last_error


def error_response(handler, message, status=400, **extra):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    json_response(handler, payload, status)


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_publish_tasks():
    global PUBLISH_TASKS
    saved = read_json(PUBLISH_TASKS_PATH, {})
    if isinstance(saved, dict):
        PUBLISH_TASKS = saved
    else:
        PUBLISH_TASKS = {}
    changed = False
    for task in PUBLISH_TASKS.values():
        window_closed = (
            task.get("status") == "error"
            and _publisher_window_closed_by_user(
                "\n".join([
                    str(task.get("message") or ""),
                    str(task.get("error") or ""),
                    str((task.get("result") or {}).get("output") or ""),
                ])
            )
        )
        interrupted = task.get("status") in {"queued", "running"}
        manual_page_lost = (
            task.get("status") == "succeeded"
            and task.get("result_state") == "awaiting_manual_confirmation"
        )
        if window_closed:
            task["status"] = "cancelled"
            task["result_state"] = "cancelled_by_user"
            task["message"] = _publish_window_closed_message(task.get("platform"))
            task["error"] = ""
            task["updated_at"] = datetime.now().isoformat(timespec="seconds")
            changed = True
        elif interrupted or manual_page_lost:
            task["status"] = "error"
            task["result_state"] = "interrupted"
            task["message"] = "应用已重启，无法确认此前的 Chrome 发布页仍可见，请重新执行。"
            task["error"] = "应用重启中断浏览器发布状态"
            task["updated_at"] = datetime.now().isoformat(timespec="seconds")
            changed = True
    if changed:
        write_json(PUBLISH_TASKS_PATH, PUBLISH_TASKS)
    return len(PUBLISH_TASKS)


def load_publish_login_tasks():
    """Restore login-task feedback without treating a stopped app as still logging in."""
    global PUBLISH_LOGIN_TASKS
    saved = read_json(PUBLISH_LOGIN_TASKS_PATH, {})
    PUBLISH_LOGIN_TASKS = saved if isinstance(saved, dict) else {}
    changed = False
    for task in PUBLISH_LOGIN_TASKS.values():
        detail = "\n".join([
            str(task.get("message") or ""),
            str(task.get("error") or ""),
        ])
        if task.get("status") == "error" and _publisher_window_closed_by_user(detail):
            task["status"] = "cancelled"
            task["message"] = _login_window_closed_message(task.get("platform"))
            task["error"] = ""
            task["updated_at"] = datetime.now().isoformat(timespec="seconds")
            changed = True
        elif task.get("status") in {"queued", "running", "waiting", "verification_required"}:
            task["status"] = "interrupted"
            task["message"] = "应用已重启，请重新发起登录准备"
            task["updated_at"] = datetime.now().isoformat(timespec="seconds")
            changed = True
    if changed:
        write_json(PUBLISH_LOGIN_TASKS_PATH, PUBLISH_LOGIN_TASKS)
    return len(PUBLISH_LOGIN_TASKS)


def persist_publish_tasks():
    with PUBLISH_TASK_LOCK:
        write_json(PUBLISH_TASKS_PATH, PUBLISH_TASKS)


def _publisher_runtime(platform):
    runtime_dir = PUBLISHER_RUNTIME_DIR / platform
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def _publisher_login_paths(platform):
    runtime_dir = _publisher_runtime(platform)
    if platform == "douyin":
        return {"state_file": runtime_dir / "douyin_state.json"}
    if platform == "channels":
        return {
            "cookie_dir": runtime_dir / "cookies",
            "cookie_file": runtime_dir / "cookies" / "weixin_video.json",
            "browser_data": runtime_dir / "browser_data",
        }
    if platform == "xiaohongshu":
        return {"data_dir": runtime_dir}
    return {}


def _state_file_looks_saved(path):
    if not path or not Path(path).is_file():
        return False
    try:
        payload = read_json(Path(path), {})
        return bool(payload.get("cookies") or payload.get("origins"))
    except Exception:
        return False


def _restore_state_cookies_into_context(context, state_file):
    """Import cookies without the legacy localStorage payload that crashes Chrome."""
    if not _state_file_looks_saved(state_file):
        return
    payload = read_json(Path(state_file), {})
    cookies = payload.get("cookies") or []
    if cookies:
        context.add_cookies(cookies)


def _publish_login_state(platform):
    paths = _publisher_login_paths(platform)
    with PUBLISH_LOGIN_LOCK:
        latest = next(
            (
                dict(item) for item in sorted(
                    PUBLISH_LOGIN_TASKS.values(),
                    key=lambda item: item.get("updated_at") or item.get("created_at") or "",
                    reverse=True,
                )
                if item.get("platform") == platform
            ),
            None,
        )
    active_statuses = {"queued", "running", "waiting", "verification_required"}
    if platform == "douyin":
        saved = _state_file_looks_saved(paths.get("state_file"))
    elif platform == "channels":
        saved = _state_file_looks_saved(paths.get("cookie_file"))
    elif platform == "xiaohongshu":
        saved = bool((latest or {}).get("result", {}).get("status") == "success")
    else:
        saved = False
    active = latest if latest and latest.get("status") in active_statuses else None
    if active:
        label = active.get("message") or "正在准备登录"
    elif saved:
        label = "已保存登录态；平台仍可能要求重新验证"
    elif latest and latest.get("status") == "error":
        latest_message = str(latest.get("message") or "")
        if "spawn EPERM" in latest_message:
            label = "上次浏览器启动被系统拒绝；现在已改用本机 Chrome，请重新点击登录准备"
        else:
            label = latest_message[:180] or "上次登录准备失败"
    else:
        label = "尚未准备登录态"
    return {
        "saved": saved,
        "active": active,
        "latest": latest,
        "label": label,
    }


def publish_capabilities():
    platforms = []
    for item in PUBLISH_PLATFORMS.values():
        current = dict(item)
        adapter = item.get("adapter")
        if adapter:
            current["adapter_present"] = (PUBLISHERS_DIR / adapter).exists()
        else:
            current["adapter_present"] = False
        diagnostics = _adapter_diagnostics(item["id"])
        current.update(diagnostics)
        current["login"] = _publish_login_state(item["id"])
        if not diagnostics.get("ready"):
            current["status"] = "setup_required"
            current["label"] = diagnostics.get("label") or ("需要配置：" + "、".join(diagnostics.get("missing") or ["适配器"]))
        platforms.append(current)
    return {"platforms": platforms, "ai_integrated": False}


def _publisher_python():
    candidate = MEDIA_CRAWLER_VENV_DIR / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    return str(candidate if candidate.exists() else Path(sys.executable))


def _publisher_binary(platform, phase="publish"):
    if not IS_FROZEN:
        return None
    names = {
        ("douyin", "publish"): "douyin-publisher",
        ("channels", "publish"): "channels-publisher",
        ("channels", "login"): "channels-login",
    }
    name = names.get((platform, phase))
    if not name:
        return None
    suffix = ".exe" if os.name == "nt" else ""
    candidate = BIN_DIR / f"{name}{suffix}"
    return str(candidate) if candidate.is_file() else None


def _publisher_site_packages():
    if os.name == "nt":
        return MEDIA_CRAWLER_VENV_DIR / "Lib" / "site-packages"
    candidates = sorted((MEDIA_CRAWLER_VENV_DIR / "lib").glob("python*/site-packages"))
    return candidates[0] if candidates else None


def _chrome_executable():
    """Return Google Chrome only; publishing never falls back to Edge or Chromium."""
    candidates = [
        os.environ.get("PUBLISHER_BROWSER_EXECUTABLE"),
        os.environ.get("GOOGLE_CHROME_BIN"),
    ]
    if os.name == "nt":
        candidates.extend([
            str(Path(os.environ.get("PROGRAMFILES") or "") / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(os.environ.get("PROGRAMFILES(X86)") or "") / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(os.environ.get("LOCALAPPDATA") or "") / "Google" / "Chrome" / "Application" / "chrome.exe"),
        ])
    elif sys.platform == "darwin":
        candidates.extend([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            str(Path.home() / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"),
        ])
    else:
        candidates.extend(["google-chrome", "google-chrome-stable"])
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        name = path.name.lower()
        is_google_chrome = name in {"chrome.exe", "chrome", "google chrome", "google-chrome", "google-chrome-stable"}
        if path.is_file() and is_google_chrome:
            return str(path)
        located = shutil.which(str(candidate))
        if located and Path(located).name.lower() in {"chrome.exe", "chrome", "google chrome", "google-chrome", "google-chrome-stable"}:
            return located
    return None


def _publisher_script(platform):
    if platform == "douyin":
        return PUBLISHERS_DIR / "douyin-auto-publish" / "scripts" / "dy_video_publish.py"
    if platform == "channels":
        return PUBLISHERS_DIR / "auto-weixin-video" / "scripts" / "publish.py"
    return None


def _publisher_command(platform, phase, *arguments):
    binary = _publisher_binary(platform, phase)
    if binary:
        return [binary, *arguments]
    script = _publisher_script(platform) if phase == "publish" else None
    if platform == "channels" and phase == "login":
        script = PUBLISHERS_DIR / "auto-weixin-video" / "scripts" / "get_cookie.py"
    if not script or not script.exists():
        raise RuntimeError(f"未找到 {platform} 发布适配器")
    return [_publisher_python(), str(script), *arguments]


def _python_can_import(module_name):
    """Check a publisher dependency in the same interpreter used to launch it."""
    try:
        completed = subprocess.run(
            [_publisher_python(), "-c", f"import {module_name}"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return completed.returncode == 0
    except Exception:
        return False


def _adapter_diagnostics(platform):
    if platform == "douyin":
        script = _publisher_script(platform)
        chrome = _chrome_executable()
        playwright_ready = bool(_publisher_binary("douyin") or _python_can_import("playwright"))
        ready = bool(script and script.exists() and chrome and playwright_ready)
        missing = []
        if not chrome:
            missing.append("Google Chrome")
        if not playwright_ready:
            missing.append("Playwright Python 依赖")
        return {
            "ready": ready,
            "setup_required": not ready,
            "execution_mode": "chrome_direct" if ready else "unavailable",
            "missing": missing,
            "label": "douyin-auto-publish · Google Chrome 直接启动" if ready else "douyin-auto-publish 需要 Google Chrome 和 Playwright Python 依赖",
            "login_hint": "点击登录准备会直接打开 Google Chrome；douyin-auto-publish 的登录态保存在应用运行目录。",
        }
    if platform == "channels":
        script = _publisher_script(platform)
        chrome = _chrome_executable()
        playwright_ready = bool(_publisher_binary("channels") or _python_can_import("playwright"))
        ready = bool(script and script.exists() and chrome and playwright_ready)
        missing = []
        if not chrome:
            missing.append("Google Chrome")
        if not playwright_ready:
            missing.append("Playwright Python 依赖")
        return {
            "ready": ready,
            "setup_required": not ready,
            "execution_mode": "chrome_direct" if ready else "unavailable",
            "missing": missing,
            "label": "auto-weixin-video · Google Chrome 直接启动" if ready else "auto-weixin-video 需要 Google Chrome 和 Playwright Python 依赖",
            "login_hint": "点击登录准备会直接打开 Google Chrome；auto-weixin-video 负责保存视频号 Cookie。",
        }
    if platform == "xiaohongshu":
        root = PUBLISHERS_DIR / "xhs-mcp"
        built = (root / "dist" / "index.js").exists()
        node = _node_executable()
        running = _xhs_mcp_is_running() if built and node is not None else False
        chrome = _chrome_executable()
        ready = built and node is not None and chrome is not None
        missing = []
        if not built:
            missing.append("xhs-mcp 构建产物 dist/index.js")
        if node is None:
            missing.append("Node.js 运行时")
        if chrome is None:
            missing.append("Google Chrome")
        return {
            "ready": ready,
            "setup_required": not ready,
            "execution_mode": "mcp_http" if ready else "unavailable",
            "missing": missing,
            "service_running": running,
            "label": ("xhs-mcp · MCP HTTP 服务运行中" if running else "xhs-mcp · MCP HTTP 按需启动") if ready else ("需要构建 xhs-mcp" if not built else "需要 Node.js、Google Chrome 运行环境"),
            "login_hint": "点击登录准备后，xhs-mcp 会创建自己的扫码会话并保存账号状态。",
        }
    return {
        "ready": False,
        "setup_required": True,
        "execution_mode": "unavailable",
        "missing": ["平台适配器"],
        "label": "暂未配置平台适配器",
        "login_hint": "当前没有可执行的本地适配器。",
    }


def _node_executable():
    if IS_FROZEN:
        bundled = BIN_DIR / ("node.exe" if os.name == "nt" else "node")
        if bundled.is_file():
            return str(bundled)
    configured = os.environ.get("XHS_MCP_NODE_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured
    return shutil.which("node")


XHS_MCP_PROCESS = None
XHS_MCP_LOCK = threading.Lock()
XHS_MCP_LOG_HANDLE = None


def _xhs_mcp_url():
    url = (os.environ.get("XHS_MCP_URL") or "http://127.0.0.1:18060").rstrip("/")
    return url[:-4] if url.endswith("/mcp") else url


def _xhs_mcp_is_running():
    try:
        request = urllib.request.Request(f"{_xhs_mcp_url()}/health", method="GET")
        with http_opener().open(request, timeout=0.8) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def _tail_text(path, limit=1600):
    try:
        with Path(path).open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - limit), os.SEEK_SET)
            return handle.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def _ensure_xhs_mcp_server():
    """Start the bundled xhs-mcp HTTP service when a built checkout is available."""
    global XHS_MCP_PROCESS, XHS_MCP_LOG_HANDLE
    if _xhs_mcp_is_running():
        return
    root = PUBLISHERS_DIR / "xhs-mcp"
    entry = root / "dist" / "index.js"
    node = _node_executable()
    chrome = _chrome_executable()
    if not entry.exists() or not node or not chrome:
        raise RuntimeError("小红书适配器尚未就绪：需要 xhs-mcp 构建产物、Node.js 和 Google Chrome")
    with XHS_MCP_LOCK:
        if _xhs_mcp_is_running():
            return
        runtime_dir = PUBLISHER_RUNTIME_DIR / "xhs-mcp"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        env = strip_proxy_environment(os.environ.copy())
        env["XHS_MCP_DATA_DIR"] = str(runtime_dir)
        env["XHS_MCP_PORT"] = "18060"
        env["XHS_MCP_HEADLESS"] = "false"
        env["XHS_MCP_KEEP_OPEN"] = "true"
        env["XHS_MCP_LOG_LEVEL"] = "info"
        env["XHS_MCP_CHROME_EXECUTABLE"] = chrome
        log_path = runtime_dir / "xhs-mcp-server.log"
        if XHS_MCP_LOG_HANDLE:
            try:
                XHS_MCP_LOG_HANDLE.close()
            except OSError:
                pass
        XHS_MCP_LOG_HANDLE = log_path.open("a", encoding="utf-8")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        XHS_MCP_PROCESS = subprocess.Popen(
            [node, str(entry), "--http", "--port", "18060"],
            cwd=str(root),
            env=env,
            stdout=XHS_MCP_LOG_HANDLE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        deadline = time.time() + 12
        while time.time() < deadline:
            if _xhs_mcp_is_running():
                return
            if XHS_MCP_PROCESS.poll() is not None:
                break
            time.sleep(0.4)
    detail = _tail_text(log_path)
    if "canvas.node" in detail:
        detail = "缺少 canvas 原生模块；请在 xhs-mcp 目录执行 npm rebuild canvas"
    elif detail:
        detail = detail[-700:]
    raise RuntimeError(
        "小红书适配器启动失败：xhs-mcp HTTP 服务未能在 12 秒内就绪"
        + (f"。详情：{detail}" if detail else "")
    )


def _task_update(task_id, **updates):
    with PUBLISH_TASK_LOCK:
        task = PUBLISH_TASKS.get(task_id)
        if not task:
            return None
        task.update(updates)
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(PUBLISH_TASKS_PATH, PUBLISH_TASKS)
        return dict(task)


def _mcp_http_call(method, params=None, url=None):
    endpoint = (url or _xhs_mcp_url()).rstrip("/")
    if not endpoint.endswith("/mcp"):
        endpoint += "/mcp"
    request_body = {
        "jsonrpc": "2.0",
        "id": uuid4().hex,
        "method": method,
        "params": params or {},
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        method="POST",
    )
    with http_opener().open(request, timeout=30) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        for line in raw.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line.removeprefix("data:").strip())
                except json.JSONDecodeError:
                    continue
        raise RuntimeError(f"xhs-mcp 返回了无法解析的响应：{raw[:300]}")


def _mcp_tool_call(name, arguments):
    init = _mcp_http_call("initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "mp4-golden-clip-workbench", "version": "1.0"},
    })
    if init.get("error"):
        raise RuntimeError(init["error"].get("message") or "xhs-mcp 初始化失败")
    # xhs-mcp uses stateless HTTP transport. Some MCP implementations answer
    # this notification with an empty 202 body, which is valid and needs no
    # JSON response from our client.
    try:
        _mcp_http_call("notifications/initialized", {})
    except Exception:
        pass
    result = _mcp_http_call("tools/call", {"name": name, "arguments": arguments or {}})
    if result.get("error"):
        raise RuntimeError(result["error"].get("message") or f"xhs-mcp 调用 {name} 失败")
    return result


def _mcp_text_payload(result):
    for item in result.get("result", {}).get("content", []) if isinstance(result, dict) else []:
        if item.get("type") != "text":
            continue
        text = item.get("text") or ""
        try:
            return json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return {"text": text}
    return {}


def _xhs_publish(task):
    if task.get("schedule") != "publish_now":
        raise RuntimeError("小红书当前适配器执行后会直接发布，请选择“自动点击发布”并确认后再执行")
    _ensure_xhs_mcp_server()
    result = _mcp_tool_call(
        "xhs_publish_video",
        {
            "title": str(task.get("title") or "")[:20],
            "content": str(task.get("description") or ""),
            "videoPath": str(task["file_path"]),
            "tags": task.get("hashtags") or [],
            "scheduleTime": task.get("schedule_time") or None,
        },
    )
    return {"raw": result, "payload": _mcp_text_payload(result)}


def _login_task_update(login_id, **updates):
    with PUBLISH_LOGIN_LOCK:
        task = PUBLISH_LOGIN_TASKS.get(login_id)
        if not task:
            return None
        task.update(updates)
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(PUBLISH_LOGIN_TASKS_PATH, PUBLISH_LOGIN_TASKS)
        return dict(task)


def list_publish_login_tasks():
    with PUBLISH_LOGIN_LOCK:
        return sorted(PUBLISH_LOGIN_TASKS.values(), key=lambda item: item.get("created_at") or "", reverse=True)


def _login_environment(platform):
    paths = _publisher_login_paths(platform)
    env = strip_proxy_environment(os.environ.copy())
    env["PUBLISHER_AI_DISABLED"] = "1"
    env["PYTHONUTF8"] = "1"
    chrome = _chrome_executable()
    if not chrome:
        raise RuntimeError("未找到 Google Chrome；一键发布不会回退到 Edge 或其他浏览器")
    PUBLISH_CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    env["PUBLISHER_BROWSER_EXECUTABLE"] = chrome
    env["PUBLISHER_CHROME_PROFILE_DIR"] = str(PUBLISH_CHROME_PROFILE_DIR)
    if platform == "douyin":
        env["DOUYIN_STATE_FILE"] = str(paths["state_file"])
        env["DOUYIN_LOG_FILE"] = str(_publisher_runtime(platform) / "douyin.log")
        env["DOUYIN_SCREENSHOT_DIR"] = str(_publisher_runtime(platform) / "screenshots")
        Path(env["DOUYIN_SCREENSHOT_DIR"]).mkdir(parents=True, exist_ok=True)
    elif platform == "channels":
        paths["cookie_dir"].mkdir(parents=True, exist_ok=True)
        paths["browser_data"].mkdir(parents=True, exist_ok=True)
        env["WEIXIN_COOKIE_DIR"] = str(paths["cookie_dir"])
        env["WEIXIN_LOG_DIR"] = str(_publisher_runtime(platform) / "logs")
        env["WEIXIN_BROWSER_DATA_DIR"] = str(paths["browser_data"])
        Path(env["WEIXIN_LOG_DIR"]).mkdir(parents=True, exist_ok=True)
    return env


def _hidden_console_subprocess_kwargs():
    """Do not flash a Windows console when publisher scripts run in the background."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def _reuse_or_create_douyin_creator_page(context):
    """Use the existing creator page before opening another Chrome tab."""
    pages = []
    for page in context.pages:
        try:
            if not page.is_closed():
                pages.append(page)
        except Exception:
            continue
    creator_root = "https://creator.douyin.com/"
    for page in pages:
        if str(page.url or "").rstrip("/") == creator_root.rstrip("/"):
            return page
    for page in pages:
        if str(page.url or "").startswith(creator_root):
            return page
    for page in pages:
        if str(page.url or "") in {"", "about:blank", "chrome://newtab/"}:
            return page
    return context.new_page()


def _douyin_login_prepare(cancel_event=None, on_browser_opened=None, keep_open=True):
    """Use the upstream direct-launch flow to save a Douyin login state."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        site_packages = _publisher_site_packages()
        if site_packages and site_packages.is_dir() and str(site_packages) not in sys.path:
            sys.path.insert(0, str(site_packages))
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("抖音登录准备需要 Playwright Python 依赖") from exc
    publishers_path = str(PUBLISHERS_DIR)
    if publishers_path not in sys.path:
        sys.path.insert(0, publishers_path)
    from chrome_runtime import (
        CHROME_LAUNCH_ARGS,
        PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE,
        keep_only_page,
        prepare_single_visible_page,
        restore_visible_window,
    )
    paths = _publisher_login_paths("douyin")
    state_file = paths["state_file"]
    state_file.parent.mkdir(parents=True, exist_ok=True)
    chrome = _chrome_executable()
    if not chrome:
        raise RuntimeError("未找到 Google Chrome，请安装 Chrome 后再点击登录准备")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            executable_path=chrome,
            ignore_default_args=PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE,
            args=CHROME_LAUNCH_ARGS,
        )
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        _restore_state_cookies_into_context(context, state_file)
        page = prepare_single_visible_page(context, "https://creator.douyin.com/")
        if on_browser_opened:
            on_browser_opened()
        deadline = time.time() + 600
        logged_in = False
        state_saved = False
        try:
            page.goto("https://creator.douyin.com/", wait_until="domcontentloaded", timeout=60000)
            keep_only_page(context, page)
            restore_visible_window(page)
            while time.time() < deadline:
                if cancel_event and cancel_event.is_set():
                    raise RuntimeError("登录准备已由新的请求替换")
                if page.is_closed():
                    if state_saved:
                        break
                    raise RuntimeError("登录窗口已关闭，尚未保存登录态。可再次点击“登录准备”重新打开。")
                current_url = page.url.lower()
                try:
                    text = page.locator("body").inner_text(timeout=3000)
                except Exception:
                    text = ""
                cookies = context.cookies()
                has_session = any("sessionid" in str(cookie.get("name") or "").lower() for cookie in cookies)
                if has_session and "login" not in current_url and not any(marker in text for marker in ("扫码登录", "手机号登录")):
                    logged_in = True
                    if not state_saved:
                        context.storage_state(path=str(state_file))
                        state_saved = True
                    break
                time.sleep(1)
            if not logged_in:
                raise RuntimeError("等待抖音登录超时（10 分钟），请重新点击登录准备")
            if not state_saved:
                context.storage_state(path=str(state_file))
        finally:
            try:
                browser.close()
            except Exception:
                pass
    if not _state_file_looks_saved(state_file):
        raise RuntimeError("抖音登录态未能保存，请重新扫码登录")


def _channels_login_prepare():
    script = PUBLISHERS_DIR / "auto-weixin-video" / "scripts" / "get_cookie.py"
    if not script.exists():
        raise RuntimeError("未找到视频号登录准备脚本")
    completed = subprocess.run(
        _publisher_command("channels", "login"),
        cwd=str(script.parent.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=720,
        env=_login_environment("channels"),
        **_hidden_console_subprocess_kwargs(),
    )
    output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    if completed.returncode != 0:
        raise RuntimeError(output[-2000:] or "视频号登录准备失败")
    cookie_file = _publisher_login_paths("channels")["cookie_file"]
    if not _state_file_looks_saved(cookie_file):
        raise RuntimeError("视频号登录态未能保存，请在打开的浏览器完成扫码后重试")


def _xhs_login_prepare():
    _ensure_xhs_mcp_server()
    return _mcp_text_payload(_mcp_tool_call("xhs_add_account", {}))


def publish_login_worker(login_id, cancel_event=None):
    task = _login_task_update(
        login_id,
        status="running",
        message="正在打开平台登录窗口，请在浏览器中完成登录",
        started_at=datetime.now().isoformat(timespec="seconds"),
    )
    if not task:
        return
    browser_lock_acquired = False
    try:
        PUBLISH_BROWSER_LOCK.acquire()
        browser_lock_acquired = True
        platform = task["platform"]
        record_publish_diagnostic(platform, "login_started", "用户发起登录准备", "启动平台登录页", f"login_id={login_id}")
        if platform == "douyin":
            _douyin_login_prepare(
                cancel_event=cancel_event,
                on_browser_opened=lambda: _login_task_update(
                    login_id,
                    status="waiting",
                    message="浏览器已打开，请在抖音创作者中心完成登录",
                ),
                keep_open=True,
            )
            result = {"saved": True}
            message = "抖音登录态已保存，后续发布将自动复用"
        elif platform == "channels":
            _channels_login_prepare()
            result = {"saved": True}
            message = "视频号登录态已保存，后续发布将自动复用"
        elif platform == "xiaohongshu":
            result = _xhs_login_prepare()
            login_status = result.get("status")
            if login_status == "success":
                _login_task_update(login_id, status="succeeded", message="小红书登录态已保存", result=result)
            else:
                _login_task_update(
                    login_id,
                    status="waiting",
                    message="小红书登录页已打开，请在浏览器中扫码后点击“检查登录”",
                    result=result,
                )
            return
        else:
            raise RuntimeError("该平台尚未配置登录适配器")
        _login_task_update(login_id, status="succeeded", message=message, result=result)
        record_publish_diagnostic(platform, "login_finished", "登录态已保存", message)
    except Exception as exc:
        with PUBLISH_LOGIN_LOCK:
            cancelled = PUBLISH_LOGIN_TASKS.get(login_id, {}).get("status") == "cancelled"
        if not cancelled:
            if _publisher_window_closed_by_user(exc):
                message = _login_window_closed_message(task.get("platform"))
                _login_task_update(login_id, status="cancelled", message=message, error="")
                record_publish_diagnostic(task.get("platform"), "login_cancelled", "用户关闭了登录窗口", message)
            else:
                _login_task_update(login_id, status="error", message=str(exc), error=str(exc))
                record_publish_diagnostic(
                    task.get("platform"),
                    "login_failed",
                    str(exc),
                    "查看 AGENTS.md 中同类原因；修复后重新点击登录准备。",
                )
    finally:
        if browser_lock_acquired:
            PUBLISH_BROWSER_LOCK.release()
        with PUBLISH_LOGIN_LOCK:
            PUBLISH_LOGIN_WORKERS.pop(login_id, None)
            PUBLISH_LOGIN_CANCEL_EVENTS.pop(login_id, None)


def check_publish_login(login_id):
    login_id = str(login_id or "").strip()
    with PUBLISH_LOGIN_LOCK:
        task = PUBLISH_LOGIN_TASKS.get(login_id)
        if not task:
            raise RuntimeError("找不到登录准备任务")
        task = dict(task)
    if task.get("platform") != "xiaohongshu":
        return task
    session_id = str((task.get("result") or {}).get("sessionId") or "").strip()
    if not session_id:
        raise RuntimeError("小红书登录会话信息不完整，请重新点击登录准备")
    _ensure_xhs_mcp_server()
    result = _mcp_text_payload(_mcp_tool_call("xhs_check_login_session", {"sessionId": session_id}))
    status = str(result.get("status") or "waiting_scan")
    if status == "success":
        return _login_task_update(login_id, status="succeeded", message="小红书登录态已保存", result=result)
    if status == "verification_required":
        return _login_task_update(
            login_id,
            status="verification_required",
            message="小红书要求短信验证，请完成平台验证后再检查登录",
            result=result,
        )
    if status in {"failed", "expired"}:
        return _login_task_update(
            login_id,
            status="error",
            message="小红书登录会话已失效，请重新点击登录准备",
            result=result,
            error=result.get("error") or status,
        )
    return _login_task_update(
        login_id,
        status="waiting",
        message="等待小红书扫码登录",
        result=result,
    )


def start_publish_login(platform, restart=False):
    platform = str(platform or "").strip()
    if platform not in PUBLISH_PLATFORMS:
        raise RuntimeError("不支持的发布平台")
    diagnostics = _adapter_diagnostics(platform)
    if not diagnostics.get("ready") and platform != "xiaohongshu":
        raise RuntimeError(diagnostics.get("label") or "发布适配器尚未就绪")
    if platform == "xiaohongshu" and not (PUBLISHERS_DIR / "xhs-mcp" / "dist" / "index.js").exists():
        raise RuntimeError("小红书适配器尚未构建，暂时无法登录")
    with PUBLISH_LOGIN_LOCK:
        existing = next(
            (
                item for item in sorted(
                    PUBLISH_LOGIN_TASKS.values(),
                    key=lambda current: current.get("created_at") or "",
                    reverse=True,
                )
                if item.get("platform") == platform
                and item.get("status") in {"queued", "running", "waiting", "verification_required"}
            ),
            None,
        )
        if existing:
            worker = PUBLISH_LOGIN_WORKERS.get(existing.get("login_id"))
            worker_is_running = bool(worker and worker.is_alive())
            if not restart and worker_is_running:
                return dict(existing)
            cancel_event = PUBLISH_LOGIN_CANCEL_EVENTS.get(existing.get("login_id"))
            if cancel_event:
                cancel_event.set()
            existing["status"] = "cancelled"
            existing["message"] = "已由新的登录准备替代"
            existing["updated_at"] = datetime.now().isoformat(timespec="seconds")
        now = datetime.now().isoformat(timespec="seconds")
        login_id = f"publish-login-{uuid4().hex[:12]}"
        task = {
            "login_id": login_id,
            "platform": platform,
            "platform_name": PUBLISH_PLATFORMS[platform]["name"],
            "status": "queued",
            "message": "已加入登录准备队列",
            "created_at": now,
            "updated_at": now,
        }
        PUBLISH_LOGIN_TASKS[login_id] = task
        write_json(PUBLISH_LOGIN_TASKS_PATH, PUBLISH_LOGIN_TASKS)
        cancel_event = threading.Event()
        worker = threading.Thread(target=publish_login_worker, args=(login_id, cancel_event), daemon=True)
        PUBLISH_LOGIN_CANCEL_EVENTS[login_id] = cancel_event
        PUBLISH_LOGIN_WORKERS[login_id] = worker
    worker.start()
    return task


def _run_publisher_task(task):
    platform = task.get("platform")
    if platform == "xiaohongshu":
        return _xhs_publish(task)
    script = _publisher_script(platform)
    if not script or not script.exists():
        raise RuntimeError(f"未找到 {platform} 发布适配器")
    video_path = Path(str(task.get("file_path") or ""))
    if not video_path.is_file():
        raise RuntimeError("成片文件不存在，请刷新成片列表")
    login = _publish_login_state(platform)
    if not login.get("saved"):
        raise RuntimeError(f"{PUBLISH_PLATFORMS[platform]['name']}尚未保存登录态，请先点击上方“登录准备”完成登录")
    title = str(task.get("title") or video_path.stem)
    description = str(task.get("description") or "")
    short_title = str((task.get("platform_payload") or {}).get("short_title") or "").strip()
    hashtags = " ".join(f"#{tag}" for tag in (task.get("hashtags") or []))
    command = _publisher_command(platform, "publish", "--video", str(video_path), "--title", title)
    if platform == "douyin":
        command = _publisher_command("douyin", "publish", str(video_path), "--title", title, "--body", description, "--topics", hashtags, "--location", "")
        if task.get("schedule") == "publish_now":
            command.append("--publish")
    elif platform == "channels":
        command = _publisher_command(
            "channels",
            "publish",
            "--video",
            str(video_path),
            "--title",
            description or title,
            "--short-title",
            short_title,
            "--tags",
            hashtags,
            "--no-location",
        )
        if task.get("schedule") == "manual_review":
            command.append("--manual-finish")
        elif task.get("schedule") == "draft":
            command.append("--draft")
    env = strip_proxy_environment(os.environ.copy())
    env.update(_login_environment(platform))
    completed = subprocess.run(
        command,
        cwd=str(script.parent.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        env=env,
        **_hidden_console_subprocess_kwargs(),
    )
    output = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    if completed.returncode != 0:
        if _publisher_window_closed_by_user(output):
            raise PublishWindowClosedByUser(_publish_window_closed_message(platform))
        if "ERR_NETWORK_ACCESS_DENIED" in output:
            raise RuntimeError(
                "抖音发布页无法访问：浏览器网络连接被系统拒绝（ERR_NETWORK_ACCESS_DENIED）。"
                "当前发布器未设置代理；请检查 Windows 防火墙、VPN 或安全软件的网络限制后重试。"
            )
        if "BrowserType.launch: spawn EPERM" in output:
            raise RuntimeError("浏览器启动被系统拒绝（spawn EPERM）。请关闭占用中的 Chrome 后重试，或检查安全软件拦截。")
        raise RuntimeError(output[-2000:] or f"发布进程退出码 {completed.returncode}")
    return {"output": output[-4000:]}


def publish_task_worker(task_id):
    task = _task_update(task_id, status="running", message="正在启动 Chrome 并打开平台发布页", started_at=datetime.now().isoformat(timespec="seconds"))
    if not task:
        return
    record_publish_diagnostic(
        task.get("platform"),
        "publish_started",
        "用户发起一键发布",
        "启动对应平台的本地发布器",
        f"task_id={task_id}",
    )
    try:
        # Keep one publisher browser active at a time. On this Windows setup,
        # concurrently creating two Playwright Chrome contexts can close both
        # drivers before either platform page is ready.
        with PUBLISH_BROWSER_LOCK:
            result = _run_publisher_task(task)
        platform = task.get("platform")
        schedule = task.get("schedule")
        if schedule == "manual_review":
            state = "awaiting_manual_confirmation"
            message = "已打开并填写发布页，请在浏览器中检查后手动发布"
        elif schedule == "draft":
            state = "draft_saved"
            message = "平台草稿流程已完成"
        elif platform == "xiaohongshu":
            payload = result.get("payload") or {}
            state = "scheduled" if payload.get("scheduled") else ("published" if payload.get("success") else "unknown")
            message = "小红书发布流程已完成" if state != "unknown" else "小红书已返回结果，请在平台确认发布状态"
        else:
            state = "published_or_pending_review"
            message = "已提交发布流程，请在平台作品列表确认审核状态"
        _task_update(task_id, status="succeeded", result_state=state, message=message, result=result)
        record_publish_diagnostic(task.get("platform"), "publish_finished", "发布器正常返回", message)
    except PublishWindowClosedByUser as exc:
        _task_update(
            task_id,
            status="cancelled",
            result_state="cancelled_by_user",
            message=str(exc),
            error="",
        )
        record_publish_diagnostic(task.get("platform"), "publish_cancelled", "用户关闭了发布窗口", str(exc))
    except Exception as exc:
        _task_update(task_id, status="error", message=str(exc), error=str(exc))
        record_publish_diagnostic(
            task.get("platform"),
            "publish_failed",
            str(exc),
            "查看 AGENTS.md 中同类原因；修复后重新执行。",
        )


def execute_publish_tasks(task_ids):
    requested = [str(item).strip() for item in (task_ids or []) if str(item).strip()]
    if not requested:
        raise RuntimeError("请至少选择一个发布任务")
    with PUBLISH_TASK_LOCK:
        selected_tasks = [PUBLISH_TASKS[task_id] for task_id in requested if task_id in PUBLISH_TASKS]
    if not selected_tasks:
        raise RuntimeError("找不到可执行的发布任务")
    for task in selected_tasks:
        platform = task.get("platform")
        if platform in {"douyin", "channels"} and not _publish_login_state(platform).get("saved"):
            raise RuntimeError(f"{PUBLISH_PLATFORMS[platform]['name']}尚未保存登录态，请先点击“登录准备”并完成登录")
    started = []
    with PUBLISH_TASK_LOCK:
        for task_id in requested:
            task = PUBLISH_TASKS.get(task_id)
            if not task:
                continue
            if task.get("status") == "running":
                continue
            task["status"] = "queued"
            task["message"] = "已加入发布队列"
            task["updated_at"] = datetime.now().isoformat(timespec="seconds")
            started.append(task_id)
        write_json(PUBLISH_TASKS_PATH, PUBLISH_TASKS)
    for task_id in started:
        threading.Thread(target=publish_task_worker, args=(task_id,), daemon=True).start()
    return [PUBLISH_TASKS[item] for item in started]


def sanitize_name(name):
    stem = Path(name).stem.strip() or "video"
    stem = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", stem, flags=re.UNICODE).strip(".-")
    return stem[:48] or "video"


def sanitize_output_name(name):
    """Keep a readable source-video name while making it safe for Windows folders."""
    stem = Path(name).stem.strip() or "video"
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", stem).rstrip(". ")
    return stem[:100] or "video"


def suffixed_name(base_name, index):
    """Append a readable duplicate suffix while keeping the Windows folder name valid."""
    suffix = f"（{index}）"
    return f"{base_name[: max(1, 100 - len(suffix))].rstrip('. ')}{suffix}"


def unique_task_title(filename):
    """Use one user-facing name for the task tab and its result folder."""
    base_name = sanitize_output_name(filename)
    used_names = set()
    for path in JOBS_DIR.glob("*"):
        if not path.is_dir():
            continue
        meta = read_json(path / "metadata.json", {})
        for key in ("title", "output_title", "output_folder"):
            value = str(meta.get(key) or "").strip()
            if value:
                used_names.add(value.casefold())
    if OUTPUTS_DIR.exists():
        used_names.update(path.name.casefold() for path in OUTPUTS_DIR.iterdir() if path.is_dir())

    candidate = base_name
    index = 1
    while candidate.casefold() in used_names or (OUTPUTS_DIR / candidate).exists():
        candidate = suffixed_name(base_name, index)
        index += 1
    return candidate


def job_dir(job_id):
    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]", "", job_id)
    return JOBS_DIR / safe


def trend_search_path(search_id):
    safe = re.sub(r"[^0-9A-Za-z_-]", "", str(search_id or ""))
    return TRENDS_DIR / f"{safe}.json"


def trend_person_pool_path(pool_id):
    safe = re.sub(r"[^0-9A-Za-z_-]", "", str(pool_id or ""))
    return TRENDS_DIR / f"{safe}.json"


def trend_hotspot_pool_path(pool_id):
    safe = re.sub(r"[^0-9A-Za-z_-]", "", str(pool_id or ""))
    return TRENDS_DIR / f"{safe}.json"


def trend_knowledge_store():
    data = read_json(TREND_KNOWLEDGE_PATH, {"entries": []})
    if not isinstance(data, dict):
        data = {"entries": []}
    if not isinstance(data.get("entries"), list):
        data["entries"] = []
    changed = False
    normalized_entries = []
    for item in data["entries"]:
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        if not str(entry.get("entry_id") or "").strip():
            entry["entry_id"] = f"taste-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
            changed = True
        if not str(entry.get("created_at") or "").strip():
            entry["created_at"] = datetime.now().isoformat(timespec="seconds")
            changed = True
        normalized_entries.append(entry)
    if len(normalized_entries) != len(data["entries"]):
        changed = True
    data["entries"] = normalized_entries
    if changed:
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(TREND_KNOWLEDGE_PATH, data)
    return data


def trend_knowledge_context(limit=18):
    entries = trend_knowledge_store().get("entries", [])[-limit:]
    compact = []
    for entry in entries:
        compact.append({
            "主题": entry.get("title") or "",
            "摘要": entry.get("summary") or "",
            "内容方向": entry.get("themes") or [],
            "偏好人物": entry.get("speaker_preferences") or [],
            "喜欢信号": entry.get("positive_signals") or [],
            "排除信号": entry.get("negative_signals") or [],
            "爆款结构": entry.get("content_patterns") or [],
        })
    return compact


def compact_trend_knowledge_context(limit=6):
    """Keep taste guidance small; 36Kr supplies the actual current topics."""
    context = trend_knowledge_context(limit=limit)
    return [
        {
            "主题": item.get("主题", ""),
            "喜欢信号": item.get("喜欢信号", [])[:4],
            "排除信号": item.get("排除信号", [])[:4],
            "爆款结构": item.get("爆款结构", [])[:3],
        }
        for item in context
    ]


def trend_download_dir(task_id):
    safe = re.sub(r"[^0-9A-Za-z_-]", "", str(task_id or ""))
    target = TRENDS_DIR / "downloads" / safe
    target.mkdir(parents=True, exist_ok=True)
    return target


def set_trend_task(task_id, **changes):
    with TREND_TASK_LOCK:
        task = TREND_TASKS.setdefault(task_id, {"task_id": task_id, "created_at": datetime.now().isoformat(timespec="seconds")})
        task.update(changes)
        if "progress" in changes:
            try:
                progress = max(0.0, min(1.0, float(task.get("progress") or 0)))
            except (TypeError, ValueError):
                progress = 0.0
            task["progress"] = progress
            task["percent"] = int(round(progress * 100))
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        return dict(task)


def get_trend_task(task_id):
    with TREND_TASK_LOCK:
        return dict(TREND_TASKS.get(task_id, {}))


def set_broll_task(task_id, **changes):
    with BROLL_TASK_LOCK:
        task = BROLL_TASKS.setdefault(task_id, {"task_id": task_id, "created_at": datetime.now().isoformat(timespec="seconds")})
        task.update(changes)
        if "progress" in changes:
            try:
                progress = max(0.0, min(1.0, float(task.get("progress") or 0)))
            except (TypeError, ValueError):
                progress = 0.0
            task["progress"] = progress
            task["percent"] = int(round(progress * 100))
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        return dict(task)


def get_broll_task(task_id):
    with BROLL_TASK_LOCK:
        return dict(BROLL_TASKS.get(task_id, {}))


def strip_html(text):
    clean = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", html.unescape(clean)).strip()


def video_platform(url):
    host = urllib.parse.urlparse(str(url or "")).netloc.lower().removeprefix("www.")
    platforms = {
        "youtube.com": "YouTube",
        "youtu.be": "YouTube",
        "bilibili.com": "Bilibili",
        "douyin.com": "抖音",
        "iesdouyin.com": "抖音",
        "tiktok.com": "TikTok",
        "vimeo.com": "Vimeo",
        "xiaohongshu.com": "小红书",
        "instagram.com": "Instagram",
        "weibo.com": "微博",
        "x.com": "X",
        "twitter.com": "X",
    }
    for domain, label in platforms.items():
        if host == domain or host.endswith(f".{domain}"):
            return label
    return host or "网页视频"


def parse_result_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{10}(?:\.\d+)?", text):
        try:
            return datetime.fromtimestamp(float(text))
        except (OSError, OverflowError, ValueError):
            return None
    if re.fullmatch(r"\d{13}", text):
        try:
            return datetime.fromtimestamp(int(text) / 1000)
        except (OSError, OverflowError, ValueError):
            return None
    normalized = text.replace("Z", "+00:00")
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            parsed = datetime.strptime(normalized, fmt)
            if parsed.tzinfo:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            continue
    return None


def parse_result_date(value):
    parsed = parse_result_datetime(value)
    return parsed.date() if parsed else None


def is_published_before(value, cutoff):
    """Compare publication dates only; time-of-day and timezone are ignored."""
    published = parse_result_date(value)
    threshold = parse_result_date(cutoff)
    return bool(published and threshold and published < threshold)


def in_selected_date_range(published_at, start_at, end_at):
    published = parse_result_date(published_at)
    if not published:
        return True
    try:
        start = datetime.strptime(start_at, "%Y-%m-%d").date() if start_at else None
        end = datetime.strptime(end_at, "%Y-%m-%d").date() if end_at else None
    except ValueError:
        return True
    return (not start or published >= start) and (not end or published <= end)


def candidate_heat_score(title, description, platform, published_at, keywords):
    haystack = f"{title} {description}".casefold()
    score = 45
    if platform != "网页视频":
        score += 18
    matched = sum(1 for keyword in keywords if keyword.casefold() in haystack)
    score += min(20, matched * 8)
    published = parse_result_date(published_at)
    if published:
        age_days = max(0, (datetime.now().date() - published).days)
        score += max(0, 17 - min(age_days, 17))
    return min(100, score)


def fetch_bing_video_candidates(query, keywords, start_at="", end_at=""):
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote(query)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"})
    try:
        # Keep the news-discovery layer consistent with LLM requests: use the
        # same direct-only network policy for every public request.
        with open_public_request(request, timeout=18) as response:
            root = ElementTree.fromstring(response.read())
    except Exception as exc:
        raise RuntimeError(f"搜索服务暂时不可用：{exc}") from exc

    candidates = []
    outside_date_range = []
    for item in root.findall(".//item"):
        title = strip_html(item.findtext("title"))
        link = str(item.findtext("link") or "").strip()
        description = strip_html(item.findtext("description"))
        published_at = str(item.findtext("pubDate") or "").strip()
        if not title or not link or not link.startswith(("https://", "http://")):
            continue
        platform = video_platform(link)
        candidate = {
            "title": title,
            "url": link,
            "description": description,
            "published_at": published_at,
            "platform": platform,
            "heat_score": candidate_heat_score(title, description, platform, published_at, keywords),
        }
        if in_selected_date_range(published_at, start_at, end_at):
            candidates.append(candidate)
        else:
            outside_date_range.append(candidate)
    return candidates, outside_date_range


def search_video_candidates(keywords, limit, start_at="", end_at=""):
    normalized = []
    for keyword in keywords:
        value = re.sub(r"\s+", " ", str(keyword or "")).strip()
        if value and value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError("请至少输入一个关键词")

    found = []
    outside_date_range = []
    errors = []
    for keyword in normalized:
        query = f"{keyword} 视频"
        try:
            matched, outside_range = fetch_bing_video_candidates(query, normalized, start_at, end_at)
            for candidate in matched:
                candidate["keyword"] = keyword
                candidate["search_query"] = query
                found.append(candidate)
            for candidate in outside_range:
                candidate["keyword"] = keyword
                candidate["search_query"] = query
                outside_date_range.append(candidate)
        except RuntimeError as exc:
            errors.append(str(exc))

    if not found and errors:
        raise RuntimeError(errors[0])
    if not found and outside_date_range:
        found = outside_date_range
        errors.append("网页搜索的 RSS 日期不一定是原视频发布时间，已放宽日期筛选并显示相关候选；需要严格按发布时间筛选时，请使用 MediaCrawler 平台来源。")

    deduped = []
    seen_urls = set()
    for candidate in sorted(found, key=lambda item: item["heat_score"], reverse=True):
        canonical = candidate["url"].rstrip("/")
        if canonical in seen_urls:
            continue
        seen_urls.add(canonical)
        candidate["candidate_id"] = f"candidate-{len(deduped) + 1:03d}-{uuid4().hex[:6]}"
        candidate["status"] = "ready"
        candidate["heat_label"] = "相关度与新鲜度"
        deduped.append(candidate)
        if len(deduped) >= limit:
            break
    return normalized, deduped, errors


def media_crawler_python_path():
    configured = str(os.environ.get("MEDIACRAWLER_PYTHON") or "").strip()
    if configured and Path(configured).exists():
        return configured
    candidates = [
        MEDIA_CRAWLER_VENV_DIR / "Scripts" / "python.exe",
        MEDIA_CRAWLER_VENV_DIR / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def bundled_tool_path(name):
    candidates = [BIN_DIR / name]
    if os.name == "nt" and not name.endswith(".exe"):
        candidates.insert(0, BIN_DIR / f"{name}.exe")
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def media_crawler_runner():
    """Return the packaged crawler executable or the development runner."""
    configured = str(os.environ.get("MEDIACRAWLER_EXECUTABLE") or "").strip()
    if configured and Path(configured).exists():
        return [configured], MEDIA_CRAWLER_RUNTIME_DIR
    bundled = bundled_tool_path("mediacrawler")
    if bundled:
        return [bundled], MEDIA_CRAWLER_RUNTIME_DIR
    if not MEDIA_CRAWLER_DIR.is_dir() or not (MEDIA_CRAWLER_DIR / "main.py").exists():
        raise RuntimeError("MediaCrawler 运行组件不存在")
    python_executable = media_crawler_python_path()
    if not python_executable:
        raise RuntimeError("MediaCrawler 依赖尚未安装，请先完成 vendor/MediaCrawler 的 .venv 初始化")
    return [python_executable, str(MEDIA_CRAWLER_DIR / "main.py")], MEDIA_CRAWLER_DIR


def media_crawler_platform_label(platform):
    return {
        "bili": "Bilibili",
        "dy": "抖音",
        "xhs": "小红书",
        "ks": "快手",
        "wb": "微博",
        "zhihu": "知乎",
        "tieba": "贴吧",
    }.get(platform, platform)


def normalize_trend_platforms(value):
    """Keep the user's order while ensuring Douyin is the fallback for Bilibili."""
    selected = []
    for item in value or ("bili", "dy"):
        platform = str(item or "").strip()
        if platform in {"bili", "dy"} and platform not in selected:
            selected.append(platform)
    if not selected:
        selected = ["bili", "dy"]
    if "bili" in selected and "dy" not in selected:
        selected.append("dy")
    return selected


def to_metric_number(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value).strip().lower().replace(",", "")
    if not text:
        return 0.0
    multiplier = 1.0
    if text.endswith("万") or text.endswith("w"):
        multiplier = 10000.0
        text = text[:-1]
    elif text.endswith("亿"):
        multiplier = 100000000.0
        text = text[:-1]
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) * multiplier if match else 0.0


def first_present(mapping, *keys):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def normalize_media_crawler_candidate(item, platform, keyword):
    title = str(first_present(item, "title", "desc", "content", "text") or "未命名视频").strip()
    description = str(first_present(item, "desc", "content", "text", "title") or "").strip()
    url = str(first_present(item, "note_url", "video_url", "aweme_url", "share_url", "url") or "").strip()
    author = str(first_present(item, "nickname", "author", "author_name", "user_name", "author_nickname") or "").strip()
    published_at = str(first_present(item, "time", "create_time", "publish_time", "last_update_time") or "").strip()
    views = to_metric_number(first_present(item, "view_count", "play_count", "play_num", "view_num"))
    likes = to_metric_number(first_present(item, "liked_count", "like_count", "digg_count", "like_num"))
    comments = to_metric_number(first_present(item, "comment_count", "comments_count", "comment_num"))
    shares = to_metric_number(first_present(item, "share_count", "share_num", "forward_count"))
    collects = to_metric_number(first_present(item, "collected_count", "collect_count", "favorite_count"))
    interaction = likes + comments * 2.5 + shares * 4 + collects * 2
    score = min(100, round(38 + min(38, math.log10(views + 1) * 7) + min(34, math.log10(interaction + 1) * 9)))
    return {
        "title": title,
        "url": url,
        "description": description,
        "published_at": published_at,
        "platform": media_crawler_platform_label(platform),
        "author": author,
        "heat_score": score,
        "heat_label": "公开互动数据",
        "metrics": {"views": views, "likes": likes, "comments": comments, "shares": shares, "collects": collects},
        "keyword": keyword,
        "search_query": keyword,
    }


def read_jsonl_items(root):
    items = []
    for path in root.rglob("search_contents_*.jsonl"):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    item = json.loads(line)
                    if isinstance(item, dict):
                        items.append(item)
        except (OSError, json.JSONDecodeError):
            continue
    return items


def search_media_crawler_candidates(
    keywords,
    platform,
    limit,
    start_at="",
    end_at="",
    min_published_at="",
):
    runner, working_dir = media_crawler_runner()

    normalized = []
    for keyword in keywords:
        value = re.sub(r"\s+", " ", str(keyword or "")).strip()
        if value and value not in normalized:
            normalized.append(value)
    if not normalized:
        raise ValueError("请至少输入一个关键词")

    run_id = f"mc-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    output_dir = TRENDS_DIR / "mediacrawler" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    query_keywords = ",".join(normalized)
    command = [
        *runner,
        "--platform", platform,
        "--lt", "qrcode",
        "--type", "search",
        "--keywords", query_keywords,
        "--get_comment", "no",
        "--get_sub_comment", "no",
        "--headless", "no",
        "--save_data_option", "jsonl",
        "--save_data_path", str(output_dir),
        "--crawler_max_notes_count", str(limit),
        "--max_concurrency_num", "1",
    ]
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    working_dir.mkdir(parents=True, exist_ok=True)
    try:
        process = subprocess.run(
            command,
            cwd=working_dir,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=MEDIA_CRAWLER_TIMEOUT,
            **_hidden_console_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        suffix = f"：{detail[-600:]}" if detail else ""
        raise RuntimeError(
            f"MediaCrawler 搜索超时（{MEDIA_CRAWLER_TIMEOUT} 秒）。"
            "首次使用该平台请先完成扫码登录，确认浏览器已正常打开后再重试" + suffix
        ) from exc
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()
        raise RuntimeError(detail[-1600:] or "MediaCrawler 搜索失败")

    raw_items = read_jsonl_items(output_dir)
    candidates = []
    before_cutoff_count = 0
    seen = set()
    for item in raw_items:
        keyword = str(first_present(item, "source_keyword") or normalized[0])
        candidate = normalize_media_crawler_candidate(item, platform, keyword)
        if not candidate["url"] or candidate["url"] in seen:
            continue
        if not in_selected_date_range(candidate["published_at"], start_at, end_at):
            continue
        if is_published_before(candidate["published_at"], min_published_at):
            before_cutoff_count += 1
            continue
        seen.add(candidate["url"])
        candidate["candidate_id"] = f"candidate-{len(candidates) + 1:03d}-{uuid4().hex[:6]}"
        candidate["status"] = "ready"
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    candidates.sort(key=lambda item: item["heat_score"], reverse=True)
    warnings = []
    if before_cutoff_count:
        warnings.append(
            f"已排除 {before_cutoff_count} 条早于热点报道发布时间的视频素材。"
        )
    if not candidates:
        if raw_items:
            warnings.append(
                f"MediaCrawler 已获取 {len(raw_items)} 条 {media_crawler_platform_label(platform)} 结果，但没有视频发布时间落在 {start_at or '不限'} 至 {end_at or '不限'}；请扩大时间范围或选择‘不限时间’。"
            )
        else:
            warnings.append("MediaCrawler 已运行，但平台没有返回可用视频结果；请确认关键词、登录状态和网络连接。")
    return normalized, candidates, warnings


def safe_string_list(value, limit=8, item_limit=80):
    if not isinstance(value, list):
        return []
    values = []
    for item in value:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if text and text not in values:
            values.append(text[:item_limit])
        if len(values) >= limit:
            break
    return values


GENERIC_TREND_QUERY_TERMS = {
    "ai", "人工智能", "热点", "商业", "科技", "公司", "企业", "产品", "行业", "市场", "36氪", "36kr", "新智元",
    "新闻", "视频", "现场", "采访", "访谈", "演讲", "发布会", "权威报道", "活动", "事件",
    "医疗", "治疗", "疗法", "癌症", "临床试验", "合作", "发布", "宣布", "全球",
    "人类", "首次", "史上首次", "突破", "治愈", "历史上第一次", "成功",
}


def compact_search_term(value):
    return re.sub(r"[\s\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)


def hotspot_search_anchors(hotspot, limit=4):
    """Keep only explicit, discriminative names from the reviewed hotspot."""
    hotspot = hotspot or {}
    source_text = compact_search_term(hotspot.get("source_article_text"))
    anchors = []
    candidates = merge_search_terms(
        safe_string_list(hotspot.get("verified_anchors"), limit=8, item_limit=80),
        safe_string_list(hotspot.get("entities"), limit=8, item_limit=80),
        limit=12,
    )
    for entity in candidates:
        compact = compact_search_term(entity)
        if len(compact) < 2 or compact in GENERIC_TREND_QUERY_TERMS:
            continue
        if source_text and compact not in source_text:
            continue
        if compact not in {compact_search_term(item) for item in anchors}:
            anchors.append(entity)
        if len(anchors) >= limit:
            break
    return anchors


def hotspot_query_subject(hotspot, anchors=None):
    anchors = anchors if anchors is not None else hotspot_search_anchors(hotspot)
    if anchors:
        return " ".join(anchors[:3])
    return str((hotspot or {}).get("title") or (hotspot or {}).get("source_title") or "热点事件").strip()[:80]


def query_anchor_matches(query, anchors):
    compact_query = compact_search_term(query)
    return [anchor for anchor in anchors if compact_search_term(anchor) and compact_search_term(anchor) in compact_query]


def enforce_hotspot_query_anchors(hotspot, queries, limit=3):
    """Ensure every media query carries enough verified names to avoid stale generic results."""
    anchors = hotspot_search_anchors(hotspot)
    if not anchors:
        return []
    subject = hotspot_query_subject(hotspot, anchors)
    required_count = min(2, len(anchors)) if anchors else 0
    normalized = []
    for query in safe_string_list(queries, limit=limit, item_limit=120):
        matches = query_anchor_matches(query, anchors)
        if len(matches) < required_count:
            missing = [anchor for anchor in anchors if anchor not in matches][:required_count - len(matches)]
            query = f"{' '.join(missing)} {query}".strip()
        query = re.sub(r"\s+", " ", query).strip()[:120]
        if query and query not in normalized:
            normalized.append(query)
    if normalized:
        return normalized
    if not subject:
        return []
    return [
        f"{subject} 新闻现场"[:120],
        f"{subject} 发布会"[:120],
        f"{subject} 权威报道"[:120],
    ]


def merge_search_terms(*groups, limit=6):
    merged = []
    seen = set()
    for group in groups:
        for value in group or []:
            text = re.sub(r"\s+", " ", str(value or "")).strip()[:80]
            key = compact_search_term(text)
            if not text or not key or key in seen:
                continue
            seen.add(key)
            merged.append(text)
            if len(merged) >= limit:
                return merged
    return merged


def structure_trend_knowledge(note, provider_id=None):
    note = re.sub(r"\s+", " ", str(note or "")).strip()
    if len(note) < 12:
        raise RuntimeError("请至少补充一段往期主题、偏好或不想要的内容说明。")
    prompt = f"""把用户的历史短视频主题和选题偏好整理成一条结构化知识库记录。
不要补充用户未提供的事实；不确定时返回空数组。所有文字使用简体中文。

用户输入：
{note[:6000]}

返回 JSON：
{{
  "title": "不超过24字的主题名称",
  "summary": "不超过100字，说明这类内容为什么适合或不适合用户",
  "themes": ["主题或行业"],
  "speaker_preferences": ["人物类型、人物或身份"],
  "positive_signals": ["用户偏好的表达、冲突或内容特征"],
  "negative_signals": ["用户明确不希望出现的内容特征"],
  "content_patterns": ["可复用的爆款结构，例如企业家判断、失败复盘"],
  "source_note": "一句话概括原始输入"
}}"""
    structure_source = "llm"
    try:
        result = llm_json(prompt, provider_id=provider_id, max_tokens=1800)
    except RuntimeError as exc:
        # Keep the user's preference usable when the configured LLM is temporarily
        # unreachable. This fallback never invents tags or claims AI succeeded.
        result = {
            "title": note[:24],
            "summary": note[:100],
            "themes": [],
            "speaker_preferences": [],
            "positive_signals": [],
            "negative_signals": [],
            "content_patterns": [],
            "source_note": note[:800],
        }
        structure_source = "fallback"
        result["structure_warning"] = str(exc)
    return {
        "title": str(result.get("title") or "未命名主题").strip()[:80],
        "summary": str(result.get("summary") or "").strip()[:360],
        "themes": safe_string_list(result.get("themes")),
        "speaker_preferences": safe_string_list(result.get("speaker_preferences")),
        "positive_signals": safe_string_list(result.get("positive_signals")),
        "negative_signals": safe_string_list(result.get("negative_signals")),
        "content_patterns": safe_string_list(result.get("content_patterns")),
        "source_note": str(result.get("source_note") or note).strip()[:800],
        "raw_note": note[:6000],
        "structure_source": structure_source,
        "structure_warning": str(result.get("structure_warning") or "").strip()[:500],
    }


def plan_trend_discovery_queries(knowledge_context, provider_id=None):
    # 36Kr hot-list data is already current and China-focused. Avoid an extra
    # LLM planning call that can fail before any public hotspot is fetched.
    return [
        "中国 创始人 访谈 商业判断",
        "中国 科技企业家 公开演讲",
        "中国 CEO 行业趋势 观点",
        "中国 消费品牌 创始人 对话",
    ], ["中国商业热点", "企业家公开发言", "科技与消费趋势"]


def is_36kr_url(url):
    try:
        host = urllib.parse.urlsplit(str(url or "")).netloc.casefold().split(":", 1)[0]
    except ValueError:
        return False
    return host == "36kr.com" or host.endswith(".36kr.com")


class ArticleBodyParser(HTMLParser):
    """Extract text from common article-body containers without a browser."""

    CONTENT_CLASS_MARKERS = (
        "article-detail", "article_content", "article-content", "articlecontent",
        "detail-content", "detail_content", "content-detail", "content_detail",
        "article-body", "article_body", "post-content", "post_content",
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture_depth = 0
        self.skip_depth = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        class_name = " ".join(value for key, value in attrs if key == "class" and value).casefold()
        is_article = tag == "article" or any(marker in class_name for marker in self.CONTENT_CLASS_MARKERS)
        if self.capture_depth:
            self.capture_depth += 1
        elif is_article:
            self.capture_depth = 1
        if self.capture_depth and tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "blockquote"}:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if self.capture_depth:
            if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "blockquote"}:
                self.chunks.append("\n")
            self.capture_depth -= 1

    def handle_data(self, data):
        if self.capture_depth and not self.skip_depth:
            self.chunks.append(data)


def normalize_article_text(value, limit=18000):
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\t\r\f\v ]+", " ", text)
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return "\n".join(lines)[:limit]


def _collect_article_json_text(value, candidates, key_hint=""):
    if isinstance(value, dict):
        for key, child in value.items():
            _collect_article_json_text(child, candidates, str(key).casefold())
        return
    if isinstance(value, list):
        for child in value:
            _collect_article_json_text(child, candidates, key_hint)
        return
    if not isinstance(value, str):
        return
    priorities = {
        "articlebody": 12, "articlecontent": 11, "contenttext": 10,
        "content": 9, "detail": 8, "body": 7, "description": 4,
    }
    priority = priorities.get(key_hint, 0)
    if not priority:
        return
    text = normalize_article_text(value)
    if len(text) >= 80:
        candidates.append((priority, len(text), text))


def extract_article_body_from_html(page_html):
    page_html = str(page_html or "")
    json_candidates = []
    for script in re.findall(r"<script\b[^>]*>(.*?)</script\s*>", page_html, flags=re.IGNORECASE | re.DOTALL):
        script = script.strip()
        if not script or script[0] not in "[{":
            continue
        try:
            _collect_article_json_text(json.loads(script), json_candidates)
        except ValueError:
            continue
    parser = ArticleBodyParser()
    try:
        parser.feed(page_html)
        parser.close()
    except Exception:
        pass
    dom_text = normalize_article_text("".join(parser.chunks))
    if dom_text and len(dom_text) >= 80:
        json_candidates.append((10, len(dom_text), dom_text))
    if not json_candidates:
        return ""
    json_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return json_candidates[0][2]


def trend_article_cache_path(url):
    digest = hashlib.sha256(str(url or "").encode("utf-8")).hexdigest()
    return TREND_ARTICLE_CACHE_DIR / f"{digest}.json"


def source_article_url_candidates(url):
    """Return equivalent 36Kr article URLs, including the readable regional page."""
    original = str(url or "").strip()
    if not original:
        return []
    parsed = urllib.parse.urlsplit(original)
    candidates = [original]
    path_match = re.match(r"^/p/(\d+)", parsed.path or "")
    if path_match:
        article_id = path_match.group(1)
        candidates.extend([
            f"https://eu.36kr.com/zh/p/{article_id}",
            f"https://www.36kr.com/p/{article_id}",
        ])
    deduped = []
    seen = set()
    for candidate in candidates:
        key = candidate.rstrip("/")
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


# Keep the article-rendering fallback on the browser's normal networking,
# sandbox, and GPU paths. Chromium flags do not change Python socket
# permissions, so passing bypass flags here only obscures the real diagnosis.
ARTICLE_BROWSER_LAUNCH_ARGS = ()


def fetch_source_article_content_with_browser(urls):
    """Read a source article in a direct-only Chromium fallback.

    The HTTP path remains the fast path. This fallback is intentionally
    isolated because Chromium flags do not change Python urllib socket
    permissions; they only help when the article itself requires rendering.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        site_packages = _publisher_site_packages()
        if site_packages and site_packages.is_dir() and str(site_packages) not in sys.path:
            sys.path.insert(0, str(site_packages))
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as nested_exc:
            raise RuntimeError("正文浏览器兜底需要 Playwright Python 依赖") from nested_exc

    chrome = _chrome_executable()
    launch_kwargs = {"headless": True}
    if ARTICLE_BROWSER_LAUNCH_ARGS:
        launch_kwargs["args"] = list(ARTICLE_BROWSER_LAUNCH_ARGS)
    if chrome:
        launch_kwargs["executable_path"] = chrome
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_kwargs)
        try:
            context = browser.new_context(ignore_https_errors=True)
            try:
                for candidate_url in urls:
                    page = context.new_page()
                    try:
                        page.goto(candidate_url, wait_until="domcontentloaded", timeout=30000)
                        try:
                            page.wait_for_timeout(1200)
                        except Exception:
                            pass
                        content = extract_article_body_from_html(page.content())
                        if len(content) < 80:
                            try:
                                content = normalize_article_text(page.locator("body").inner_text(timeout=5000))
                            except Exception:
                                content = ""
                        if len(content) >= 80:
                            return {
                                "content": content,
                                "resolved_url": candidate_url,
                                "source": "browser",
                            }
                        errors.append(f"{candidate_url}：浏览器页面未返回正文")
                    except Exception as exc:
                        errors.append(f"{candidate_url}：{exc}")
                    finally:
                        try:
                            page.close()
                        except Exception:
                            pass
            finally:
                context.close()
        finally:
            browser.close()
    detail = errors[-1] if errors else "浏览器页面为空"
    raise RuntimeError(f"浏览器兜底未读取到正文：{detail}")


def fetch_source_article_content(url):
    """Read and cache the source article used to ground video-search anchors."""
    url = str(url or "").strip()
    if not is_36kr_url(url):
        raise RuntimeError("热点缺少可核对的来源报道链接。")
    cache_path = trend_article_cache_path(url)
    cached = read_json(cache_path, {})
    cached_text = normalize_article_text(cached.get("content") if isinstance(cached, dict) else "")
    if len(cached_text) >= 80:
        return {"url": url, "content": cached_text, "source": "cache"}
    errors = []
    content = ""
    resolved_url = url
    for candidate_url in source_article_url_candidates(url):
        request = urllib.request.Request(
            candidate_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        try:
            with open_public_request(request, timeout=22) as response:
                page_html = response.read().decode("utf-8", errors="replace")
            content = extract_article_body_from_html(page_html)
            if len(content) >= 80:
                resolved_url = candidate_url
                break
            errors.append(f"{candidate_url}：未返回正文")
        except ExternalNetworkError as exc:
            errors.append(f"{candidate_url}：{exc}")
        except (urllib.error.URLError, OSError) as exc:
            errors.append(f"{candidate_url}：{getattr(exc, 'reason', exc)}")
    if len(content) < 80:
        try:
            browser_result = fetch_source_article_content_with_browser(source_article_url_candidates(url))
            content = normalize_article_text(browser_result.get("content"))
            if len(content) >= 80:
                resolved_url = browser_result.get("resolved_url") or resolved_url
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                write_json(cache_path, {"url": url, "resolved_url": resolved_url, "content": content, "fetched_at": datetime.now().isoformat(timespec="seconds")})
                return {"url": url, "resolved_url": resolved_url, "content": content, "source": "browser"}
        except Exception as exc:
            errors.append(f"浏览器兜底：{exc}")
        detail = errors[-1] if errors else "返回内容为空"
        raise RuntimeError(f"无法读取来源报道正文：{detail}")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(cache_path, {"url": url, "resolved_url": resolved_url, "content": content, "fetched_at": datetime.now().isoformat(timespec="seconds")})
    return {"url": url, "resolved_url": resolved_url, "content": content, "source": "network"}


def enrich_hotspots_with_source_articles(selected_hotspots, progress_callback=None):
    """Attach source-report text to each chosen hotspot before query generation."""
    selected_hotspots = [item for item in selected_hotspots or [] if isinstance(item, dict)]
    urls = []
    title_by_url = {}
    for hotspot in selected_hotspots:
        url = str(hotspot.get("source_url") or "").rstrip("/")
        if not url:
            raise RuntimeError("所选热点缺少来源报道链接，无法核对检索锚点。")
        if url not in urls:
            urls.append(url)
            title_by_url[url] = str(hotspot.get("title") or "热点")
    by_url = {}
    for index, url in enumerate(urls, start=1):
        if progress_callback:
            progress_callback(index, len(urls), title_by_url[url])
        by_url[url] = fetch_source_article_content(url)
    enriched = []
    for hotspot in selected_hotspots:
        url = str(hotspot.get("source_url") or "").rstrip("/")
        item = dict(hotspot)
        item["source_article_text"] = by_url[url]["content"]
        item["source_article_source"] = by_url[url]["source"]
        enriched.append(item)
    return enriched


def trend_hotlist_dates(start_at="", end_at="", max_days=14):
    today = datetime.now().date()
    try:
        start = datetime.strptime(start_at, "%Y-%m-%d").date() if start_at else today - timedelta(days=6)
        end = datetime.strptime(end_at, "%Y-%m-%d").date() if end_at else today
    except ValueError:
        start, end = today - timedelta(days=6), today
    end = min(end, today)
    if start > end:
        return []
    if (end - start).days + 1 > max_days:
        start = end - timedelta(days=max_days - 1)
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def fetch_36kr_hotlist(day):
    date_text = day.isoformat()
    urls = [
        f"https://openclaw.36krcdn.com/media/hotlist/{date_text}/24h_hot_list.json",
        f"https://gateway.36kr.com/api/mis/nav/home/nav/rank/hot?partner_id=wap&platform_id=2",
    ]
    errors = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36", "Accept": "application/json,text/plain,*/*"}
    for url in urls:
        request = urllib.request.Request(url, headers=headers)
        try:
            with open_public_request(request, timeout=18) as response:
                payload = json.loads(response.read().decode("utf-8"))
            items = payload.get("data") if isinstance(payload, dict) else []
            if isinstance(items, dict):
                items = items.get("items") or items.get("hotList") or items.get("data") or []
            if not isinstance(items, list):
                continue
            normalized = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                article = item.get("item") if isinstance(item.get("item"), dict) else item
                article = article.get("itemInfo") if isinstance(article.get("itemInfo"), dict) else article
                normalized.append(article)
            if normalized:
                return normalized
        except (ValueError, urllib.error.URLError, OSError, RuntimeError) as exc:
            errors.append(str(exc))
    detail = errors[-1] if errors else "返回内容为空"
    raise RuntimeError(f"近期热点暂时不可用：{detail}")


def load_cached_36kr_sources(start_at="", end_at="", max_age_days=30, max_files=24):
    """Recover verified 36Kr sources from prior local discovery results."""
    cutoff = datetime.now().date() - timedelta(days=max_age_days)
    recovered = []
    for path in sorted(TRENDS_DIR.glob("trend-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:max_files]:
        result = read_json(path, {})
        for topic in result.get("topics", []) if isinstance(result, dict) else []:
            if not isinstance(topic, dict) or not is_36kr_url(topic.get("source_url")):
                continue
            published_at = str(topic.get("published_at") or "").strip()
            published = parse_result_date(published_at)
            if published and published < cutoff:
                continue
            if not in_selected_date_range(published_at, start_at, end_at):
                continue
            recovered.append({
                "title": str(topic.get("source_title") or topic.get("title") or "").strip(),
                "url": str(topic.get("source_url") or "").strip(),
                "description": str(topic.get("evidence_excerpt") or topic.get("statement_summary") or "").strip(),
                "published_at": published_at,
                "platform": "36Kr",
                "author": "36Kr",
                "heat_score": 70,
                "hot_rank": 99,
                "source_type": "36kr-cache",
                "source_name": "36Kr（本地缓存）",
                "search_query": "36Kr 24 小时热榜（本地缓存）",
            })
    deduped = []
    seen = set()
    for source in recovered:
        url = source["url"].rstrip("/")
        if url in seen or not source["title"]:
            continue
        seen.add(url)
        deduped.append(source)
    return deduped


def fetch_hot_topic_sources(queries, start_at="", end_at="", per_query=8):
    sources = []
    warnings = []
    for day in reversed(trend_hotlist_dates(start_at, end_at)):
        try:
            ranked_items = fetch_36kr_hotlist(day)
            for item in ranked_items[:20]:
                url = str(item.get("url") or "").strip()
                title = str(item.get("title") or "").strip()
                if not title or not is_36kr_url(url):
                    continue
                rank = max(1, int(item.get("rank") or 99))
                published_at = str(item.get("publishTime") or day.isoformat()).strip()
                source = {
                    "title": title,
                    "url": url,
                    "description": str(item.get("content") or "").strip(),
                    "published_at": published_at,
                    "platform": "36Kr",
                    "author": str(item.get("author") or "").strip(),
                    "heat_score": max(45, 100 - min(rank, 55)),
                    "hot_rank": rank,
                }
                if not in_selected_date_range(published_at, start_at, end_at):
                    continue
                source["source_type"] = "36kr"
                source["source_name"] = "36Kr"
                source["search_query"] = "36Kr 24 小时热榜"
                sources.append(source)
        except RuntimeError as exc:
            message = str(exc)
            warnings.append(message)
            if "WinError 10013" in message or "外部网络连接" in message:
                break
    deduped = []
    seen = set()
    for source in sorted(sources, key=lambda item: item.get("heat_score", 0), reverse=True):
        url = str(source.get("url") or "").rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(source)
        if len(deduped) >= max(36, per_query * max(1, len(queries))):
            break
    if not deduped and warnings:
        cached = load_cached_36kr_sources(start_at, end_at)
        if cached:
            deduped = cached[:max(36, per_query * max(1, len(queries)))]
            warnings.insert(0, f"实时热点暂时不可连接，已使用最近 {len(deduped)} 条本地缓存热点；请核对来源链接后再制作。")
    if not deduped and not warnings:
        warnings.append("当前时间范围内未找到可用的热点报道。")
    return deduped, warnings


CHINESE_PERSON_SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉龚程嵇邢滑裴陆荣翁荀羊惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹龙叶幸司黎白黑"
PERSON_ACTION_PATTERN = r"谈|说|称|表示|回应|宣布|发布|分享|提到|提出|认为|指出|现身|出席|会见|任命|卸任|接任|离职|辞任|被查|致歉|道歉|质疑|加入|创业|投资|收购|推出|带队|担任|成为"
PERSON_ROLE_PATTERN = r"创始人|联合创始人|董事长|CEO|总裁|创办人|董事|首席执行官|负责人|掌门人|投资人|企业家|科学家|导演|演员|歌手|运动员"
PERSON_NAME_STOP_WORDS = ("公司", "集团", "科技", "汽车", "中国", "美国", "全球", "企业", "市场", "行业", "产品", "品牌", "创始", "董事", "首席", "热点", "商业")


def extract_hot_people_from_text(text):
    """Find explicitly named people in a headline or excerpt without an LLM."""
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return []
    name_pattern = rf"([{CHINESE_PERSON_SURNAMES}][\u4e00-\u9fff]{{1,2}})"
    matches = []
    patterns = (
        rf"{name_pattern}(?=(?:{PERSON_ACTION_PATTERN})|[:：])",
        rf"(?:{PERSON_ROLE_PATTERN})[，、：: ]*{name_pattern}(?=(?:{PERSON_ACTION_PATTERN})|在|的|就|将|已|曾|亦|与|和|[，。、：:])",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, compact):
            name = str(match.group(1) or "").strip()
            if len(name) < 2 or any(word in name for word in PERSON_NAME_STOP_WORDS):
                continue
            if name not in matches:
                matches.append(name)
    return matches


def build_trend_person_pool(start_at="", end_at=""):
    """Fetch 36Kr over HTTP, then persist the local, reviewable people pool."""
    sources, warnings = fetch_hot_topic_sources(["36Kr 24 小时热榜"], start_at, end_at)
    if not sources:
        raise RuntimeError(warnings[0] if warnings else "未获取到近期 36Kr 中国商业热点，请稍后重试。")

    people_by_name = {}
    for source in sources:
        evidence = {
            "title": str(source.get("title") or "").strip(),
            "url": str(source.get("url") or "").strip(),
            "description": str(source.get("description") or "").strip(),
            "published_at": str(source.get("published_at") or "").strip(),
            "heat_score": source.get("heat_score") or 0,
            "hot_rank": source.get("hot_rank") or "",
            "source_name": str(source.get("source_name") or "36Kr").strip(),
        }
        if not evidence["title"] or not is_36kr_url(evidence["url"]):
            continue
        for name in extract_hot_people_from_text(f"{evidence['title']}\n{evidence['description']}"):
            person = people_by_name.setdefault(name, {"name": name, "sources": []})
            if evidence["url"] not in {item.get("url") for item in person["sources"]}:
                person["sources"].append(evidence)

    ranked_people = []
    for person in people_by_name.values():
        person_sources = sorted(
            person["sources"],
            key=lambda item: (float(item.get("heat_score") or 0), str(item.get("published_at") or "")),
            reverse=True,
        )
        ranked_people.append({
            "name": person["name"],
            "source_count": len(person_sources),
            "heat_score": round(sum(float(item.get("heat_score") or 0) for item in person_sources)),
            "sources": person_sources,
        })
    ranked_people.sort(key=lambda item: (-item["heat_score"], -item["source_count"], item["name"]))
    for index, person in enumerate(ranked_people, start=1):
        person["person_id"] = f"person-{index:03d}"

    pool_id = f"people-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    pool = {
        "pool_id": pool_id,
        "provider": "36Kr 热点（HTTP）",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "start_at": start_at,
        "end_at": end_at,
        "source_count": len(sources),
        "people": ranked_people,
        "warnings": warnings[:8],
    }
    write_json(trend_person_pool_path(pool_id), pool)
    return pool


def load_selected_trend_people(pool_id, raw_person_ids):
    if not str(pool_id or "").startswith("people-"):
        raise RuntimeError("请先获取 36Kr 候选人物，再生成选题。")
    pool = read_json(trend_person_pool_path(pool_id), {})
    if not isinstance(pool, dict) or not isinstance(pool.get("people"), list):
        raise RuntimeError("候选人物已失效，请重新获取 36Kr 热点。")
    if isinstance(raw_person_ids, str):
        raw_person_ids = [raw_person_ids]
    person_ids = []
    for person_id in raw_person_ids or []:
        value = str(person_id or "").strip()
        if value and value not in person_ids:
            person_ids.append(value)
    if not person_ids:
        raise RuntimeError("请至少选择 1 位候选人物。")
    if len(person_ids) > 6:
        raise RuntimeError("最多只能选择 6 位候选人物。")

    people_by_id = {str(person.get("person_id") or ""): person for person in pool["people"] if isinstance(person, dict)}
    missing = [person_id for person_id in person_ids if person_id not in people_by_id]
    if missing:
        raise RuntimeError("部分候选人物已失效，请重新获取 36Kr 热点。")
    selected_people = [people_by_id[person_id] for person_id in person_ids]
    selected_sources = {}
    for person in selected_people:
        person_id = str(person.get("person_id") or "")
        person_name = str(person.get("name") or "")
        for source in person.get("sources") or []:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url") or "").rstrip("/")
            if not url:
                continue
            item = selected_sources.setdefault(url, dict(source, selected_person_ids=[], selected_people=[]))
            if person_id not in item["selected_person_ids"]:
                item["selected_person_ids"].append(person_id)
                item["selected_people"].append(person_name)
    return pool, selected_people, list(selected_sources.values())


def fallback_trend_topic(person, source):
    name = str(person.get("name") or "候选人物").strip()
    source_title = str(source.get("title") or "36Kr 热点").strip()
    return {
        "topic_id": f"topic-{person.get('person_id')}-{uuid4().hex[:6]}",
        "person_id": person.get("person_id"),
        "title": f"{name}：{source_title}"[:120],
        "category": "36Kr 热点",
        "speaker_name": name,
        "speaker_role": "",
        "statement_summary": str(source.get("description") or source_title).strip()[:300],
        "heat_reason": "来自用户确认的 36Kr 近期热点人物。",
        "evidence_excerpt": str(source.get("description") or source_title).strip()[:500],
        "source_confidence": "medium",
        "source_title": source_title,
        "source_url": str(source.get("url") or ""),
        "source_name": str(source.get("source_name") or "36Kr"),
        "published_at": str(source.get("published_at") or ""),
        "material_queries": [f"{name} {source_title[:36]} 完整采访", f"{name} 访谈", f"{name} 演讲"],
        "recommendation_reason": "已按用户选择的人物保留，等待人工核对。",
        "query_generation": "fallback",
        "materials": [],
    }


def choose_trend_topics(sources, knowledge_context, selected_people, provider_id=None):
    selected_people = [item for item in selected_people or [] if isinstance(item, dict) and item.get("person_id") and item.get("name")]
    if not selected_people:
        return []
    evidence = [
        {
            "id": f"source_{index + 1:03d}",
            "标题": source.get("title", ""),
            "摘要": source.get("description", ""),
            "发布时间": source.get("published_at", ""),
            "链接": source.get("url", ""),
            "可用人物ID": source.get("selected_person_ids", []),
            "可用人物": source.get("selected_people", []),
        }
        for index, source in enumerate(sources[:36])
    ]
    selected_person_payload = [{"person_id": item["person_id"], "name": item["name"]} for item in selected_people]
    prompt = f"""你是中文商业短视频选题编辑。请只为用户已确认的热点人物生成选题和视频素材检索词。
必须为“已选人物”中的每个人最多生成 1 条；speaker_name 必须逐字使用该人物的 name，person_id 必须对应同一人。source_id 只能使用其“可用人物ID”中包含该 person_id 的网页证据。不能引入未选择的人物，不能编造原话、来源或视频。每条 material_queries 必须包含该人物姓名，并同时包含来源证据中的具体事件、公司、产品或活动名称；不得只输出“AI”“创业”“商业趋势”等泛词。
只保留商业、科技、消费、创业议题，并优先原始访谈、演讲、发布会或权威媒体视频。用户知识库只用于轻量排序参考，不能排除用户已选择且有明确 36Kr 证据的人物。

已选人物：
{json.dumps(selected_person_payload, ensure_ascii=False)}

    用户偏好知识库（只用于轻量排序，不能筛掉已选热点）：
    {json.dumps((knowledge_context or [])[-6:], ensure_ascii=False)[:6000]}

网页证据：
{json.dumps(evidence, ensure_ascii=False)[:24000]}

返回 JSON：
{{
  "topics": [
    {{
      "person_id":"person-001",
      "source_id":"source_001",
      "title":"适合做短视频的选题标题",
      "category":"商业趋势|企业家访谈|科技判断|消费洞察",
      "speaker_name":"证据中出现的人物姓名",
      "speaker_role":"人物身份",
      "statement_summary":"仅根据证据摘要概括人物的观点；不是逐字引用",
      "heat_reason":"为什么值得关注",
      "evidence_excerpt":"从输入摘要中摘取或忠实压缩，不超过100字",
      "source_confidence":"high|medium",
      "material_queries":["人物 具体事件 完整采访", "人物 具体事件 演讲", "人物 具体事件 发布会"],
      "recommendation_reason":"与用户历史主题的匹配原因"
    }}
  ]
}}"""
    result = llm_json(prompt, provider_id=provider_id, max_tokens=6000)
    source_by_id = {item["id"]: item for item in evidence}
    people_by_id = {str(item["person_id"]): item for item in selected_people}
    topics_by_person_id = {}
    for item in result.get("topics", []) if isinstance(result.get("topics"), list) else []:
        source = source_by_id.get(str(item.get("source_id") or ""))
        person_id = str(item.get("person_id") or "").strip()
        person = people_by_id.get(person_id)
        source_url = str(source.get("链接") or "") if source else ""
        if not source or not person or person_id in topics_by_person_id or not is_36kr_url(source_url):
            continue
        if person_id not in set(source.get("可用人物ID") or []):
            continue
        speaker = str(person.get("name") or "").strip()
        query_anchor_source = {"entities": [speaker], "title": source.get("标题") or "热点事件", "source_title": source.get("标题") or "热点事件"}
        queries = enforce_hotspot_query_anchors(query_anchor_source, item.get("material_queries"), limit=3)
        if not queries:
            queries = [f"{speaker} 访谈", f"{speaker} 演讲", f"{speaker} 发布会"]
        topics_by_person_id[person_id] = {
            "topic_id": f"topic-{person_id}-{uuid4().hex[:6]}",
            "person_id": person_id,
            "title": str(item.get("title") or source["标题"]).strip()[:120],
            "category": str(item.get("category") or "商业观点").strip()[:40],
            "speaker_name": speaker[:60],
            "speaker_role": str(item.get("speaker_role") or "").strip()[:80],
            "statement_summary": str(item.get("statement_summary") or "").strip()[:300],
            "heat_reason": str(item.get("heat_reason") or "").strip()[:200],
            "evidence_excerpt": str(item.get("evidence_excerpt") or source["摘要"]).strip()[:500],
            "source_confidence": "high" if str(item.get("source_confidence")).lower() == "high" else "medium",
            "source_title": source["标题"],
            "source_url": source_url,
            "source_name": "36Kr",
            "published_at": source["发布时间"],
            "material_queries": queries,
            "search_anchors": [speaker],
            "recommendation_reason": str(item.get("recommendation_reason") or "").strip()[:240],
            "query_generation": "llm",
            "materials": [],
        }
    for person in selected_people:
        person_id = str(person["person_id"])
        if person_id in topics_by_person_id:
            continue
        matching_source = next((source for source in sources if person_id in set(source.get("selected_person_ids") or [])), None)
        if matching_source:
            topics_by_person_id[person_id] = fallback_trend_topic(person, matching_source)
    return [topics_by_person_id[str(person["person_id"])] for person in selected_people if str(person["person_id"]) in topics_by_person_id]


def build_trend_hotspot_pool(start_at="", end_at="", provider_id=None, progress_callback=None):
    """Fetch 36Kr by HTTP, then ask the LLM to split mixed reports into hotspots."""
    def report(progress, message):
        if progress_callback:
            progress_callback(max(0.0, min(0.99, float(progress))), message)

    report(0.06, "正在获取近期热点报道")
    sources, warnings = fetch_hot_topic_sources(["36Kr 24 小时热榜"], start_at, end_at)
    if not sources:
        raise RuntimeError(warnings[0] if warnings else "未获取到近期热点，请稍后重试。")

    report(0.28, f"已获取 {len(sources)} 条近期报道，正在整理可核对证据")
    evidence = []
    # The selection UI allows at most ten choices. Keeping the initial LLM
    # batch focused avoids a long, opaque wait on large multi-day hotlists.
    for index, source in enumerate(sources[:24], start=1):
        title = str(source.get("title") or "").strip()
        url = str(source.get("url") or "").strip()
        if not title or not is_36kr_url(url):
            continue
        evidence.append({
            "source_id": f"source_{index:03d}",
            "标题": title,
            "摘要": str(source.get("description") or "").strip(),
            "发布时间": str(source.get("published_at") or "").strip(),
            "热度": source.get("heat_score") or 0,
            "链接": url,
            "来源": str(source.get("source_name") or "36Kr").strip(),
        })
    if not evidence:
        raise RuntimeError("热点报道未返回可核对的文章链接。")

    report(0.46, f"正在由 AI 拆分 {len(evidence)} 条报道中的独立热点")
    prompt = f"""你是中文商业热点编辑。下面是 36Kr 热榜的标题和摘要；一篇报道可能把多个独立新闻、公司动态或人物事件拼在一起。
请逐篇拆分成可单独制作短视频、可单独检索视频素材的“独立热点”。热点不要求是名人事件，可以是公司、产品、融资、政策、行业变化、发布会或争议；但必须能完全从输入证据中核对，不能补写或猜测事实。
每条热点必须只对应一个 source_id；同一 source_id 最多拆 2 条。排除没有明确事实主体的泛泛评论、广告文案和重复热点。尽量保留输入中出现的明确主体、动作和时间线。总计最多返回 40 条。

36Kr 证据：
{json.dumps(evidence, ensure_ascii=False)[:36000]}

返回严格 JSON：
{{
  "hotspots": [
    {{
      "source_id":"source_001",
      "title":"独立热点标题",
      "category":"公司动态|产品发布|融资并购|行业趋势|政策监管|人物事件|消费市场|其他",
      "summary":"仅根据原文摘要整理的热点事实，不超过180字",
      "why_hot":"该热点值得进一步检索视频素材的原因，不超过100字",
      "evidence_excerpt":"从输入标题或摘要摘取/忠实压缩，不超过120字",
      "entities":["原文中明确出现的公司、产品、人物或事件主体，2至5项"]
    }}
  ]
    }}"""
    split_result = {}
    split_finished = threading.Event()

    def split_hotspots_with_llm():
        try:
            split_result["response"] = llm_json(prompt, provider_id=provider_id, max_tokens=4800)
        except BaseException as exc:
            split_result["error"] = exc
        finally:
            split_finished.set()

    threading.Thread(target=split_hotspots_with_llm, daemon=True).start()
    waiting_progress = 0.46
    while not split_finished.wait(2.5):
        waiting_progress = min(0.72, waiting_progress + 0.02)
        report(waiting_progress, f"正在由 AI 拆分 {len(evidence)} 条报道中的独立热点（模型处理中）")
    if "error" in split_result:
        raise split_result["error"]
    response = split_result.get("response") or {}
    report(0.78, "AI 已返回拆分结果，正在核对来源证据")
    source_by_id = {item["source_id"]: item for item in evidence}
    per_source_count = {}
    seen = set()
    hotspots = []
    for item in response.get("hotspots", []) if isinstance(response.get("hotspots"), list) else []:
        source_id = str(item.get("source_id") or "").strip()
        source = source_by_id.get(source_id)
        title = str(item.get("title") or "").strip()
        key = re.sub(r"\s+", "", title).casefold()
        if not source or len(title) < 4 or key in seen or per_source_count.get(source_id, 0) >= 2:
            continue
        entities = safe_string_list(item.get("entities"), limit=5, item_limit=60)
        hotspots.append({
            "hotspot_id": f"hotspot-{len(hotspots) + 1:03d}",
            "source_id": source_id,
            "title": title[:140],
            "category": str(item.get("category") or "其他").strip()[:40],
            "summary": str(item.get("summary") or source["摘要"]).strip()[:300],
            "why_hot": str(item.get("why_hot") or "来自近期 36Kr 热榜报道。").strip()[:160],
            "evidence_excerpt": str(item.get("evidence_excerpt") or source["摘要"] or source["标题"]).strip()[:500],
            "entities": entities,
            "source_title": source["标题"],
            "source_url": source["链接"],
            "source_name": source["来源"],
            "published_at": source["发布时间"],
            "heat_score": source["热度"],
        })
        seen.add(key)
        per_source_count[source_id] = per_source_count.get(source_id, 0) + 1
        if len(hotspots) >= 40:
            break
    if not hotspots:
        raise RuntimeError("AI 未能从当前报道中拆出可核对的独立热点。")

    pool_id = f"hotspots-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    pool = {
        "pool_id": pool_id,
        "provider": "热点发现",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "start_at": start_at,
        "end_at": end_at,
        "source_count": len(sources),
        "hotspots": hotspots,
        "warnings": warnings[:8],
    }
    write_json(trend_hotspot_pool_path(pool_id), pool)
    report(0.97, f"已保存 {len(hotspots)} 条候选热点")
    return pool


def load_selected_trend_hotspots(pool_id, raw_hotspot_ids, max_selection=10):
    if not str(pool_id or "").startswith("hotspots-"):
        raise RuntimeError("请先获取并拆分 36Kr 候选热点，再生成检索词。")
    pool = read_json(trend_hotspot_pool_path(pool_id), {})
    if not isinstance(pool, dict) or not isinstance(pool.get("hotspots"), list):
        raise RuntimeError("候选热点已失效，请重新获取 36Kr 热点。")
    if isinstance(raw_hotspot_ids, str):
        raw_hotspot_ids = [raw_hotspot_ids]
    hotspot_ids = []
    for hotspot_id in raw_hotspot_ids or []:
        value = str(hotspot_id or "").strip()
        if value and value not in hotspot_ids:
            hotspot_ids.append(value)
    if not hotspot_ids:
        raise RuntimeError("请至少选择 1 条候选热点。")
    if len(hotspot_ids) > max_selection:
        raise RuntimeError(f"最多只能选择 {max_selection} 条候选热点。")
    hotspots_by_id = {str(item.get("hotspot_id") or ""): item for item in pool["hotspots"] if isinstance(item, dict)}
    missing = [hotspot_id for hotspot_id in hotspot_ids if hotspot_id not in hotspots_by_id]
    if missing:
        raise RuntimeError("部分候选热点已失效，请重新获取 36Kr 热点。")
    return pool, [hotspots_by_id[hotspot_id] for hotspot_id in hotspot_ids]


def fallback_hotspot_topic(hotspot):
    title = str(hotspot.get("title") or "36Kr 热点").strip()
    entities = hotspot_search_anchors(hotspot, limit=5)
    match_terms = entities or [title[:30]]
    material_queries = []
    if entities:
        material_queries = enforce_hotspot_query_anchors(
            hotspot,
            [f"{hotspot_query_subject(hotspot, entities)} 新闻现场", f"{hotspot_query_subject(hotspot, entities)} 发布会", f"{hotspot_query_subject(hotspot, entities)} 权威报道"],
        )
    return {
        "topic_id": f"topic-{hotspot.get('hotspot_id')}-{uuid4().hex[:6]}",
        "hotspot_id": hotspot.get("hotspot_id"),
        "title": title[:140],
        "category": str(hotspot.get("category") or "36Kr 热点")[:40],
        "subject_label": "、".join(entities[:3]) or "热点主体待核对",
        "statement_summary": str(hotspot.get("summary") or title).strip()[:300],
        "heat_reason": str(hotspot.get("why_hot") or "来自用户确认的 36Kr 近期热点。").strip()[:200],
        "evidence_excerpt": str(hotspot.get("evidence_excerpt") or title).strip()[:500],
        "source_confidence": "medium",
        "source_title": str(hotspot.get("source_title") or title),
        "source_url": str(hotspot.get("source_url") or ""),
        "source_name": str(hotspot.get("source_name") or "36Kr"),
        "published_at": str(hotspot.get("published_at") or ""),
        "material_queries": material_queries,
        "match_terms": match_terms,
        "search_anchors": entities,
        "recommendation_reason": "已按用户选择的热点保留，等待人工核对。" if entities else "来源报道中未能确认可用于检索的主体锚点，未执行泛词搜索。",
        "query_generation": "fallback" if entities else "anchor_missing",
        "materials": [],
    }


def generate_trend_topics_from_hotspots(selected_hotspots, knowledge_context, provider_id=None):
    selected_hotspots = [item for item in selected_hotspots or [] if isinstance(item, dict) and item.get("hotspot_id")]
    if not selected_hotspots:
        return []
    evidence = [
        {
            "hotspot_id": item["hotspot_id"],
            "热点": item.get("title", ""),
            "分类": item.get("category", ""),
            "摘要": item.get("summary", ""),
            "证据摘录": item.get("evidence_excerpt", ""),
            "主体": item.get("entities", []),
            "已核对锚点": hotspot_search_anchors(item),
            "原报道正文": str(item.get("source_article_text") or "")[:12000],
            "来源标题": item.get("source_title", ""),
            "来源链接": item.get("source_url", ""),
        }
        for item in selected_hotspots
    ]
    prompt = f"""你是中文短视频素材检索编辑。用户已确认下列独立热点；请只为这些热点逐条生成可用于视频素材搜索的检索词。
每个 hotspot_id 最多输出 1 条，必须覆盖每一个输入热点。不能引入未选择的热点、人物或事实。每条 material_queries 必须根据“原报道正文”生成，不能只根据热点标题、摘要或泛概念生成。
先从原报道正文中找出明确出现的公司名、人物名、产品名、项目名、活动名或机构名，写入 verified_anchors。每个 verified_anchors 必须能在原报道正文逐字找到；有 2 个及以上锚点时，每条 material_queries 至少包含其中 2 个；只有 1 个锚点时，每条必须包含它。不得只输出“AI 治疗癌症”“机器人”“新能源”等泛概念词。
例如，若原报道正文包含 Moderna、默沙东、intismeran autogene，则应写成“Moderna 默沙东 intismeran autogene 黑色素瘤 III期临床试验”一类可追溯的查询，而不是“AI 治疗癌症”。检索词应保留原报道中已核对的主体和具体事件，并优先适合寻找新闻现场、发布会、产品演示、采访、权威媒体报道等公开视频；热点不要求有名人。
知识库只用于轻量排序，不得排除用户已选择的热点。

用户偏好知识库：
{json.dumps(compact_trend_knowledge_context(), ensure_ascii=False)[:6000]}

已选热点证据：
{json.dumps(evidence, ensure_ascii=False)[:18000]}

返回严格 JSON：
{{
  "topics": [
    {{
      "hotspot_id":"hotspot-001",
      "title":"适合短视频的选题标题",
      "category":"与输入热点一致或更具体的分类",
      "subject_label":"公司/产品/人物/事件主体，最多3项",
      "statement_summary":"只根据输入概括热点事实，不超过200字",
      "heat_reason":"为什么值得做，不超过100字",
      "evidence_excerpt":"只摘取或忠实压缩输入证据，不超过120字",
       "source_confidence":"high|medium",
       "verified_anchors":["原报道正文中逐字出现的公司、人名、产品、活动或机构名称，2至5项"],
       "material_queries":["主体 事件 新闻现场", "主体 事件 发布会", "主体 事件 权威报道"],
      "match_terms":["用于判断视频是否相关的明确主体或关键词，2至5项"],
      "recommendation_reason":"与用户偏好的轻量匹配原因"
    }}
  ]
}}"""
    response = llm_json(prompt, provider_id=provider_id, max_tokens=7000)
    hotspots_by_id = {str(item["hotspot_id"]): item for item in selected_hotspots}
    topics_by_hotspot_id = {}
    for item in response.get("topics", []) if isinstance(response.get("topics"), list) else []:
        hotspot_id = str(item.get("hotspot_id") or "").strip()
        hotspot = hotspots_by_id.get(hotspot_id)
        if not hotspot or hotspot_id in topics_by_hotspot_id:
            continue
        verified_context = dict(hotspot, verified_anchors=item.get("verified_anchors"))
        anchors = hotspot_search_anchors(verified_context, limit=5)
        queries = enforce_hotspot_query_anchors(verified_context, item.get("material_queries"), limit=3)
        match_terms = safe_string_list(item.get("match_terms"), limit=5, item_limit=60)
        if not anchors or not queries or not match_terms:
            topics_by_hotspot_id[hotspot_id] = fallback_hotspot_topic(hotspot)
            continue
        topics_by_hotspot_id[hotspot_id] = {
            "topic_id": f"topic-{hotspot_id}-{uuid4().hex[:6]}",
            "hotspot_id": hotspot_id,
            "title": str(item.get("title") or hotspot["title"]).strip()[:140],
            "category": str(item.get("category") or hotspot.get("category") or "36Kr 热点").strip()[:40],
            "subject_label": str(item.get("subject_label") or "、".join(anchors or hotspot.get("entities") or [])).strip()[:100],
            "statement_summary": str(item.get("statement_summary") or hotspot.get("summary") or "").strip()[:300],
            "heat_reason": str(item.get("heat_reason") or hotspot.get("why_hot") or "").strip()[:200],
            "evidence_excerpt": str(item.get("evidence_excerpt") or hotspot.get("evidence_excerpt") or "").strip()[:500],
            "source_confidence": "high" if str(item.get("source_confidence")).lower() == "high" else "medium",
            "source_title": str(hotspot.get("source_title") or hotspot["title"]),
            "source_url": str(hotspot.get("source_url") or ""),
            "source_name": str(hotspot.get("source_name") or "36Kr"),
            "published_at": str(hotspot.get("published_at") or ""),
            "material_queries": queries,
            "match_terms": merge_search_terms(anchors, match_terms, limit=6),
            "search_anchors": anchors,
            "source_article_excerpt": normalize_article_text(hotspot.get("source_article_text"), limit=1800),
            "source_article_source": str(hotspot.get("source_article_source") or ""),
            "recommendation_reason": str(item.get("recommendation_reason") or "").strip()[:240],
            "query_generation": "llm",
            "materials": [],
        }
    for hotspot in selected_hotspots:
        hotspot_id = str(hotspot["hotspot_id"])
        if hotspot_id not in topics_by_hotspot_id:
            topics_by_hotspot_id[hotspot_id] = fallback_hotspot_topic(hotspot)
    return [topics_by_hotspot_id[str(item["hotspot_id"])] for item in selected_hotspots]


def material_candidate_quality(candidate, topic):
    haystack = " ".join(str(candidate.get(key) or "") for key in ("title", "description", "author")).casefold()
    speaker = str(topic.get("speaker_name") or "").casefold()
    search_anchors = safe_string_list(topic.get("search_anchors"), limit=5, item_limit=80)
    match_terms = safe_string_list(topic.get("match_terms"), limit=6, item_limit=60)
    if speaker and speaker not in match_terms:
        match_terms.insert(0, speaker)
    normalized_terms = [term.casefold() for term in match_terms if len(term.strip()) >= 2]
    normalized_anchors = [term.casefold() for term in search_anchors if len(term.strip()) >= 2]
    score = float(candidate.get("heat_score") or 0)
    reasons = []
    matched_terms = [term for term in normalized_terms if term in haystack]
    matched_anchors = [term for term in normalized_anchors if term in haystack]
    topic_matched = bool(matched_anchors) if normalized_anchors else bool(matched_terms)
    if topic_matched:
        score += 30
        if speaker and speaker in haystack:
            reasons.append("标题或简介包含目标人物")
        elif matched_anchors:
            reasons.append(f"标题或简介包含热点主体：{matched_anchors[0]}")
        else:
            reasons.append(f"标题或简介包含热点关键词：{matched_terms[0]}")
    else:
        score -= 40
        reasons.append("未能确认热点主体或关键词")
    if re.search(r"采访|访谈|专访|对话|演讲|发布会|现场|完整", haystack):
        score += 16
        reasons.append("更接近原始发言场景")
    if re.search(r"解读|鸡汤|励志|文案|语录|混剪|搬运", haystack):
        score -= 28
        reasons.append("可能是二次创作")
    score = max(0, min(100, round(score)))
    grade = "A" if score >= 82 else "B" if score >= 62 else "C"
    return score, grade, "；".join(reasons) or "基于公开互动和主题匹配筛选", topic_matched


def append_topic_material(topic, candidate):
    score, grade, reason, topic_matched = material_candidate_quality(candidate, topic)
    if not topic_matched:
        return
    material = dict(candidate)
    material["material_score"] = score
    material["source_grade"] = grade
    material["material_reason"] = reason
    material["trend_topic_id"] = topic["topic_id"]
    material["trend_topic_title"] = topic["title"]
    topic["materials"].append(material)


def dedupe_topic_materials(topics, material_limit):
    for topic in topics:
        deduped = []
        seen_urls = set()
        for candidate in sorted(topic["materials"], key=lambda item: item.get("material_score", 0), reverse=True):
            url = str(candidate.get("url") or "").rstrip("/")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            deduped.append(candidate)
            if len(deduped) >= material_limit:
                break
        topic["materials"] = deduped


def enforce_topic_material_date_cutoff(topics, material_limit=None):
    """Remove any material published before its hotspot's calendar date.

    MediaCrawler results are filtered at ingestion time, but this final pass also
    protects the persisted response when an adapter supplies a non-standard date
    field or a topic already contains candidates from an older pipeline run.
    """
    discarded = 0
    for topic in topics:
        cutoff = str(topic.get("published_at") or "").strip()
        if not cutoff:
            continue
        kept = []
        for material in topic.get("materials") or []:
            if is_published_before(material.get("published_at"), cutoff):
                discarded += 1
                continue
            kept.append(material)
        topic["materials"] = kept
    if material_limit is not None:
        dedupe_topic_materials(topics, material_limit)
    return discarded


def collect_trend_materials(
    topics,
    platforms,
    material_limit,
    start_at="",
    end_at="",
    target_count=None,
    progress_callback=None,
    progress_start=0.45,
    progress_end=0.90,
):
    warnings = []
    cutoff_warnings = set()
    max_attempts = max((len(topic.get("material_queries") or []) for topic in topics), default=0)
    total_operations = max(1, max_attempts * max(1, len(topics)) * max(1, len(platforms)))
    completed_operations = 0
    for query_index in range(max_attempts):
        for topic in topics:
            if len(topic.get("materials") or []) >= material_limit:
                continue
            if target_count and len(topics_with_materials(topics)) >= target_count:
                return warnings
            queries = topic.get("material_queries") or []
            if query_index >= len(queries):
                continue
            query = str(queries[query_index] or "").strip()
            if not query:
                continue
            # Query one topic at a time: a slow or blocked platform request must
            # not hold every other topic hostage, and we can stop as soon as the
            # requested number of material-backed topics is ready.
            for platform in platforms:
                completed_operations += 1
                if progress_callback:
                    ratio = min(1.0, completed_operations / total_operations)
                    progress_callback(
                        progress_start + (progress_end - progress_start) * ratio,
                        f"正在搜索视频素材：{topic.get('subject_label') or topic.get('speaker_name') or topic.get('title') or '候选热点'} · {completed_operations}/{total_operations}",
                    )
                try:
                    _, candidates, platform_warnings = search_media_crawler_candidates(
                        [query],
                        platform,
                        max(24, material_limit * 8),
                        start_at,
                        end_at,
                        str(topic.get("published_at") or "").strip(),
                    )
                    warnings.extend(platform_warnings)
                except RuntimeError as exc:
                    warnings.append(f"{media_crawler_platform_label(platform)} 素材检索失败：{exc}")
                    continue
                cutoff = str(topic.get("published_at") or "").strip()
                filtered_candidates = []
                discarded_before_cutoff = 0
                for candidate in candidates:
                    if is_published_before(candidate.get("published_at"), cutoff):
                        discarded_before_cutoff += 1
                        continue
                    filtered_candidates.append(candidate)
                if discarded_before_cutoff and cutoff not in cutoff_warnings:
                    cutoff_warnings.add(cutoff)
                    warnings.append(
                        f"{topic.get('subject_label') or topic.get('speaker_name') or topic.get('title') or '该热点'}："
                        f"已排除 {discarded_before_cutoff} 条早于热点报道发布时间的视频素材。"
                    )
                for candidate in filtered_candidates:
                    append_topic_material(topic, candidate)
                dedupe_topic_materials([topic], material_limit)
                if target_count and len(topics_with_materials(topics)) >= target_count:
                    return warnings
                if len(topic.get("materials") or []) >= material_limit:
                    break
    final_discarded = enforce_topic_material_date_cutoff(topics, material_limit)
    if final_discarded:
        warnings.append(f"最终校验已移除 {final_discarded} 条早于热点报道日期的视频素材。")
    return warnings


def topics_with_materials(topics):
    return [topic for topic in topics if topic.get("materials")]


def discover_selected_trend_hotspots(payload, progress_callback=None):
    """Generate queries and source footage only for user-approved split hotspots."""
    def report(progress, message):
        if progress_callback:
            progress_callback(max(0.0, min(0.99, float(progress))), message)

    payload = payload or {}
    report(0.03, "正在读取轻量选题偏好")
    knowledge_context = trend_knowledge_context()
    start_at = str(payload.get("start_at") or "").strip()
    end_at = str(payload.get("end_at") or "").strip()
    platforms = normalize_trend_platforms(payload.get("platforms"))
    pool, selected_hotspots = load_selected_trend_hotspots(
        payload.get("hotspot_pool_id"), payload.get("hotspot_ids")
    )
    report(0.08, f"已确认 {len(selected_hotspots)} 条热点，正在读取来源报道")

    def report_source_read(index, total, title):
        progress = 0.08 + 0.10 * (index / max(1, total))
        report(progress, f"正在核对来源报道 {index}/{total}：{title[:36]}")

    selected_hotspots = enrich_hotspots_with_source_articles(
        selected_hotspots, progress_callback=report_source_read
    )
    report(0.20, f"已核对 {len(selected_hotspots)} 条来源报道，正在生成检索词")
    topics = generate_trend_topics_from_hotspots(
        selected_hotspots, knowledge_context, provider_id=payload.get("provider_id")
    )
    if not topics:
        raise RuntimeError("AI 未能为所选热点生成检索词，请稍后重试。")

    report(0.42, "正在根据所选热点搜索视频素材")
    warnings = list(pool.get("warnings") or [])
    warnings.extend(collect_trend_materials(
        topics,
        platforms,
        material_limit=3,
        target_count=None,
        progress_callback=progress_callback,
        progress_start=0.44,
        progress_end=0.93,
    ))
    material_topic_count = len(topics_with_materials(topics))
    summary_warning = (
        f"已为 {len(topics)} 条所选热点生成检索词，其中 {material_topic_count} 条找到视频素材；"
        "未找到素材的热点仍会保留供人工核对。"
    )
    warnings.insert(0, summary_warning)
    fallback_topics = [topic for topic in topics if topic.get("query_generation") == "fallback"]
    if fallback_topics:
        warnings.append(f"AI 未返回 {len(fallback_topics)} 条热点的完整结构化结果，已保留默认检索词。")

    flat_candidates = [candidate for topic in topics for candidate in topic.get("materials", [])]
    report(0.98, f"正在整理 {len(topics)} 条选题和视频素材")
    search_id = f"trend-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    result = {
        "search_id": search_id,
        "provider": "视频素材搜索",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "start_at": start_at,
        "end_at": end_at,
        "material_platforms": platforms,
        "material_date_policy": "按自然日排除早于热点报道日期的视频",
        "knowledge_count": len(knowledge_context),
        "hotspot_pool_id": pool.get("pool_id"),
        "selected_hotspots": [
            {"hotspot_id": hotspot.get("hotspot_id"), "title": hotspot.get("title")}
            for hotspot in selected_hotspots
        ],
        "generated_queries": [query for topic in topics for query in topic.get("material_queries") or []],
        "editorial_focus": [hotspot.get("title") for hotspot in selected_hotspots],
        "requested_count": len(selected_hotspots),
        "source_count": int(pool.get("source_count") or 0),
        "topics": topics,
        "candidates": flat_candidates,
        "warnings": warnings[:8],
    }
    write_json(trend_search_path(search_id), result)
    return result


def discover_ai_trends(payload, progress_callback=None):
    payload = payload or {}
    if payload.get("hotspot_pool_id"):
        return discover_selected_trend_hotspots(payload, progress_callback=progress_callback)

    def report(progress, message):
        if progress_callback:
            progress_callback(max(0.0, min(0.99, float(progress))), message)

    report(0.03, "正在读取轻量选题偏好")
    knowledge_context = trend_knowledge_context()
    start_at = str(payload.get("start_at") or "").strip()
    end_at = str(payload.get("end_at") or "").strip()
    platforms = normalize_trend_platforms(payload.get("platforms"))
    pool, selected_people, sources = load_selected_trend_people(payload.get("person_pool_id"), payload.get("person_ids"))
    if not sources:
        raise RuntimeError("所选人物缺少可用的 36Kr 热点证据，请重新获取候选人物。")
    report(0.18, f"已确认 {len(selected_people)} 位人物，正在生成选题和检索词")
    topics = choose_trend_topics(sources, knowledge_context, selected_people, provider_id=payload.get("provider_id"))
    if not topics:
        raise RuntimeError("AI 未能为所选人物生成选题，请稍后重试。")
    # The source report timestamp is the lower bound for footage. This prevents
    # a current hotspot from being matched to an unrelated years-old upload.
    report(0.42, "正在根据所选人物搜索视频素材")
    warnings = list(pool.get("warnings") or [])
    warnings.extend(collect_trend_materials(
        topics,
        platforms,
        material_limit=3,
        target_count=None,
        progress_callback=progress_callback,
        progress_start=0.44,
        progress_end=0.93,
    ))
    selected_topics = topics
    cache_warning = next((warning for warning in warnings if "本地缓存" in warning), "")
    material_topic_count = len(topics_with_materials(selected_topics))
    summary_warning = f"已为 {len(selected_topics)} 位所选人物生成选题，其中 {material_topic_count} 位找到匹配视频素材；未找到素材的选题仍会保留供人工核对。"
    warnings.insert(0, summary_warning)
    if cache_warning:
        warnings.remove(cache_warning)
        warnings.insert(1, cache_warning)
    fallback_people = [topic.get("speaker_name") for topic in selected_topics if topic.get("query_generation") == "fallback"]
    if fallback_people:
        warnings.append(f"AI 未返回 {len(fallback_people)} 位人物的完整结构化结果，已保留默认检索词：{'、'.join(fallback_people)}。")
    flat_candidates = [candidate for topic in selected_topics for candidate in topic.get("materials", [])]
    report(0.98, f"正在整理 {len(selected_topics)} 条选题和视频素材")
    search_id = f"trend-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    result = {
        "search_id": search_id,
        "provider": "视频素材搜索",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "start_at": start_at,
        "end_at": end_at,
        "material_platforms": platforms,
        "material_date_policy": "按自然日排除早于热点报道日期的视频",
        "knowledge_count": len(knowledge_context),
        "person_pool_id": pool.get("pool_id"),
        "selected_people": [{"person_id": person.get("person_id"), "name": person.get("name")} for person in selected_people],
        "generated_queries": [query for topic in selected_topics for query in topic.get("material_queries") or []],
        "editorial_focus": [person.get("name") for person in selected_people],
        "requested_count": len(selected_people),
        "source_count": len(sources),
        "topics": selected_topics,
        "candidates": flat_candidates,
        "warnings": warnings[:8],
    }
    write_json(trend_search_path(search_id), result)
    return result


def trend_discovery_worker(task_id, payload):
    try:
        set_trend_task(
            task_id,
            status="running",
            stage="discovering",
            progress=0.01,
            message="正在启动 AI 爆款发现",
            started_at=datetime.now().isoformat(timespec="seconds"),
        )

        def update_progress(progress, message):
            set_trend_task(task_id, status="running", stage="discovering", progress=progress, message=message)

        result = discover_ai_trends(payload, progress_callback=update_progress)
        topics = result.get("topics") or []
        material_topic_count = len(topics_with_materials(topics))
        set_trend_task(
            task_id,
            status="done",
            stage="done",
            progress=1,
            message=(
                f"发现完成：已生成 {len(topics)}/{result.get('requested_count') or len(topics)} 条"
                f"{'热点' if result.get('selected_hotspots') else '人物'}选题，其中 {material_topic_count} 条找到素材"
            ),
            search_id=result.get("search_id"),
            requested_count=result.get("requested_count"),
            topic_count=len(topics),
            candidate_count=len(result.get("candidates") or []),
        )
    except Exception as exc:
        set_trend_task(
            task_id,
            status="error",
            stage="error",
            progress=0,
            message=str(exc),
            error=str(exc),
        )
    finally:
        global ACTIVE_TREND_DISCOVERY_TASK_ID
        with TREND_DISCOVERY_LOCK:
            if ACTIVE_TREND_DISCOVERY_TASK_ID == task_id:
                ACTIVE_TREND_DISCOVERY_TASK_ID = None


def start_trend_discovery(payload):
    global ACTIVE_TREND_DISCOVERY_TASK_ID
    payload = payload or {}
    raw_person_ids = payload.get("person_ids", [])
    if isinstance(raw_person_ids, str):
        raw_person_ids = [raw_person_ids]
    person_ids = [str(item).strip() for item in raw_person_ids if str(item).strip()][:6]
    raw_hotspot_ids = payload.get("hotspot_ids", [])
    if isinstance(raw_hotspot_ids, str):
        raw_hotspot_ids = [raw_hotspot_ids]
    hotspot_ids = [str(item).strip() for item in raw_hotspot_ids if str(item).strip()]
    with TREND_DISCOVERY_LOCK:
        active_task = get_trend_task(ACTIVE_TREND_DISCOVERY_TASK_ID) if ACTIVE_TREND_DISCOVERY_TASK_ID else {}
        if active_task.get("status") in {"queued", "running"}:
            return active_task
        task_id = f"trend-discover-{uuid4().hex[:12]}"
        task = set_trend_task(
            task_id,
            kind="discovery",
            status="queued",
            stage="queued",
            progress=0,
            person_ids=person_ids,
            hotspot_ids=hotspot_ids,
            message="已加入 AI 爆款发现队列",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        ACTIVE_TREND_DISCOVERY_TASK_ID = task_id
    threading.Thread(
        target=trend_discovery_worker,
        args=(task_id, dict(payload)),
        daemon=True,
    ).start()
    return task


def trend_hotspot_pool_worker(task_id, payload):
    try:
        set_trend_task(
            task_id,
            status="running",
            stage="fetching_hotspots",
            progress=0.01,
            progress_label="热点拆分进度",
            message="正在启动热点获取",
            started_at=datetime.now().isoformat(timespec="seconds"),
        )

        def update_progress(progress, message):
            set_trend_task(
                task_id,
                status="running",
                stage="fetching_hotspots",
                progress=progress,
                progress_label="热点拆分进度",
                message=message,
            )

        pool = build_trend_hotspot_pool(
            str(payload.get("start_at") or "").strip(),
            str(payload.get("end_at") or "").strip(),
            provider_id=payload.get("provider_id"),
            progress_callback=update_progress,
        )
        set_trend_task(
            task_id,
            status="done",
            stage="done",
            progress=1,
            progress_label="热点拆分进度",
            message=f"热点拆分完成：已得到 {len(pool.get('hotspots') or [])} 条候选热点",
            pool=pool,
            pool_id=pool.get("pool_id"),
            source_count=pool.get("source_count") or 0,
            hotspot_count=len(pool.get("hotspots") or []),
        )
    except Exception as exc:
        set_trend_task(
            task_id,
            status="error",
            stage="error",
            progress=0,
            progress_label="热点拆分进度",
            message=str(exc),
            error=str(exc),
        )
    finally:
        global ACTIVE_TREND_HOTSPOT_TASK_ID
        with TREND_HOTSPOT_LOCK:
            if ACTIVE_TREND_HOTSPOT_TASK_ID == task_id:
                ACTIVE_TREND_HOTSPOT_TASK_ID = None


def start_trend_hotspot_pool_build(payload):
    global ACTIVE_TREND_HOTSPOT_TASK_ID
    payload = payload or {}
    with TREND_HOTSPOT_LOCK:
        active_task = get_trend_task(ACTIVE_TREND_HOTSPOT_TASK_ID) if ACTIVE_TREND_HOTSPOT_TASK_ID else {}
        if active_task.get("status") in {"queued", "running"}:
            return active_task
        task_id = f"trend-hotspots-{uuid4().hex[:12]}"
        task = set_trend_task(
            task_id,
            kind="hotspot_pool",
            status="queued",
            stage="queued",
            progress=0,
            progress_label="热点拆分进度",
            message="已加入热点整理队列",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        ACTIVE_TREND_HOTSPOT_TASK_ID = task_id
    threading.Thread(
        target=trend_hotspot_pool_worker,
        args=(task_id, dict(payload)),
        daemon=True,
    ).start()
    return task


def resolve_relative_path(base_dir, relative_path):
    """Resolve a request path only when it stays inside the allowed directory."""
    base = base_dir.resolve()
    try:
        target = (base / Path(urllib.parse.unquote(str(relative_path)))).resolve()
        target.relative_to(base)
    except (OSError, ValueError):
        return None
    return target


def seconds_to_clock(seconds):
    seconds = max(0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def clip_filename(index, title, start, end):
    safe_title = sanitize_name(title)[:32]
    return f"{index:03d}_{safe_title}_{seconds_to_clock(start).replace(':', '-')}_to_{seconds_to_clock(end).replace(':', '-')}.mp4"


def job_output_dir(job_id, create=True):
    """Return a task's result folder, creating it only for an output action."""
    base_dir = job_dir(job_id)
    meta_path = base_dir / "metadata.json"
    meta = read_json(meta_path, {})
    folder_name = sanitize_output_name(meta.get("output_folder") or meta.get("output_title") or meta.get("title") or job_id)
    if not meta.get("output_folder"):
        candidate = folder_name
        suffix = 1
        while (OUTPUTS_DIR / folder_name).exists():
            folder_name = suffixed_name(candidate, suffix)
            suffix += 1
        meta["output_folder"] = folder_name
        write_json(meta_path, meta)
    target = OUTPUTS_DIR / folder_name
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def clip_output_folder_name(clip):
    start = seconds_to_clock(clip.get("start") or 0).replace(":", "-")
    end = seconds_to_clock(clip.get("end") or 0).replace(":", "-")
    return f"{start}_to_{end}"


def clip_output_dir(job_id, clip, create=True):
    target = job_output_dir(job_id, create=create) / "clips" / clip_output_folder_name(clip)
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def clip_analysis_markdown(clip):
    title = str(clip.get("title") or clip.get("id") or "clip").strip()
    start = seconds_to_clock(clip.get("start") or 0)
    end = seconds_to_clock(clip.get("end") or 0)
    duration = max(0.0, float(clip.get("end") or 0) - float(clip.get("start") or 0))
    lines = [
        f"# {title}",
        "",
        f"- \u65f6\u95f4\u8303\u56f4: {start} - {end}",
        f"- \u65f6\u957f: {duration:.3f}\u79d2",
    ]
    if clip.get("clip_type"):
        lines.append(f"- \u7247\u6bb5\u7c7b\u578b: {clip['clip_type']}")
    if clip.get("confidence") not in {None, ""}:
        lines.append(f"- \u7f6e\u4fe1\u5ea6: {clip['confidence']}")

    score_names = [
        ("quote_score", "\u91d1\u53e5\u5206"),
        ("context_score", "\u4e0a\u4e0b\u6587\u5206"),
        ("edit_score", "\u53ef\u526a\u8f91\u5206"),
        ("viral_score", "\u4f20\u64ad\u5206"),
        ("selection_score", "\u7efc\u5408\u5206"),
    ]
    scores = [f"{label} {clip[key]}" for key, label in score_names if clip.get(key) not in {None, ""}]
    if scores:
        lines.extend(["", "## \u8bc4\u5206", "", "- " + "\n- ".join(scores)])

    sections = [
        ("\u5019\u9009\u6807\u9898", "suggested_title"),
        ("\u5019\u9009\u6807\u9898 B", "alternate_title"),
        ("\u91d1\u53e5", "quote"),
        ("\u5165\u9009\u539f\u56e0", "reason"),
        ("\u539f\u58f0\u6587\u6848\uff08\u5df2\u7cbe\u7b80\u53e3\u8bef\uff09", "original_copy"),
        ("\u5c0f\u7ea2\u4e66\u6587\u6848", "xiaohongshu_copy"),
        ("\u8bc4\u8bba\u533a\u5f15\u5bfc", "comment_prompt"),
        ("\u5f00\u573a\u94a9\u5b50", "hook_text"),
        ("\u5c01\u9762\u6587\u6848", "cover_text"),
        ("\u526a\u8f91\u5efa\u8bae", "editor_note"),
    ]
    for heading, key in sections:
        text = str(clip.get(key) or "").strip()
        if text:
            lines.extend(["", f"## {heading}", "", text])
    tags = clip.get("hashtags") or clip.get("tags") or []
    if isinstance(tags, str):
        tags = [item for item in re.split(r"[\s,\uff0c]+", tags) if item]
    if isinstance(tags, list) and tags:
        lines.extend(["", "## \u8bdd\u9898\u6807\u7b7e", "", " ".join(f"#{str(tag).lstrip('#')}" for tag in tags if str(tag).strip())])
    return "\n".join(lines).rstrip() + "\n"


def write_grouped_transcript_output(job_id):
    base_dir = job_dir(job_id)
    grouped = read_json(base_dir / "transcript_grouped.json", {"groups": []})
    groups = grouped.get("groups", [])
    lines = [
        f"[{seconds_to_clock(group.get('start') or 0)} - {seconds_to_clock(group.get('end') or 0)}] {str(group.get('text') or '').strip()}"
        for group in groups
        if str(group.get("text") or "").strip()
    ]
    transcript_dir = job_output_dir(job_id) / "transcript"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    target = transcript_dir / "transcript_grouped.md"
    target.write_text("\n\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target


def ensure_transcript_output_dir(job_id):
    """Create the user-visible transcript directory only after transcription is started."""
    target = job_output_dir(job_id) / "transcript"
    target.mkdir(parents=True, exist_ok=True)
    return target


def sync_job_output(job_id, include_candidates=False, prune_clip_folders=False):
    """Sync persistent result files without creating per-clip export folders prematurely."""
    transcript_source = job_dir(job_id) / "transcript_grouped.json"
    # Loading an uploaded draft or opening storage management must not create an
    # empty result folder. Results begin at transcription, or at analysis for a
    # legacy task that already has highlight data.
    if not transcript_source.exists() and not include_candidates:
        return job_output_dir(job_id, create=False)

    root = job_output_dir(job_id)
    if transcript_source.exists():
        write_grouped_transcript_output(job_id)
    if not include_candidates:
        return root

    highlights = get_highlights(job_id)
    clips = highlights.get("clips", [])
    clips_root = root / "clips"
    clips_root.mkdir(parents=True, exist_ok=True)
    write_json(clips_root / "candidates.json", {"clips": clips})
    legacy_transcript = root / "transcript_grouped.md"
    if legacy_transcript.exists():
        legacy_transcript.unlink()
    if prune_clip_folders:
        current_folders = {clip_output_folder_name(clip) for clip in clips if clip.get("export_file") or clip.get("export_path")}
        for child in clips_root.iterdir():
            if child.is_dir() and child.name not in current_folders:
                shutil.rmtree(child, ignore_errors=True)
    return root


def remove_clip_output_folder(job_id, clip):
    shutil.rmtree(clip_output_dir(job_id, clip, create=False), ignore_errors=True)


def remove_clip_output_video(job_id, clip):
    folder = clip_output_dir(job_id, clip, create=False)
    if not folder.exists():
        return
    for path in folder.glob("clip.*"):
        if path.is_file():
            path.unlink()


def bundled_binary(name):
    candidates = [BIN_DIR / name]
    if os.name == "nt":
        candidates.insert(0, BIN_DIR / f"{name}.exe")
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which(name) or name


def ffmpeg_path():
    return bundled_binary("ffmpeg")


def ffprobe_path():
    return bundled_binary("ffprobe")


def run_process(cmd, cancel_check=None, on_process=None, env=None):
    if cancel_check:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env)
        if on_process:
            on_process(proc)
        while proc.poll() is None:
            if cancel_check():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise RuntimeError("转写已结束")
            time.sleep(0.1)
        stdout, stderr = proc.communicate()
    else:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
        stdout, stderr = proc.stdout, proc.stderr
    if proc.returncode != 0:
        detail = (stderr or stdout or "").strip()
        raise RuntimeError(detail or f"命令执行失败：{' '.join(cmd)}")
    return stdout


def ytdlp_environment():
    """Make the bundled yt-dlp package importable by its console launcher."""
    environment = os.environ.copy()
    if YTDLP_PACKAGE_DIR.is_dir():
        current = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(part for part in (str(YTDLP_PACKAGE_DIR), current) if part)
    return environment


def ytdlp_command():
    """Prefer the bundled or MediaCrawler virtual-environment yt-dlp module."""
    python_executable = media_crawler_python_path()
    if not IS_FROZEN and python_executable:
        if YTDLP_PACKAGE_DIR.is_dir():
            return [python_executable, "-m", "yt_dlp"]
        try:
            installed = subprocess.run(
                [python_executable, "-c", "import yt_dlp"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if installed.returncode == 0:
                return [python_executable, "-m", "yt_dlp"]
        except OSError:
            pass
    tool = ytdlp_path()
    return [tool] if tool else []


def run_ytdlp_process(command, task_id):
    """Run yt-dlp while translating its download percentage to the import task."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=ytdlp_environment(),
    )
    output = []
    while True:
        line = process.stdout.readline() if process.stdout else ""
        if line:
            text_line = line.strip()
            if text_line:
                output.append(text_line)
                match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", text_line)
                if match:
                    percent = max(0.0, min(100.0, float(match.group(1))))
                    progress = 0.05 + (percent / 100.0) * 0.70
                    set_trend_task(task_id, progress=progress, message=f"正在下载视频 · {percent:.0f}%")
        elif process.poll() is not None:
            break
        else:
            time.sleep(0.05)
    return_code = process.wait()
    if return_code != 0:
        detail = "\n".join(output[-12:]).strip()
        raise RuntimeError(detail or f"yt-dlp 下载失败（退出码 {return_code}）")


def ytdlp_path():
    candidates = [
        BIN_DIR / "yt-dlp.exe",
        BIN_DIR / "yt-dlp",
        YTDLP_PACKAGE_DIR / "bin" / "yt-dlp.exe",
        YTDLP_PACKAGE_DIR / "bin" / "yt-dlp",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")


def create_video_job(source_path, filename, source_url="", source_meta=None):
    """Create the same persistent workspace used by manual uploads."""
    source_path = Path(source_path)
    ext = source_path.suffix.lower()
    if ext not in {".mp4", ".mov"}:
        raise RuntimeError("只支持 MP4 或 MOV 视频")
    if not source_path.exists() or source_path.stat().st_size <= 0:
        raise RuntimeError("下载后没有找到有效的视频文件")

    with UPLOAD_LOCK:
        task_title = unique_task_title(filename)
        job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{sanitize_name(task_title)}-{uuid4().hex[:8]}"
        base_dir = job_dir(job_id)
        base_dir.mkdir(parents=True, exist_ok=False)
        source = base_dir / f"source{ext}"
        shutil.copy2(source_path, source)
        meta = {
            "job_id": job_id,
            "title": task_title,
            "output_title": task_title,
            "output_folder": task_title,
            "source_filename": filename,
            "original_file": source.name,
            "source_url": source_url,
            "source_kind": "viral_search" if source_url else "local_upload",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_size": source.stat().st_size,
            "status": "uploaded",
            "entered_task_center": True,
        }
        if source_meta:
            meta.update({key: value for key, value in source_meta.items() if key not in {"job_id", "original_file"}})
        meta.update(probe_video(source))
        write_json(base_dir / "metadata.json", meta)

    preview_queued = should_make_browser_preview(ext, meta)
    message = "源视频已保存，正在生成浏览器兼容预览" if preview_queued else "源视频已保存，可开始转写"
    set_job(job_id, stage="uploaded", message=message, metadata=meta, progress=0)
    if preview_queued:
        threading.Thread(target=browser_preview_worker, args=(job_id,), daemon=True).start()
    return {
        "job_id": job_id,
        "metadata": meta,
        "preview_url": f"/media/{job_id}/{source.name}",
        "browser_preview_queued": preview_queued,
    }


def download_video_as_mp4(candidate, task_id):
    runner = ytdlp_command()
    if not runner:
        raise RuntimeError("未找到 yt-dlp，请先将 yt-dlp.exe 放入项目 bin 或 .tools/yt-dlp/bin")
    target_dir = trend_download_dir(task_id)
    for old_file in target_dir.iterdir():
        if old_file.is_file():
            old_file.unlink(missing_ok=True)
    output_template = str(target_dir / "download.%(ext)s")
    command = [
        *runner,
        "--no-playlist",
        "--newline",
        "--no-warnings",
        "--restrict-filenames",
        "--format", "bv*+ba/b",
        "--merge-output-format", "mkv",
        "-o", output_template,
        candidate["url"],
    ]
    run_ytdlp_process(command, task_id)
    files = [path for path in target_dir.iterdir() if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}]
    if not files:
        raise RuntimeError("下载器没有产出可识别的视频文件")
    source = max(files, key=lambda path: path.stat().st_mtime)
    meta = probe_video(source)
    if meta.get("has_audio") is False:
        raise RuntimeError("下载结果不含音轨：该视频网页可能只提供纯视频流，或平台限制了音频下载。请打开原视频网页确认后重试。")
    target = target_dir / "source.mp4"
    normalize_cmd = [
        ffmpeg_path(), "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0",
        "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(target),
    ]
    try:
        run_process(normalize_cmd)
    except Exception:
        run_process([
            ffmpeg_path(), "-y", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(target),
        ])
    final_meta = probe_video(target)
    if final_meta.get("has_audio") is not True:
        raise RuntimeError("MP4 音轨合并失败：生成文件仍没有可用音频流。")
    return target


def chrome_executable():
    return _chrome_executable()


def open_chrome_search(payload):
    keywords = str(payload.get("keywords") or "").strip()
    source = str(payload.get("source") or "web").strip()
    if not keywords:
        raise RuntimeError("请先输入关键词")
    encoded = urllib.parse.quote_plus(keywords)
    urls = {
        "mediacrawler_bili": f"https://search.bilibili.com/all?keyword={encoded}",
        "mediacrawler_dy": f"https://www.douyin.com/search/{urllib.parse.quote(keywords)}?type=general",
        "mediacrawler_xhs": f"https://www.xiaohongshu.com/search_result?keyword={encoded}",
        "mediacrawler_ks": f"https://www.kuaishou.com/search/video?searchKey={encoded}",
        "mediacrawler_wb": f"https://s.weibo.com/video?q={encoded}",
        "web": f"https://www.google.com/search?tbm=vid&q={encoded}",
    }
    url = urls.get(source, urls["web"])
    executable = chrome_executable()
    if executable:
        try:
            subprocess.Popen([executable, "--new-window", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            return {"url": url, "browser": "chrome", "message": "已打开搜索网页，请完成登录后返回应用。"}
        except OSError as exc:
            logging.warning("无法启动 Chrome (%s): %s", executable, exc)
    raise RuntimeError("未找到或无法启动 Google Chrome；应用不会回退到 Edge 或系统默认浏览器")


def trend_import_worker(task_id, candidate):
    set_trend_task(task_id, status="running", stage="downloading", progress=0.05, message="正在下载视频")
    try:
        source = download_video_as_mp4(candidate, task_id)
        set_trend_task(task_id, stage="creating_job", progress=0.82, message="视频已下载，正在进入工作台")
        imported = create_video_job(
            source,
            f"{candidate.get('title') or '爆款视频'}.mp4",
            source_url=candidate.get("url", ""),
            source_meta={
                "trend_candidate_id": candidate.get("candidate_id"),
                "trend_platform": candidate.get("platform"),
                "trend_keyword": candidate.get("keyword"),
                "trend_heat_score": candidate.get("heat_score"),
            },
        )
        set_trend_task(task_id, status="done", stage="done", progress=1, message="已进入工作台", job_id=imported["job_id"], metadata=imported["metadata"])
    except Exception as exc:
        set_trend_task(task_id, status="error", stage="error", progress=1, message=str(exc))



def parse_ffmpeg_time(value):
    value = str(value or "").strip()
    if not value or value == "N/A":
        return None
    if ":" not in value:
        try:
            return max(0, float(value))
        except ValueError:
            return None
    try:
        h, m, s = value.split(":")
        return max(0, int(h) * 3600 + int(m) * 60 + float(s))
    except Exception:
        return None


def ffmpeg_progress_cmd(cmd):
    return [cmd[0], "-hide_banner", "-nostats", "-progress", "pipe:1", *cmd[1:]]


def run_process_with_progress(cmd, duration=None, on_progress=None, fallback_cmd=None, on_fallback=None, on_process=None, cancel_check=None):
    last_error = None
    commands = [(cmd, False)]
    if fallback_cmd:
        commands.append((fallback_cmd, True))
    for current_cmd, is_fallback in commands:
        if is_fallback and on_fallback:
            on_fallback()
        stderr_lines = []
        started = time.time()
        proc = subprocess.Popen(
            ffmpeg_progress_cmd(current_cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if on_process:
            on_process(proc)

        def drain_stderr():
            try:
                for err_line in proc.stderr:
                    err_line = err_line.strip()
                    if err_line:
                        stderr_lines.append(err_line)
                        del stderr_lines[:-20]
            except Exception:
                pass

        threading.Thread(target=drain_stderr, daemon=True).start()
        last_notify = 0
        out_time = 0.0
        try:
            while True:
                if cancel_check and cancel_check():
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    raise RuntimeError("\u5df2\u53d6\u6d88\u751f\u6210\u4efb\u52a1")
                line = proc.stdout.readline() if proc.stdout else ""
                if line:
                    line = line.strip()
                    if "=" in line:
                        key, value = line.split("=", 1)
                        if key in {"out_time_ms", "out_time_us"}:
                            try:
                                out_time = max(out_time, float(value) / 1000000.0)
                            except ValueError:
                                pass
                        elif key == "out_time":
                            parsed = parse_ffmpeg_time(value)
                            if parsed is not None:
                                out_time = max(out_time, parsed)
                if on_progress and duration:
                    now = time.time()
                    if now - last_notify >= 0.25:
                        progress = min(0.99, max(0.0, out_time / max(0.01, float(duration))))
                        elapsed = max(0.0, now - started)
                        remaining = None
                        if progress > 0.01:
                            remaining = max(0.0, elapsed * (1.0 - progress) / progress)
                        on_progress(progress, elapsed, remaining)
                        last_notify = now
                if not line and proc.poll() is not None:
                    break
                if not line:
                    time.sleep(0.05)
            if proc.returncode == 0:
                if on_progress:
                    on_progress(1.0, max(0.0, time.time() - started), 0)
                return ""
            detail = "\n".join(stderr_lines).strip()
            last_error = RuntimeError(detail or f"FFmpeg \u6267\u884c\u5931\u8d25\uff0c\u9000\u51fa\u7801 {proc.returncode}")
        except Exception as exc:
            last_error = exc
        finally:
            if on_process:
                on_process(None)
        if not is_fallback and fallback_cmd:
            continue
        raise last_error or RuntimeError("FFmpeg \u6267\u884c\u5931\u8d25")



ENCODER_CACHE = None


def detect_h264_encoder():
    global ENCODER_CACHE
    if ENCODER_CACHE:
        return ENCODER_CACHE
    preferred = [
        ("h264_nvenc", "NVIDIA 硬件编码"),
        ("h264_qsv", "Intel Quick Sync 硬件编码"),
        ("h264_amf", "AMD 硬件编码"),
    ]
    try:
        raw = run_process([ffmpeg_path(), "-hide_banner", "-encoders"])
    except Exception:
        raw = ""
    for name, label in preferred:
        if name in raw:
            ENCODER_CACHE = {"name": name, "label": label, "hardware": True}
            return ENCODER_CACHE
    ENCODER_CACHE = {"name": "libx264", "label": "CPU x264 编码", "hardware": False}
    return ENCODER_CACHE


def preview_video_args(encoder_name):
    common = ["-vf", "scale='min(1280,iw)':-2,fps=24", "-pix_fmt", "yuv420p"]
    if encoder_name == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "27", "-b:v", "0", *common]
    if encoder_name == "h264_qsv":
        return ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "27", *common]
    if encoder_name == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "speed", "-rc", "cqp", "-qp_i", "27", "-qp_p", "29", *common]
    return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "27", *common]


def build_preview_cmd(source, target, start=None, duration=None, encoder_name=None):
    encoder = encoder_name or detect_h264_encoder()["name"]
    cmd = [ffmpeg_path(), "-y"]
    if start is not None:
        cmd += ["-ss", seconds_to_clock(start)]
    if duration is not None:
        cmd += ["-t", f"{max(0.01, float(duration)):.3f}"]
    cmd += [
        "-i", str(source),
        "-map", "0:v:0",
        "-map", "0:a?",
        "-sn", "-dn",
        *preview_video_args(encoder),
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(target),
    ]
    return cmd


def run_preview_process(cmd, fallback_cmd=None, duration=None, on_progress=None, on_fallback=None, on_process=None, cancel_check=None):
    if on_progress:
        return run_process_with_progress(
            cmd,
            duration=duration,
            on_progress=on_progress,
            fallback_cmd=fallback_cmd,
            on_fallback=on_fallback,
            on_process=on_process,
            cancel_check=cancel_check,
        )
    try:
        return run_process(cmd)
    except Exception:
        if fallback_cmd:
            return run_process(fallback_cmd)
        raise


def should_make_browser_preview(ext, meta):
    codec = (meta.get("video_codec") or "").lower()
    pix = (meta.get("pixel_format") or "").lower()
    transfer = (meta.get("color_transfer") or "").lower()
    if ext.lower() == ".mov":
        return True
    if codec not in {"h264", "avc1"}:
        return True
    if pix and pix not in {"yuv420p", "yuvj420p"}:
        return True
    if transfer in {"smpte2084", "arib-std-b67"}:
        return True
    return False

def normalize_browser_preview_meta(base_dir, meta):
    preview_file = meta.get("browser_preview_file")
    if preview_file and not (base_dir / preview_file).exists():
        meta.pop("browser_preview_file", None)
        meta.pop("browser_preview_encoder", None)
        write_json(base_dir / "metadata.json", meta)
    return meta



def browser_preview_worker(job_id):
    base_dir = job_dir(job_id)
    meta = read_json(base_dir / "metadata.json", {})
    source = base_dir / meta.get("original_file", "source.mp4")
    target = base_dir / "browser-preview.mp4"
    started = time.time()
    encoder = detect_h264_encoder()
    try:
        set_job(job_id, stage="previewing", message=f"正在生成兼容预览（{encoder['label']}）", preview_progress=0, preview_elapsed=0, preview_remaining=None, metadata=meta)
        duration = float(meta.get("duration") or 0)
        cmd = build_preview_cmd(source, target, duration=duration or None, encoder_name=encoder["name"])
        fallback = None
        if encoder["name"] != "libx264":
            fallback = build_preview_cmd(source, target, duration=duration or None, encoder_name="libx264")
        run_preview_process(
            cmd,
            fallback,
            duration=duration or None,
            on_progress=lambda progress, elapsed, remaining: set_job(
                job_id,
                stage="previewing",
                message=f"\u6b63\u5728\u751f\u6210\u517c\u5bb9\u9884\u89c8\uff08{encoder['label']}\uff09",
                preview_progress=progress,
                preview_elapsed=elapsed,
                preview_remaining=remaining,
                metadata=meta,
            ),
            on_fallback=lambda: set_job(job_id, stage="previewing", message="\u786c\u4ef6\u7f16\u7801\u5931\u8d25\uff0c\u6b63\u5728\u81ea\u52a8\u5207\u6362 CPU \u7f16\u7801", metadata=meta),
        )
        meta["browser_preview_file"] = "browser-preview.mp4"
        meta["browser_preview_encoder"] = encoder["label"]
        write_json(base_dir / "metadata.json", meta)
        elapsed = max(0, time.time() - started)
        set_job(job_id, stage="preview_ready", message="兼容预览已生成", preview_progress=1, preview_elapsed=elapsed, preview_remaining=0, metadata=meta, browser_preview_url=f"/media/{job_id}/browser-preview.mp4")
    except Exception as exc:
        set_job(job_id, stage="preview_error", message=f"兼容预览生成失败：{exc}", preview_progress=0, preview_elapsed=max(0, time.time() - started), error=str(exc), metadata=meta)

def probe_video_with_ffmpeg(source_path):
    """Read the small metadata subset needed by the workbench without ffprobe."""
    proc = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(source_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    text_output = proc.stderr or proc.stdout or ""
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text_output)
    duration = 0
    if duration_match:
        duration = int(duration_match.group(1)) * 3600 + int(duration_match.group(2)) * 60 + float(duration_match.group(3))
    video_match = re.search(r"Video:\s*([^,\s]+).*?(\d{2,6})x(\d{2,6})", text_output, re.S)
    audio_match = re.search(r"Audio:\s*([^,\s]+)", text_output)
    if not video_match:
        raise RuntimeError("FFmpeg 无法读取视频流信息")
    codec = video_match.group(1)
    width, height = int(video_match.group(2)), int(video_match.group(3))
    pixel_match = re.search(r"\b(yuv\w+|gbr\w*|rgb\w*)\b", video_match.group(0), re.I)
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", video_match.group(0), re.I)
    return {
        "duration": float(duration),
        "width": width,
        "height": height,
        "fps": float(fps_match.group(1)) if fps_match else 0,
        "has_audio": bool(audio_match),
        "video_codec": codec,
        "video_codec_tag": None,
        "pixel_format": pixel_match.group(1) if pixel_match else None,
        "color_transfer": None,
        "color_primaries": None,
        "audio_codec": audio_match.group(1) if audio_match else None,
    }


def probe_video(source_path):
    cmd = [
        ffprobe_path(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source_path),
    ]
    try:
        raw = run_process(cmd)
        data = json.loads(raw)
    except Exception as exc:
        try:
            return probe_video_with_ffmpeg(source_path)
        except Exception as fallback_exc:
            return {"probe_error": str(fallback_exc or exc)}

    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    duration = data.get("format", {}).get("duration") or video_stream.get("duration") or 0
    fps = 0
    rate = video_stream.get("avg_frame_rate") or "0/1"
    try:
        num, den = rate.split("/")
        fps = round(float(num) / float(den), 3) if float(den) else 0
    except Exception:
        pass
    return {
        "duration": float(duration or 0),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "fps": fps,
        "has_audio": audio_stream is not None,
        "video_codec": video_stream.get("codec_name"),
        "video_codec_tag": video_stream.get("codec_tag_string"),
        "pixel_format": video_stream.get("pix_fmt"),
        "color_transfer": video_stream.get("color_transfer"),
        "color_primaries": video_stream.get("color_primaries"),
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
    }


def set_job(job_id, **updates):
    with JOB_LOCK:
        current = JOBS.setdefault(job_id, {})
        current["job_id"] = job_id
        preview_stages = {"previewing", "preview_ready", "preview_error"}
        incoming_stage = updates.get("stage")
        if incoming_stage in preview_stages and current.get("stage") not in preview_stages:
            updates = dict(updates)
            updates["preview_stage"] = updates.pop("stage")
            if "message" in updates:
                updates["preview_message"] = updates.pop("message")
            if "error" in updates:
                updates["preview_error"] = updates.pop("error")
        current.update(updates)
        if current.get("transcribe_started_at"):
            current["transcribe_elapsed"] = max(0, time.time() - float(current["transcribe_started_at"]))
        current["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(RUNTIME_DIR / "active_job.json", current)
        return dict(current)


def transcription_stop_requested(job_id, task_id=None):
    state = get_job_state(job_id)
    return bool(state.get("stop_requested") or clip_task_cancelled(task_id))


def transcription_pause_requested(job_id, task_id=None):
    state = get_job_state(job_id)
    return bool(state.get("pause_requested") or clip_task_paused(task_id))


def wait_for_transcription_resume(job_id, task_id=None, update_task=None):
    """Gate every local/cloud stage so pause and stop requests are observed."""
    while transcription_pause_requested(job_id, task_id):
        if transcription_stop_requested(job_id, task_id):
            raise RuntimeError("转写已结束")
        set_job(job_id, stage="paused", message="转写已暂停，等待继续")
        if update_task:
            update_task(status="paused", message="转写已暂停，等待继续")
        time.sleep(0.2)
    if transcription_stop_requested(job_id, task_id):
        raise RuntimeError("转写已结束")


def get_job_state(job_id):
    with JOB_LOCK:
        state = dict(JOBS.get(job_id, {}))
    if state:
        return state
    active = read_json(RUNTIME_DIR / "active_job.json", {})
    if active.get("job_id") == job_id:
        return active
    meta = read_json(job_dir(job_id) / "metadata.json", {})
    if meta:
        return {
            "job_id": job_id,
            "stage": meta.get("status", "ready"),
            "message": "\u5df2\u8f7d\u5165\u5386\u53f2\u4efb\u52a1",
            "metadata": meta,
        }
    return {}


def persist_clip_tasks():
    with CLIP_TASK_LOCK:
        tasks = [serialize_clip_task(task) for task in CLIP_TASKS.values()]
    write_json(TASKS_PATH, {"tasks": tasks, "updated_at": datetime.now().isoformat(timespec="seconds")})


def persist_clip_tasks_throttled(force=False):
    global TASK_PERSIST_LAST
    now = time.time()
    if force or now - TASK_PERSIST_LAST >= TASK_PERSIST_MIN_INTERVAL:
        TASK_PERSIST_LAST = now
        persist_clip_tasks()


def load_clip_tasks():
    payload = read_json(TASKS_PATH, {"tasks": []})
    loaded = 0
    with CLIP_TASK_LOCK:
        CLIP_TASKS.clear()
        for task in payload.get("tasks", []):
            if not task or not task.get("task_id"):
                continue
            task = dict(task)
            if task.get("status") in {"queued", "running"}:
                task["status"] = "cancelled"
                task["message"] = "\u670d\u52a1\u91cd\u542f\uff0c\u539f\u8fd0\u884c\u4efb\u52a1\u5df2\u4e2d\u65ad"
                task["remaining"] = 0
            task["process"] = None
            task["cancel_requested"] = False
            CLIP_TASKS[task["task_id"]] = task
            loaded += 1
    return loaded


def create_clip_task(job_id, clip_id, task_type="preview"):
    task_id = uuid4().hex
    now = time.time()
    task = {
        "task_id": task_id,
        "job_id": job_id,
        "clip_id": clip_id,
        "type": task_type,
        "status": "queued",
        "progress": 0,
        "percent": 0,
        "message": "\u5df2\u52a0\u5165\u751f\u6210\u961f\u5217",
        "started_at": now,
        "elapsed": 0,
        "remaining": None,
        "encoder": detect_h264_encoder().get("label"),
        "cancel_requested": False,
        "process": None,
    }
    with CLIP_TASK_LOCK:
        CLIP_TASKS[task_id] = task
    persist_clip_tasks()
    return task_id, serialize_clip_task(task)


def serialize_clip_task(task):
    if not task:
        return None
    public = {k: v for k, v in task.items() if k != "process"}
    started = public.get("started_at")
    if started and public.get("status") in {"queued", "running"}:
        public["elapsed"] = max(0, time.time() - float(started))
    return public


def get_clip_task(task_id):
    with CLIP_TASK_LOCK:
        task = CLIP_TASKS.get(task_id)
        return serialize_clip_task(task)


def list_clip_tasks(job_id=None, limit=30):
    with CLIP_TASK_LOCK:
        tasks = [serialize_clip_task(task) for task in CLIP_TASKS.values()]
    if job_id:
        tasks = [task for task in tasks if task and task.get("job_id") == job_id]
    tasks.sort(key=lambda task: float(task.get("started_at") or 0), reverse=True)
    return tasks[: max(1, int(limit or 30))]


def clear_finished_clip_tasks(job_id=None):
    removable = {"done", "error", "cancelled"}
    removed = 0
    with CLIP_TASK_LOCK:
        for task_id, task in list(CLIP_TASKS.items()):
            if job_id and task.get("job_id") != job_id:
                continue
            if task.get("status") in removable:
                CLIP_TASKS.pop(task_id, None)
                removed += 1
    if removed:
        persist_clip_tasks()
    return removed


def retry_clip_task(task_id):
    with CLIP_TASK_LOCK:
        old = serialize_clip_task(CLIP_TASKS.get(task_id))
    if not old:
        raise RuntimeError("Task record not found")
    if old.get("status") in {"queued", "running"}:
        raise RuntimeError("Task is still running and cannot be retried")
    task_type = old.get("type")
    job_id = old.get("job_id")
    if task_type == "preview":
        clip_id = old.get("clip_id")
        new_task_id, task = create_clip_task(job_id, clip_id, "preview")
        set_clip_task(new_task_id, retry_of=task_id, message="Retry preview task queued")
        threading.Thread(target=clip_render_worker, args=(new_task_id, job_id, clip_id), daemon=True).start()
        return get_clip_task(new_task_id)
    if task_type == "export":
        clip_ids = old.get("clip_ids") or []
        export_dir = old.get("export_dir") or ""
        new_task_id, _task = create_clip_task(job_id, "export", "export")
        task = set_clip_task(new_task_id, retry_of=task_id, clip_ids=clip_ids, export_dir=export_dir, message="Retry export task queued")
        threading.Thread(target=clip_export_worker, args=(new_task_id, job_id, clip_ids, export_dir), daemon=True).start()
        return task
    if task_type == "transcribe":
        new_task_id, _task = create_clip_task(job_id, "transcribe", "transcribe")
        task = set_clip_task(
            new_task_id,
            retry_of=task_id,
            transcribe_engine="volcengine_bigmodel",
            transcribe_mode="volcengine_bigmodel",
            transcribe_model="volcengine_bigmodel",
            encoder="\u706b\u5c71 BigModel ASR",
            message="火山转写任务已加入队列（重试）",
        )
        set_job(
            job_id,
            stage="queued",
            message="火山转写任务已加入队列（重试）",
            pause_requested=False,
            stop_requested=False,
            progress=0,
            transcribe_task_id=new_task_id,
            transcribe_engine="volcengine_bigmodel",
            transcribe_mode="volcengine_bigmodel",
            transcribe_model="volcengine_bigmodel",
        )
        threading.Thread(target=transcribe_worker, args=(job_id, new_task_id), daemon=True).start()
        return task
    if task_type == "analyze":
        params = old.get("params") or {}
        payload = dict(params)
        provider = enabled_provider("llm")
        if not provider or not provider.get("api_key"):
            raise RuntimeError("请先在供应商管理中添加并启用一个 LLM 配置。")
        payload["provider_id"] = provider.get("id")
        new_task_id, _task = create_clip_task(job_id, "analyze", "analyze")
        task = set_clip_task(new_task_id, retry_of=task_id, params=params, encoder="DeepSeek", message="\u91cd\u8bd5\u5206\u6790\u4efb\u52a1\u5df2\u52a0\u5165\u961f\u5217")
        threading.Thread(target=analyze_worker, args=(new_task_id, job_id, payload), daemon=True).start()
        return task
    raise RuntimeError("This task type does not support retry")

def set_clip_task(task_id, **updates):
    with CLIP_TASK_LOCK:
        task = CLIP_TASKS.get(task_id)
        if not task:
            return None
        task.update(updates)
        if "progress" in updates:
            progress = max(0.0, min(1.0, float(task.get("progress") or 0)))
            task["progress"] = progress
            task["percent"] = int(round(progress * 100))
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        result = serialize_clip_task(task)
    force_persist = updates.get("status") not in {None, "queued", "running"} or "progress" not in updates
    persist_clip_tasks_throttled(force=force_persist)
    return result


def cancel_clip_task(task_id):
    with CLIP_TASK_LOCK:
        task = CLIP_TASKS.get(task_id)
        if not task:
            return None
        task["cancel_requested"] = True
        proc = task.get("process")
    if proc and proc.poll() is None:
        proc.terminate()
    return set_clip_task(task_id, message="\u6b63\u5728\u53d6\u6d88\u4efb\u52a1")


def clip_task_cancelled(task_id):
    with CLIP_TASK_LOCK:
        task = CLIP_TASKS.get(task_id)
        return bool(task and task.get("cancel_requested"))


def clip_task_paused(task_id):
    with CLIP_TASK_LOCK:
        task = CLIP_TASKS.get(task_id)
        return bool(task and task.get("pause_requested"))


def wait_for_clip_task_resume(task_id):
    """Pause only between request stages; an in-flight API request cannot be paused."""
    while clip_task_paused(task_id):
        if clip_task_cancelled(task_id):
            raise RuntimeError("Analysis task cancelled")
        set_clip_task(task_id, status="paused", message="DeepSeek analysis paused")
        time.sleep(0.25)
    if clip_task_cancelled(task_id):
        raise RuntimeError("Analysis task cancelled")


def clip_task_set_process(task_id, proc):
    with CLIP_TASK_LOCK:
        task = CLIP_TASKS.get(task_id)
        if task is not None:
            task["process"] = proc


def clip_render_worker(task_id, job_id, clip_id):
    try:
        encoder = detect_h264_encoder()
        set_clip_task(task_id, status="running", progress=0.02, message=f"\u6b63\u5728\u751f\u6210\u517c\u5bb9\u9884\u89c8\uff08{encoder['label']}\uff09", encoder=encoder.get("label"))
        clip = render_clip(
            job_id,
            clip_id,
            export=False,
            progress_callback=lambda progress, elapsed, remaining: set_clip_task(
                task_id,
                status="running",
                progress=progress,
                elapsed=elapsed,
                remaining=remaining,
                message="\u6b63\u5728\u751f\u6210\u517c\u5bb9\u9884\u89c8",
            ),
            fallback_callback=lambda: set_clip_task(task_id, message="\u786c\u4ef6\u7f16\u7801\u5931\u8d25\uff0c\u6b63\u5728\u81ea\u52a8\u5207\u6362 CPU \u7f16\u7801", encoder="CPU x264 \u7f16\u7801"),
            process_callback=lambda proc: clip_task_set_process(task_id, proc),
            cancel_check=lambda: clip_task_cancelled(task_id),
        )
        set_clip_task(task_id, status="done", progress=1, remaining=0, message="\u9884\u89c8\u751f\u6210\u5b8c\u6210", clip=clip)
    except Exception as exc:
        status = "cancelled" if "\u53d6\u6d88" in str(exc) else "error"
        set_clip_task(task_id, status=status, progress=1 if status == "cancelled" else 0, message=str(exc), error=str(exc), remaining=0)


def clip_export_worker(task_id, job_id, clip_ids, export_dir=None):
    exported = []
    errors = []
    total = len(clip_ids)
    started = time.time()
    try:
        if total == 0:
            set_clip_task(task_id, status="done", progress=1, remaining=0, message="\u6ca1\u6709\u9700\u8981\u5bfc\u51fa\u7684\u7247\u6bb5", exported=[], errors=[])
            return
        for index, clip_id in enumerate(clip_ids, start=1):
            if clip_task_cancelled(task_id):
                raise RuntimeError("\u5df2\u53d6\u6d88\u751f\u6210\u4efb\u52a1")
            base_progress = (index - 1) / total
            set_clip_task(task_id, status="running", progress=base_progress, message=f"\u6b63\u5728\u5bfc\u51fa\u7b2c {index}/{total} \u6761\u539f\u753b\u8d28\u7247\u6bb5", exported=exported, errors=errors)
            try:
                clip = render_clip(
                    job_id,
                    clip_id,
                    export=True,
                    precise=True,
                    export_dir=export_dir or None,
                    progress_callback=lambda progress, elapsed, remaining, index=index: set_clip_task(
                        task_id,
                        status="running",
                        progress=((index - 1) + progress) / total,
                        elapsed=max(0, time.time() - started),
                        remaining=None,
                        message=f"\u6b63\u5728\u5bfc\u51fa\u7b2c {index}/{total} \u6761\u539f\u753b\u8d28\u7247\u6bb5",
                        exported=exported,
                        errors=errors,
                    ),
                    process_callback=lambda proc: clip_task_set_process(task_id, proc),
                    cancel_check=lambda: clip_task_cancelled(task_id),
                )
                exported.append(clip)
            except Exception as exc:
                errors.append({"clip_id": clip_id, "error": str(exc)})
        set_clip_task(task_id, status="done", progress=1, remaining=0, message=f"\u5bfc\u51fa\u5b8c\u6210\uff1a\u6210\u529f {len(exported)} \u6761\uff0c\u5931\u8d25 {len(errors)} \u6761", exported=exported, errors=errors, export_dir=export_dir or "")
    except Exception as exc:
        status = "cancelled" if "\u53d6\u6d88" in str(exc) else "error"
        set_clip_task(task_id, status=status, progress=1 if status == "cancelled" else 0, message=str(exc), error=str(exc), exported=exported, errors=errors, export_dir=export_dir or "")


def group_transcript_segments(segments, max_gap=1.2, max_duration=45.0, max_chars=260):
    groups = []
    current = None
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        if current is None:
            current = {
                "id": len(groups) + 1,
                "start": seg["start"],
                "end": seg["end"],
                "text": text,
                "segment_ids": [seg["id"]],
            }
            continue
        gap = float(seg["start"]) - float(current["end"])
        duration = float(seg["end"]) - float(current["start"])
        merged_text = current["text"] + " " + text
        should_split = gap > max_gap or duration > max_duration or len(merged_text) > max_chars
        if should_split:
            groups.append(current)
            current = {
                "id": len(groups) + 1,
                "start": seg["start"],
                "end": seg["end"],
                "text": text,
                "segment_ids": [seg["id"]],
            }
        else:
            current["end"] = seg["end"]
            current["text"] = merged_text
            current["segment_ids"].append(seg["id"])
    if current:
        groups.append(current)
    return groups


def save_transcript_files(base_dir, segments):
    transcript_json = {"language": "zh", "segments": segments}
    write_json(base_dir / "transcript.json", transcript_json)
    groups = group_transcript_segments(segments)
    write_json(base_dir / "transcript_grouped.json", {"language": "zh", "groups": groups})
    write_grouped_transcript_output(base_dir.name)


def provider_id():
    return uuid4().hex


PROVIDER_COLLECTIONS = {
    "llm": "llm_providers",
    "volcengine": "volcengine_providers",
    "pexels": "pexels_providers",
    "pixabay": "pixabay_providers",
}


def provider_collection_key(kind):
    try:
        return PROVIDER_COLLECTIONS[str(kind or "").strip().lower()]
    except KeyError as exc:
        raise RuntimeError("未知供应商类型") from exc


def mask_secret(value):
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 10:
        return value[:3] + "..."
    return f"{value[:6]}...{value[-4:]}"


def provider_settings():
    """Load only the provider-manager configuration schema.

    Legacy single-key settings are deliberately removed instead of migrated.
    This prevents the packaged app's old and new forms from disagreeing about
    which credential is active.
    """
    saved = read_json(SETTINGS_PATH, {})
    changed = False
    legacy_keys = {
        "deepseek_api_key",
        "volcengine_api_key", "volcengine_resource_id", "volcengine_appid",
        "volcengine_token", "volcengine_cluster", "volcengine_audio_url",
        "volcengine_poll_interval",
        "tos_access_key", "tos_secret_key", "tos_endpoint", "tos_region",
        "tos_bucket", "tos_prefix", "tos_url_expires",
    }
    for key in legacy_keys:
        if key in saved:
            saved.pop(key, None)
            changed = True
    llms = saved.get("llm_providers")
    volcengines = saved.get("volcengine_providers")
    pexels = saved.get("pexels_providers")
    pixabay = saved.get("pixabay_providers")
    if not isinstance(llms, list):
        llms = []
        saved["llm_providers"] = llms
        changed = True
    for item in llms:
        if not isinstance(item, dict):
            continue
        normalized_url = normalize_llm_base_url(item.get("base_url"))
        if normalized_url and normalized_url != item.get("base_url"):
            item["base_url"] = normalized_url
            changed = True
    if not isinstance(volcengines, list):
        volcengines = []
        saved["volcengine_providers"] = volcengines
        changed = True
    for key in ("pexels_providers", "pixabay_providers"):
        if not isinstance(saved.get(key), list):
            saved[key] = []
            changed = True
    if changed:
        write_json(SETTINGS_PATH, saved)
    return saved


def enabled_provider(kind, preferred_id=None):
    saved = provider_settings()
    key = provider_collection_key(kind)
    providers = saved.get(key, [])
    if preferred_id:
        provider = next((item for item in providers if item.get("id") == preferred_id), None)
        if provider and provider.get("enabled"):
            return provider
    return next((item for item in providers if item.get("enabled")), None)


def public_provider(provider, kind):
    item = dict(provider)
    item.pop("api_key", None)
    item["has_api_key"] = bool(provider.get("api_key"))
    item["masked_api_key"] = mask_secret(provider.get("api_key"))
    if kind == "volcengine":
        item.pop("tos_access_key", None)
        item.pop("tos_secret_key", None)
        item["has_tos_access_key"] = bool(provider.get("tos_access_key"))
        item["has_tos_secret"] = bool(provider.get("tos_secret_key"))
    if kind in {"pexels", "pixabay"}:
        item["platform"] = kind
        item["result_limit"] = int(provider.get("result_limit") or 12)
    return item


def normalize_llm_base_url(value):
    """Normalize an OpenAI-compatible base URL without duplicating endpoint paths."""
    base_url = str(value or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/models"):
        if base_url.lower().endswith(suffix):
            base_url = base_url[: -len(suffix)].rstrip("/")
    return base_url


def llm_endpoint(base_url, suffix):
    normalized = normalize_llm_base_url(base_url)
    return f"{normalized}/{suffix.lstrip('/')}"


def is_deepseek_provider(provider, base_url=None):
    """Identify DeepSeek direct or OpenAI-compatible gateway configurations."""
    provider = provider or {}
    model = str(provider.get("model") or "").strip().lower()
    if model.startswith("deepseek"):
        return True
    parsed = urllib.parse.urlparse(str(base_url or provider.get("base_url") or ""))
    host = (parsed.hostname or "").strip().lower()
    return host == "api.deepseek.com" or host.endswith(".deepseek.com")


def llm_provider_from_payload(payload):
    provider_id_value = str(payload.get("provider_id") or payload.get("id") or "").strip()
    if provider_id_value:
        saved = provider_settings()
        provider = next((item for item in saved.get("llm_providers", []) if item.get("id") == provider_id_value), None)
        if provider:
            merged = dict(provider)
            if payload.get("api_key"):
                merged["api_key"] = str(payload.get("api_key")).strip()
            if payload.get("base_url"):
                merged["base_url"] = payload.get("base_url")
            if payload.get("protocol"):
                merged["protocol"] = payload.get("protocol")
            return merged
    return {
        "name": str(payload.get("name") or "LLM").strip()[:80],
        "api_key": str(payload.get("api_key") or "").strip(),
        "base_url": normalize_llm_base_url(payload.get("base_url")),
        "protocol": str(payload.get("protocol") or "openai").strip().lower(),
        "model": str(payload.get("model") or "").strip(),
    }


def fetch_llm_models(payload):
    """Read the provider's model catalog using its OpenAI-compatible GET /models endpoint."""
    provider = llm_provider_from_payload(payload)
    key = str(provider.get("api_key") or "").strip()
    base_url = normalize_llm_base_url(provider.get("base_url"))
    protocol = str(provider.get("protocol") or "openai").strip().lower()
    if protocol != "openai":
        raise RuntimeError("当前仅支持通过 OpenAI 兼容协议获取模型列表。")
    if not key or not base_url:
        raise RuntimeError("请先填写接口 URL 和 API Key，再获取模型列表。")
    request = urllib.request.Request(
        llm_endpoint(base_url, "models"),
        headers={"Accept": "application/json", "Authorization": f"Bearer {key}"},
        method="GET",
    )
    provider_name = provider.get("name") or "LLM"
    try:
        with open_public_request(request, timeout=35) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise RuntimeError(f"{provider_name} 模型列表请求失败：HTTP {exc.code} {detail}") from exc
    except ExternalNetworkError as exc:
        raise RuntimeError(f"{provider_name} 模型列表网络失败：{exc}") from exc
    except (ValueError, urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"{provider_name} 模型列表请求失败：{exc}") from exc
    items = result.get("data") if isinstance(result, dict) else []
    if not isinstance(items, list):
        items = result.get("models") if isinstance(result, dict) else []
    models = []
    for item in items if isinstance(items, list) else []:
        model_id = item.get("id") if isinstance(item, dict) else item
        if model_id:
            models.append(str(model_id).strip())
    models = sorted(set(model for model in models if model), key=str.casefold)
    if not models:
        raise RuntimeError(f"{provider_name} 返回的模型列表为空。")
    return {"models": models, "provider_name": provider_name, "endpoint": llm_endpoint(base_url, "models")}


def llm_content_text(value):
    """Normalize OpenAI/Anthropic text blocks and provider-specific JSON fields."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text")
                if text is None:
                    text = item.get("content")
                if text is None:
                    text = item.get("output_text")
                if text is not None:
                    normalized = llm_content_text(text)
                    if normalized:
                        parts.append(normalized)
            elif isinstance(item, str):
                parts.append(item.strip())
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "output_text", "response"):
            if value.get(key) not in (None, "", [], {}):
                normalized = llm_content_text(value[key])
                if normalized:
                    return normalized
    return ""


def parse_llm_json_payload(content):
    """Parse JSON even when the model adds prose or Markdown fences around it."""
    if isinstance(content, dict):
        return content
    text = llm_content_text(content).lstrip("\ufeff").strip()
    if not text:
        raise RuntimeError("模型返回内容为空")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        parsed = None
        for index, char in enumerate(text):
            if char not in "[{":
                continue
            try:
                candidate, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                parsed = candidate
                break
        if parsed is None:
            raise RuntimeError("模型返回内容中没有可解析的 JSON 对象")
    if not isinstance(parsed, dict):
        raise RuntimeError("模型返回的 JSON 必须是对象")
    return parsed


def llm_json(prompt, provider_id=None, timeout=180, max_tokens=4096):
    """Call the currently enabled LLM and return a JSON object only."""
    provider = enabled_provider("llm", provider_id)
    if not provider or not provider.get("api_key"):
        raise RuntimeError("请先在供应商管理中添加并启用一个 LLM 配置。")
    key = provider["api_key"].strip()
    provider_name = provider.get("name") or "LLM"
    model = (provider.get("model") or "").strip()
    base_url = normalize_llm_base_url(provider.get("base_url"))
    protocol = (provider.get("protocol") or "openai").strip().lower()
    if not model or not base_url:
        raise RuntimeError(f"LLM 配置“{provider_name}”缺少模型或接口 URL。")
    system_prompt = "Return valid JSON only. Do not use Markdown. Do not invent sources, links, people, or quotations."
    if protocol == "anthropic":
        endpoint = base_url if base_url.endswith("/v1/messages") else base_url + "/v1/messages"
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        endpoint = llm_endpoint(base_url, "chat/completions")
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        if is_deepseek_provider(provider, base_url):
            body["response_format"] = {"type": "json_object"}
            body["thinking"] = {"type": "disabled"}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    retry_parse = protocol == "openai" and is_deepseek_provider(provider, base_url)
    parse_error = None
    attempts = 2 if retry_parse else 1
    for attempt in range(attempts):
        request_body = dict(body)
        if attempt and protocol == "openai":
            request_body["messages"] = [
                {"role": "system", "content": system_prompt + " Return one complete JSON object in the final answer; do not return an empty answer."},
                {"role": "user", "content": prompt},
            ]
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with open_public_request(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{provider_name} 请求失败: {exc.code} {detail}") from exc
        except ExternalNetworkError as exc:
            raise RuntimeError(f"{provider_name} 网络连接失败：{exc}") from exc
        except RuntimeError:
            raise
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"{provider_name} 网络连接失败：{reason}") from exc
        if protocol == "anthropic":
            content = result.get("content")
        else:
            choices = result.get("choices") if isinstance(result, dict) else None
            message = choices[0].get("message", {}) if isinstance(choices, list) and choices else {}
            content = message.get("content") if isinstance(message, dict) else ""
            if not content and isinstance(choices, list) and choices:
                content = choices[0].get("text")
            if not content and isinstance(result, dict):
                content = result.get("output_text") or result.get("content") or result.get("response")
        try:
            return parse_llm_json_payload(content)
        except RuntimeError as exc:
            # Some compatible gateways return the JSON object directly instead of a
            # chat-completion envelope. Accept that shape when it is unambiguous.
            if isinstance(result, dict) and any(key in result for key in ("ok", "topics", "queries", "title")):
                return result
            parse_error = exc
            if attempt + 1 < attempts:
                continue
    raise RuntimeError(f"{provider_name} 未返回可解析的内容：{parse_error}") from parse_error


def test_llm_provider(provider_id=None):
    """Verify an enabled LLM with a fixed, non-user-content payload."""
    started = time.monotonic()
    result = llm_json(
        "Return a JSON object with exactly one boolean field named ok set to true.",
        provider_id=provider_id,
        timeout=35,
        max_tokens=32,
    )
    if result.get("ok") is not True:
        raise RuntimeError("LLM 连通性测试未返回预期的 JSON 结果。")
    provider = enabled_provider("llm", provider_id) or {}
    return {
        "provider_id": provider.get("id") or "",
        "provider_name": provider.get("name") or "LLM",
        "model": provider.get("model") or "",
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


def test_material_provider(provider_id_value=None, kind=None):
    """Verify a Pexels or Pixabay key with a minimal search request."""
    kind = str(kind or "").strip().lower()
    if kind not in {"pexels", "pixabay"}:
        raise RuntimeError("素材平台连通性测试仅支持 Pexels 或 Pixabay。")
    provider = enabled_provider(kind, provider_id_value)
    if not provider or not provider.get("api_key"):
        raise RuntimeError(f"请先在供应商管理中添加并启用 {kind} 配置。")
    key = str(provider.get("api_key") or "").strip()
    started = time.monotonic()
    request = material_search_request(kind, "nature", {**provider, "result_limit": 1})
    try:
        with open_public_request(request, timeout=25) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"{provider.get('name') or kind} 测试失败：HTTP {exc.code} {detail}") from exc
    except ExternalNetworkError as exc:
        raise RuntimeError(f"{provider.get('name') or kind} 网络连接失败：{exc}") from exc
    except (ValueError, urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"{provider.get('name') or kind} 测试失败：{exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"{provider.get('name') or kind} 返回了无法识别的数据。")
    return {
        "provider_id": provider.get("id") or "",
        "provider_name": provider.get("name") or kind,
        "platform": kind,
        "result_count": len(result.get("videos") or result.get("hits") or []),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


def material_search_url(kind, query, limit):
    if kind == "pexels":
        limit = max(1, min(30, int(limit or 12)))
        return "https://api.pexels.com/videos/search?" + urllib.parse.urlencode({"query": query, "per_page": limit})
    if kind == "pixabay":
        # Pixabay's video API rejects per_page values below 3.
        limit = max(3, min(200, int(limit or 12)))
        return "https://pixabay.com/api/videos/?" + urllib.parse.urlencode({"q": query, "per_page": limit})
    raise RuntimeError("不支持的素材平台")


def material_search_request(kind, query, provider):
    key = str(provider.get("api_key") or "").strip()
    if not key:
        raise RuntimeError(f"{provider.get('name') or kind} 缺少 API Key。")
    url = material_search_url(kind, query, provider.get("result_limit") or 12)
    headers = {
        "Accept": "application/json",
        # Pexels' Cloudflare edge rejects Python's default urllib signature.
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
    }
    if kind == "pexels":
        headers["Authorization"] = key
        return urllib.request.Request(url, headers=headers, method="GET")
    separator = "&" if "?" in url else "?"
    return urllib.request.Request(f"{url}{separator}{urllib.parse.urlencode({'key': key})}", headers=headers, method="GET")


def normalize_material_candidates(kind, payload, query):
    candidates = []
    if kind == "pexels":
        for video in payload.get("videos", []) if isinstance(payload, dict) else []:
            files = [item for item in video.get("video_files", []) if item.get("link")]
            files.sort(key=lambda item: (int(item.get("width") or 0), int(item.get("height") or 0)), reverse=True)
            candidates.append({
                "id": f"pexels-{video.get('id')}",
                "source": "pexels",
                "title": f"Pexels video {video.get('id')}",
                "description": str(video.get("url") or ""),
                "url": str(video.get("url") or ""),
                "preview_url": str(video.get("image") or ""),
                "download_url": str(files[0].get("link") or "") if files else "",
                "duration": int(video.get("duration") or 0),
                "width": int(video.get("width") or 0),
                "height": int(video.get("height") or 0),
                "matched_query": query,
            })
    elif kind == "pixabay":
        for video in payload.get("hits", []) if isinstance(payload, dict) else []:
            files = video.get("videos") or {}
            source = files.get("large") or files.get("medium") or files.get("small") or {}
            candidates.append({
                "id": f"pixabay-{video.get('id')}",
                "source": "pixabay",
                "title": str(video.get("tags") or "Pixabay video"),
                "description": str(video.get("tags") or ""),
                "url": str(video.get("pageURL") or ""),
                "preview_url": str(video.get("picture_id") or ""),
                "download_url": str(source.get("url") or ""),
                "duration": int(video.get("duration") or 0),
                "width": int(source.get("width") or 0),
                "height": int(source.get("height") or 0),
                "matched_query": query,
            })
    return candidates


def search_material_provider(kind, query, provider):
    request = material_search_request(kind, query, provider)
    try:
        with open_public_request(request, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"{provider.get('name') or kind} 搜索失败：HTTP {exc.code} {detail}") from exc
    except ExternalNetworkError as exc:
        raise RuntimeError(f"{provider.get('name') or kind} 网络连接失败：{exc}") from exc
    except (ValueError, urllib.error.URLError, OSError) as exc:
        raise RuntimeError(f"{provider.get('name') or kind} 搜索失败：{exc}") from exc
    return normalize_material_candidates(kind, payload, query)


def normalize_broll_input(value, max_chars=12000):
    """Normalize free-form script or shot notes without requiring one shot per line."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    return "\n".join(lines)[:max_chars].strip()


def broll_search_queries(requirements):
    input_text = normalize_broll_input("\n".join(str(item) for item in requirements) if isinstance(requirements, (list, tuple)) else requirements)
    shot_inputs = [line.strip() for line in input_text.split("\n") if line.strip()]
    if not shot_inputs:
        raise RuntimeError("请至少输入一条 B-roll 分镜头需求。")
    if len(shot_inputs) > 20:
        raise RuntimeError("B-roll 分镜头需求最多支持 20 条。")
    numbered_shots = "\n".join(f"{index}. {shot}" for index, shot in enumerate(shot_inputs, start=1))
    prompt = f"""你是短视频 B-roll 素材检索编辑。用户会用换行或空行分隔已经划分好的分镜头需求，输入也可能带编号。
用户已经完成分镜头划分。不得拆分、合并或改写用户已经提供的分镜头边界；只为每个既有分镜头生成适合 Pexels 和 Pixabay 视频搜索的英文检索词。
输入共 {len(shot_inputs)} 个分镜头，必须按原顺序输出恰好 {len(shot_inputs)} 个 items。每个 item 一一对应输入中的同序号分镜头，requirement 字段原样回填对应的用户分镜头文本。
每个分镜头给 2 到 3 条具体、可拍摄的英文短语，使用主体 + 动作 + 场景，不要抽象概念或品牌名。
仅返回 JSON：{{\"items\":[{{\"requirement\":\"中文镜头需求\",\"queries\":[\"english query\"]}}]}}。
用户分镜头（编号仅用于对应，不属于需求内容）：
{numbered_shots}"""
    result = llm_json(prompt, max_tokens=2200)
    items = result.get("items") if isinstance(result, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("LLM 未返回可用的 B-roll 检索词。")
    if len(items) != len(shot_inputs):
        raise RuntimeError(
            f"LLM 返回的分镜头数量（{len(items)}）与输入数量（{len(shot_inputs)}）不一致，请重试。"
        )
    plans = []
    for shot_input, item in zip(shot_inputs, items):
        if not isinstance(item, dict):
            raise RuntimeError("LLM 返回了无效的 B-roll 分镜头条目，请重试。")
        requirement = shot_input
        queries = [str(query).strip() for query in item.get("queries", []) if str(query).strip()]
        if requirement and queries:
            plans.append({"requirement": requirement[:240], "queries": queries[:3]})
        else:
            raise RuntimeError("LLM 未为每个 B-roll 分镜头返回可用的检索词，请重试。")
    return plans


def broll_rank_candidates(requirement, candidates):
    if not candidates:
        return []
    compact = [{
        "id": item["id"], "title": item["title"], "description": item["description"],
        "source": item["source"], "duration": item["duration"], "width": item["width"],
        "height": item["height"], "query": item["matched_query"],
    } for item in candidates[:16]]
    prompt = f"""你是视频素材导演。根据 B-roll 需求，对候选视频元数据按画面主体、动作和场景的贴合度排序。
不要依据热度；不能从元数据证明相关的素材应排后。优先横屏，输出每条一句简短中文理由。
仅返回 JSON：{{\"ranked\":[{{\"id\":\"候选 id\",\"reason\":\"理由\"}}]}}。
B-roll 需求：{requirement}
候选：{json.dumps(compact, ensure_ascii=False)}"""
    try:
        result = llm_json(prompt, max_tokens=1600)
        ranked = result.get("ranked") if isinstance(result, dict) else []
    except RuntimeError:
        ranked = []
    by_id = {item["id"]: item for item in candidates}
    selected = []
    for item in ranked if isinstance(ranked, list) else []:
        candidate = by_id.pop(str(item.get("id") or ""), None)
        if candidate:
            candidate["reason"] = str(item.get("reason") or "元数据与镜头需求匹配。")[:180]
            selected.append(candidate)
    for candidate in by_id.values():
        candidate["reason"] = candidate.get("reason") or "按素材平台文本匹配结果返回。"
        selected.append(candidate)
    return selected[:8]


def search_broll_requirements(requirements, progress_callback=None):
    input_text = normalize_broll_input(requirements)
    if not input_text:
        raise RuntimeError("请至少输入一条 B-roll 需求。")
    def report(progress, message):
        if progress_callback:
            progress_callback(max(0.0, min(1.0, float(progress))), message)

    report(0.03, "正在准备 B-roll 检索")
    providers = {kind: enabled_provider(kind) for kind in ("pexels", "pixabay")}
    missing = [kind for kind, provider in providers.items() if not provider or not provider.get("api_key")]
    if missing:
        raise RuntimeError("请先在供应商管理中启用：" + "、".join(kind.title() for kind in missing))
    report(0.12, "LLM 正在生成检索词")
    query_plans = broll_search_queries(input_text)
    report(0.22, f"已生成 {len(query_plans)} 条分镜的检索词")
    results = []
    total_operations = max(1, len(query_plans) * len(providers))
    completed_operations = 0
    for plan_index, plan in enumerate(query_plans, start=1):
        groups = []
        for kind, provider in providers.items():
            operation_start = 0.22 + (completed_operations / total_operations) * 0.68
            report(operation_start, f"正在搜索 {kind.title()} · 分镜 {plan_index}/{len(query_plans)}")
            seen = set()
            candidates = []
            for query in plan["queries"]:
                for candidate in search_material_provider(kind, query, provider):
                    if candidate["id"] not in seen:
                        candidates.append(candidate)
                        seen.add(candidate["id"])
                if len(candidates) >= 16:
                    break
            report(
                operation_start + (0.28 / total_operations) * 0.68,
                f"LLM 正在进行 {kind.title()} 元数据重排 · 分镜 {plan_index}/{len(query_plans)}",
            )
            groups.append({"provider": kind, "items": broll_rank_candidates(plan["requirement"], candidates)})
            completed_operations += 1
            report(
                0.22 + (completed_operations / total_operations) * 0.68,
                f"已完成 {kind.title()} 搜索与重排 · 分镜 {plan_index}/{len(query_plans)}",
            )
        results.append({"requirement": plan["requirement"], "queries": plan["queries"], "providers": groups})
    report(0.96, "正在整理 B-roll 检索结果")
    report(1, "B-roll 检索结果已整理完成")
    return results


def broll_search_worker(task_id, requirements):
    try:
        set_broll_task(
            task_id,
            status="running",
            stage="preparing",
            progress=0.01,
            progress_label="B-roll 检索进度",
            message="正在启动 B-roll 检索",
            started_at=datetime.now().isoformat(timespec="seconds"),
        )

        def update_progress(progress, message):
            lowered = str(message or "")
            if "生成检索词" in lowered:
                stage = "querying"
            elif "元数据重排" in lowered:
                stage = "ranking"
            elif "搜索" in lowered:
                stage = "searching"
            elif "整理" in lowered:
                stage = "finalizing"
            else:
                stage = "preparing"
            set_broll_task(
                task_id,
                status="running",
                stage=stage,
                progress=progress,
                progress_label="B-roll 检索进度",
                message=message,
            )

        results = search_broll_requirements(requirements, progress_callback=update_progress)
        set_broll_task(
            task_id,
            status="done",
            stage="done",
            progress=1,
            progress_label="B-roll 检索进度",
            message=f"B-roll 检索完成：已处理 {len(results)} 条分镜需求",
            results=results,
            requirement_count=len(results),
        )
    except Exception as exc:
        current = get_broll_task(task_id)
        set_broll_task(
            task_id,
            status="error",
            stage="error",
            progress=current.get("progress", 0),
            progress_label="B-roll 检索进度",
            message=str(exc),
            error=str(exc),
        )
    finally:
        global ACTIVE_BROLL_SEARCH_TASK_ID
        with BROLL_SEARCH_LOCK:
            if ACTIVE_BROLL_SEARCH_TASK_ID == task_id:
                ACTIVE_BROLL_SEARCH_TASK_ID = None


def start_broll_search(payload):
    global ACTIVE_BROLL_SEARCH_TASK_ID
    payload = payload or {}
    requirements = normalize_broll_input(payload.get("requirements"))
    if not requirements:
        raise RuntimeError("请至少输入一条 B-roll 需求。")
    with BROLL_SEARCH_LOCK:
        active_task = get_broll_task(ACTIVE_BROLL_SEARCH_TASK_ID) if ACTIVE_BROLL_SEARCH_TASK_ID else {}
        if active_task.get("status") in {"queued", "running"}:
            return active_task
        task_id = f"broll-search-{uuid4().hex[:12]}"
        task = set_broll_task(
            task_id,
            kind="broll_search",
            status="queued",
            stage="queued",
            progress=0,
            progress_label="B-roll 检索进度",
            requirements=requirements,
            message="已加入 B-roll 检索队列",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        ACTIVE_BROLL_SEARCH_TASK_ID = task_id
    threading.Thread(target=broll_search_worker, args=(task_id, requirements), daemon=True).start()
    return task


def volcengine_settings(payload=None):
    payload = payload or {}
    provider = enabled_provider("volcengine", payload.get("provider_id")) or {}
    return {
        "api_key": str(provider.get("api_key") or "").strip(),
        "resource_id": str(provider.get("resource_id") or "volc.seedasr.auc").strip(),
        "audio_url": str(provider.get("audio_url") or "").strip(),
        "poll_interval": max(2, min(30, float(provider.get("poll_interval") or 5))),
    }


def tos_settings(payload=None):
    payload = payload or {}
    provider = enabled_provider("volcengine", payload.get("provider_id")) or {}
    return {
        "access_key": str(provider.get("tos_access_key") or "").strip(),
        "secret_key": str(provider.get("tos_secret_key") or "").strip(),
        "endpoint": str(provider.get("tos_endpoint") or "").strip(),
        "region": str(provider.get("tos_region") or "").strip(),
        "bucket": str(provider.get("tos_bucket") or "").strip(),
        "prefix": str(provider.get("tos_prefix") or "mp4-golden-asr").strip().strip("/"),
        "url_expires": max(60, min(7 * 24 * 3600, int(float(provider.get("tos_url_expires") or 86400)))),
    }


def clean_tos_key_part(value):
    value = str(value or "").strip().replace("\\", "/")
    value = re.sub(r"[^0-9A-Za-z一-鿿._/-]+", "-", value, flags=re.UNICODE).strip("/.-")
    return value or "audio"


def tos_upload_audio(audio_path, job_id, settings):
    missing = [name for name in ("access_key", "secret_key", "endpoint", "region", "bucket") if not settings.get(name)]
    if missing:
        raise RuntimeError("未填写音频公网 URL，且 TOS 配置不完整：请填写 AK、SK、Endpoint、Region、Bucket。")
    try:
        import tos
    except Exception as exc:
        raise RuntimeError(f"未安装火山 TOS Python SDK。请在复刻版目录运行 pip install tos，或 install-deps.bat。详情：{exc}")
    prefix = settings.get("prefix") or "mp4-golden-asr"
    object_key = "/".join(part for part in [clean_tos_key_part(prefix), clean_tos_key_part(job_id), f"audio-{uuid4().hex[:8]}.wav"] if part)
    ak = settings["access_key"]
    sk = settings["secret_key"]
    endpoint = settings["endpoint"].replace("https://", "").replace("http://", "").strip("/")
    region = settings["region"]
    bucket = settings["bucket"]
    try:
        client_v2 = tos.TosClientV2(ak, sk, endpoint, region)
        try:
            client_v2.put_object_from_file(bucket, object_key, str(audio_path))
        except TypeError:
            client_v2.put_object_from_file(bucket=bucket, key=object_key, file_path=str(audio_path))
    except Exception as exc:
        raise RuntimeError(f"上传 audio.wav 到 TOS 失败：{exc}")
    expires = max(60, min(7 * 24 * 3600, int(settings.get("url_expires") or 86400)))
    try:
        client = tos.TosClient(tos.Auth(ak, sk, region), endpoint)
        url = client.generate_presigned_url(Method="GET", Bucket=bucket, Key=object_key, ExpiresIn=expires)
    except Exception:
        try:
            url = client_v2.pre_signed_url("GET", bucket, object_key, expires)
            if hasattr(url, "signed_url"):
                url = url.signed_url
        except Exception as exc:
            raise RuntimeError(f"TOS 上传成功，但生成临时下载 URL 失败：{exc}")
    return {"audio_url": str(url), "object_key": object_key, "expires": expires, "bucket": bucket}


def volcengine_bigmodel_request(url, body, api_key, resource_id, request_id, timeout=30, cancel_check=None):
    data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": resource_id or "volc.seedasr.auc",
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        },
        method="POST",
    )
    def perform_request():
        try:
            with http_opener().open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                headers = {k.lower(): v for k, v in resp.headers.items()}
                return {"body": json.loads(raw or "{}"), "headers": headers, "http_status": resp.status}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            headers = {k.lower(): v for k, v in exc.headers.items()}
            message = headers.get("x-api-message") or detail or exc.reason
            raise RuntimeError(f"\u706b\u5c71 BigModel \u8bf7\u6c42\u5931\u8d25 HTTP {exc.code}: {message}")

    if not cancel_check:
        return perform_request()
    result, errors = [], []

    def request_worker():
        try:
            result.append(perform_request())
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=request_worker, daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(0.2)
        if cancel_check():
            raise RuntimeError("\u8f6c\u5199\u5df2\u7ed3\u675f")
    if errors:
        raise errors[0]
    return result[0]


def volcengine_status(result):
    headers = result.get("headers", {}) if isinstance(result, dict) else {}
    body = result.get("body", {}) if isinstance(result, dict) else {}
    code = str(headers.get("x-api-status-code") or headers.get("x-api-code") or body.get("code") or "")
    message = headers.get("x-api-message") or body.get("message") or body.get("error") or ""
    return code, message


def volcengine_extract_segments(payload):
    root = payload.get("resp", payload) if isinstance(payload, dict) else {}
    if isinstance(root, dict) and isinstance(root.get("body"), dict):
        root = root["body"]
    if isinstance(root, dict) and isinstance(root.get("result"), dict):
        root = root["result"]
    utterances = []
    if isinstance(root, dict):
        utterances = root.get("utterances") or root.get("utterance") or root.get("segments") or root.get("words") or []
    segments = []
    if isinstance(utterances, list) and utterances:
        for idx, item in enumerate(utterances, start=1):
            if not isinstance(item, dict):
                continue
            text_value = str(item.get("text") or item.get("utterance") or item.get("sentence") or "").strip()
            if not text_value:
                continue
            start_ms = item.get("start_time", item.get("start", item.get("begin_time", 0)))
            end_ms = item.get("end_time", item.get("end", item.get("stop_time", start_ms)))
            start_raw = float(start_ms or 0)
            end_raw = float(end_ms or start_ms or 0)
            start = start_raw / 1000 if start_raw > 100 else start_raw
            end = end_raw / 1000 if end_raw > 100 else end_raw
            if end <= start:
                end = start + max(1.0, len(text_value) / 4)
            segments.append({"id": idx, "start": round(start, 3), "end": round(end, 3), "text": text_value})
    if not segments and isinstance(root, dict):
        text_value = str(root.get("text") or root.get("transcript") or root.get("result") or "").strip()
        if text_value:
            segments.append({"id": 1, "start": 0, "end": 0, "text": text_value})
    return segments


def volcengine_transcribe_worker(job_id, task_id=None, volc_payload=None):
    base_dir = job_dir(job_id)
    meta = read_json(base_dir / "metadata.json", {})
    source = base_dir / meta.get("original_file", "source.mp4")
    audio = base_dir / "audio.wav"
    selected_range = meta.get("transcription_range") or {}
    range_start = max(0, float(selected_range.get("start", 0) or 0))
    range_end = max(range_start, float(selected_range.get("end", 0) or 0))
    range_duration = max(0, range_end - range_start)
    started = time.time()
    submit_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    query_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

    def update_task(progress=None, **updates):
        if not task_id:
            return None
        if progress is not None:
            updates["progress"] = progress
        updates["elapsed"] = max(0, time.time() - started)
        return set_clip_task(task_id, **updates)

    def wait_for_control():
        wait_for_transcription_resume(job_id, task_id, update_task)
        state = get_job_state(job_id)
        if state.get("stage") == "paused":
            set_job(job_id, stage="transcribing", message="继续转写")
        if task_id and get_clip_task(task_id) and get_clip_task(task_id).get("status") == "paused":
            update_task(status="running", message="继续转写")

    def wait_between_requests(seconds):
        deadline = time.time() + max(0, float(seconds or 0))
        while time.time() < deadline:
            wait_for_control()
            time.sleep(min(0.2, max(0, deadline - time.time())))

    try:
        settings = volcengine_settings(volc_payload)
        tos_cfg = tos_settings(volc_payload)
        if not settings.get("api_key"):
            raise RuntimeError("火山 ASR 未配置：请填写 API Key。")
        source_probe = probe_video(source)
        if source_probe.get("has_audio") is False:
            raise RuntimeError("当前视频不含音轨，无法进行语音转写。请上传已合并音频的视频文件。")

        wait_for_control()
        if range_duration <= 0:
            raise RuntimeError("未找到有效的转写范围")
        range_label = f"{seconds_to_clock(range_start)} - {seconds_to_clock(range_end)}"
        set_job(job_id, stage="extracting", message=f"正在提取选定范围的音频（{range_label}）", progress=0.05, transcribe_started_at=started)
        update_task(status="running", progress=0.03, message=f"正在提取选定范围音频（{range_label}）", encoder="火山 BigModel ASR")
        run_process(
            [ffmpeg_path(), "-y", "-i", str(source), "-ss", f"{range_start:.3f}", "-t", f"{range_duration:.3f}", "-vn", "-ac", "1", "-ar", "16000", str(audio)],
            cancel_check=lambda: transcription_stop_requested(job_id, task_id),
            on_process=lambda proc: clip_task_set_process(task_id, proc),
        )
        wait_for_control()
        if transcription_stop_requested(job_id, task_id):
            raise RuntimeError("transcription stopped")
        if not audio.exists() or audio.stat().st_size == 0:
            raise RuntimeError("音频提取失败：audio.wav 没有生成。")

        audio_url = settings.get("audio_url")
        tos_upload = None
        if not audio_url:
            wait_for_control()
            set_job(job_id, stage="transcribing", message="正在上传 audio.wav 到 TOS 并生成火山可访问 URL", progress=0.10, transcribe_model="volcengine_bigmodel")
            update_task(status="running", progress=0.10, message="正在上传 audio.wav 到 TOS", encoder="TOS + 火山 BigModel ASR")
            tos_upload = tos_upload_audio(audio, job_id, tos_cfg)
            audio_url = tos_upload["audio_url"]
            wait_for_control()
            if transcription_stop_requested(job_id, task_id):
                raise RuntimeError("transcription stopped")
            write_json(base_dir / "tos_audio_upload.json", {**tos_upload, "uploaded_at": datetime.now().isoformat(timespec="seconds")})

        request_id = str(uuid4())
        wait_for_control()
        submit_body = {
            "user": {"uid": "mp4-golden-workbench"},
            "audio": {"url": audio_url, "format": "wav", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": False,
                "enable_speaker_info": False,
                "enable_channel_split": False,
                "show_utterances": True,
                "vad_segment": False,
                "sensitive_words_filter": "",
            },
        }
        set_job(job_id, stage="transcribing", message="正在提交火山 BigModel ASR 任务", progress=0.16, transcribe_model="volcengine_bigmodel", volcengine_audio_url=audio_url)
        update_task(status="running", progress=0.16, message="正在提交火山 BigModel submit", encoder="火山 BigModel ASR")
        submit_result = volcengine_bigmodel_request(
            submit_url,
            submit_body,
            settings["api_key"],
            settings["resource_id"],
            request_id,
            cancel_check=lambda: transcription_stop_requested(job_id, task_id),
        )
        wait_for_control()
        code, message = volcengine_status(submit_result)
        if code and code not in {"20000000", "20000001", "20000002"}:
            raise RuntimeError(f"火山 submit 失败：{code} {message or submit_result.get('body')}")

        write_json(base_dir / "volcengine_asr_task.json", {
            "request_id": request_id,
            "resource_id": settings["resource_id"],
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
            "audio_url": audio_url,
            "tos_upload": tos_upload,
            "submit_headers": submit_result.get("headers", {}),
        })
        set_job(job_id, stage="transcribing", message=f"火山任务已提交，正在轮询结果：{request_id}", progress=0.22, volcengine_task_id=request_id)
        update_task(status="running", progress=0.22, message="火山任务已提交，等待识别完成", volcengine_task_id=request_id)

        poll_interval = max(2.0, min(30.0, float(settings.get("poll_interval") or 5)))
        query_result = None
        for poll_index in range(1, 361):
            wait_for_control()
            query_result = volcengine_bigmodel_request(
                query_url,
                {},
                settings["api_key"],
                settings["resource_id"],
                request_id,
                cancel_check=lambda: transcription_stop_requested(job_id, task_id),
            )
            wait_for_control()
            code, message = volcengine_status(query_result)
            progress = min(0.92, 0.22 + poll_index * 0.01)
            if code == "20000000":
                break
            if code in {"20000001", "20000002", ""}:
                status_text = "排队中" if code == "20000002" else "识别中"
                set_job(job_id, stage="transcribing", message=f"火山{status_text}，已轮询 {poll_index} 次", progress=progress, transcribe_elapsed=max(0, time.time() - started))
                update_task(status="running", progress=progress, message=f"火山{status_text}，已轮询 {poll_index} 次", remaining=None)
                wait_between_requests(poll_interval)
                continue
            raise RuntimeError(f"火山 query 失败：{code} {message or query_result.get('body')}")
        else:
            raise RuntimeError("火山识别超时：轮询超过 30 分钟仍未完成。")

        result_body = (query_result or {}).get("body", {})
        segments = volcengine_extract_segments(result_body)
        for segment in segments:
            segment["start"] = round(range_start + float(segment.get("start", 0) or 0), 3)
            segment["end"] = round(range_start + float(segment.get("end", 0) or 0), 3)
        if len(segments) == 1 and segments[0].get("end", 0) <= segments[0].get("start", 0) and meta.get("duration"):
            segments[0]["end"] = round(range_end, 3)
        save_transcript_files(base_dir, segments)
        transcript = read_json(base_dir / "transcript.json", {"segments": segments})
        transcript.update({"engine": "volcengine_bigmodel", "volcengine_task_id": request_id})
        write_json(base_dir / "transcript.json", transcript)
        write_json(base_dir / "volcengine_asr_result.json", query_result or {})

        meta["status"] = "transcribed"
        meta["transcribe_engine"] = "volcengine_bigmodel"
        write_json(base_dir / "metadata.json", meta)
        final_message = f"火山转写完成，共 {len(segments)} 段" if segments else "火山转写完成，但没有返回可用分段"
        set_job(job_id, stage="transcribed", message=final_message, progress=1, segment_count=len(segments), transcribe_elapsed=max(0, time.time() - started), transcript_tail=segments[-8:] if segments else [])
        update_task(status="done", progress=1, remaining=0, message=final_message, segment_count=len(segments), transcript_file="transcript.json")
    except Exception as exc:
        if transcription_stop_requested(job_id, task_id):
            message = "转写已结束；未提交的火山请求已停止。已提交的云端任务可能仍在处理。"
            set_job(job_id, stage="stopped", message=message, error=None, transcribe_elapsed=max(0, time.time() - started))
            update_task(status="cancelled", progress=0, remaining=0, message=message, error=None)
            return
        set_job(job_id, stage="error", message=str(exc), error=str(exc), transcribe_elapsed=max(0, time.time() - started))
        update_task(status="error", progress=0, remaining=0, message=str(exc), error=str(exc))


def transcribe_worker(job_id, task_id=None, payload=None):
    payload = payload or {}
    return volcengine_transcribe_worker(job_id, task_id, payload)

def deepseek_analyze(job_id, payload, task_id=None):
    base_dir = job_dir(job_id)
    grouped = read_json(base_dir / "transcript_grouped.json", {})
    raw = read_json(base_dir / "transcript.json", {})
    meta = read_json(base_dir / "metadata.json", {})

    groups = grouped.get("groups", [])
    if not groups:
        segments = raw.get("segments", [])
        if not segments:
            raise RuntimeError("No transcript is available for analysis")
        compact_segments = "\n".join(
            f"{s['id']}. [{seconds_to_clock(s['start'])} - {seconds_to_clock(s['end'])}] {s['text']}"
            for s in segments
        )
        group_count = len(segments)
    else:
        compact_segments = "\n".join(
            f"{g['id']}. [{seconds_to_clock(g['start'])} - {seconds_to_clock(g['end'])}] {g['text']}"
            for g in groups
        )
        group_count = len(groups)

    provider = enabled_provider("llm", payload.get("provider_id"))
    if not provider or not provider.get("api_key"):
        raise RuntimeError("请先在供应商管理中添加并启用一个 LLM 配置。")
    key = provider["api_key"].strip()
    provider_name = provider.get("name") or "LLM"
    model = (provider.get("model") or "").strip()
    if not model:
        raise RuntimeError(f"LLM 配置“{provider_name}”缺少模型名称。")

    target_count = int(payload.get("target_clip_count") or 5)
    min_seconds = int(payload.get("min_seconds") or 60)
    max_seconds = int(payload.get("max_seconds") or 90)
    candidate_count = min(80, max(target_count * 2, target_count + 12))
    prompt = f"""You are a senior Chinese short-video editor, quote curator, and story producer.
Your job is to find a broad candidate pool of moments that may become strong short-video highlight clips. The backend will strictly filter, deduplicate, and rank your candidates, so do not force weak moments just to fill the quota.

Video title: {meta.get('title', '')}
Video duration: {seconds_to_clock(meta.get('duration') or 0)}
Transcript units: {group_count}
Final requested clips after backend filtering: {target_count}
Raw candidate pool to return: up to {candidate_count}
Clip length range: {min_seconds}-{max_seconds} seconds

Selection workflow:
1. Broad scan: locate moments with clear judgment, contrast, method, emotion, conflict, summary, story turn, or shareable phrasing.
2. Strict rejection: remove greetings, transitions, vague slogans, repeated examples, unfinished context, isolated nouns, and anything that only sounds important without saying something concrete.
3. Editing rank: prefer moments that can start cleanly, end cleanly, stand alone, and make a viewer want to keep watching or share.

A real golden quote usually contains at least one of these:
- A sharp judgment or conclusion.
- A counterintuitive contrast.
- A practical method or framework.
- A specific result, number, case, comparison, or cause-effect chain.
- Emotional tension, conflict, or turning point.
- A sentence that can become title, cover text, or first-screen subtitle.

Scoring guidance:
- quote_score: 0-100, strength of the actual golden sentence.
- context_score: 0-100, whether the clip is understandable on its own.
- edit_score: 0-100, whether boundaries and rhythm are usable for an editor.
- viral_score: 0-100, likelihood of making a strong short-video hook.
- confidence: 0-1, overall certainty.
Only return candidates with confidence >= 0.60 unless the transcript has very few good moments.

Timing rules:
1. start and end must use seconds from the transcript timeline.
2. Do not cut in the middle of a sentence. Expand to a full semantic unit if needed.
3. The final duration after padding should stay within {min_seconds}-{max_seconds} seconds when possible.
4. Use padding_before/padding_after only for small breathing room or necessary context. Prefer 0.2-1.5 seconds.
5. If a quote is excellent but too long, choose the most self-contained core section.
6. Return more good candidates than the final requested count, but do not add weak filler.

Output requirements:
- Return only valid JSON. No Markdown. No explanation outside JSON.
 - Keep title, suggested_title, alternate_title, quote, reason, original_copy, xiaohongshu_copy, comment_prompt, hook_text, cover_text, and editor_note in Simplified Chinese.
- quote should be the most powerful sentence or compact core idea, not the whole transcript block.
- reason should explain why an editor should keep it.
- hook_text should be usable as the first-screen subtitle or short-video opening text.
- cover_text should be short enough for a video cover.
 - editor_note should mention boundary/context advice briefly.
 - original_copy must be a clean, readable spoken transcript for this clip, with filler words and obvious spoken slips removed but no invented facts.
 - xiaohongshu_copy should be a complete post-ready paragraph with a strong opening, key point, and concise conclusion.
 - comment_prompt should be one natural question that invites comments.
 - hashtags should contain 3-6 relevant Chinese topic words without the # prefix.
 - recommendation_label should be a short label such as "主推 · 有数字" or "主推 · 强反差".

JSON schema:
{{
  "clips": [
    {{
      "id": "clip_001",
       "title": "short Chinese title",
       "suggested_title": "primary short-video title in Chinese",
       "alternate_title": "a second title option in Chinese",
       "quote": "best golden sentence or core idea in Chinese",
       "reason": "why this clip is worth keeping, in Chinese",
       "original_copy": "clean spoken transcript for this clip in Chinese",
       "xiaohongshu_copy": "post-ready Xiaohongshu copy in Chinese",
       "comment_prompt": "one Chinese comment prompt",
       "hashtags": ["topic one", "topic two"],
       "recommendation_label": "主推 · 有数字",
      "hook_text": "opening hook text in Chinese",
      "cover_text": "short cover text in Chinese",
      "editor_note": "brief editing note in Chinese",
      "start": 432.2,
      "end": 448.8,
      "padding_before": 0.8,
      "padding_after": 0.8,
      "clip_type": "golden_quote|method|conflict|story_turn|summary|emotion|counterintuitive",
      "quote_score": 88,
      "context_score": 82,
      "edit_score": 80,
      "viral_score": 76,
      "confidence": 0.86
    }}
  ]
}}

Transcript:
{compact_segments}
"""
    # Keep clip analysis on the same transport and response parser used by the
    # provider test and AI trend discovery. This handles OpenAI-compatible
    # content variants consistently and never bypasses active system routing.
    highlights = llm_json(
        prompt,
        provider_id=provider.get("id") or payload.get("provider_id"),
        timeout=330,
        max_tokens=8192,
    )

    if task_id:
        wait_for_clip_task_resume(task_id)
    candidates = []
    duration = float(meta.get("duration") or 0)
    min_len = max(1.0, float(min_seconds))
    max_len = max(min_len, float(max_seconds))

    def clip_text_key(clip):
        text = " ".join(str(clip.get(k) or "") for k in ("title", "quote", "hook_text", "cover_text"))
        text = re.sub(r"[\s\W_]+", "", text.lower(), flags=re.UNICODE)
        return text

    def char_jaccard(a, b):
        if not a or not b:
            return 0.0
        if len(a) < 2 or len(b) < 2:
            return 1.0 if a == b else 0.0
        grams_a = {a[i:i + 2] for i in range(len(a) - 1)}
        grams_b = {b[i:i + 2] for i in range(len(b) - 1)}
        if not grams_a or not grams_b:
            return 0.0
        return len(grams_a & grams_b) / max(1, len(grams_a | grams_b))

    def overlap_ratio(a, b):
        overlap = max(0.0, min(float(a["end"]), float(b["end"])) - max(float(a["start"]), float(b["start"])))
        shortest = max(0.01, min(float(a["end"]) - float(a["start"]), float(b["end"]) - float(b["start"])))
        return overlap / shortest

    for clip in highlights.get("clips", []):
        try:
            raw_start = float(clip.get("start", 0))
            raw_end = float(clip.get("end", 0))
            padding_before = min(2.0, max(0.0, float(clip.get("padding_before", 0) or 0)))
            padding_after = min(2.0, max(0.0, float(clip.get("padding_after", 0) or 0)))
        except (TypeError, ValueError):
            continue
        start = max(0, raw_start - padding_before)
        end = raw_end + padding_after
        if duration:
            end = min(duration, end)
        clip_len = end - start
        if clip_len <= 0:
            continue
        confidence = float(clip.get("confidence", 0) or 0)
        quote_score = float(clip.get("quote_score", 0) or 0)
        context_score = float(clip.get("context_score", 0) or 0)
        edit_score = float(clip.get("edit_score", 0) or 0)
        viral_score = float(clip.get("viral_score", 0) or 0)
        if confidence and confidence < 0.60:
            continue
        if clip_len < max(2.0, min_len * 0.60):
            continue
        if clip_len > max_len * 1.25:
            continue
        score = (
            quote_score * 0.38
            + context_score * 0.24
            + edit_score * 0.22
            + viral_score * 0.16
            + confidence * 100 * 0.12
        )
        if score < 56:
            continue
        clip["selection_score"] = round(score, 2)
        clip["start"] = round(start, 3)
        clip["end"] = round(end, 3)
        clip["duration"] = round(clip_len, 3)
        clip["_text_key"] = clip_text_key(clip)
        candidates.append(clip)
    candidates.sort(key=lambda item: (float(item.get("selection_score") or 0), float(item.get("confidence") or 0)), reverse=True)

    selected = []
    for clip in candidates:
        if len(selected) >= target_count:
            break
        too_similar = any(char_jaccard(clip.get("_text_key", ""), item.get("_text_key", "")) >= 0.56 for item in selected)
        if too_similar:
            continue
        too_overlapped = any(overlap_ratio(clip, item) >= 0.35 for item in selected)
        if too_overlapped:
            continue
        center = (float(clip["start"]) + float(clip["end"])) / 2
        nearby_count = sum(1 for item in selected if abs(center - ((float(item["start"]) + float(item["end"])) / 2)) < 120)
        if nearby_count >= 2:
            continue
        selected.append(clip)

    # If strict distribution leaves too few results, relax only the time-distribution rule, not quality or overlap.
    if len(selected) < max(3, target_count // 2):
        for clip in candidates:
            if len(selected) >= target_count:
                break
            if clip in selected:
                continue
            if any(char_jaccard(clip.get("_text_key", ""), item.get("_text_key", "")) >= 0.56 for item in selected):
                continue
            if any(overlap_ratio(clip, item) >= 0.35 for item in selected):
                continue
            selected.append(clip)

    clips = []
    for index, clip in enumerate(selected[:target_count], start=1):
        clip.pop("_text_key", None)
        clip["id"] = f"clip_{index:03d}"
        clip["status"] = "pending"
        clip["preview_file"] = None
        clip["export_file"] = None
        clip["confirmed"] = False
        clips.append(clip)
    highlights = {"clips": clips, "candidate_count": len(candidates), "requested_count": target_count}
    save_highlights(job_id, highlights)
    return highlights


def analyze_worker(task_id, job_id, payload):
    started = time.time()
    try:
        provider = enabled_provider("llm", payload.get("provider_id")) or {}
        model_label = (provider.get("model") or provider.get("name") or "LLM").strip()
        grouped = read_json(job_dir(job_id) / "transcript_grouped.json", {})
        raw = read_json(job_dir(job_id) / "transcript.json", {})
        unit_count = len(grouped.get("groups", [])) or len(raw.get("segments", []))
        set_clip_task(task_id, status="running", progress=0.05, elapsed=0, message=f"\u6b63\u5728\u6574\u7406\u6587\u5b57\u7a3f\u4e0a\u4e0b\u6587\uff08{unit_count} \u4e2a\u5355\u5143\uff09", encoder=model_label)
        set_job(job_id, stage="analyzing", message=f"{model_label} \u5206\u6790\u5df2\u5f00\u59cb", analyze_task_id=task_id)
        wait_for_clip_task_resume(task_id)
        set_clip_task(task_id, status="running", progress=0.20, elapsed=max(0, time.time() - started), message=f"\u5df2\u53d1\u9001\u7ed9 {model_label}\uff0c\u901a\u5e38\u9700\u8981\u7b49\u5f85 4-5 \u5206\u949f\uff0c\u8bf7\u8010\u5fc3\u7b49\u5f85")
        highlights = deepseek_analyze(job_id, payload, task_id)
        if clip_task_cancelled(task_id):
            raise RuntimeError("Analysis task cancelled")
        set_clip_task(task_id, status="running", progress=0.90, elapsed=max(0, time.time() - started), message="AI \u5df2\u8fd4\u56de\u7ed3\u679c\uff0c\u6b63\u5728\u8fc7\u6ee4\u3001\u53bb\u91cd\u3001\u6392\u5e8f")
        count = len(highlights.get("clips", []))
        set_job(job_id, stage="analyzed", message=f"Found {count} candidate clips", analyze_task_id=task_id)
        set_clip_task(task_id, status="done", progress=1, remaining=0, elapsed=max(0, time.time() - started), message=f"\u5206\u6790\u5b8c\u6210\uff0c\u627e\u5230 {count} \u4e2a\u5019\u9009\u7247\u6bb5", highlights=highlights)
    except TimeoutError:
        set_job(job_id, stage="error", message=f"{model_label} \u54cd\u5e94\u8d85\u65f6\uff08\u8d85\u8fc7 5 \u5206\u949f\uff09\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc\u540e\u91cd\u8bd5", error="LLM timeout", analyze_task_id=task_id)
        set_clip_task(task_id, status="error", progress=0, remaining=0, elapsed=max(0, time.time() - started), message=f"{model_label} \u54cd\u5e94\u8d85\u65f6\uff08\u8d85\u8fc7 5 \u5206\u949f\uff09\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc\u540e\u91cd\u8bd5", error="LLM timeout")
    except Exception as exc:
        status = "cancelled" if "cancel" in str(exc).lower() else "error"
        set_job(job_id, stage="error" if status == "error" else "analyze_cancelled", message=str(exc), error=str(exc), analyze_task_id=task_id)
        set_clip_task(task_id, status=status, progress=1 if status == "cancelled" else 0, remaining=0, elapsed=max(0, time.time() - started), message=str(exc), error=str(exc))

def normalize_highlights(highlights):
    if not isinstance(highlights, dict):
        return {"clips": []}, False
    clips = highlights.get("clips")
    if not isinstance(clips, list):
        highlights["clips"] = []
        return highlights, True
    changed = False
    legacy_manual_clips = [clip for clip in clips if isinstance(clip, dict) and clip.get("clip_type") == "manual_trim"]
    if legacy_manual_clips:
        clips[:] = [clip for clip in clips if not (isinstance(clip, dict) and clip.get("clip_type") == "manual_trim")]
        changed = True
    seen = set()
    for index, clip in enumerate(clips, start=1):
        if not isinstance(clip, dict):
            clips[index - 1] = {"id": f"clip_{index:03d}", "title": f"片段 {index}", "start": 0, "end": 0}
            changed = True
            continue
        expected = f"clip_{index:03d}"
        clip_id = str(clip.get("id") or "").strip()
        if not clip_id or clip_id in seen:
            clip_id = expected
            suffix = 1
            while clip_id in seen:
                suffix += 1
                clip_id = f"{expected}_{suffix}"
            clip["id"] = clip_id
            changed = True
        seen.add(clip_id)
    return highlights, changed


def get_highlights(job_id):
    path = job_dir(job_id) / "highlights.json"
    highlights = read_json(path, {"clips": []})
    highlights, changed = normalize_highlights(highlights)
    if changed:
        write_json(path, highlights)
    return highlights


def save_highlights(job_id, highlights):
    highlights, _changed = normalize_highlights(highlights)
    write_json(job_dir(job_id) / "highlights.json", highlights)
    sync_job_output(job_id, include_candidates=True, prune_clip_folders=True)


def clip_export_filename(index, title, start, end, source_path):
    safe_title = sanitize_name(title)[:32]
    ext = source_path.suffix.lower() if source_path.suffix.lower() in {".mp4", ".mov"} else ".mp4"
    return f"{index:03d}_{safe_title}_{seconds_to_clock(start).replace(':', '-')}_to_{seconds_to_clock(end).replace(':', '-')}{ext}"




def verify_stream_copy(source_path, export_path):
    source_meta = probe_video(source_path)
    export_meta = probe_video(export_path)
    fields = ["video_codec", "width", "height", "pixel_format", "audio_codec"]
    checks = {}
    warnings = []
    for field in fields:
        source_value = source_meta.get(field)
        export_value = export_meta.get(field)
        if source_value in {None, ""} and export_value in {None, ""}:
            checks[field] = True
            continue
        ok = source_value == export_value
        checks[field] = ok
        if not ok:
            warnings.append(f"{field}: source={source_value}, export={export_value}")
    return {
        "ok": all(checks.values()),
        "mode": "original_stream_copy_no_reencode",
        "checks": checks,
        "warnings": warnings,
        "source": {field: source_meta.get(field) for field in fields},
        "export": {field: export_meta.get(field) for field in fields},
    }

def render_clip(job_id, clip_id, export=False, precise=False, export_dir=None, progress_callback=None, fallback_callback=None, process_callback=None, cancel_check=None):
    base_dir = job_dir(job_id)
    meta = read_json(base_dir / "metadata.json", {})
    highlights = get_highlights(job_id)
    clips = highlights.get("clips", [])
    clip = next((c for c in clips if c.get("id") == clip_id), None)
    if not clip:
        raise RuntimeError("\u627e\u4e0d\u5230\u8fd9\u4e2a\u7247\u6bb5")
    source = base_dir / meta.get("original_file", "source.mp4")
    start = float(clip["start"])
    end = float(clip["end"])
    if end <= start:
        raise RuntimeError("\u7247\u6bb5\u7ed3\u675f\u65f6\u95f4\u5fc5\u987b\u665a\u4e8e\u5f00\u59cb\u65f6\u95f4")

    if export:
        if export_dir:
            output_name = read_json(base_dir / "metadata.json", {}).get("output_folder") or job_output_dir(job_id).name
            folder = Path(str(export_dir)).expanduser() / output_name / clip_output_folder_name(clip)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "analysis.md").write_text(clip_analysis_markdown(clip), encoding="utf-8")
        else:
            folder = clip_output_dir(job_id, clip)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "analysis.md").write_text(clip_analysis_markdown(clip), encoding="utf-8")
    else:
        folder = base_dir / "clips" / "preview"
    folder.mkdir(parents=True, exist_ok=True)
    index = clips.index(clip) + 1

    if export:
        # Final clips preserve the original video/audio streams. No re-encoding.
        ext = source.suffix.lower() if source.suffix.lower() in {".mp4", ".mov"} else ".mp4"
        name = f"clip{ext}"
        target = folder / name
        cmd = [
            ffmpeg_path(),
            "-y",
            "-ss",
            seconds_to_clock(start),
            "-i",
            str(source),
            "-t",
            f"{max(0.01, end - start):.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-sn",
            "-dn",
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(target),
        ]
    else:
        # Preview clips are browser-compatible H.264/AAC MP4 files, separate from final exports.
        name = clip_filename(index, clip.get("title") or clip_id, start, end)
        target = folder / name
        encoder = detect_h264_encoder()
        cmd = build_preview_cmd(source, target, start=start, duration=end - start, encoder_name=encoder["name"])
        fallback_cmd = build_preview_cmd(source, target, start=start, duration=end - start, encoder_name="libx264") if encoder["name"] != "libx264" else None
    if export:
        if progress_callback:
            run_process_with_progress(cmd, duration=end - start, on_progress=progress_callback, on_process=process_callback, cancel_check=cancel_check)
        else:
            run_process(cmd)
    else:
        run_preview_process(cmd, fallback_cmd, duration=end - start, on_progress=progress_callback, on_fallback=fallback_callback, on_process=process_callback, cancel_check=cancel_check)
    key = "export_file" if export else "preview_file"
    try:
        stored_path = str(target.relative_to(base_dir)).replace("\\", "/")
    except ValueError:
        stored_path = str(target)
    clip[key] = stored_path
    if export:
        clip["export_path"] = str(target)
        clip["export_quality"] = "original_stream_copy_no_reencode"
        try:
            clip["export_verification"] = verify_stream_copy(source, target)
        except Exception as exc:
            clip["export_verification"] = {
                "ok": False,
                "mode": "original_stream_copy_no_reencode",
                "checks": {},
                "warnings": [f"verification failed: {exc}"],
            }
    clip["export_mode"] = "original_stream_copy" if export else clip.get("export_mode")
    clip["preview_mode"] = "browser_compatible_h264" if not export else clip.get("preview_mode")
    clip["status"] = "exported" if export else "ready"
    save_highlights(job_id, highlights)
    return clip



def remove_job_relative_file(base_dir, rel_path):
    if not rel_path or Path(str(rel_path)).is_absolute():
        return False
    target = (base_dir / str(rel_path)).resolve()
    try:
        target.relative_to(base_dir.resolve())
    except ValueError:
        return False
    if target.exists() and target.is_file():
        target.unlink()
        return True
    return False

def path_size(path):
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total




def command_available(path_or_cmd, version_args):
    try:
        proc = subprocess.run([path_or_cmd, *version_args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8)
        first_line = (proc.stdout or proc.stderr or "").strip().splitlines()[0] if (proc.stdout or proc.stderr or "").strip() else ""
        return {"ok": proc.returncode == 0, "path": path_or_cmd, "version": first_line}
    except Exception as exc:
        return {"ok": False, "path": path_or_cmd, "error": str(exc)}


def dependency_health():
    checks = []
    ffmpeg = command_available(ffmpeg_path(), ["-version"])
    ffprobe = command_available(ffprobe_path(), ["-version"])
    if not ffprobe.get("ok") and ffmpeg.get("ok"):
        ffprobe = {"ok": True, "path": ffmpeg.get("path"), "version": "使用 FFmpeg 元数据回退"}
    encoder = detect_h264_encoder()
    python_executable = sys.executable
    try:
        usage = shutil.disk_usage(DATA_DIR)
        disk = {
            "ok": usage.free >= 5 * 1024 ** 3,
            "total": usage.total,
            "free": usage.free,
            "used": usage.used,
            "message": "At least 5 GB free is recommended for long videos",
        }
    except Exception as exc:
        disk = {"ok": False, "error": str(exc)}
    llm = enabled_provider("llm")
    llm_status = {"ok": bool(llm and llm.get("api_key")), "has_key": bool(llm and llm.get("api_key")), "message": f"{llm.get('name')} enabled" if llm else "No LLM provider enabled"}
    checks.extend([
        {"id": "ffmpeg", "label": "FFmpeg", "ok": bool(ffmpeg.get("ok")), **ffmpeg},
        {"id": "ffprobe", "label": "FFprobe", "ok": bool(ffprobe.get("ok")), **ffprobe},
        {"id": "encoder", "label": "Preview encoder", "ok": True, "message": encoder.get("label"), "hardware": encoder.get("hardware"), "name": encoder.get("name")},
        {"id": "llm", "label": "LLM provider", **llm_status},
        {"id": "disk", "label": "Free disk space", **disk},
    ])
    required = [item for item in checks if item["id"] in {"ffmpeg", "ffprobe", "disk"}]
    warnings = [item for item in checks if not item.get("ok")]
    return {
        "ok": all(item.get("ok") for item in required),
        "checks": checks,
        "warning_count": len(warnings),
        "data_dir": str(DATA_DIR),
        "python": python_executable,
        "requirements": str(ROOT / "requirements.txt"),
    }

def storage_summary():
    items = []
    total = 0
    for path in sorted(JOBS_DIR.glob("*"), reverse=True):
        if not path.is_dir():
            continue
        meta = read_json(path / "metadata.json", {})
        highlights = read_json(path / "highlights.json", {"clips": []})
        clips = highlights.get("clips", [])
        runtime_size = path_size(path)
        output_size = path_size(job_output_dir(path.name, create=False))
        size = runtime_size + output_size
        total += size
        items.append({
            "job_id": path.name,
            "title": meta.get("title", path.name),
            "created_at": meta.get("created_at"),
            "total_size": size,
            "runtime_size": runtime_size,
            "output_size": output_size,
            "source_size": path_size(path / meta.get("original_file", "source.mp4")),
            "browser_preview_size": path_size(path / "browser-preview.mp4"),
            "audio_size": path_size(path / "audio.wav"),
            "clip_preview_size": path_size(path / "clips" / "preview"),
            "clip_export_size": path_size(path / "clips" / "exports"),
            "clip_count": len(clips),
        })
    return {"total_size": total, "items": items, "encoder": detect_h264_encoder()}


def cleanup_storage(payload):
    job_id = payload.get("job_id")
    categories = set(payload.get("categories") or [])
    targets = [job_dir(job_id)] if job_id else [p for p in JOBS_DIR.glob("*") if p.is_dir()]
    deleted = []
    for base in targets:
        meta_path = base / "metadata.json"
        meta = read_json(meta_path, {})
        highlights_path = base / "highlights.json"
        highlights = read_json(highlights_path, {"clips": []})
        if "browser_preview" in categories:
            target = base / "browser-preview.mp4"
            if target.exists():
                deleted.append(str(target))
                target.unlink()
            meta.pop("browser_preview_file", None)
            meta.pop("browser_preview_encoder", None)
            if meta:
                write_json(meta_path, meta)
        if "audio" in categories:
            target = base / "audio.wav"
            if target.exists():
                deleted.append(str(target))
                target.unlink()
        if "clip_previews" in categories:
            folder = base / "clips" / "preview"
            if folder.exists():
                for child in folder.glob("*"):
                    if child.is_file():
                        deleted.append(str(child))
                        child.unlink()
            for clip in highlights.get("clips", []):
                clip["preview_file"] = None
                if clip.get("status") == "ready":
                    clip["status"] = "needs_render"
            if highlights_path.exists():
                write_json(highlights_path, highlights)
        if "workspace_cache" in categories:
            output_dir = job_output_dir(base.name, create=False)
            if output_dir.exists():
                sync_job_output(base.name, include_candidates=highlights_path.exists(), prune_clip_folders=True)
            keep_files = {"metadata.json", "transcript.json", "transcript_grouped.json", "highlights.json"}
            for child in list(base.iterdir()):
                if child.name in keep_files:
                    continue
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                    deleted.append(str(child))
                elif child.is_file():
                    child.unlink(missing_ok=True)
                    deleted.append(str(child))
            if meta:
                meta["source_cleaned"] = True
                meta.pop("browser_preview_file", None)
                meta.pop("browser_preview_encoder", None)
                write_json(meta_path, meta)
    return {"deleted": deleted, "storage": storage_summary()}
def list_library():
    items = []
    for path in sorted(JOBS_DIR.glob("*"), reverse=True):
        if not path.is_dir():
            continue
        meta = read_json(path / "metadata.json", {})
        if not meta or not meta.get("entered_task_center"):
            continue
        highlights = read_json(path / "highlights.json", {"clips": []})
        clips = highlights.get("clips", [])
        output_dir = job_output_dir(path.name, create=False)
        items.append(
            {
                "job_id": path.name,
                "title": meta.get("title", path.name),
                "output_folder": output_dir.name,
                "output_path": str(output_dir),
                "created_at": meta.get("created_at"),
                "duration": meta.get("duration"),
                "status": meta.get("status"),
                "clip_count": len(clips),
                "confirmed_count": len([c for c in clips if c.get("confirmed")]),
                "exported_count": len([c for c in clips if c.get("export_file")]),
            }
        )
    return items


def _clip_export_path(job_id, clip):
    """Resolve an exported clip to a local file inside the app-managed folders."""
    base_dir = job_dir(job_id)
    candidates = [clip.get("export_path"), clip.get("export_file")]
    for raw in candidates:
        if not raw:
            continue
        target = Path(str(raw)).expanduser()
        if not target.is_absolute():
            target = (base_dir / target).resolve()
        else:
            target = target.resolve()
        for allowed in (base_dir.resolve(), OUTPUTS_DIR.resolve()):
            try:
                target.relative_to(allowed)
                if target.is_file():
                    return target
            except ValueError:
                continue
    return None


def list_publish_assets():
    """List only complete videos explicitly imported for publishing.

    Golden-quote exports remain task outputs. They are intentionally excluded
    here so an extracted segment cannot be mistaken for a publish-ready cut.
    """
    assets = []
    local_assets = read_json(PUBLISH_LOCAL_ASSETS_PATH, [])
    changed = False
    if not isinstance(local_assets, list):
        local_assets = []
        changed = True
    for item in local_assets:
        if not isinstance(item, dict):
            changed = True
            continue
        file_path = Path(str(item.get("file_path") or ""))
        if not file_path.is_file():
            changed = True
            continue
        assets.append({
            "asset_id": item.get("asset_id"),
            "job_id": "",
            "clip_id": "",
            "title": item.get("title") or file_path.stem,
            "file": file_path.name,
            "file_path": str(file_path),
            "file_url": f"/publish-local/{urllib.parse.quote(item.get('stored_name') or file_path.name)}",
            "file_size": file_path.stat().st_size,
            "duration": float(item.get("duration") or 0),
            "source_title": "本地导入视频",
            "status": "ready",
            "origin": "local",
        })
    if changed:
        valid_ids = {asset["asset_id"] for asset in assets if asset.get("origin") == "local"}
        write_json(PUBLISH_LOCAL_ASSETS_PATH, [item for item in local_assets if isinstance(item, dict) and item.get("asset_id") in valid_ids])
    return assets


def import_publish_local_asset(upload_item):
    if upload_item is None or not upload_item.filename:
        raise RuntimeError("请选择一个本地视频文件")
    ext = Path(upload_item.filename).suffix.lower()
    if ext not in {".mp4", ".mov", ".m4v", ".webm"}:
        raise RuntimeError("支持 MP4、MOV、M4V、WebM 视频文件")
    PUBLISH_LOCAL_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    title = sanitize_output_name(upload_item.filename)
    asset_id = f"local-{uuid4().hex[:12]}"
    stored_name = f"{asset_id}{ext}"
    target = PUBLISH_LOCAL_ASSETS_DIR / stored_name
    with UPLOAD_LOCK:
        with target.open("wb") as output:
            shutil.copyfileobj(upload_item.file, output)
    try:
        probe = probe_video(target)
        duration = float(probe.get("duration") or 0)
    except Exception:
        duration = 0.0
    record = {
        "asset_id": asset_id,
        "title": title,
        "stored_name": stored_name,
        "file_path": str(target),
        "duration": duration,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    existing = read_json(PUBLISH_LOCAL_ASSETS_PATH, [])
    if not isinstance(existing, list):
        existing = []
    existing.insert(0, record)
    write_json(PUBLISH_LOCAL_ASSETS_PATH, existing[:100])
    return {
        "asset_id": asset_id,
        "title": title,
        "file": target.name,
        "file_path": str(target),
        "file_url": f"/publish-local/{urllib.parse.quote(stored_name)}",
        "file_size": target.stat().st_size,
        "duration": duration,
        "source_title": "本地导入视频",
        "status": "ready",
        "origin": "local",
    }


def _shared_publish_browser_page_urls():
    """Legacy CDP probe retained for old state files, not direct Chrome."""
    return None


def _publish_platform_target_url(platform):
    return {
        "douyin": "https://creator.douyin.com/",
        "channels": "https://channels.weixin.qq.com/",
    }.get(str(platform or ""))


def _reconcile_closed_manual_publish_tasks(force=False):
    """Direct-launch publishers report window closure through their process."""
    # The original publisher projects own the visible browser process directly;
    # there is no shared CDP endpoint to probe and no safe way to infer closure
    # from the backend. Let the publisher return its TargetClosedError marker.
    return 0
def list_publish_tasks():
    _reconcile_closed_manual_publish_tasks()
    with PUBLISH_TASK_LOCK:
        tasks = [dict(item) for item in PUBLISH_TASKS.values()]
    for task in tasks:
        message = str(task.get("message") or "")
        if task.get("status") == "error" and _publisher_window_closed_by_user(
            "\n".join([
                message,
                str(task.get("error") or ""),
                str((task.get("result") or {}).get("output") or ""),
            ])
        ):
            task["status"] = "cancelled"
            task["result_state"] = "cancelled_by_user"
            task["message"] = _publish_window_closed_message(task.get("platform"))
            task["error"] = ""
            continue
        if (
            "ERR_NETWORK_ACCESS_DENIED" in message
            or "ERR_NETWORK_ACCESS_DENIED" in str(task.get("error") or "")
            or "浏览器网络连接被系统拒绝" in message
        ):
            task["message"] = (
                "抖音发布页无法访问：浏览器网络连接被系统拒绝。"
                "当前发布器已按此前成功路径直连本机 Chrome；请检查 Windows 防火墙、VPN 或安全软件的网络限制后重试。"
            )
    def task_sort_key(item):
        raw = str(item.get("updated_at") or item.get("created_at") or "")
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError):
            stamp = 0
        return (stamp, str(item.get("task_id") or ""))

    return sorted(tasks, key=task_sort_key, reverse=True)


def list_task_center_tasks(job_id=None, limit=100):
    """Return clip, publish, and persisted trend-search records in one feed."""
    clip_tasks = list_clip_tasks(job_id=job_id, limit=max(1, int(limit or 100)))
    publish_tasks = list_publish_tasks()
    if job_id:
        publish_tasks = [task for task in publish_tasks if task.get("job_id") == job_id]

    entries = []
    for task in clip_tasks:
        item = dict(task)
        item.setdefault("category", item.get("type") or "other")
        entries.append(item)
    for task in publish_tasks:
        item = dict(task)
        item["type"] = "publish"
        item["category"] = "publish"
        item["publish_status"] = task.get("status")
        item["percent"] = 100 if task.get("status") == "succeeded" else 0
        item["progress"] = 1 if task.get("status") == "succeeded" else 0
        item["message"] = task.get("message") or "等待发布"
        entries.append(item)
    if not job_id:
        entries.extend(list_trend_search_task_records(limit=max(1, int(limit or 100))))

    entries.sort(key=lambda task: str(task.get("updated_at") or task.get("created_at") or ""), reverse=True)
    return entries[: max(1, int(limit or 100))]


def list_trend_search_task_records(limit=100):
    """Expose saved results and in-flight trend discovery in the task center."""
    entries = []
    with TREND_TASK_LOCK:
        active_tasks = [dict(task) for task in TREND_TASKS.values()]
    for task in active_tasks:
        if task.get("kind") != "discovery" or task.get("status") == "done":
            continue
        item = dict(task)
        item["type"] = "trend_search"
        item["category"] = "trend"
        hotspot_count = max(0, min(10, len(item.get("hotspot_ids") or [])))
        person_count = max(0, min(6, len(item.get("person_ids") or [])))
        if hotspot_count:
            item["title"] = f"爆款搜索 · {hotspot_count} 条热点"
        elif person_count:
            item["title"] = f"爆款搜索 · {person_count} 位人物"
        else:
            item["title"] = "爆款搜索"
        item["message"] = item.get("message") or "正在生成爆款选题"
        entries.append(item)

    for path in sorted(TRENDS_DIR.glob("trend-*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        result = read_json(path, {})
        if not isinstance(result, dict):
            continue
        search_id = str(result.get("search_id") or "").strip()
        if not search_id.startswith("trend-"):
            continue
        topics = [topic for topic in result.get("topics", []) if isinstance(topic, dict)]
        selected_hotspots = [str(item.get("title") or "").strip() for item in result.get("selected_hotspots", []) if isinstance(item, dict)]
        selected_people = [str(item.get("name") or "").strip() for item in result.get("selected_people", []) if isinstance(item, dict)]
        labels = selected_hotspots or selected_people
        if not labels:
            labels = [str(topic.get("subject_label") or topic.get("speaker_name") or topic.get("title") or "").strip() for topic in topics]
        names = list(dict.fromkeys(name for name in labels if name))
        title_suffix = "、".join(names[:3]) or "已保存结果"
        created_at = str(result.get("created_at") or datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"))
        material_topic_count = len(topics_with_materials(topics))
        entries.append({
            "task_id": f"trend-record-{search_id}",
            "search_id": search_id,
            "type": "trend_search",
            "category": "trend",
            "status": "done",
            "progress": 1,
            "percent": 100,
            "title": f"爆款搜索 · {title_suffix}",
            "message": f"已生成 {len(topics)} 条选题，其中 {material_topic_count} 条找到视频素材",
            "created_at": created_at,
            "updated_at": created_at,
            "topic_count": len(topics),
            "candidate_count": len(result.get("candidates") or []),
        })
        if len(entries) >= max(1, int(limit or 100)) + len(active_tasks):
            break
    return entries


def clear_finished_publish_tasks():
    removable = {"succeeded", "error", "cancelled"}
    removed = 0
    with PUBLISH_TASK_LOCK:
        for task_id, task in list(PUBLISH_TASKS.items()):
            if task.get("status") in removable:
                PUBLISH_TASKS.pop(task_id, None)
                removed += 1
        if removed:
            write_json(PUBLISH_TASKS_PATH, PUBLISH_TASKS)
    return removed


def clear_finished_trend_search_records():
    """Remove completed discovery records while leaving temporary candidate pools alone."""
    removed = 0
    with TREND_TASK_LOCK:
        for task_id, task in list(TREND_TASKS.items()):
            if task.get("kind") == "discovery" and task.get("status") in {"done", "error"}:
                TREND_TASKS.pop(task_id, None)
                removed += 1
    for path in TRENDS_DIR.glob("trend-*.json"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def delete_task_record(task_id):
    """Delete one task-center record without deleting its workspace files."""
    task_id = str(task_id or "").strip()
    if not task_id:
        raise RuntimeError("缺少任务记录 ID")

    removed_clip = False
    with CLIP_TASK_LOCK:
        clip_task = CLIP_TASKS.get(task_id)
        if clip_task:
            if clip_task.get("status") in {"queued", "running", "paused"}:
                raise RuntimeError("任务仍在运行，请先取消或结束后再删除记录")
            CLIP_TASKS.pop(task_id, None)
            removed_clip = True
    if removed_clip:
        persist_clip_tasks()
        return {"task_id": task_id, "deleted": True, "kind": "clip"}

    with PUBLISH_TASK_LOCK:
        publish_task = PUBLISH_TASKS.get(task_id)
        if publish_task:
            if publish_task.get("status") in {"queued", "running"}:
                raise RuntimeError("发布任务仍在运行，请等待结束后再删除记录")
            PUBLISH_TASKS.pop(task_id, None)
            write_json(PUBLISH_TASKS_PATH, PUBLISH_TASKS)
            return {"task_id": task_id, "deleted": True, "kind": "publish"}

    with TREND_TASK_LOCK:
        trend_task = TREND_TASKS.get(task_id)
        if trend_task:
            if trend_task.get("status") in {"queued", "running"}:
                raise RuntimeError("爆款搜索仍在运行，请等待结束后再删除记录")
            TREND_TASKS.pop(task_id, None)
            return {"task_id": task_id, "deleted": True, "kind": "trend"}

    record_prefix = "trend-record-"
    if task_id.startswith(record_prefix):
        search_id = task_id.removeprefix(record_prefix)
        if not search_id.startswith("trend-"):
            raise RuntimeError("无效的爆款搜索记录 ID")
        path = trend_search_path(search_id)
        if not path.exists():
            raise RuntimeError("找不到爆款搜索记录")
        try:
            path.unlink()
        except OSError as exc:
            raise RuntimeError(f"删除爆款搜索记录失败：{exc}") from exc
        return {"task_id": task_id, "deleted": True, "kind": "trend_record"}

    raise RuntimeError("找不到任务记录")


def _normalize_publish_hashtags(value):
    if isinstance(value, str):
        value = re.split(r"[\s,，、#]+", value)
    return [str(item).strip().lstrip("#") for item in (value or []) if str(item).strip()]


def _platform_publish_payload(platform, supplied, legacy):
    """Normalize per-platform metadata while retaining the old publish API."""
    raw = supplied if isinstance(supplied, dict) else {}
    schedule = str(raw.get("schedule") or legacy["schedule"]).strip()
    if schedule not in {"manual_review", "publish_now", "draft"}:
        schedule = "manual_review"

    if platform == "douyin":
        return {
            "title": str(raw.get("title") or legacy["title"]).strip(),
            "description": str(raw.get("description") or legacy["description"]).strip(),
            "hashtags": _normalize_publish_hashtags(raw.get("hashtags", legacy["hashtags"])),
            "schedule": schedule,
        }
    if platform == "channels":
        return {
            "description": str(raw.get("description") or legacy["description"]).strip(),
            "short_title": str(raw.get("short_title") or "").strip(),
            "hashtags": _normalize_publish_hashtags(raw.get("hashtags", legacy["hashtags"])),
            "schedule": schedule,
        }
    if platform == "xiaohongshu":
        return {
            "title": str(raw.get("title") or legacy["title"]).strip(),
            "content": str(raw.get("content") or raw.get("description") or legacy["description"]).strip(),
            "hashtags": _normalize_publish_hashtags(raw.get("hashtags", legacy["hashtags"])),
            "schedule": schedule,
        }
    raise RuntimeError("包含不支持的发布平台")


def _publish_task_metadata(platform, platform_payload, asset_title):
    """Map platform-specific fields to the common task fields used by adapters."""
    if platform == "channels":
        description = platform_payload["description"]
        return {
            "title": platform_payload["short_title"] or description or asset_title,
            "description": description,
            "hashtags": platform_payload["hashtags"],
            "schedule": platform_payload["schedule"],
        }
    if platform == "xiaohongshu":
        return {
            "title": platform_payload["title"] or asset_title,
            "description": platform_payload["content"],
            "hashtags": platform_payload["hashtags"],
            "schedule": platform_payload["schedule"],
        }
    return {
        "title": platform_payload["title"] or asset_title,
        "description": platform_payload["description"],
        "hashtags": platform_payload["hashtags"],
        "schedule": platform_payload["schedule"],
    }


def create_publish_tasks(payload):
    _reconcile_closed_manual_publish_tasks(force=True)
    asset_ids = [str(item).strip() for item in (payload.get("asset_ids") or []) if str(item).strip()]
    platforms = [str(item).strip() for item in (payload.get("platforms") or []) if str(item).strip()]
    assets = {item["asset_id"]: item for item in list_publish_assets()}
    if not asset_ids:
        raise RuntimeError("请至少选择一个成片")
    if not platforms:
        raise RuntimeError("请至少选择一个发布平台")
    missing = [item for item in asset_ids if item not in assets]
    if missing:
        raise RuntimeError("所选成片已不存在，请刷新成片列表")
    unknown = [item for item in platforms if item not in PUBLISH_PLATFORMS]
    if unknown:
        raise RuntimeError("包含不支持的发布平台")
    unavailable = [
        item for item in platforms
        if not _adapter_diagnostics(item).get("ready")
    ]
    if unavailable:
        names = "、".join(PUBLISH_PLATFORMS[item]["name"] for item in unavailable)
        raise RuntimeError(f"{names} 尚未准备好本地发布适配器，请先完成配置或选择其他平台")
    legacy = {
        "title": str(payload.get("title") or "").strip(),
        "description": str(payload.get("description") or "").strip(),
        "hashtags": payload.get("hashtags") or [],
        "schedule": str(payload.get("schedule") or "manual_review").strip(),
    }
    supplied_payloads = payload.get("platform_payloads") or {}
    if not isinstance(supplied_payloads, dict):
        raise RuntimeError("平台发布参数格式不正确")
    platform_payloads = {
        platform: _platform_publish_payload(platform, supplied_payloads.get(platform), legacy)
        for platform in platforms
    }
    if platform_payloads.get("xiaohongshu", {}).get("schedule") != "publish_now" and "xiaohongshu" in platforms:
        raise RuntimeError("小红书当前适配器会直接提交发布，请选择“自动点击发布”后再创建任务")
    now = datetime.now().isoformat(timespec="seconds")
    created = []
    with PUBLISH_TASK_LOCK:
        active_pairs = {
            (task.get("asset_id"), task.get("platform"))
            for task in PUBLISH_TASKS.values()
            if task.get("status") in {"planned", "queued", "running"}
        }
        for asset_id in asset_ids:
            asset = assets[asset_id]
            for platform in platforms:
                if (asset_id, platform) in active_pairs:
                    platform_name = PUBLISH_PLATFORMS[platform]["name"]
                    raise RuntimeError(
                        f"该成片的{platform_name}发布任务仍在启动或运行中。"
                        "请等待该任务结束后重试。"
                    )
                platform_info = PUBLISH_PLATFORMS[platform]
                platform_payload = platform_payloads[platform]
                metadata = _publish_task_metadata(platform, platform_payload, asset["title"])
                task_id = f"publish-{uuid4().hex[:12]}"
                task = {
                    "task_id": task_id,
                    "asset_id": asset_id,
                    "job_id": asset["job_id"],
                    "clip_id": asset["clip_id"],
                    "file": asset["file"],
                    "file_path": asset.get("file_path"),
                    "platform": platform,
                    "platform_name": platform_info["name"],
                    "title": metadata["title"],
                    "description": metadata["description"],
                    "hashtags": metadata["hashtags"],
                    "schedule": metadata["schedule"],
                    "platform_payload": platform_payload,
                    "status": "planned",
                    "message": "已创建发布任务，等待执行",
                    "created_at": now,
                    "updated_at": now,
                }
                PUBLISH_TASKS[task_id] = task
                created.append(task)
                active_pairs.add((asset_id, platform))
        write_json(PUBLISH_TASKS_PATH, PUBLISH_TASKS)
    return created


def list_task_center_jobs():
    """List uploaded video workspaces that are waiting for transcription."""
    items = []
    for path in sorted(JOBS_DIR.glob("*"), reverse=True):
        if not path.is_dir():
            continue
        meta = read_json(path / "metadata.json", {})
        if not meta or not meta.get("entered_task_center"):
            continue
        items.append({
            "job_id": path.name,
            "title": meta.get("title", path.name),
            "created_at": meta.get("created_at"),
            "status": meta.get("status", "uploaded"),
            "duration": meta.get("duration"),
        })
    return items


def clear_library():
    """删除全部历史任务目录并清空内存中的任务状态。"""
    removed = 0
    with JOB_LOCK:
        JOBS.clear()
    with CLIP_TASK_LOCK:
        CLIP_TASKS.clear()
    with PUBLISH_TASK_LOCK:
        PUBLISH_TASKS.clear()
        write_json(PUBLISH_TASKS_PATH, PUBLISH_TASKS)
    if JOBS_DIR.exists():
        for path in list(JOBS_DIR.glob("*")):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed += 1
    if OUTPUTS_DIR.exists():
        for path in list(OUTPUTS_DIR.glob("*")):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
    return {"removed": removed}


def delete_library_job(job_id):
    """Delete one inactive workspace and its project-managed output folder."""
    base_dir = job_dir(job_id)
    if not base_dir.exists() or not base_dir.is_dir():
        raise RuntimeError("找不到要删除的存储任务")

    active_stages = {"queued", "extracting", "transcribing", "paused", "analyzing"}
    if get_job_state(job_id).get("stage") in active_stages:
        raise RuntimeError("任务仍在运行，请先暂停或结束任务后再删除")
    with CLIP_TASK_LOCK:
        running = [task for task in CLIP_TASKS.values() if task.get("job_id") == job_id and task.get("status") in {"queued", "running", "paused"}]
    if running:
        raise RuntimeError("任务仍有进行中的处理，请结束后再删除")

    meta = read_json(base_dir / "metadata.json", {})
    output_folder = str(meta.get("output_folder") or "").strip()
    output_dir = OUTPUTS_DIR / sanitize_output_name(output_folder) if output_folder else None
    shutil.rmtree(base_dir, ignore_errors=True)
    if output_dir and output_dir.exists() and output_dir.is_dir():
        shutil.rmtree(output_dir, ignore_errors=True)

    with JOB_LOCK:
        JOBS.pop(job_id, None)
    with CLIP_TASK_LOCK:
        for task_id, task in list(CLIP_TASKS.items()):
            if task.get("job_id") == job_id:
                CLIP_TASKS.pop(task_id, None)
    with PUBLISH_TASK_LOCK:
        for task_id, task in list(PUBLISH_TASKS.items()):
            if task.get("job_id") == job_id:
                PUBLISH_TASKS.pop(task_id, None)
        write_json(PUBLISH_TASKS_PATH, PUBLISH_TASKS)
    active_path = RUNTIME_DIR / "active_job.json"
    if read_json(active_path, {}).get("job_id") == job_id:
        write_json(active_path, {})
    persist_clip_tasks()
    return {"job_id": job_id, "title": meta.get("title", job_id), "deleted": True}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), fmt % args))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            self.serve_file(STATIC_DIR / "index.html")
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif path.startswith("/static/"):
            static_path = resolve_relative_path(STATIC_DIR, path.removeprefix("/static/"))
            if not static_path:
                self.send_error(403)
                return
            self.serve_file(static_path)
        elif path.startswith("/media/"):
            self.serve_media(path.removeprefix("/media/"))
        elif path.startswith("/media-output/"):
            relative = urllib.parse.unquote(path.removeprefix("/media-output/"))
            target = resolve_relative_path(OUTPUTS_DIR, relative)
            if not target:
                self.send_error(403)
                return
            self.serve_file(target)
        elif path.startswith("/publish-local/"):
            relative = urllib.parse.unquote(path.removeprefix("/publish-local/"))
            target = resolve_relative_path(PUBLISH_LOCAL_ASSETS_DIR, relative)
            if not target:
                self.send_error(403)
                return
            self.serve_file(target)
        elif path == "/api/publish/capabilities":
            json_response(self, {"ok": True, **publish_capabilities()})
        elif path == "/api/publish/assets":
            assets = list_publish_assets()
            json_response(self, {"ok": True, "assets": assets})
        elif path == "/api/publish/tasks":
            tasks = list_publish_tasks()
            json_response(self, {
                "ok": True,
                "tasks": tasks,
                "current": tasks[0] if tasks else None,
            })
        elif path == "/api/publish/login-tasks":
            json_response(self, {"ok": True, "tasks": list_publish_login_tasks()})
        elif path == "/api/job/status":
            job_id = query.get("job_id", [""])[0]
            job = get_job_state(job_id)
            transcript = read_json(job_dir(job_id) / "transcript.json", {"segments": []})
            segments = transcript.get("segments", [])
            if segments:
                job["segment_count"] = len(segments)
                job["latest_segment"] = segments[-1]
                job["transcript_tail"] = segments[-8:]
                job["transcribed_position"] = segments[-1].get("end")
            json_response(self, {"ok": True, "job": job})
        elif path == "/api/library":
            json_response(self, {"ok": True, "items": list_library()})
        elif path == "/api/storage":
            json_response(self, {"ok": True, **storage_summary()})
        elif path == "/api/health":
            json_response(self, {"ok": True, **dependency_health()})
        elif path == "/api/tasks":
            job_id = query.get("job_id", [""])[0] or None
            limit = int(query.get("limit", ["100"])[0] or 100)
            json_response(self, {
                "ok": True,
                "tasks": list_task_center_tasks(job_id=job_id, limit=limit),
                "clip_tasks": list_clip_tasks(job_id=job_id, limit=limit),
                "publish_tasks": [task for task in list_publish_tasks() if not job_id or task.get("job_id") == job_id],
                "jobs": list_task_center_jobs(),
            })
        elif path in {"/api/trends/discover/status", "/api/trends/hotspots/status"}:
            task_id = query.get("task_id", [""])[0]
            task = get_trend_task(task_id)
            if not task:
                error_response(self, "找不到 AI 爆款任务", 404)
                return
            json_response(self, {"ok": True, "task": task})
        elif path == "/api/broll/search/status":
            task_id = query.get("task_id", [""])[0]
            task = get_broll_task(task_id)
            if not task:
                error_response(self, "找不到 B-roll 检索任务", 404)
                return
            json_response(self, {"ok": True, "task": task})
        elif path == "/api/trends/import/status":
            task_id = query.get("task_id", [""])[0]
            task = get_trend_task(task_id)
            if not task:
                error_response(self, "找不到爆款导入任务", 404)
                return
            json_response(self, {"ok": True, "task": task})
        elif path == "/api/trends/search/results":
            search_id = query.get("search_id", [""])[0]
            result = read_json(trend_search_path(search_id), {})
            if not result:
                error_response(self, "找不到搜索结果", 404)
                return
            json_response(self, {"ok": True, **result})
        elif path == "/api/trends/knowledge":
            knowledge = trend_knowledge_store()
            json_response(self, {"ok": True, "entries": knowledge.get("entries", [])})
        elif path == "/api/clips/render-status":
            task_id = query.get("task_id", [""])[0]
            task = get_clip_task(task_id)
            if not task:
                error_response(self, "\u627e\u4e0d\u5230\u751f\u6210\u4efb\u52a1", 404)
                return
            json_response(self, {"ok": True, "task": task})
        elif path == "/api/job/load":
            job_id = query.get("job_id", [""])[0]
            base_dir = job_dir(job_id)
            meta = normalize_browser_preview_meta(base_dir, read_json(base_dir / "metadata.json", {}))
            transcript_source = base_dir / "transcript_grouped.json"
            highlights_source = base_dir / "highlights.json"
            if transcript_source.exists() or highlights_source.exists():
                output_dir = sync_job_output(job_id, include_candidates=highlights_source.exists())
            else:
                output_dir = job_output_dir(job_id, create=False)
            json_response(
                self,
                {
                    "ok": True,
                    "metadata": meta,
                    "transcript": read_json(base_dir / "transcript.json", {"segments": []}),
                    "transcript_grouped": read_json(base_dir / "transcript_grouped.json", {"groups": []}),
                    "transcript_files": {
                        "folder": str(output_dir),
                        "markdown": str(output_dir / "transcript" / "transcript_grouped.md"),
                        "grouped_markdown": str(output_dir / "transcript" / "transcript_grouped.md"),
                    },
                    "highlights": get_highlights(job_id),
                },
            )
        elif path == "/api/providers":
            saved = provider_settings()
            json_response(self, {
                "ok": True,
                "packaged": IS_FROZEN,
                "settings_initialized": (not IS_FROZEN) or PACKAGED_PROFILE_MARKER.exists(),
                "llm": [public_provider(item, "llm") for item in saved.get("llm_providers", [])],
                "volcengine": [public_provider(item, "volcengine") for item in saved.get("volcengine_providers", [])],
                "pexels": [public_provider(item, "pexels") for item in saved.get("pexels_providers", [])],
                "pixabay": [public_provider(item, "pixabay") for item in saved.get("pixabay_providers", [])],
            })
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/video/upload":
                self.handle_upload()
            elif path == "/api/publish/local-assets":
                self.handle_publish_local_asset()
            else:
                payload = self.read_body_json()
                if path == "/api/video/browser-preview":
                    self.handle_browser_preview(payload)
                elif path == "/api/transcribe/range":
                    self.handle_transcription_range(payload)
                elif path == "/api/providers":
                    self.handle_providers(payload)
                elif path == "/api/providers/models":
                    json_response(self, {"ok": True, **fetch_llm_models(payload)})
                elif path == "/api/providers/llm-test":
                    json_response(self, {"ok": True, **test_llm_provider(payload.get("provider_id"))})
                elif path == "/api/providers/material-test":
                    json_response(self, {"ok": True, **test_material_provider(payload.get("provider_id"), payload.get("kind"))})
                elif path == "/api/broll/search":
                    json_response(self, {"ok": True, "task": start_broll_search(payload)})
                elif path == "/api/transcribe/start":
                    self.handle_transcribe_start(payload)
                elif path == "/api/transcribe/control":
                    self.handle_transcribe_control(payload)
                elif path == "/api/highlights/analyze":
                    self.handle_analyze(payload)
                elif path == "/api/clips/render-preview":
                    self.handle_render_preview(payload)
                elif path == "/api/clips/render-cancel":
                    self.handle_render_cancel(payload)
                elif path == "/api/clips/update-time":
                    self.handle_update_time(payload)
                elif path == "/api/clips/manual":
                    self.handle_manual_clip(payload)
                elif path == "/api/clips/confirm":
                    self.handle_confirm(payload)
                elif path == "/api/clips/action":
                    self.handle_clip_action(payload)
                elif path == "/api/clips/export":
                    self.handle_export(payload)
                elif path == "/api/dialog/export-dir":
                    self.handle_pick_export_dir(payload)
                elif path == "/api/dialog/open-path":
                    self.handle_open_path(payload)
                elif path == "/api/dialog/save-transcript":
                    self.handle_save_transcript(payload)
                elif path == "/api/tasks/control":
                    self.handle_task_control(payload)
                elif path == "/api/storage/cleanup":
                    json_response(self, {"ok": True, **cleanup_storage(payload)})
                elif path == "/api/tasks/clear-finished":
                    job_id = payload.get("job_id") or None
                    removed = clear_finished_clip_tasks(job_id)
                    if not job_id:
                        removed += clear_finished_publish_tasks()
                        removed += clear_finished_trend_search_records()
                    json_response(self, {"ok": True, "removed": removed, "tasks": list_task_center_tasks(job_id=job_id)})
                elif path == "/api/tasks/delete":
                    json_response(self, {"ok": True, **delete_task_record(payload.get("task_id"))})
                elif path == "/api/tasks/retry":
                    json_response(self, {"ok": True, "task": retry_clip_task(payload.get("task_id"))})
                elif path == "/api/trends/search":
                    self.handle_trend_search(payload)
                elif path == "/api/trends/people":
                    self.handle_trend_people(payload)
                elif path == "/api/trends/hotspots":
                    self.handle_trend_hotspots(payload)
                elif path == "/api/trends/discover":
                    self.handle_trend_discovery(payload)
                elif path == "/api/trends/knowledge":
                    self.handle_trend_knowledge(payload)
                elif path == "/api/trends/browser/open":
                    json_response(self, {"ok": True, **open_chrome_search(payload)})
                elif path == "/api/trends/import":
                    self.handle_trend_import(payload)
                elif path == "/api/library/delete":
                    json_response(self, {"ok": True, **delete_library_job(payload.get("job_id") or "")})
                elif path == "/api/library/clear-all":
                    json_response(self, {"ok": True, **clear_library()})
                elif path == "/api/publish/tasks":
                    tasks = create_publish_tasks(payload)
                    json_response(self, {"ok": True, "tasks": tasks, "created": len(tasks)})
                elif path == "/api/publish/execute":
                    tasks = execute_publish_tasks(payload.get("task_ids") or [])
                    json_response(self, {"ok": True, "tasks": tasks, "started": len(tasks)})
                elif path == "/api/publish/login":
                    task = start_publish_login(payload.get("platform"), restart=bool(payload.get("restart")))
                    json_response(self, {"ok": True, "task": task})
                elif path == "/api/publish/login/check":
                    task = check_publish_login(payload.get("login_id"))
                    json_response(self, {"ok": True, "task": task})
                else:
                    self.send_error(404)
        except Exception as exc:
            error_response(self, str(exc), 500)

    def read_body_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def serve_file(self, path):
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        size = path.stat().st_size
        range_header = self.headers.get("Range")
        if range_header:
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if match:
                start_text, end_text = match.groups()
                start = int(start_text) if start_text else 0
                end = int(end_text) if end_text else size - 1
                end = min(end, size - 1)
                if start <= end:
                    self.send_response(206)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.send_header("Content-Length", str(end - start + 1))
                    self.end_headers()
                    with path.open("rb") as f:
                        f.seek(start)
                        remaining = end - start + 1
                        try:
                            while remaining > 0:
                                chunk = f.read(min(1024 * 1024, remaining))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                remaining -= len(chunk)
                        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                            return
                    return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if ctype.startswith(("text/html", "text/javascript", "text/css")):
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        try:
            with path.open("rb") as f:
                shutil.copyfileobj(f, self.wfile)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            return

    def serve_media(self, relative):
        path = resolve_relative_path(JOBS_DIR, relative)
        if not path:
            self.send_error(403)
            return
        self.serve_file(path)

    def handle_trend_search(self, payload):
        raw_keywords = payload.get("keywords") or []
        if isinstance(raw_keywords, str):
            raw_keywords = re.split(r"[\s,，、]+", raw_keywords)
        keywords = [str(item).strip() for item in raw_keywords if str(item).strip()]
        limit = max(1, min(50, int(payload.get("limit") or 20)))
        start_at = str(payload.get("start_at") or "").strip()
        end_at = str(payload.get("end_at") or "").strip()
        source = str(payload.get("source") or "web").strip()
        if source.startswith("mediacrawler_"):
            platform = source.removeprefix("mediacrawler_")
            normalized, candidates, errors = search_media_crawler_candidates(keywords, platform, limit, start_at, end_at)
            provider = f"视频素材搜索 · {media_crawler_platform_label(platform)}"
        else:
            normalized, candidates, errors = search_video_candidates(keywords, limit, start_at, end_at)
            provider = "bing_rss"
        search_id = f"trend-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        result = {
            "search_id": search_id,
            "provider": provider,
            "keywords": normalized,
            "start_at": start_at,
            "end_at": end_at,
            "limit": limit,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "candidates": candidates,
            "warnings": errors,
        }
        write_json(trend_search_path(search_id), result)
        json_response(self, {"ok": True, **result})

    def handle_trend_discovery(self, payload):
        if payload.get("async"):
            task = start_trend_discovery(payload)
            json_response(self, {"ok": True, "task": task})
            return
        result = discover_ai_trends(payload)
        json_response(self, {"ok": True, **result})

    def handle_trend_people(self, payload):
        start_at = str(payload.get("start_at") or "").strip()
        end_at = str(payload.get("end_at") or "").strip()
        if start_at and end_at and start_at > end_at:
            raise RuntimeError("开始日期不能晚于结束日期。")
        pool = build_trend_person_pool(start_at, end_at)
        json_response(self, {"ok": True, **pool})

    def handle_trend_hotspots(self, payload):
        start_at = str(payload.get("start_at") or "").strip()
        end_at = str(payload.get("end_at") or "").strip()
        if start_at and end_at and start_at > end_at:
            raise RuntimeError("开始日期不能晚于结束日期。")
        if payload.get("async"):
            task = start_trend_hotspot_pool_build(payload)
            json_response(self, {"ok": True, "task": task})
            return
        pool = build_trend_hotspot_pool(start_at, end_at, provider_id=payload.get("provider_id"))
        json_response(self, {"ok": True, **pool})

    def handle_trend_knowledge(self, payload):
        action = str(payload.get("action") or "save").strip()
        knowledge = trend_knowledge_store()
        entries = knowledge["entries"]
        if action == "delete":
            entry_id = str(payload.get("entry_id") or "").strip()
            before = len(entries)
            entries[:] = [item for item in entries if item.get("entry_id") != entry_id]
            if len(entries) == before:
                error_response(self, "找不到该知识库记录", 404)
                return
            write_json(TREND_KNOWLEDGE_PATH, knowledge)
            json_response(self, {"ok": True, "entries": entries})
            return
        if action == "update":
            entry_id = str(payload.get("entry_id") or "").strip()
            index = next((position for position, item in enumerate(entries) if item.get("entry_id") == entry_id), -1)
            if index < 0:
                error_response(self, "找不到该知识库记录", 404)
                return
            structured = structure_trend_knowledge(payload.get("note"), payload.get("provider_id"))
            existing = entries[index]
            updated_at = datetime.now().isoformat(timespec="seconds")
            structured.update({
                "entry_id": entry_id,
                "created_at": existing.get("created_at") or updated_at,
                "updated_at": updated_at,
            })
            entries[index] = structured
            knowledge["updated_at"] = updated_at
            write_json(TREND_KNOWLEDGE_PATH, knowledge)
            json_response(self, {"ok": True, "entry": structured, "entries": entries})
            return
        if action != "save":
            error_response(self, "未知知识库操作", 400)
            return
        structured = structure_trend_knowledge(payload.get("note"), payload.get("provider_id"))
        structured.update({
            "entry_id": f"taste-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        entries.append(structured)
        knowledge["updated_at"] = structured["created_at"]
        write_json(TREND_KNOWLEDGE_PATH, knowledge)
        json_response(self, {"ok": True, "entry": structured, "entries": entries})

    def handle_trend_import(self, payload):
        search_id = str(payload.get("search_id") or "").strip()
        result = read_json(trend_search_path(search_id), {})
        if not result:
            error_response(self, "搜索结果已不存在，请重新搜索", 404)
            return
        requested = set(str(item) for item in (payload.get("candidate_ids") or []))
        candidates = [item for item in result.get("candidates", []) if item.get("candidate_id") in requested]
        if not candidates:
            error_response(self, "请至少选择一个视频")
            return

        tasks = []
        for candidate in candidates:
            task_id = f"trend-import-{uuid4().hex[:12]}"
            task = set_trend_task(
                task_id,
                status="queued",
                stage="queued",
                progress=0,
                message="等待下载",
                title=candidate.get("title") or "爆款视频",
                candidate_id=candidate.get("candidate_id"),
                search_id=search_id,
                url=candidate.get("url"),
            )
            tasks.append(task)
            threading.Thread(target=trend_import_worker, args=(task_id, candidate), daemon=True).start()
        json_response(self, {"ok": True, "tasks": tasks})

    def handle_upload(self):
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
        item = form["file"] if "file" in form else None
        if item is None or not item.filename:
            error_response(self, "没有收到 MP4/MOV 文件", 400)
            return
        ext = Path(item.filename).suffix.lower()
        if ext not in {".mp4", ".mov"}:
            error_response(self, "MVP 版支持 MP4 / MOV 文件", 400)
            return
        with UPLOAD_LOCK:
            task_title = unique_task_title(item.filename)
            job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{sanitize_name(task_title)}-{uuid4().hex[:8]}"
            base_dir = job_dir(job_id)
            base_dir.mkdir(parents=True, exist_ok=False)
            source = base_dir / f"source{ext}"
            with source.open("wb") as f:
                shutil.copyfileobj(item.file, f)
            meta = {
                "job_id": job_id,
                "title": task_title,
                "output_title": task_title,
                "output_folder": task_title,
                "source_filename": item.filename,
                "original_file": f"source{ext}",
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source_size": source.stat().st_size,
                "status": "uploaded",
                "entered_task_center": True,
            }
            meta.update(probe_video(source))
            duration = float(meta.get("duration") or 0)
            if duration > 0:
                meta["transcription_range"] = {"start": 0, "end": round(duration, 3), "duration": round(duration, 3)}
            write_json(base_dir / "metadata.json", meta)
        preview_queued = should_make_browser_preview(ext, meta)
        message = "\u6e90\u89c6\u9891\u5df2\u4fdd\u5b58\uff0c\u6b63\u5728\u751f\u6210\u6d4f\u89c8\u5668\u517c\u5bb9\u9884\u89c8" if preview_queued else "\u6e90\u89c6\u9891\u5df2\u4fdd\u5b58\uff0c\u53ef\u5f00\u59cb\u8f6c\u5199"
        set_job(job_id, stage="uploaded", message=message, metadata=meta, progress=0)
        if preview_queued:
            threading.Thread(target=browser_preview_worker, args=(job_id,), daemon=True).start()
        json_response(
            self,
            {
                "ok": True,
                "job_id": job_id,
                "metadata": meta,
                "preview_url": f"/media/{job_id}/source{ext}",
                "browser_preview_queued": preview_queued,
            },
        )

    def handle_publish_local_asset(self):
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
        item = form["file"] if "file" in form else None
        try:
            asset = import_publish_local_asset(item)
            json_response(self, {"ok": True, "asset": asset})
        except RuntimeError as exc:
            error_response(self, str(exc), 400)

    def handle_browser_preview(self, payload):
        job_id = payload.get("job_id")
        if not job_id:
            raise RuntimeError("\u7f3a\u5c11 job_id")
        base_dir = job_dir(job_id)
        meta = normalize_browser_preview_meta(base_dir, read_json(base_dir / "metadata.json", {}))
        if meta.get("browser_preview_file"):
            json_response(self, {"ok": True, "url": f"/media/{job_id}/{meta['browser_preview_file']}", "metadata": meta})
            return
        set_job(job_id, stage="previewing", message="\u6b63\u5728\u751f\u6210\u6d4f\u89c8\u5668\u517c\u5bb9\u9884\u89c8 MP4", metadata=meta, progress=0)
        threading.Thread(target=browser_preview_worker, args=(job_id,), daemon=True).start()
        json_response(self, {"ok": True, "queued": True})

    def handle_transcription_range(self, payload):
        job_id = payload.get("job_id")
        if not job_id:
            raise RuntimeError("缺少 job_id")
        base_dir = job_dir(job_id)
        meta_path = base_dir / "metadata.json"
        meta = read_json(meta_path, {})
        if not meta:
            raise RuntimeError("任务不存在")
        source = base_dir / meta.get("original_file", "source.mp4")
        source_probe = probe_video(source)
        if not source_probe.get("probe_error"):
            meta.pop("probe_error", None)
            meta.update(source_probe)
        start = round(float(payload.get("start", 0)), 3)
        end = round(float(payload.get("end", 0)), 3)
        duration = float(meta.get("duration") or 0)
        if duration:
            start = max(0, min(start, duration))
            end = max(0, min(end, duration))
        if end <= start:
            raise RuntimeError("结束时间必须大于开始时间")
        meta["transcription_range"] = {"start": start, "end": end, "duration": round(end - start, 3)}
        meta["status"] = "ready_to_transcribe"
        meta["entered_task_center"] = True
        write_json(meta_path, meta)
        job = set_job(job_id, stage="ready", message="转写范围已保存，可开始转写", metadata=meta, transcription_range=meta["transcription_range"])
        json_response(self, {"ok": True, "job": job, "metadata": meta, "range": meta["transcription_range"]})

    def handle_transcribe_start(self, payload):
        job_id = payload.get("job_id")
        if not job_id:
            raise RuntimeError("\u7f3a\u5c11 job_id")
        state = get_job_state(job_id)
        if state.get("stage") in ("extracting", "transcribing", "paused"):
            task = get_clip_task(state.get("transcribe_task_id")) if state.get("transcribe_task_id") else None
            json_response(self, {"ok": True, "job": state, "task": task})
            return
        engine = payload.get("transcribe_engine") or state.get("transcribe_engine") or "volcengine_bigmodel"
        meta_path = job_dir(job_id) / "metadata.json"
        meta = read_json(meta_path, {})
        source = job_dir(job_id) / meta.get("original_file", "source.mp4")
        source_probe = probe_video(source)
        if not source_probe.get("probe_error"):
            meta.pop("probe_error", None)
            meta.update(source_probe)
        if meta.get("has_audio") is False:
            write_json(meta_path, meta)
            raise RuntimeError("当前视频不含音轨，无法进行语音转写。请上传已合并音频的视频文件。")
        transcription_range = meta.get("transcription_range") or {}
        if float(transcription_range.get("end", 0) or 0) <= float(transcription_range.get("start", 0) or 0):
            raise RuntimeError("请先在原视频轨道中选定范围并点击保存裁剪时间")
        if meta:
            meta["entered_task_center"] = True
            meta["status"] = "queued"
            write_json(meta_path, meta)
        ensure_transcript_output_dir(job_id)
        task_id, task = create_clip_task(job_id, "transcribe", "transcribe")
        task = set_clip_task(
            task_id,
            transcribe_engine="volcengine_bigmodel",
            transcribe_mode="volcengine_bigmodel",
            transcribe_model="volcengine_bigmodel",
            encoder="\u706b\u5c71 BigModel ASR",
            message="火山转写任务已加入队列",
        )
        set_job(
            job_id,
            stage="queued",
            message="火山转写任务已加入队列",
            pause_requested=False,
            stop_requested=False,
            progress=0,
            transcribe_task_id=task_id,
            transcribe_engine="volcengine_bigmodel",
            transcribe_mode="volcengine_bigmodel",
            transcribe_model="volcengine_bigmodel",
            volcengine_audio_url=(payload.get("volcengine_audio_url") or ""),
            transcription_range=transcription_range,
        )
        thread = threading.Thread(target=transcribe_worker, args=(job_id, task_id, payload), daemon=True)
        thread.start()
        json_response(self, {"ok": True, "job": get_job_state(job_id), "task": task})

    def handle_transcribe_control(self, payload):
        job_id = payload.get("job_id")
        action = payload.get("action")
        state = get_job_state(job_id)
        task_id = state.get("transcribe_task_id")
        if action == "pause":
            job = set_job(job_id, pause_requested=True, stage="paused", message="转写暂停请求已生效")
            if task_id:
                set_clip_task(task_id, pause_requested=True, status="paused", message="转写已暂停")
        elif action == "resume":
            job = set_job(job_id, pause_requested=False, stage="transcribing", message="继续转写")
            if task_id:
                set_clip_task(task_id, pause_requested=False, status="running", message="继续转写")
        elif action == "stop":
            job = set_job(job_id, pause_requested=False, stop_requested=True, stage="stopped", message="结束请求已生效，正在中止本地流程")
            if task_id:
                cancel_clip_task(task_id)
                set_clip_task(task_id, pause_requested=False, message="结束请求已生效，正在中止本地流程")
        else:
            raise RuntimeError("未知控制动作")
        json_response(self, {"ok": True, "job": job, "task": get_clip_task(task_id) if task_id else None})

    def handle_analyze(self, payload):
        job_id = payload.get("job_id")
        if not job_id:
            raise RuntimeError("Missing job_id")
        provider = enabled_provider("llm", payload.get("provider_id"))
        if not provider or not provider.get("api_key"):
            raise RuntimeError("请先在供应商管理中添加并启用一个 LLM 配置。")
        # The clips directory appears only when the user has actually started
        # a valid LLM analysis, never while merely uploading or viewing a task.
        (job_output_dir(job_id) / "clips").mkdir(parents=True, exist_ok=True)
        params = {
            "job_id": job_id,
            "target_clip_count": int(payload.get("target_clip_count") or 5),
            "min_seconds": int(payload.get("min_seconds") or 60),
            "max_seconds": int(payload.get("max_seconds") or 90),
        }
        runtime_payload = dict(params)
        runtime_payload["provider_id"] = provider.get("id")
        model_label = (provider.get("model") or provider.get("name") or "LLM").strip()
        task_id, task = create_clip_task(job_id, "analyze", "analyze")
        task = set_clip_task(task_id, params=params, encoder=model_label, message=f"\u5206\u6790\u4efb\u52a1\u5df2\u52a0\u5165\u961f\u5217\uff1a{model_label}")
        set_job(job_id, stage="analyzing", message=f"\u5206\u6790\u4efb\u52a1\u5df2\u52a0\u5165\u961f\u5217\uff1a{model_label}", analyze_task_id=task_id)
        threading.Thread(target=analyze_worker, args=(task_id, job_id, runtime_payload), daemon=True).start()
        json_response(self, {"ok": True, "task": task})

    def handle_task_control(self, payload):
        task_id = payload.get("task_id")
        action = payload.get("action")
        with CLIP_TASK_LOCK:
            task = CLIP_TASKS.get(task_id)
            if not task:
                raise RuntimeError("Task record not found")
            if task.get("type") != "analyze":
                raise RuntimeError("This control is only available for DeepSeek analysis")
            if task.get("status") not in {"queued", "running", "paused"}:
                raise RuntimeError("Analysis task is no longer active")
            if action == "pause":
                task["pause_requested"] = True
            elif action == "resume":
                task["pause_requested"] = False
            elif action == "stop":
                task["cancel_requested"] = True
                task["pause_requested"] = False
            else:
                raise RuntimeError("Unknown task control action")
        if action == "pause":
            task = set_clip_task(task_id, status="paused", message="Pause requested; any in-flight DeepSeek response will wait before it is saved")
        elif action == "resume":
            task = set_clip_task(task_id, status="running", message="DeepSeek analysis resumed")
        else:
            task = set_clip_task(task_id, message="Stopping DeepSeek analysis; any in-flight response will be discarded")
        json_response(self, {"ok": True, "task": task})

    def handle_providers(self, payload):
        kind = payload.get("kind")
        if kind not in PROVIDER_COLLECTIONS:
            raise RuntimeError("未知供应商类型")
        saved = provider_settings()
        collection_key = provider_collection_key(kind)
        providers = saved.setdefault(collection_key, [])
        action = payload.get("action") or "save"
        provider_id_value = (payload.get("id") or "").strip()
        existing = next((item for item in providers if item.get("id") == provider_id_value), None)

        if action == "delete":
            if not existing:
                raise RuntimeError("供应商配置不存在")
            providers.remove(existing)
        elif action == "toggle":
            if not existing:
                raise RuntimeError("供应商配置不存在")
            should_enable = bool(payload.get("enabled"))
            if should_enable:
                for item in providers:
                    item["enabled"] = False
            existing["enabled"] = should_enable
        elif action == "save":
            is_new = existing is None
            provider = existing if existing is not None else {"id": provider_id()}
            name = (payload.get("name") or "").strip()[:80]
            api_key = (payload.get("api_key") or "").strip()
            if not name:
                raise RuntimeError("供应商名称不能为空。")
            if is_new and not api_key:
                raise RuntimeError("API Key 不能为空。")
            provider["name"] = name
            if api_key:
                provider["api_key"] = api_key
            if kind == "llm":
                protocol = (payload.get("protocol") or "openai").strip().lower()
                base_url = normalize_llm_base_url(payload.get("base_url"))
                model = (payload.get("model") or "").strip()
                if protocol not in {"openai", "anthropic"}:
                    raise RuntimeError("仅支持 OpenAI 兼容或 Anthropic Messages 协议。")
                if not base_url or not model:
                    raise RuntimeError("LLM 的接口 URL 和模型不能为空。")
                provider.update({"protocol": protocol, "base_url": base_url, "model": model})
            elif kind == "volcengine":
                provider.update({
                    "resource_id": (payload.get("resource_id") or "volc.seedasr.auc").strip(),
                    "audio_url": (payload.get("audio_url") or "").strip(),
                    "poll_interval": max(2, min(30, float(payload.get("poll_interval") or 5))),
                    "tos_endpoint": (payload.get("tos_endpoint") or "").strip().replace("https://", "").replace("http://", "").strip("/"),
                    "tos_region": (payload.get("tos_region") or "").strip(),
                    "tos_bucket": (payload.get("tos_bucket") or "").strip(),
                    "tos_prefix": (payload.get("tos_prefix") or "mp4-golden-asr").strip().strip("/"),
                    "tos_url_expires": max(60, min(7 * 24 * 3600, int(float(payload.get("tos_url_expires") or 86400)))),
                })
                tos_access_key = (payload.get("tos_access_key") or "").strip()
                if tos_access_key:
                    provider["tos_access_key"] = tos_access_key
                tos_secret_key = (payload.get("tos_secret_key") or "").strip()
                if tos_secret_key:
                    provider["tos_secret_key"] = tos_secret_key
            else:
                result_limit = int(float(payload.get("result_limit") or 12))
                provider.update({"result_limit": max(1, min(30, result_limit))})
            provider["enabled"] = bool(payload.get("enabled"))
            if provider["enabled"]:
                for item in providers:
                    if item is not provider:
                        item["enabled"] = False
            if is_new:
                providers.append(provider)
        else:
            raise RuntimeError("未知供应商操作")

        write_json(SETTINGS_PATH, saved)
        json_response(self, {
            "ok": True,
            "packaged": IS_FROZEN,
            "settings_initialized": (not IS_FROZEN) or PACKAGED_PROFILE_MARKER.exists(),
            "llm": [public_provider(item, "llm") for item in saved.get("llm_providers", [])],
            "volcengine": [public_provider(item, "volcengine") for item in saved.get("volcengine_providers", [])],
            "pexels": [public_provider(item, "pexels") for item in saved.get("pexels_providers", [])],
            "pixabay": [public_provider(item, "pixabay") for item in saved.get("pixabay_providers", [])],
        })

    def handle_render_preview(self, payload):
        job_id = payload.get("job_id")
        clip_id = payload.get("clip_id")
        if not job_id or not clip_id:
            raise RuntimeError("\u7f3a\u5c11 job_id \u6216 clip_id")
        task_id, task = create_clip_task(job_id, clip_id, "preview")
        threading.Thread(target=clip_render_worker, args=(task_id, job_id, clip_id), daemon=True).start()
        json_response(self, {"ok": True, "task": task})

    def handle_render_cancel(self, payload):
        task_id = payload.get("task_id")
        task = cancel_clip_task(task_id)
        if not task:
            raise RuntimeError("\u627e\u4e0d\u5230\u751f\u6210\u4efb\u52a1")
        json_response(self, {"ok": True, "task": task})

    def handle_update_time(self, payload):
        job_id = payload.get("job_id")
        clip_id = payload.get("clip_id")
        highlights = get_highlights(job_id)
        clip = next((c for c in highlights.get("clips", []) if c.get("id") == clip_id), None)
        if not clip:
            raise RuntimeError("片段不存在")
        remove_clip_output_folder(job_id, clip)
        clip.setdefault("original_start", clip.get("start"))
        clip.setdefault("original_end", clip.get("end"))
        clip["start"] = round(float(payload.get("start")), 3)
        clip["end"] = round(float(payload.get("end")), 3)
        clip["status"] = "needs_render"
        clip["preview_file"] = None
        clip["export_file"] = None
        clip["export_path"] = None
        clip["export_quality"] = None
        clip["export_verification"] = None
        save_highlights(job_id, highlights)
        # Keep the new time-range folder's analysis available immediately.
        # The final video remains absent until the user explicitly exports it.
        sync_job_output(job_id, include_candidates=True, prune_clip_folders=True)
        json_response(self, {"ok": True, "clip": clip})

    def handle_manual_clip(self, payload):
        raise RuntimeError("原视频裁剪只用于保存转写范围，候选片段只能由 LLM 分析生成。")
        job_id = payload.get("job_id")
        if not job_id:
            raise RuntimeError("缺少 job_id")
        start = round(float(payload.get("start", 0)), 3)
        end = round(float(payload.get("end", 0)), 3)
        if end <= start:
            raise RuntimeError("结束时间必须大于开始时间")
        meta = read_json(job_dir(job_id) / "metadata.json", {})
        duration = float(meta.get("duration") or 0)
        if duration:
            start = max(0, min(start, duration))
            end = max(0, min(end, duration))
        if end <= start:
            raise RuntimeError("剪切范围超出视频时长")
        highlights = get_highlights(job_id)
        clips = highlights.setdefault("clips", [])
        used = {c.get("id") for c in clips}
        index = len(clips) + 1
        clip_id = f"clip_{index:03d}"
        while clip_id in used:
            index += 1
            clip_id = f"clip_{index:03d}"
        title = (payload.get("title") or f"手动剪切 {index}").strip()[:80]
        clip = {
            "id": clip_id,
            "title": title,
            "quote": title,
            "reason": "用户在原视频中手动选择的剪切范围。",
            "start": start,
            "end": end,
            "original_start": start,
            "original_end": end,
            "clip_type": "manual_trim",
            "confidence": 1,
            "status": "needs_render",
            "preview_file": None,
            "export_file": None,
            "confirmed": False,
        }
        clips.append(clip)
        save_highlights(job_id, highlights)
        json_response(self, {"ok": True, "clip": clip, "highlights": highlights})

    def handle_confirm(self, payload):
        job_id = payload.get("job_id")
        clip_id = payload.get("clip_id")
        highlights = get_highlights(job_id)
        clip = next((c for c in highlights.get("clips", []) if c.get("id") == clip_id), None)
        if not clip:
            raise RuntimeError("片段不存在")
        clip["confirmed"] = bool(payload.get("confirmed"))
        clip["status"] = "confirmed" if clip["confirmed"] else "ready"
        save_highlights(job_id, highlights)
        json_response(self, {"ok": True, "clip": clip})



    def handle_clip_action(self, payload):
        job_id = payload.get("job_id")
        action = payload.get("action")
        clip_id = payload.get("clip_id")
        base_dir = job_dir(job_id)
        highlights = get_highlights(job_id)
        clips = highlights.get("clips", [])
        if action == "clear_all":
            highlights["clips"] = []
            save_highlights(job_id, highlights)
            json_response(self, {"ok": True, "highlights": highlights})
            return
        clip = next((c for c in clips if c.get("id") == clip_id), None)
        if not clip:
            raise RuntimeError("片段不存在")
        if action == "delete":
            clips.remove(clip)
            highlights["clips"] = clips
            save_highlights(job_id, highlights)
            json_response(self, {"ok": True, "highlights": highlights})
            return
        if action == "reset_time":
            remove_clip_output_folder(job_id, clip)
            clip["start"] = round(float(clip.get("original_start", clip.get("start", 0))), 3)
            clip["end"] = round(float(clip.get("original_end", clip.get("end", 0))), 3)
            clip["status"] = "needs_render"
            clip["preview_file"] = None
            clip["export_file"] = None
            clip["export_path"] = None
            clip["export_quality"] = None
            clip["export_verification"] = None
        elif action == "clear_preview":
            remove_job_relative_file(base_dir, clip.get("preview_file"))
            clip["preview_file"] = None
            if clip.get("status") == "ready":
                clip["status"] = "needs_render"
        elif action == "clear_export":
            remove_clip_output_video(job_id, clip)
            clip["export_file"] = None
            clip["export_path"] = None
            clip["export_quality"] = None
            if clip.get("status") == "exported":
                clip["status"] = "confirmed" if clip.get("confirmed") else "ready"
        else:
            raise RuntimeError("未知片段操作")
        save_highlights(job_id, highlights)
        json_response(self, {"ok": True, "clip": clip, "highlights": highlights})
    def handle_pick_export_dir(self, payload):
        initial = (payload.get("initial_dir") or "").strip()
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            kwargs = {"title": "选择金句视频导出文件夹"}
            if initial and Path(initial).exists():
                kwargs["initialdir"] = initial
            selected = filedialog.askdirectory(**kwargs)
            root.destroy()
            if not selected:
                json_response(self, {"ok": True, "selected": False, "path": ""})
                return
            json_response(self, {"ok": True, "selected": True, "path": selected})
        except Exception as exc:
            json_response(self, {"ok": False, "error": f"无法打开文件夹选择窗口：{exc}"}, 500)
    def handle_open_path(self, payload):
        job_id = payload.get("job_id")
        if not job_id:
            raise RuntimeError("Missing job_id")
        base_dir = job_dir(job_id)
        clip_id = (payload.get("clip_id") or "").strip()
        if clip_id:
            clip = next((item for item in get_highlights(job_id).get("clips", []) if item.get("id") == clip_id), None)
            export_path = clip.get("export_path") if clip else None
            if not export_path:
                raise RuntimeError("该候选片段尚未导出")
            target = Path(str(export_path))
            if not target.is_absolute():
                target = (base_dir / target).resolve()
            output_dir = target if target.is_dir() else target.parent
        else:
            output_dir = job_output_dir(job_id)
        if not output_dir.exists():
            raise RuntimeError("Task folder not found")
        if os.name == "nt":
            os.startfile(str(output_dir))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(output_dir)])
        else:
            subprocess.Popen(["xdg-open", str(output_dir)])
        json_response(self, {"ok": True, "folder": str(output_dir)})

    def handle_save_transcript(self, payload):
        job_id = payload.get("job_id")
        if not job_id:
            raise RuntimeError("Missing job_id")
        source = job_output_dir(job_id) / "transcript" / "transcript_grouped.md"
        if not source.exists():
            base_dir = job_dir(job_id)
            transcript = read_json(base_dir / "transcript.json", {"segments": []})
            save_transcript_files(base_dir, transcript.get("segments", []))
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            target = filedialog.asksaveasfilename(
                title="Save transcript",
                initialfile="transcript_grouped.md",
                defaultextension=".md",
                filetypes=[("Markdown transcript", "*.md"), ("Text file", "*.txt")],
            )
            root.destroy()
        except Exception as exc:
            raise RuntimeError(f"Unable to open save dialog: {exc}")
        if not target:
            json_response(self, {"ok": True, "saved": False, "path": ""})
            return
        target_path = Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target_path)
        json_response(self, {"ok": True, "saved": True, "path": str(target_path)})

    def handle_export(self, payload):
        job_id = payload.get("job_id")
        clip_ids = payload.get("clip_ids") or []
        export_dir = (payload.get("export_dir") or "").strip()
        if not job_id:
            raise RuntimeError("\u7f3a\u5c11 job_id")
        if not clip_ids:
            highlights = get_highlights(job_id)
            clip_ids = [c["id"] for c in highlights.get("clips", []) if c.get("confirmed")]
        task_id, _task = create_clip_task(job_id, "export", "export")
        task = set_clip_task(task_id, clip_ids=clip_ids, export_dir=export_dir, message="\u5bfc\u51fa\u4efb\u52a1\u5df2\u52a0\u5165\u961f\u5217")
        threading.Thread(target=clip_export_worker, args=(task_id, job_id, clip_ids, export_dir), daemon=True).start()
        json_response(self, {"ok": True, "task": task})


def main():
    ensure_dirs()
    remember_public_proxy_candidate()
    loaded_tasks = load_clip_tasks()
    loaded_publish_tasks = load_publish_tasks()
    loaded_publish_login_tasks = load_publish_login_tasks()
    os.chdir(ROOT)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MP4 金句片段筛选导出工作台已启动：http://{HOST}:{PORT}，已恢复 {loaded_tasks} 条处理任务、{loaded_publish_tasks} 条发布任务记录、{loaded_publish_login_tasks} 条登录准备记录")
    server.serve_forever()


if __name__ == "__main__":
    main()
