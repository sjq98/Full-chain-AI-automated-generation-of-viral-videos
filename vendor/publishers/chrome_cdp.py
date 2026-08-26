"""Utilities for launching a visible installed Chrome with a CDP endpoint."""

from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def _available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class ReusedChromeProcess:
    """Small Popen-compatible handle for an already-running shared Chrome."""

    def __init__(self, pid=None):
        self.pid = pid

    def poll(self):
        return None

    def terminate(self):
        return None


def _normalized_url(value):
    return str(value or "").strip().rstrip("/")


def _live_pages(context):
    pages = []
    for page in context.pages:
        try:
            if not page.is_closed():
                pages.append(page)
        except Exception:
            continue
    return pages


def _page_host(page):
    try:
        return urlsplit(str(page.url or "")).netloc.lower()
    except Exception:
        return ""


def page_matches_url(page, target_url):
    """Whether a live page already points to the requested URL."""
    try:
        return _normalized_url(page.url) == _normalized_url(target_url)
    except Exception:
        return False


def reusable_page(context, target_url):
    """Find a suitable existing page without adding another browser tab."""
    pages = _live_pages(context)
    for page in pages:
        if page_matches_url(page, target_url):
            return page
    target_host = urlsplit(str(target_url or "")).netloc.lower()
    if target_host:
        for page in pages:
            if _page_host(page) == target_host:
                return page
    for page in pages:
        if _normalized_url(page.url) in {"", "about:blank", "chrome://newtab"}:
            return page
    return None


def reuse_or_create_page(context, target_url):
    """Reuse a tab for the target host, or create one only as a last resort.

    A freshly started Chrome exposes its DevTools endpoint slightly before its
    first normal tab is reported to Playwright.  Waiting briefly here avoids a
    race where a second ``about:blank`` tab is created beside the URL Chrome
    was already opening.
    """
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        page = reusable_page(context, target_url)
        if page is not None:
            return page
        time.sleep(0.1)
    return context.new_page()


async def reuse_or_create_page_async(context, target_url):
    """Async Playwright counterpart of :func:`reuse_or_create_page`."""
    return reusable_page(context, target_url) or await context.new_page()


def close_duplicate_pages(context, keep_page):
    """Close tabs that duplicate the exact URL of the page being kept."""
    target_url = getattr(keep_page, "url", "")
    if not _normalized_url(target_url):
        return 0
    closed = 0
    for page in _live_pages(context):
        if page is keep_page or not page_matches_url(page, target_url):
            continue
        try:
            page.close()
            closed += 1
        except Exception:
            pass
    return closed


def close_blank_pages(context, keep_page):
    """Remove disposable blank tabs while preserving the active platform page."""
    closed = 0
    for page in _live_pages(context):
        if page is keep_page or _normalized_url(page.url) not in {"", "about:blank", "chrome://newtab"}:
            continue
        try:
            page.close()
            closed += 1
        except Exception:
            pass
    return closed


def close_pages_for_host(context, keep_page, target_url):
    """Keep one platform tab and close other live tabs on that same host."""
    target_host = urlsplit(str(target_url or "")).netloc.lower()
    if not target_host:
        return 0
    closed = 0
    for page in _live_pages(context):
        if page is keep_page or _page_host(page) != target_host:
            continue
        try:
            page.close()
            closed += 1
        except Exception:
            pass
    return closed


async def close_duplicate_pages_async(context, keep_page):
    """Async Playwright counterpart of :func:`close_duplicate_pages`."""
    target_url = getattr(keep_page, "url", "")
    if not _normalized_url(target_url):
        return 0
    closed = 0
    for page in _live_pages(context):
        if page is keep_page or not page_matches_url(page, target_url):
            continue
        try:
            await page.close()
            closed += 1
        except Exception:
            pass
    return closed


async def close_blank_pages_async(context, keep_page):
    """Async Playwright counterpart of :func:`close_blank_pages`."""
    closed = 0
    for page in _live_pages(context):
        if page is keep_page or _normalized_url(page.url) not in {"", "about:blank", "chrome://newtab"}:
            continue
        try:
            await page.close()
            closed += 1
        except Exception:
            pass
    return closed


async def close_pages_for_host_async(context, keep_page, target_url):
    """Async counterpart for keeping exactly one tab for a platform host."""
    target_host = urlsplit(str(target_url or "")).netloc.lower()
    if not target_host:
        return 0
    closed = 0
    for page in _live_pages(context):
        if page is keep_page or _page_host(page) != target_host:
            continue
        try:
            await page.close()
            closed += 1
        except Exception:
            pass
    return closed


