import cgi
import html
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree


# 本工具为本地直连服务，只访问火山/DeepSeek 公网 API。
# 若用户系统设置了代理（如 Clash 127.0.0.1:7890）但代理软件未运行，
# requests/urllib 会走代理导致连接失败（WinError 10061）。这里统一禁用代理。
for _proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
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
MEDIA_CRAWLER_DIR = ROOT / "vendor" / "MediaCrawler"
MEDIA_CRAWLER_VENV_DIR = MEDIA_CRAWLER_DIR / ".venv"
SETTINGS_PATH = ROOT / "user-settings.json"
FROZEN_SETTINGS_MARKER = ROOT / ".settings-initialized-v2"
TASKS_PATH = RUNTIME_DIR / "tasks.json"
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





def ensure_dirs():
    for path in (STATIC_DIR, JOBS_DIR, OUTPUTS_DIR, RUNTIME_DIR, TRENDS_DIR):
        path.mkdir(parents=True, exist_ok=True)
    initialize_frozen_settings()


def initialize_frozen_settings():
    """Start packaged builds with a clean, private settings store.

    A development ``user-settings.json`` must never be carried into an exe.
    The marker is created only in the per-user APPDATA directory, so settings
    entered by the user in the packaged app remain available on later starts.
    """
    if not IS_FROZEN or FROZEN_SETTINGS_MARKER.exists():
        return
    # Do not migrate or copy any settings from the bundled application files.
    # A one-time reset also handles an APPDATA file left by an older build that
    # had already exposed the development provider list in the packaged UI.
    write_json(SETTINGS_PATH, {})
    FROZEN_SETTINGS_MARKER.parent.mkdir(parents=True, exist_ok=True)
    FROZEN_SETTINGS_MARKER.write_text("2\n", encoding="utf-8")


