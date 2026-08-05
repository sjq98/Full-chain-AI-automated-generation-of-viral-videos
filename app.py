import cgi
import json
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


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
JOBS_DIR = DATA_DIR / "jobs"
RUNTIME_DIR = DATA_DIR / "runtime"
SETTINGS_PATH = ROOT / "user-settings.json"
TASKS_PATH = RUNTIME_DIR / "tasks.json"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8767"))

JOB_LOCK = threading.Lock()
JOBS = {}
CLIP_TASK_LOCK = threading.Lock()
CLIP_TASKS = {}
TASK_PERSIST_LAST = 0.0
TASK_PERSIST_MIN_INTERVAL = 0.75





def ensure_dirs():
    for path in (STATIC_DIR, JOBS_DIR, RUNTIME_DIR):
        path.mkdir(parents=True, exist_ok=True)


def json_response(handler, payload, status=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


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


def job_dir(job_id):
    safe = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]", "", job_id)
    return JOBS_DIR / safe


def seconds_to_clock(seconds):
    seconds = max(0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def clip_filename(index, title, start, end):
    safe_title = sanitize_name(title)[:32]
    return f"{index:03d}_{safe_title}_{seconds_to_clock(start).replace(':', '-')}_to_{seconds_to_clock(end).replace(':', '-')}.mp4"


def ffmpeg_path():
    bundled = ROOT / "bin" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_path():
    bundled = ROOT / "bin" / "ffprobe.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("ffprobe") or "ffprobe"


def run_process(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"命令执行失败：{' '.join(cmd)}")
    return proc.stdout



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
        return {"probe_error": str(exc)}

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
        current.update(updates)
        if current.get("transcribe_started_at"):
            current["transcribe_elapsed"] = max(0, time.time() - float(current["transcribe_started_at"]))
        current["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(RUNTIME_DIR / "active_job.json", current)
        return dict(current)


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
    lines = [f"[{seconds_to_clock(s['start'])} - {seconds_to_clock(s['end'])}] {s['text']}" for s in segments]
    (base_dir / "transcript.md").write_text("\n".join(lines), encoding="utf-8")
    grouped_lines = [f"[{seconds_to_clock(g['start'])} - {seconds_to_clock(g['end'])}] {g['text']}" for g in groups]
    (base_dir / "transcript_grouped.md").write_text("\n\n".join(grouped_lines), encoding="utf-8")


def volcengine_settings(payload=None):
    saved = read_json(SETTINGS_PATH, {})
    payload = payload or {}
    return {
        "api_key": (payload.get("volcengine_api_key") or saved.get("volcengine_api_key") or os.environ.get("VOLCENGINE_API_KEY") or "").strip(),
        "resource_id": (payload.get("volcengine_resource_id") or saved.get("volcengine_resource_id") or os.environ.get("VOLCENGINE_RESOURCE_ID") or "volc.seedasr.auc").strip(),
        "audio_url": (payload.get("volcengine_audio_url") or saved.get("volcengine_audio_url") or os.environ.get("VOLCENGINE_AUDIO_URL") or "").strip(),
        "poll_interval": float(payload.get("volcengine_poll_interval") or saved.get("volcengine_poll_interval") or os.environ.get("VOLCENGINE_POLL_INTERVAL") or 5),
    }


def tos_settings(payload=None):
    saved = read_json(SETTINGS_PATH, {})
    payload = payload or {}
    return {
        "access_key": (payload.get("tos_access_key") or saved.get("tos_access_key") or os.environ.get("TOS_ACCESS_KEY") or "").strip(),
        "secret_key": (payload.get("tos_secret_key") or saved.get("tos_secret_key") or os.environ.get("TOS_SECRET_KEY") or "").strip(),
        "endpoint": (payload.get("tos_endpoint") or saved.get("tos_endpoint") or os.environ.get("TOS_ENDPOINT") or "").strip(),
        "region": (payload.get("tos_region") or saved.get("tos_region") or os.environ.get("TOS_REGION") or "").strip(),
        "bucket": (payload.get("tos_bucket") or saved.get("tos_bucket") or os.environ.get("TOS_BUCKET") or "").strip(),
        "prefix": (payload.get("tos_prefix") or saved.get("tos_prefix") or os.environ.get("TOS_PREFIX") or "mp4-golden-asr").strip().strip("/"),
        "url_expires": int(float(payload.get("tos_url_expires") or saved.get("tos_url_expires") or os.environ.get("TOS_URL_EXPIRES") or 86400)),
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


def volcengine_bigmodel_request(url, body, api_key, resource_id, request_id, timeout=30):
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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return {"body": json.loads(raw or "{}"), "headers": headers, "http_status": resp.status}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        headers = {k.lower(): v for k, v in exc.headers.items()}
        message = headers.get("x-api-message") or detail or exc.reason
        raise RuntimeError(f"\u706b\u5c71 BigModel \u8bf7\u6c42\u5931\u8d25 HTTP {exc.code}: {message}")


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

    try:
        settings = volcengine_settings(volc_payload)
        tos_cfg = tos_settings(volc_payload)
        if not settings.get("api_key"):
            raise RuntimeError("火山 ASR 未配置：请填写 API Key。")

        set_job(job_id, stage="extracting", message="正在提取音频，准备提交火山 BigModel 识别", progress=0.05, transcribe_started_at=started)
        update_task(status="running", progress=0.03, message="正在提取本地音频", encoder="火山 BigModel ASR")
        run_process([ffmpeg_path(), "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(audio)])
        if not audio.exists() or audio.stat().st_size == 0:
            raise RuntimeError("音频提取失败：audio.wav 没有生成。")

        audio_url = settings.get("audio_url")
        tos_upload = None
        if not audio_url:
            set_job(job_id, stage="transcribing", message="正在上传 audio.wav 到 TOS 并生成火山可访问 URL", progress=0.10, transcribe_model="volcengine_bigmodel")
            update_task(status="running", progress=0.10, message="正在上传 audio.wav 到 TOS", encoder="TOS + 火山 BigModel ASR")
            tos_upload = tos_upload_audio(audio, job_id, tos_cfg)
            audio_url = tos_upload["audio_url"]
            write_json(base_dir / "tos_audio_upload.json", {**tos_upload, "uploaded_at": datetime.now().isoformat(timespec="seconds")})

        request_id = str(uuid4())
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
        submit_result = volcengine_bigmodel_request(submit_url, submit_body, settings["api_key"], settings["resource_id"], request_id)
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
            state = get_job_state(job_id)
            if state.get("stop_requested") or clip_task_cancelled(task_id):
                raise RuntimeError("已结束转写；火山云端任务可能仍在处理。")
            query_result = volcengine_bigmodel_request(query_url, {}, settings["api_key"], settings["resource_id"], request_id)
            code, message = volcengine_status(query_result)
            progress = min(0.92, 0.22 + poll_index * 0.01)
            if code == "20000000":
                break
            if code in {"20000001", "20000002", ""}:
                status_text = "排队中" if code == "20000002" else "识别中"
                set_job(job_id, stage="transcribing", message=f"火山{status_text}，已轮询 {poll_index} 次", progress=progress, transcribe_elapsed=max(0, time.time() - started))
                update_task(status="running", progress=progress, message=f"火山{status_text}，已轮询 {poll_index} 次", remaining=None)
                time.sleep(poll_interval)
                continue
            raise RuntimeError(f"火山 query 失败：{code} {message or query_result.get('body')}")
        else:
            raise RuntimeError("火山识别超时：轮询超过 30 分钟仍未完成。")

        result_body = (query_result or {}).get("body", {})
        segments = volcengine_extract_segments(result_body)
        if len(segments) == 1 and segments[0].get("end", 0) <= segments[0].get("start", 0) and meta.get("duration"):
            segments[0]["end"] = round(float(meta.get("duration") or 0), 3)
        transcript = {"segments": segments, "engine": "volcengine_bigmodel", "volcengine_task_id": request_id}
        write_json(base_dir / "transcript.json", transcript)
        write_json(base_dir / "transcript_grouped.json", {"groups": group_transcript_segments(segments)})
        write_json(base_dir / "volcengine_asr_result.json", query_result or {})

        meta["status"] = "transcribed"
        meta["transcribe_engine"] = "volcengine_bigmodel"
        write_json(base_dir / "metadata.json", meta)
        final_message = f"火山转写完成，共 {len(segments)} 段" if segments else "火山转写完成，但没有返回可用分段"
        set_job(job_id, stage="transcribed", message=final_message, progress=1, segment_count=len(segments), transcribe_elapsed=max(0, time.time() - started), transcript_tail=segments[-8:] if segments else [])
        update_task(status="done", progress=1, remaining=0, message=final_message, segment_count=len(segments), transcript_file="transcript.json")
    except Exception as exc:
        set_job(job_id, stage="error", message=str(exc), error=str(exc), transcribe_elapsed=max(0, time.time() - started))
        update_task(status="error", progress=0, remaining=0, message=str(exc), error=str(exc))


def transcribe_worker(job_id, task_id=None, payload=None):
    payload = payload or {}
    return volcengine_transcribe_worker(job_id, task_id, payload)

def deepseek_analyze(job_id, payload):
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

    key = (payload.get("api_key") or read_json(SETTINGS_PATH, {}).get("deepseek_api_key") or "").strip()
    if not key:
        raise RuntimeError("Please enter a DeepSeek API Key first")
    if payload.get("save_key"):
        write_json(SETTINGS_PATH, {"deepseek_api_key": key})

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
- Keep title, quote, reason, hook_text, cover_text, and editor_note in Simplified Chinese.
- quote should be the most powerful sentence or compact core idea, not the whole transcript block.
- reason should explain why an editor should keep it.
- hook_text should be usable as the first-screen subtitle or short-video opening text.
- cover_text should be short enough for a video cover.
- editor_note should mention boundary/context advice briefly.

JSON schema:
{{
  "clips": [
    {{
      "id": "clip_001",
      "title": "short Chinese title",
      "quote": "best golden sentence or core idea in Chinese",
      "reason": "why this clip is worth keeping, in Chinese",
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
    body = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": "Return valid JSON only. No Markdown, no explanation outside JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.15,
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek request failed: {exc.code} {detail}")

    content = result["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S).strip()
    (base_dir / "analysis.raw.txt").write_text(content, encoding="utf-8")
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
    md = "\n\n".join(
        f"## {i}. {c.get('title', c['id'])}\n\n- Time: {seconds_to_clock(c['start'])} - {seconds_to_clock(c['end'])}\n- Quote: {c.get('quote', '')}\n- Reason: {c.get('reason', '')}"
        for i, c in enumerate(clips, start=1)
    )
    (base_dir / "analysis.md").write_text(md, encoding="utf-8")
    return highlights


def analyze_worker(task_id, job_id, payload):
    started = time.time()
    try:
        grouped = read_json(job_dir(job_id) / "transcript_grouped.json", {})
        raw = read_json(job_dir(job_id) / "transcript.json", {})
        unit_count = len(grouped.get("groups", [])) or len(raw.get("segments", []))
        set_clip_task(task_id, status="running", progress=0.05, elapsed=0, message=f"\u6b63\u5728\u6574\u7406\u6587\u5b57\u7a3f\u4e0a\u4e0b\u6587\uff08{unit_count} \u4e2a\u5355\u5143\uff09", encoder="DeepSeek")
        set_job(job_id, stage="analyzing", message="DeepSeek \u5206\u6790\u5df2\u5f00\u59cb", analyze_task_id=task_id)
        if clip_task_cancelled(task_id):
            raise RuntimeError("Analysis task cancelled")
        set_clip_task(task_id, status="running", progress=0.20, elapsed=max(0, time.time() - started), message="\u6b63\u5728\u8bf7\u6c42 DeepSeek \u7b5b\u9009\u91d1\u53e5\u7247\u6bb5")
        highlights = deepseek_analyze(job_id, payload)
        if clip_task_cancelled(task_id):
            raise RuntimeError("Analysis task cancelled")
        count = len(highlights.get("clips", []))
        set_job(job_id, stage="analyzed", message=f"Found {count} candidate clips", analyze_task_id=task_id)
        set_clip_task(task_id, status="done", progress=1, remaining=0, elapsed=max(0, time.time() - started), message=f"\u5206\u6790\u5b8c\u6210\uff0c\u627e\u5230 {count} \u4e2a\u5019\u9009\u7247\u6bb5", highlights=highlights)
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

    if export and export_dir:
        folder = Path(str(export_dir)).expanduser()
    else:
        folder = base_dir / "clips" / ("exports" if export else "preview")
    folder.mkdir(parents=True, exist_ok=True)
    index = clips.index(clip) + 1

    if export:
        # Final clips preserve the original video/audio streams. No re-encoding.
        name = clip_export_filename(index, clip.get("title") or clip_id, start, end, source)
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
    key = read_json(SETTINGS_PATH, {}).get("deepseek_api_key", "")
    deepseek = {"ok": bool(key), "has_key": bool(key), "message": "DeepSeek Key saved" if key else "DeepSeek Key not saved"}
    checks.extend([
        {"id": "ffmpeg", "label": "FFmpeg", "ok": bool(ffmpeg.get("ok")), **ffmpeg},
        {"id": "ffprobe", "label": "FFprobe", "ok": bool(ffprobe.get("ok")), **ffprobe},
        {"id": "encoder", "label": "Preview encoder", "ok": True, "message": encoder.get("label"), "hardware": encoder.get("hardware"), "name": encoder.get("name")},
        {"id": "deepseek", "label": "DeepSeek Key", **deepseek},
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
        size = path_size(path)
        total += size
        items.append({
            "job_id": path.name,
            "title": meta.get("title", path.name),
            "created_at": meta.get("created_at"),
            "total_size": size,
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
    return {"deleted": deleted, "storage": storage_summary()}
def list_library():
    items = []
    for path in sorted(JOBS_DIR.glob("*"), reverse=True):
        if not path.is_dir():
            continue
        meta = read_json(path / "metadata.json", {})
        if not meta:
            continue
        highlights = read_json(path / "highlights.json", {"clips": []})
        clips = highlights.get("clips", [])
        items.append(
            {
                "job_id": path.name,
                "title": meta.get("title", path.name),
                "created_at": meta.get("created_at"),
                "duration": meta.get("duration"),
                "status": meta.get("status"),
                "clip_count": len(clips),
                "confirmed_count": len([c for c in clips if c.get("confirmed")]),
                "exported_count": len([c for c in clips if c.get("export_file")]),
            }
        )
    return items


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
            self.serve_file(STATIC_DIR / path.removeprefix("/static/"))
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
            json_response(self, {"ok": True, "tasks": list_clip_tasks(job_id=job_id, limit=limit)})
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
            json_response(
                self,
                {
                    "ok": True,
                    "metadata": meta,
                    "transcript": read_json(base_dir / "transcript.json", {"segments": []}),
                    "highlights": read_json(base_dir / "highlights.json", {"clips": []}),
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
                elif path == "/api/settings":
                    self.handle_save_settings(payload)
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
                elif path == "/api/storage/cleanup":
                    json_response(self, {"ok": True, **cleanup_storage(payload)})
                elif path == "/api/tasks/clear-finished":
                    json_response(self, {"ok": True, "removed": clear_finished_clip_tasks(payload.get("job_id") or None), "tasks": list_clip_tasks(job_id=payload.get("job_id") or None)})
                elif path == "/api/tasks/retry":
                    json_response(self, {"ok": True, "task": retry_clip_task(payload.get("task_id"))})
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
        parts = Path(urllib.parse.unquote(relative)).parts
        if not parts:
            self.send_error(404)
            return
        path = (JOBS_DIR / Path(*parts)).resolve()
        if not str(path).startswith(str(JOBS_DIR.resolve())):
            self.send_error(403)
            return
        self.serve_file(path)

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
        title = sanitize_name(item.filename)
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + title
        base_dir = job_dir(job_id)
        base_dir.mkdir(parents=True, exist_ok=True)
        source = base_dir / f"source{ext}"
        with source.open("wb") as f:
            shutil.copyfileobj(item.file, f)
        meta = {
            "job_id": job_id,
            "title": title,
            "original_file": f"source{ext}",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_size": source.stat().st_size,
            "status": "uploaded",
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
            job = set_job(job_id, pause_requested=True, message="收到暂停请求")
            if task_id:
                set_clip_task(task_id, message="收到暂停请求")
        elif action == "resume":
            job = set_job(job_id, pause_requested=False, stage="transcribing", message="继续转写")
            if task_id:
                set_clip_task(task_id, status="running", message="继续转写")
        elif action == "stop":
            job = set_job(job_id, stop_requested=True, message="收到结束请求")
            if task_id:
                set_clip_task(task_id, cancel_requested=True, message="正在结束转写，保留已生成文字稿")
        else:
            raise RuntimeError("未知控制动作")
        json_response(self, {"ok": True, "job": job, "task": get_clip_task(task_id) if task_id else None})

    def handle_analyze(self, payload):
        job_id = payload.get("job_id")
        if not job_id:
            raise RuntimeError("Missing job_id")
        key = (payload.get("api_key") or read_json(SETTINGS_PATH, {}).get("deepseek_api_key") or "").strip()
        if not key:
            raise RuntimeError("Please enter a DeepSeek API Key first")
        if payload.get("save_key") and key:
            write_json(SETTINGS_PATH, {"deepseek_api_key": key})
        params = {
            "job_id": job_id,
            "target_clip_count": int(payload.get("target_clip_count") or 20),
            "min_seconds": int(payload.get("min_seconds") or 8),
            "max_seconds": int(payload.get("max_seconds") or 45),
        }
        runtime_payload = dict(params)
        runtime_payload["api_key"] = key
        runtime_payload["save_key"] = bool(payload.get("save_key"))
        task_id, task = create_clip_task(job_id, "analyze", "analyze")
        task = set_clip_task(task_id, params=params, encoder="DeepSeek", message="\u5206\u6790\u4efb\u52a1\u5df2\u52a0\u5165\u961f\u5217")
        set_job(job_id, stage="analyzing", message="\u5206\u6790\u4efb\u52a1\u5df2\u52a0\u5165\u961f\u5217", analyze_task_id=task_id)
        threading.Thread(target=analyze_worker, args=(task_id, job_id, runtime_payload), daemon=True).start()
        json_response(self, {"ok": True, "task": task})

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
        clip.setdefault("original_start", clip.get("start"))
        clip.setdefault("original_end", clip.get("end"))
        clip["start"] = round(float(payload.get("start")), 3)
        clip["end"] = round(float(payload.get("end")), 3)
        clip["status"] = "needs_render"
        clip["preview_file"] = None
        save_highlights(job_id, highlights)
        json_response(self, {"ok": True, "clip": clip})

    def handle_manual_clip(self, payload):
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
            clip["start"] = round(float(clip.get("original_start", clip.get("start", 0))), 3)
            clip["end"] = round(float(clip.get("original_end", clip.get("end", 0))), 3)
            clip["status"] = "needs_render"
            clip["preview_file"] = None
        elif action == "clear_preview":
            remove_job_relative_file(base_dir, clip.get("preview_file"))
            clip["preview_file"] = None
            if clip.get("status") == "ready":
                clip["status"] = "needs_render"
        elif action == "clear_export":
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