def _cdp_details(endpoint):
    try:
        with urllib.request.urlopen(f"{endpoint}/json/version", timeout=1) as response:
            details = json.loads(response.read().decode("utf-8"))
        return details if details.get("webSocketDebuggerUrl") else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def active_page_urls(profile_dir):
    """Return page URLs for a live shared Chrome profile, without launching it."""
    profile_root = Path(profile_dir).expanduser()
    active_session = _active_session(profile_root)
    if active_session:
        endpoint = active_session[0]
    else:
        endpoint = _profile_debug_endpoint(profile_root)
    if not endpoint:
        return None
    try:
        with urllib.request.urlopen(f"{endpoint}/json/list", timeout=1) as response:
            targets = json.loads(response.read().decode("utf-8"))
        return [
            str(target.get("url") or "")
            for target in targets
            if isinstance(target, dict) and target.get("type") == "page"
        ]
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _session_file(profile_root):
    return profile_root / "cdp-session.json"


def _active_session(profile_root):
    try:
        payload = json.loads(_session_file(profile_root).read_text(encoding="utf-8"))
        endpoint = str(payload.get("endpoint") or "").rstrip("/")
    except (OSError, TypeError, ValueError):
        return None
    if endpoint and _cdp_details(endpoint):
        return endpoint, int(payload.get("pid") or 0)
    try:
        _session_file(profile_root).unlink()
    except OSError:
        pass
    return None


def _profile_debug_endpoint(profile_root):
    """Recover an active Chrome endpoint when the session marker is stale."""
    try:
        lines = (profile_root / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
        port = int(lines[0].strip())
    except (OSError, ValueError, IndexError):
        return None
    endpoint = f"http://127.0.0.1:{port}"
    return endpoint if _cdp_details(endpoint) else None


def _save_session(profile_root, endpoint, process):
    target = _session_file(profile_root)
    temporary = target.with_suffix(".tmp")
    payload = {
        "endpoint": endpoint,
        "pid": process.pid,
        "updated_at": int(time.time()),
    }
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(target)


def _debug_port_pid(endpoint):
    """Resolve the real Chrome process that owns the CDP port on Windows."""
    if os.name != "nt":
        return 0
    try:
        port = urlsplit(endpoint).port
        if not port:
            return 0
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
        )
        for line in completed.stdout.splitlines():
            fields = line.split()
            if len(fields) < 5 or fields[0].upper() != "TCP":
                continue
            local = fields[1].rsplit(":", 1)
            if len(local) != 2 or local[1] != str(port) or fields[3].upper() != "LISTENING":
                continue
            try:
                return int(fields[4])
            except ValueError:
                return 0
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0
    return 0


def _chrome_process_family(pid):
    """Return the browser PID plus its descendants that can own Chrome windows."""
    if os.name != "nt" or not pid:
        return {int(pid)} if pid else set()
    try:
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        invalid = ctypes.c_void_p(-1).value
        if snapshot in (0, invalid):
            return {int(pid)}
        parents = {}
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while has_entry:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)

        family = {int(pid)}
        parent = parents.get(int(pid))
        while parent and parent not in family:
            family.add(parent)
            parent = parents.get(parent)
        changed = True
        while changed:
            changed = False
            for child, parent in parents.items():
                if parent in family and child not in family:
                    family.add(child)
                    changed = True
        return family
    except Exception:
        return {int(pid)}