def json_response(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


_NO_PROXY_OPENER = None


def http_opener():
    """返回不读取系统/环境变量代理的 urllib opener，保证直连火山/DeepSeek。"""
    global _NO_PROXY_OPENER
    if _NO_PROXY_OPENER is None:
        _NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _NO_PROXY_OPENER


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


def trend_download_dir(task_id):
    safe = re.sub(r"[^0-9A-Za-z_-]", "", str(task_id or ""))
    target = TRENDS_DIR / "downloads" / safe
    target.mkdir(parents=True, exist_ok=True)
    return target


def set_trend_task(task_id, **changes):
    with TREND_TASK_LOCK:
        task = TREND_TASKS.setdefault(task_id, {"task_id": task_id, "created_at": datetime.now().isoformat(timespec="seconds")})
        task.update(changes)
        task["updated_at"] = datetime.now().isoformat(timespec="seconds")
        return dict(task)


def get_trend_task(task_id):
    with TREND_TASK_LOCK:
        return dict(TREND_TASKS.get(task_id, {}))


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


def parse_result_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{10}(?:\.\d+)?", text):
        try:
            return datetime.fromtimestamp(float(text)).date()
        except (OSError, OverflowError, ValueError):
            return None
    if re.fullmatch(r"\d{13}", text):
        try:
            return datetime.fromtimestamp(int(text) / 1000).date()
        except (OSError, OverflowError, ValueError):
            return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


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
        with http_opener().open(request, timeout=18) as response:
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


def search_media_crawler_candidates(keywords, platform, limit, start_at="", end_at=""):
    if not MEDIA_CRAWLER_DIR.is_dir() or not (MEDIA_CRAWLER_DIR / "main.py").exists():
        raise RuntimeError("MediaCrawler 源码目录不存在")
    python_executable = media_crawler_python_path()
    if not python_executable:
        raise RuntimeError("MediaCrawler 依赖尚未安装，请先完成 vendor/MediaCrawler 的 .venv 初始化")

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
        python_executable, "main.py",
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
    try:
        process = subprocess.run(
            command,
            cwd=MEDIA_CRAWLER_DIR,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=MEDIA_CRAWLER_TIMEOUT,
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
    seen = set()
    for item in raw_items:
        keyword = str(first_present(item, "source_keyword") or normalized[0])
        candidate = normalize_media_crawler_candidate(item, platform, keyword)
        if not candidate["url"] or candidate["url"] in seen:
            continue
        if not in_selected_date_range(candidate["published_at"], start_at, end_at):
            continue
        seen.add(candidate["url"])
        candidate["candidate_id"] = f"candidate-{len(candidates) + 1:03d}-{uuid4().hex[:6]}"
        candidate["status"] = "ready"
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    candidates.sort(key=lambda item: item["heat_score"], reverse=True)
    warnings = []
    if not candidates:
        if raw_items:
            warnings.append(
                f"MediaCrawler 已获取 {len(raw_items)} 条 {media_crawler_platform_label(platform)} 结果，但没有视频发布时间落在 {start_at or '不限'} 至 {end_at or '不限'}；请扩大时间范围或选择‘不限时间’。"
            )
        else:
            warnings.append("MediaCrawler 已运行，但平台没有返回可用视频结果；请确认关键词、登录状态和网络连接。")
    return normalized, candidates, warnings


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
    package_root = ROOT.parent / ".tools" / "yt-dlp"
    if package_root.is_dir():
        current = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(part for part in (str(package_root), current) if part)
    return environment


def ytdlp_command():
    """Prefer the bundled Python package over the relocated Windows shim."""
    package_root = ROOT.parent / ".tools" / "yt-dlp"
    python_executable = media_crawler_python_path()
    if package_root.is_dir() and python_executable:
        return [python_executable, "-m", "yt_dlp"]
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
        ROOT.parent / ".tools" / "yt-dlp" / "bin" / "yt-dlp.exe",
        ROOT.parent / ".tools" / "yt-dlp" / "bin" / "yt-dlp",
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
    output_template = str(target_dir / "source.%(ext)s")
    command = [
        *runner,
        "--no-playlist",
        "--newline",
        "--no-warnings",
        "--restrict-filenames",
        "--merge-output-format", "mp4",
        "--remux-video", "mp4",
        "-o", output_template,
        candidate["url"],
    ]
    run_ytdlp_process(command, task_id)
    files = [path for path in target_dir.iterdir() if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}]
    if not files:
        raise RuntimeError("下载器没有产出可识别的视频文件")
    source = max(files, key=lambda path: path.stat().st_mtime)
    if source.suffix.lower() == ".mp4":
        return source

    target = target_dir / "source.mp4"
    run_process([
        ffmpeg_path(), "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(target),
    ])
    return target


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
        payload["api_key"] = (read_json(SETTINGS_PATH, {}).get("deepseek_api_key") or "").strip()
        payload["save_key"] = False
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


def mask_secret(value):
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 10:
        return value[:3] + "..."
    return f"{value[:6]}...{value[-4:]}"


def provider_settings():
    """Load provider records and migrate the old single-key settings without losing them."""
    saved = read_json(SETTINGS_PATH, {})
    changed = False
    llms = saved.get("llm_providers")
    volcengines = saved.get("volcengine_providers")
    if not isinstance(llms, list):
        llms = []
        old_key = (saved.get("deepseek_api_key") or "").strip()
        if old_key:
            llms.append({
                "id": provider_id(), "name": "DeepSeek", "api_key": old_key,
                "base_url": "https://api.deepseek.com/chat/completions",
                "protocol": "openai", "model": "deepseek-v4-flash", "enabled": True,
            })
        saved["llm_providers"] = llms
        changed = True
    if not isinstance(volcengines, list):
        volcengines = []
        old_key = (saved.get("volcengine_api_key") or "").strip()
        if old_key:
            volcengines.append({
                "id": provider_id(), "name": "火山语音转写", "api_key": old_key,
                "resource_id": saved.get("volcengine_resource_id", "volc.seedasr.auc"),
                "audio_url": saved.get("volcengine_audio_url", ""),
                "poll_interval": saved.get("volcengine_poll_interval", 5),
                "tos_access_key": saved.get("tos_access_key", ""),
                "tos_secret_key": saved.get("tos_secret_key", ""),
                "tos_endpoint": saved.get("tos_endpoint", ""),
                "tos_region": saved.get("tos_region", ""),
                "tos_bucket": saved.get("tos_bucket", ""),
                "tos_prefix": saved.get("tos_prefix", "mp4-golden-asr"),
                "tos_url_expires": saved.get("tos_url_expires", 86400),
                "enabled": True,
            })
        saved["volcengine_providers"] = volcengines
        changed = True
    if changed:
        write_json(SETTINGS_PATH, saved)
    return saved


def enabled_provider(kind, preferred_id=None):
    saved = provider_settings()
    key = "llm_providers" if kind == "llm" else "volcengine_providers"
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
        item.pop("audio_url", None)
        item.pop("tos_access_key", None)
        item.pop("tos_secret_key", None)
        item["has_tos_access_key"] = bool(provider.get("tos_access_key"))
        item["has_tos_secret"] = bool(provider.get("tos_secret_key"))
    return item


def volcengine_settings(payload=None):
    payload = payload or {}
    provider = enabled_provider("volcengine", payload.get("provider_id")) or {}
    return {
        "api_key": (payload.get("volcengine_api_key") or provider.get("api_key") or os.environ.get("VOLCENGINE_API_KEY") or "").strip(),
        "resource_id": (payload.get("volcengine_resource_id") or provider.get("resource_id") or os.environ.get("VOLCENGINE_RESOURCE_ID") or "volc.seedasr.auc").strip(),
        "audio_url": (payload.get("volcengine_audio_url") or os.environ.get("VOLCENGINE_AUDIO_URL") or "").strip(),
        "poll_interval": float(os.environ.get("VOLCENGINE_POLL_INTERVAL") or 5),
    }


def tos_settings(payload=None):
    payload = payload or {}
    provider = enabled_provider("volcengine", payload.get("provider_id")) or {}
    return {
        "access_key": (payload.get("tos_access_key") or provider.get("tos_access_key") or os.environ.get("TOS_ACCESS_KEY") or "").strip(),
        "secret_key": (payload.get("tos_secret_key") or provider.get("tos_secret_key") or os.environ.get("TOS_SECRET_KEY") or "").strip(),
        "endpoint": (payload.get("tos_endpoint") or provider.get("tos_endpoint") or os.environ.get("TOS_ENDPOINT") or "").strip(),
        "region": (payload.get("tos_region") or provider.get("tos_region") or os.environ.get("TOS_REGION") or "").strip(),
        "bucket": (payload.get("tos_bucket") or provider.get("tos_bucket") or os.environ.get("TOS_BUCKET") or "").strip(),
        "prefix": (payload.get("tos_prefix") or provider.get("tos_prefix") or os.environ.get("TOS_PREFIX") or "mp4-golden-asr").strip().strip("/"),
        "url_expires": int(float(os.environ.get("TOS_URL_EXPIRES") or 86400)),
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

    target_count = int(payload.get("target_clip_count") or 20)
    min_seconds = int(payload.get("min_seconds") or 8)
    max_seconds = int(payload.get("max_seconds") or 45)
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
    protocol = (provider.get("protocol") or "openai").strip().lower()
    base_url = (provider.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError(f"LLM 配置“{provider_name}”缺少接口 URL。")
    system_prompt = "Return valid JSON only. No Markdown, no explanation outside JSON."
    if protocol == "anthropic":
        endpoint = base_url if base_url.endswith("/v1/messages") else base_url + "/v1/messages"
        body = {
            "model": model,
            "max_tokens": 8192,
            "temperature": 0.15,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        endpoint = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            "temperature": 0.15,
        }
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with http_opener().open(req, timeout=330) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{provider_name} 请求失败: {exc.code} {detail}")

    if task_id:
        wait_for_clip_task_resume(task_id)
    if protocol == "anthropic":
        content = "".join(part.get("text", "") for part in result.get("content", []) if part.get("type") == "text").strip()
    else:
        content = result["choices"][0]["message"]["content"].strip()
    if not content:
        raise RuntimeError(f"{provider_name} 未返回可解析的文本内容。")
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S).strip()
    highlights = json.loads(content)
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
        elif path.startswith("/static/"):
            static_path = resolve_relative_path(STATIC_DIR, path.removeprefix("/static/"))
            if not static_path:
                self.send_error(403)
                return
            self.serve_file(static_path)
        elif path.startswith("/media/"):
            self.serve_media(path.removeprefix("/media/"))
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
            limit = int(query.get("limit", ["30"])[0] or 30)
            json_response(self, {
                "ok": True,
                "tasks": list_clip_tasks(job_id=job_id, limit=limit),
                "jobs": list_task_center_jobs(),
            })
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
        elif path == "/api/settings":
            saved = read_json(SETTINGS_PATH, {})
            key = saved.get("deepseek_api_key", "")
            volc_key = saved.get("volcengine_api_key", "")
            masked = f"{key[:6]}...{key[-4:]}" if len(key) > 12 else ""
            volc_masked = f"{volc_key[:6]}...{volc_key[-4:]}" if len(volc_key) > 12 else (volc_key[:4] + "..." if volc_key else "")
            json_response(self, {
                "ok": True,
                "has_key": bool(key),
                "masked_key": masked,
                "volcengine": {
                    "has_token": bool(volc_key),
                    "masked_token": volc_masked,
                    "has_api_key": bool(volc_key),
                    "masked_api_key": volc_masked,
                    "resource_id": saved.get("volcengine_resource_id", "volc.seedasr.auc"),
                    "audio_url": saved.get("volcengine_audio_url", ""),
                    "poll_interval": saved.get("volcengine_poll_interval", 5),
                },
                "tos": {
                    "has_secret": bool(saved.get("tos_secret_key")),
                    "access_key": saved.get("tos_access_key", ""),
                    "endpoint": saved.get("tos_endpoint", ""),
                    "region": saved.get("tos_region", ""),
                    "bucket": saved.get("tos_bucket", ""),
                    "prefix": saved.get("tos_prefix", "mp4-golden-asr"),
                    "url_expires": saved.get("tos_url_expires", 86400),
                },
            })
        elif path == "/api/providers":
            saved = provider_settings()
            json_response(self, {
                "ok": True,
                "packaged": IS_FROZEN,
                "settings_initialized": (not IS_FROZEN) or FROZEN_SETTINGS_MARKER.exists(),
                "llm": [public_provider(item, "llm") for item in saved.get("llm_providers", [])],
                "volcengine": [public_provider(item, "volcengine") for item in saved.get("volcengine_providers", [])],
            })
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/video/upload":
                self.handle_upload()
            else:
                payload = self.read_body_json()
                if path == "/api/video/browser-preview":
                    self.handle_browser_preview(payload)
                elif path == "/api/transcribe/range":
                    self.handle_transcription_range(payload)
                elif path == "/api/settings":
                    self.handle_save_settings(payload)
                elif path == "/api/providers":
                    self.handle_providers(payload)
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
                    json_response(self, {"ok": True, "removed": clear_finished_clip_tasks(payload.get("job_id") or None), "tasks": list_clip_tasks(job_id=payload.get("job_id") or None)})
                elif path == "/api/tasks/retry":
                    json_response(self, {"ok": True, "task": retry_clip_task(payload.get("task_id"))})
                elif path == "/api/trends/search":
                    self.handle_trend_search(payload)
                elif path == "/api/trends/import":
                    self.handle_trend_import(payload)
                elif path == "/api/library/delete":
                    json_response(self, {"ok": True, **delete_library_job(payload.get("job_id") or "")})
                elif path == "/api/library/clear-all":
                    json_response(self, {"ok": True, **clear_library()})
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
            provider = f"MediaCrawler · {media_crawler_platform_label(platform)}"
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
            "target_clip_count": int(payload.get("target_clip_count") or 20),
            "min_seconds": int(payload.get("min_seconds") or 8),
            "max_seconds": int(payload.get("max_seconds") or 45),
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
        if kind not in {"llm", "volcengine"}:
            raise RuntimeError("未知供应商类型")
        saved = provider_settings()
        collection_key = "llm_providers" if kind == "llm" else "volcengine_providers"
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
                base_url = (payload.get("base_url") or "").strip().rstrip("/")
                model = (payload.get("model") or "").strip()
                if protocol not in {"openai", "anthropic"}:
                    raise RuntimeError("仅支持 OpenAI 兼容或 Anthropic Messages 协议。")
                if not base_url or not model:
                    raise RuntimeError("LLM 的接口 URL 和模型不能为空。")
                provider.update({"protocol": protocol, "base_url": base_url, "model": model})
            else:
                provider.update({
                    "resource_id": (payload.get("resource_id") or "volc.seedasr.auc").strip(),
                    "poll_interval": 5,
                    "tos_endpoint": (payload.get("tos_endpoint") or "").strip().replace("https://", "").replace("http://", "").strip("/"),
                    "tos_region": (payload.get("tos_region") or "").strip(),
                    "tos_bucket": (payload.get("tos_bucket") or "").strip(),
                    "tos_prefix": (payload.get("tos_prefix") or "mp4-golden-asr").strip().strip("/"),
                    "tos_url_expires": 86400,
                })
                provider.pop("audio_url", None)
                tos_access_key = (payload.get("tos_access_key") or "").strip()
                if tos_access_key:
                    provider["tos_access_key"] = tos_access_key
                tos_secret_key = (payload.get("tos_secret_key") or "").strip()
                if tos_secret_key:
                    provider["tos_secret_key"] = tos_secret_key
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
            "settings_initialized": (not IS_FROZEN) or FROZEN_SETTINGS_MARKER.exists(),
            "llm": [public_provider(item, "llm") for item in saved.get("llm_providers", [])],
            "volcengine": [public_provider(item, "volcengine") for item in saved.get("volcengine_providers", [])],
        })

    def handle_save_settings(self, payload):
        """Save or clear DeepSeek, Volcengine BigModel ASR, and TOS settings."""
        saved = read_json(SETTINGS_PATH, {})
        action = payload.get("action")
        if action == "clear":
            saved.pop("deepseek_api_key", None)
            write_json(SETTINGS_PATH, saved)
            json_response(self, {"ok": True, "cleared": "deepseek"})
            return
        if action == "clear_volcengine":
            for key in ["volcengine_api_key", "volcengine_resource_id", "volcengine_appid", "volcengine_token", "volcengine_cluster", "volcengine_audio_url", "volcengine_poll_interval"]:
                saved.pop(key, None)
            write_json(SETTINGS_PATH, saved)
            json_response(self, {"ok": True, "cleared": "volcengine"})
            return
        if action == "clear_tos":
            for key in ["tos_access_key", "tos_secret_key", "tos_endpoint", "tos_region", "tos_bucket", "tos_prefix", "tos_url_expires"]:
                saved.pop(key, None)
            write_json(SETTINGS_PATH, saved)
            json_response(self, {"ok": True, "cleared": "tos"})
            return
        if "api_key" in payload and payload.get("settings_type") != "volcengine":
            key = (payload.get("api_key") or "").strip()
            if not key:
                json_response(self, {"ok": False, "error": "Key 不能为空"}, 400)
                return
            saved["deepseek_api_key"] = key
            write_json(SETTINGS_PATH, saved)
            masked = f"{key[:6]}...{key[-4:]}" if len(key) > 12 else key[:6] + "..."
            json_response(self, {"ok": True, "masked_key": masked})
            return
        if payload.get("settings_type") == "tos":
            access_key = (payload.get("tos_access_key") or "").strip()
            secret_key = (payload.get("tos_secret_key") or saved.get("tos_secret_key") or "").strip()
            endpoint = (payload.get("tos_endpoint") or "").strip().replace("https://", "").replace("http://", "").strip("/")
            region = (payload.get("tos_region") or "").strip()
            bucket = (payload.get("tos_bucket") or "").strip()
            prefix = (payload.get("tos_prefix") or "mp4-golden-asr").strip().strip("/")
            url_expires = int(float(payload.get("tos_url_expires") or 86400))
            if not access_key or not secret_key or not endpoint or not region or not bucket:
                json_response(self, {"ok": False, "error": "TOS AK、SK、Endpoint、Region、Bucket 都不能为空。"}, 400)
                return
            saved.update({
                "tos_access_key": access_key,
                "tos_secret_key": secret_key,
                "tos_endpoint": endpoint,
                "tos_region": region,
                "tos_bucket": bucket,
                "tos_prefix": prefix or "mp4-golden-asr",
                "tos_url_expires": max(60, min(7 * 24 * 3600, url_expires)),
            })
            write_json(SETTINGS_PATH, saved)
            json_response(self, {"ok": True, "bucket": bucket, "endpoint": endpoint})
            return
        if payload.get("settings_type") == "volcengine":
            api_key = (payload.get("volcengine_api_key") or saved.get("volcengine_api_key") or "").strip()
            resource_id = (payload.get("volcengine_resource_id") or "volc.seedasr.auc").strip()
            audio_url = (payload.get("volcengine_audio_url") or "").strip()
            poll_interval = float(payload.get("volcengine_poll_interval") or 5)
            if not api_key:
                json_response(self, {"ok": False, "error": "火山 API Key 不能为空。"}, 400)
                return
            saved.update({
                "volcengine_api_key": api_key,
                "volcengine_resource_id": resource_id or "volc.seedasr.auc",
                "volcengine_audio_url": audio_url,
                "volcengine_poll_interval": max(2, min(30, poll_interval)),
            })
            write_json(SETTINGS_PATH, saved)
            masked = f"{api_key[:6]}...{api_key[-4:]}" if len(api_key) > 12 else api_key[:4] + "..."
            json_response(self, {"ok": True, "masked_token": masked, "masked_api_key": masked})
            return
        json_response(self, {"ok": False, "error": "未知设置类型"}, 400)

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
    loaded_tasks = load_clip_tasks()
    os.chdir(ROOT)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MP4 金句片段筛选导出工作台已启动：http://{HOST}:{PORT}，已恢复 {loaded_tasks} 条任务记录")
    server.serve_forever()


if __name__ == "__main__":
    main()