def _focus_chrome_window(pid, timeout=5):
    """Restore a Chrome window and bring an off-screen one back to the desktop."""
    if os.name != "nt" or not pid:
        return False
    try:
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        screen_left = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        screen_top = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        screen_width = max(1, user32.GetSystemMetrics(78) or user32.GetSystemMetrics(0))
        screen_height = max(1, user32.GetSystemMetrics(79) or user32.GetSystemMetrics(1))
        deadline = time.monotonic() + max(0.5, float(timeout))

        while time.monotonic() < deadline:
            found = []
            candidate_pids = _chrome_process_family(pid)

            @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
            def visit(hwnd, _lparam):
                owner_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
                if owner_pid.value not in candidate_pids:
                    return True
                class_name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_name, len(class_name))
                if not class_name.value.startswith("Chrome_WidgetWin"):
                    return True
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                width = rect.right - rect.left
                height = rect.bottom - rect.top
                # Ignore Chrome's message-only helpers and operate on the frame.
                if width < 300 or height < 200:
                    return True
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                width = min(max(width, 900), max(900, screen_width - 120))
                height = min(max(height, 650), max(650, screen_height - 100))
                left = rect.left
                top = rect.top
                if (
                    rect.right <= screen_left + 40
                    or rect.left >= screen_left + screen_width - 40
                    or rect.bottom <= screen_top + 40
                    or rect.top >= screen_top + screen_height - 40
                ):
                    left = screen_left + 60
                    top = screen_top + 40
                else:
                    left = max(screen_left, min(left, screen_left + screen_width - width))
                    top = max(screen_top, min(top, screen_top + screen_height - height))
                user32.SetWindowPos(
                    hwnd, 0, left, top, width, height,
                    0x0040,  # SWP_SHOWWINDOW
                )
                user32.ShowWindow(hwnd, 5)  # SW_SHOW
                user32.BringWindowToTop(hwnd)
                user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
                user32.SetForegroundWindow(hwnd)
                found.append(hwnd)
                return True

            user32.EnumWindows(visit, 0)
            if found:
                return True
            time.sleep(0.1)
        return False
    except Exception:
        return False


def start_visible_chrome(executable, profile_dir, initial_url="about:blank", timeout=30):
    """Start or reuse a normal visible Chrome session and return its CDP endpoint."""
    chrome = Path(str(executable or "")).expanduser()
    if not chrome.is_file():
        raise RuntimeError("未找到可执行的 Google Chrome")
    profile_root = Path(profile_dir).expanduser()
    profile_root.mkdir(parents=True, exist_ok=True)
    active_session = _active_session(profile_root)
    if active_session:
        endpoint, pid = active_session
        pid = _debug_port_pid(endpoint) or pid
        _focus_chrome_window(pid)
        return ReusedChromeProcess(pid), endpoint
    active_endpoint = _profile_debug_endpoint(profile_root)
    if active_endpoint:
        pid = _debug_port_pid(active_endpoint)
        _save_session(profile_root, active_endpoint, ReusedChromeProcess(pid))
        _focus_chrome_window(pid)
        return ReusedChromeProcess(pid), active_endpoint

    # A stable profile makes all publisher subprocesses attach to the same
    # user-visible Chrome window instead of launching a new browser per task.
    # Keep the command close to a normal headed Chrome launch. There is no
    # proxy, sandbox override, GPU workaround, or hidden browser fallback.
    profile = profile_root
    port = _available_port()
    command = [
        str(chrome),
        "--window-position=60,40",
        "--window-size=1280,800",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "--remote-allow-origins=*",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
    ]
    if initial_url:
        command.append(str(initial_url))
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    endpoint = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + max(3, int(timeout))
    last_error = None
    launcher_exit_code = None
    while time.monotonic() < deadline:
        # Windows Chrome can hand off to a child process and exit the original
        # launcher immediately. The DevTools endpoint, not the launcher PID,
        # is the authoritative signal that the visible browser is ready.
        if process.poll() is not None:
            launcher_exit_code = process.returncode
        try:
            details = _cdp_details(endpoint)
            if details:
                real_pid = _debug_port_pid(endpoint) or process.pid
                _save_session(profile_root, endpoint, ReusedChromeProcess(real_pid))
                _focus_chrome_window(real_pid, timeout=5)
                return process, endpoint
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(0.25)
    try:
        process.terminate()
    except OSError:
        pass
    detail = f"，启动器退出码 {launcher_exit_code}" if launcher_exit_code is not None else ""
    raise RuntimeError(f"Google Chrome 未能启动 CDP 调试连接{detail}：{last_error or '超时'}")


def restore_storage_state(context, state_file):
    """Restore saved Playwright cookies into an existing CDP browser context."""
    path = Path(state_file)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cookies = payload.get("cookies") or []
        if cookies:
            context.add_cookies(cookies)
        return bool(cookies)
    except (OSError, TypeError, ValueError):
        return False


async def restore_storage_state_async(context, state_file):
    """Async counterpart for Playwright's async API."""
    path = Path(state_file)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cookies = payload.get("cookies") or []
        if cookies:
            await context.add_cookies(cookies)
        return bool(cookies)
    except (OSError, TypeError, ValueError):
        return False
