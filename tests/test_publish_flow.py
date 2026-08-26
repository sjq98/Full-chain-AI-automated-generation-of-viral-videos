import tempfile
import unittest
import importlib.util
import inspect
import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import app


def load_douyin_publisher(log_file):
    script = app.PUBLISHERS_DIR / "douyin-auto-publish" / "scripts" / "dy_video_publish.py"
    spec = importlib.util.spec_from_file_location("douyin_publisher_test", script)
    module = importlib.util.module_from_spec(spec)
    site_packages = app._publisher_site_packages()
    if site_packages and str(site_packages) not in sys.path:
        sys.path.insert(0, str(site_packages))
    with patch.dict(os.environ, {"DOUYIN_LOG_FILE": str(log_file)}, clear=False):
        spec.loader.exec_module(module)
    return module


def load_chrome_cdp():
    script = app.PUBLISHERS_DIR / "chrome_cdp.py"
    spec = importlib.util.spec_from_file_location("chrome_cdp_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_chrome_runtime():
    script = app.PUBLISHERS_DIR / "chrome_runtime.py"
    spec = importlib.util.spec_from_file_location("chrome_runtime_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PendingThread:
    """A thread double that lets these state-machine tests stay fully local."""

    def __init__(self, target, args=(), daemon=False):
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started


class PublishFlowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.paths = {
            "PUBLISH_TASKS_PATH": app.PUBLISH_TASKS_PATH,
            "PUBLISH_LOGIN_TASKS_PATH": app.PUBLISH_LOGIN_TASKS_PATH,
            "NETWORK_SETTINGS_PATH": app.NETWORK_SETTINGS_PATH,
        }
        app.PUBLISH_TASKS_PATH = root / "publish_tasks.json"
        app.PUBLISH_LOGIN_TASKS_PATH = root / "publish_login_tasks.json"
        app.NETWORK_SETTINGS_PATH = root / "network-settings.json"
        app.PUBLISH_TASKS = {}
        app.PUBLISH_LOGIN_TASKS = {}
        app.PUBLISH_LOGIN_WORKERS = {}
        app.PUBLISH_LOGIN_CANCEL_EVENTS = {}
        app.PUBLISH_MANUAL_TASK_PROBE_LAST = 0.0

    def tearDown(self):
        app.PUBLISH_TASKS_PATH = self.paths["PUBLISH_TASKS_PATH"]
        app.PUBLISH_LOGIN_TASKS_PATH = self.paths["PUBLISH_LOGIN_TASKS_PATH"]
        app.NETWORK_SETTINGS_PATH = self.paths["NETWORK_SETTINGS_PATH"]
        app.PUBLISH_TASKS = {}
        app.PUBLISH_LOGIN_TASKS = {}
        app.PUBLISH_LOGIN_WORKERS = {}
        app.PUBLISH_LOGIN_CANCEL_EVENTS = {}
        app.PUBLISH_MANUAL_TASK_PROBE_LAST = 0.0
        self.tempdir.cleanup()

    def test_restart_replaces_active_login_task(self):
        with (
            patch.object(app, "_adapter_diagnostics", return_value={"ready": True}),
            patch.object(app.threading, "Thread", PendingThread),
        ):
            first = app.start_publish_login("douyin")
            second = app.start_publish_login("douyin", restart=True)

        self.assertNotEqual(first["login_id"], second["login_id"])
        self.assertEqual(app.PUBLISH_LOGIN_TASKS[first["login_id"]]["status"], "cancelled")
        self.assertTrue(app.PUBLISH_LOGIN_CANCEL_EVENTS[first["login_id"]].is_set())
        self.assertEqual(app.PUBLISH_LOGIN_TASKS[second["login_id"]]["status"], "queued")

    def test_closed_login_window_is_recorded_as_cancelled_not_an_automation_error(self):
        login_id = "publish-login-test"
        app.PUBLISH_LOGIN_TASKS[login_id] = {
            "login_id": login_id,
            "platform": "douyin",
            "status": "queued",
            "message": "已加入登录准备队列",
        }
        with patch.object(
            app,
            "_douyin_login_prepare",
            side_effect=RuntimeError("登录窗口已关闭，尚未保存登录态。可再次点击“登录准备”重新打开。"),
        ):
            app.publish_login_worker(login_id)

        task = app.PUBLISH_LOGIN_TASKS[login_id]
        self.assertEqual(task["status"], "cancelled")
        self.assertIn("用户已关闭抖音登录窗口", task["message"])
        self.assertEqual(task["error"], "")

    def test_legacy_closed_login_window_is_migrated_to_cancelled(self):
        app.PUBLISH_LOGIN_TASKS_PATH.write_text(json.dumps({
            "closed-login": {
                "login_id": "closed-login",
                "platform": "channels",
                "status": "error",
                "message": "TargetClosedError: Target page, context or browser has been closed",
                "error": "TargetClosedError",
            },
        }, ensure_ascii=False), encoding="utf-8")

        app.load_publish_login_tasks()

        task = app.PUBLISH_LOGIN_TASKS["closed-login"]
        self.assertEqual(task["status"], "cancelled")
        self.assertIn("用户已关闭视频号登录窗口", task["message"])
        self.assertEqual(task["error"], "")

    def test_restart_marks_interrupted_browser_publish_tasks_as_retriable_errors(self):
        app.PUBLISH_TASKS_PATH.write_text(json.dumps({
            "publish-active": {"task_id": "publish-active", "status": "running", "message": "正在启动 Chrome"},
            "publish-done": {"task_id": "publish-done", "status": "succeeded", "message": "已完成"},
            "publish-manual": {
                "task_id": "publish-manual",
                "status": "succeeded",
                "result_state": "awaiting_manual_confirmation",
                "message": "已打开发布页",
            },
        }, ensure_ascii=False), encoding="utf-8")
        app.load_publish_tasks()
        self.assertEqual(app.PUBLISH_TASKS["publish-active"]["status"], "error")
        self.assertIn("重新执行", app.PUBLISH_TASKS["publish-active"]["message"])
        self.assertEqual(app.PUBLISH_TASKS["publish-done"]["status"], "succeeded")
        self.assertEqual(app.PUBLISH_TASKS["publish-manual"]["status"], "error")
        self.assertEqual(app.PUBLISH_TASKS["publish-manual"]["result_state"], "interrupted")

    def test_execute_requires_saved_login_before_queueing_work(self):
        task_id = "publish-task-test"
        app.PUBLISH_TASKS[task_id] = {
            "task_id": task_id,
            "platform": "douyin",
            "platform_name": "抖音",
            "status": "planned",
        }
        with patch.object(app, "_publish_login_state", return_value={"saved": False}):
            with self.assertRaisesRegex(RuntimeError, "尚未保存登录态"):
                app.execute_publish_tasks([task_id])

        self.assertEqual(app.PUBLISH_TASKS[task_id]["status"], "planned")

    def test_publish_worker_reports_manual_review_page_ready(self):
        task_id = "publish-task-test"
        app.PUBLISH_TASKS[task_id] = {
            "task_id": task_id,
            "platform": "douyin",
            "platform_name": "抖音",
            "status": "queued",
            "schedule": "manual_review",
        }
        with patch.object(app, "_run_publisher_task", return_value={"output": "opened"}):
            app.publish_task_worker(task_id)

        task = app.PUBLISH_TASKS[task_id]
        self.assertEqual(task["status"], "succeeded")
        self.assertEqual(task["result_state"], "awaiting_manual_confirmation")
        self.assertIn("发布页", task["message"])

    def test_user_closed_publish_window_is_recorded_as_cancelled_not_an_automation_error(self):
        task_id = "publish-closed-window"
        app.PUBLISH_TASKS[task_id] = {
            "task_id": task_id,
            "platform": "douyin",
            "platform_name": "抖音",
            "status": "queued",
        }
        with patch.object(
            app,
            "_run_publisher_task",
            side_effect=app.PublishWindowClosedByUser("用户已关闭抖音发布窗口，任务已停止，未发布。"),
        ):
            app.publish_task_worker(task_id)

        task = app.PUBLISH_TASKS[task_id]
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(task["result_state"], "cancelled_by_user")
        self.assertIn("用户已关闭抖音发布窗口", task["message"])
        self.assertEqual(task["error"], "")

    def test_direct_launch_manual_review_state_is_not_probed_via_cdp(self):
        task_id = "publish-manual-page-closed"
        app.PUBLISH_TASKS[task_id] = {
            "task_id": task_id,
            "platform": "douyin",
            "status": "succeeded",
            "result_state": "awaiting_manual_confirmation",
            "message": "已打开并填写发布页，请在浏览器中检查后手动发布",
        }
        with patch.object(app, "_shared_publish_browser_page_urls", return_value=None):
            reconciled = app._reconcile_closed_manual_publish_tasks(force=True)

        self.assertEqual(reconciled, 0)
        self.assertEqual(app.PUBLISH_TASKS[task_id]["status"], "succeeded")

    def test_login_start_reuses_an_active_worker_without_restarting_it(self):
        with (
            patch.object(app, "_adapter_diagnostics", return_value={"ready": True}),
            patch.object(app.threading, "Thread", PendingThread),
        ):
            first = app.start_publish_login("douyin")
            second = app.start_publish_login("douyin")
        self.assertEqual(first["login_id"], second["login_id"])

    def test_task_center_merges_publish_records_and_deletes_finished_record(self):
        task_id = "publish-task-center-test"
        app.PUBLISH_TASKS[task_id] = {
            "task_id": task_id,
            "job_id": "job-test",
            "platform": "douyin",
            "platform_name": "抖音",
            "title": "任务中心测试",
            "status": "succeeded",
            "message": "已打开发布页",
            "created_at": "2026-08-24T00:00:00",
            "updated_at": "2026-08-24T00:00:01",
        }
        entries = app.list_task_center_tasks()
        entry = next(item for item in entries if item["task_id"] == task_id)
        self.assertEqual(entry["type"], "publish")
        self.assertEqual(entry["category"], "publish")
        self.assertEqual(entry["status"], "succeeded")
        self.assertEqual(app.delete_task_record(task_id)["kind"], "publish")
        self.assertNotIn(task_id, app.PUBLISH_TASKS)

    def test_network_denied_publish_error_is_summarized(self):
        task_id = "publish-network-error"
        app.PUBLISH_TASKS[task_id] = {
            "task_id": task_id,
            "platform": "douyin",
            "status": "error",
            "message": "Page.goto: net::ERR_NETWORK_ACCESS_DENIED at https://creator.douyin.com/",
            "error": "Page.goto: net::ERR_NETWORK_ACCESS_DENIED",
            "created_at": "2026-08-24T00:00:00",
        }
        task = next(item for item in app.list_publish_tasks() if item["task_id"] == task_id)
        self.assertIn("浏览器网络连接被系统拒绝", task["message"])

    def test_legacy_target_closed_error_is_shown_as_user_cancelled(self):
        task_id = "publish-target-closed"
        app.PUBLISH_TASKS[task_id] = {
            "task_id": task_id,
            "platform": "douyin",
            "status": "error",
            "message": "playwright._impl._errors.TargetClosedError: Target page, context or browser has been closed",
            "error": "TargetClosedError",
            "created_at": "2026-08-25T00:00:00",
        }

        task = next(item for item in app.list_publish_tasks() if item["task_id"] == task_id)

        self.assertEqual(task["status"], "cancelled")
        self.assertIn("用户已关闭抖音发布窗口", task["message"])

    def test_publisher_processes_strip_every_proxy_setting(self):
        with patch.dict(os.environ, {
            "APP_PROXY": "http://127.0.0.1:7897",
            "PUBLISHER_PROXY_SERVER": "http://127.0.0.1:7897",
            "HTTP_PROXY": "http://127.0.0.1:7897",
            "HTTPS_PROXY": "http://127.0.0.1:7897",
        }, clear=False):
            environment = app._login_environment("douyin")
        for key in app.PROXY_ENVIRONMENT_KEYS:
            self.assertNotIn(key, environment)
        self.assertEqual(app.public_proxy_url(), "")

    def test_browser_search_starts_chrome_without_a_proxy_argument(self):
        with (
            patch.dict(os.environ, {"APP_PROXY": "http://127.0.0.1:7897"}, clear=False),
            patch.object(app, "chrome_executable", return_value="C:/Chrome/chrome.exe"),
            patch.object(app.subprocess, "Popen") as popen,
        ):
            result = app.open_chrome_search({"keywords": "热点", "source": "mediacrawler_dy"})

        command = popen.call_args.args[0]
        self.assertFalse(any(item.startswith("--proxy-server=") for item in command))
        self.assertEqual(result["browser"], "chrome")

    def test_douyin_chrome_launcher_uses_normal_network_and_sandbox_settings(self):
        launcher = load_chrome_cdp()
        profile = Path(self.tempdir.name) / "chrome-profile"
        process = MagicMock(pid=12345)
        process.poll.return_value = None
        with (
            patch.object(launcher.Path, "is_file", return_value=True),
            patch.object(launcher, "_available_port", return_value=51234),
            patch.object(launcher.subprocess, "Popen", return_value=process) as popen,
            patch.object(launcher, "_cdp_details", return_value={"webSocketDebuggerUrl": "ws://test"}),
            patch.object(launcher, "_debug_port_pid", return_value=12345),
            patch.object(launcher, "_focus_chrome_window", return_value=True),
        ):
            launcher.start_visible_chrome(
                "C:/Chrome/chrome.exe",
                profile,
                initial_url="https://creator.douyin.com/",
            )

        command = popen.call_args.args[0]
        self.assertNotIn("--new-window", command)
        self.assertFalse(any(item.startswith("--proxy-server=") for item in command))
        for argument in ("--no-sandbox", "--disable-gpu", "--in-process-gpu", "--disable-software-rasterizer"):
            self.assertNotIn(argument, command)

    def test_shared_chrome_page_picker_reuses_and_deduplicates_platform_login_tabs(self):
        launcher = load_chrome_cdp()
        first_login = MagicMock()
        first_login.url = "https://channels.weixin.qq.com/login.html"
        first_login.is_closed.return_value = False
        duplicate_login = MagicMock()
        duplicate_login.url = "https://channels.weixin.qq.com/login.html"
        duplicate_login.is_closed.return_value = False
        context = MagicMock()
        context.pages = [first_login, duplicate_login]

        page = launcher.reuse_or_create_page(
            context,
            "https://channels.weixin.qq.com/platform/post/list",
        )
        closed = launcher.close_duplicate_pages(context, page)

        self.assertIs(page, first_login)
        context.new_page.assert_not_called()
        self.assertEqual(closed, 1)
        duplicate_login.close.assert_called_once()

    def test_shared_chrome_cleanup_removes_blank_page(self):
        launcher = load_chrome_cdp()
        target_page = MagicMock()
        target_page.url = "https://creator.douyin.com/creator-micro/content/upload"
        target_page.is_closed.return_value = False
        blank_page = MagicMock()
        blank_page.url = "about:blank"
        blank_page.is_closed.return_value = False
        context = MagicMock()
        context.pages = [target_page, blank_page]

        closed = launcher.close_blank_pages(context, target_page)

        self.assertEqual(closed, 1)
        blank_page.close.assert_called_once()

    def test_shared_chrome_cleanup_keeps_one_platform_tab(self):
        launcher = load_chrome_cdp()
        keep_page = MagicMock()
        keep_page.url = "https://creator.douyin.com/creator-micro/content/upload"
        keep_page.is_closed.return_value = False
        old_creator_page = MagicMock()
        old_creator_page.url = "https://creator.douyin.com/"
        old_creator_page.is_closed.return_value = False
        unrelated_page = MagicMock()
        unrelated_page.url = "https://channels.weixin.qq.com/platform/post/list"
        unrelated_page.is_closed.return_value = False
        context = MagicMock()
        context.pages = [keep_page, old_creator_page, unrelated_page]

        closed = launcher.close_pages_for_host(context, keep_page, keep_page.url)

        self.assertEqual(closed, 1)
        old_creator_page.close.assert_called_once()
        unrelated_page.close.assert_not_called()

    def test_channel_adapters_use_one_direct_chrome_page_and_hide_windows_console(self):
        self.assertEqual(
            app.PUBLISH_PLATFORMS["channels"]["label"],
            "auto-weixin-video · Google Chrome 直接启动",
        )
        channel_login = (app.PUBLISHERS_DIR / "auto-weixin-video" / "scripts" / "get_cookie.py").read_text(encoding="utf-8")
        channel_publish = (app.PUBLISHERS_DIR / "auto-weixin-video" / "scripts" / "publish.py").read_text(encoding="utf-8")
        self.assertIn("launch_persistent_context", channel_login)
        self.assertIn("executable_path=BROWSER_EXECUTABLE", channel_login)
        self.assertIn("ignore_default_args=PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE", channel_login)
        self.assertIn("args=CHROME_LAUNCH_ARGS", channel_login)
        self.assertIn("prepare_single_visible_page_async", channel_login)
        self.assertIn("p.chromium.launch(", channel_publish)
        self.assertIn("executable_path=BROWSER_EXECUTABLE", channel_publish)
        self.assertIn("ignore_default_args=PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE", channel_publish)
        self.assertIn("args=CHROME_LAUNCH_ARGS", channel_publish)
        self.assertIn("prepare_single_visible_page_async", channel_publish)
        self.assertIn("keep_only_page_async", channel_publish)
        self.assertIn("restore_visible_window_async", channel_publish)
        self.assertIn("await browser.new_context(viewport=None)", channel_publish)
        self.assertNotIn("new_context(storage_state", channel_publish)
        self.assertNotIn("connect_over_cdp", channel_login)
        self.assertNotIn("connect_over_cdp", channel_publish)
        if os.name == "nt":
            self.assertIn("creationflags", app._hidden_console_subprocess_kwargs())

    def test_publish_platforms_do_not_include_kuaishou(self):
        self.assertNotIn("kuaishou", app.PUBLISH_PLATFORMS)
        page = (app.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('value="kuaishou"', page)

    def test_open_creator_center_reuses_its_existing_tab_and_keeps_chrome_open(self):
        creator_page = MagicMock()
        creator_page.url = "https://creator.douyin.com/"
        creator_page.is_closed.return_value = False
        other_page = MagicMock()
        other_page.url = "https://example.com/"
        other_page.is_closed.return_value = False
        context = MagicMock()
        context.pages = [other_page, creator_page]

        page = app._reuse_or_create_douyin_creator_page(context)

        self.assertIs(page, creator_page)
        context.new_page.assert_not_called()
        source = inspect.getsource(app._douyin_login_prepare)
        self.assertIn("p.chromium.launch(", source)
        self.assertIn("executable_path=chrome", source)
        self.assertIn("browser.new_context", source)
        self.assertIn("prepare_single_visible_page", source)
        self.assertIn("restore_visible_window", source)
        self.assertNotIn("new_context(**context_options)", source)
        self.assertNotIn("connect_over_cdp", source)

    def test_legacy_proxy_cache_is_removed_instead_of_reused(self):
        app.NETWORK_SETTINGS_PATH.write_text(json.dumps({"app_proxy": "http://127.0.0.1:7897"}), encoding="utf-8")
        app.remember_public_proxy_candidate()
        self.assertNotIn("app_proxy", app.read_json(app.NETWORK_SETTINGS_PATH, {}))

    def test_douyin_does_not_supply_a_hidden_default_location(self):
        publisher = load_douyin_publisher(Path(self.tempdir.name) / "douyin.log")
        self.assertEqual(publisher.LOCATION, "")
        self.assertEqual(publisher.DEFAULT_TITLE, "")
        self.assertEqual(publisher.DEFAULT_BODY, "")
        self.assertEqual(publisher.DEFAULT_TOPICS, [])
        self.assertEqual(publisher.normalize_location(None), "")
        self.assertEqual(publisher.normalize_location("   "), "")
        self.assertEqual(publisher.normalize_location("上海市"), "上海市")
        source = (app.PUBLISHERS_DIR / "douyin-auto-publish" / "scripts" / "dy_video_publish.py").read_text(encoding="utf-8")
        self.assertIn("p.chromium.launch(", source)
        self.assertIn("executable_path=BROWSER_EXECUTABLE", source)
        self.assertIn("prepare_single_visible_page", source)
        self.assertIn("keep_only_page", source)
        self.assertIn("restore_visible_window", source)
        self.assertIn("ignore_default_args=PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE", source)
        self.assertIn("args=CHROME_LAUNCH_ARGS", source)
        self.assertIn("browser.new_context", source)
        self.assertNotIn("new_context(**context_options)", source)
        self.assertNotIn("connect_over_cdp", source)
        self.assertNotIn("start_visible_chrome", source)
        self.assertNotIn("proxy_server=", source)
        self.assertIn("PUBLISHER_USER_CLOSED_WINDOW", source)
        self.assertIn("用户已关闭抖音发布窗口", source)

    def test_douyin_login_prepare_has_no_legacy_proxy_argument(self):
        source = inspect.getsource(app._douyin_login_prepare)
        self.assertNotIn("proxy_server=", source)
        self.assertIn("p.chromium.launch(", source)
        self.assertIn("executable_path=chrome", source)
        self.assertIn("ignore_default_args=PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE", source)
        self.assertIn("args=CHROME_LAUNCH_ARGS", source)
        self.assertIn("prepare_single_visible_page", source)
        self.assertIn("keep_only_page", source)
        self.assertIn("restore_visible_window", source)
        self.assertIn("browser.new_context", source)
        self.assertNotIn("connect_over_cdp", source)

    def test_xhs_login_keeps_the_visible_page_when_qr_link_extraction_changes(self):
        source = (app.PUBLISHERS_DIR / "xhs-mcp" / "src" / "core" / "login-session.ts").read_text(encoding="utf-8")
        self.assertIn("keep the visible login page open for direct scanning", source)
        self.assertNotIn("throw new Error('Failed to extract QR code data from page state.')", source)

    def test_completed_manual_review_record_does_not_block_a_new_publish_task(self):
        app.PUBLISH_TASKS["publish-open"] = {
            "task_id": "publish-open",
            "asset_id": "asset-1",
            "platform": "douyin",
            "status": "succeeded",
            "result_state": "awaiting_manual_confirmation",
        }
        asset = {
            "asset_id": "asset-1",
            "job_id": "",
            "clip_id": "",
            "file": "clip.mp4",
            "file_path": str(Path(self.tempdir.name) / "clip.mp4"),
            "title": "测试成片",
        }
        with (
            patch.object(app, "list_publish_assets", return_value=[asset]),
            patch.object(app, "_adapter_diagnostics", return_value={"ready": True}),
        ):
            tasks = app.create_publish_tasks({
                "asset_ids": ["asset-1"],
                "platforms": ["douyin"],
                "schedule": "manual_review",
            })

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "planned")

    def test_publish_assets_exclude_exported_golden_quote_clips(self):
        root = Path(self.tempdir.name)
        local_assets_path = root / "publish_local_assets.json"
        local_video = root / "publish-assets" / "complete-video.mp4"
        local_video.parent.mkdir(parents=True)
        local_video.write_bytes(b"complete-video")
        local_assets_path.write_text(json.dumps([{
            "asset_id": "local-complete-video",
            "title": "完整成片",
            "stored_name": local_video.name,
            "file_path": str(local_video),
            "duration": 42,
        }]), encoding="utf-8")

        jobs_dir = root / "jobs"
        exported_clip = jobs_dir / "job-1" / "clips" / "exports" / "quote" / "clip.mp4"
        exported_clip.parent.mkdir(parents=True)
        exported_clip.write_bytes(b"golden-quote-clip")
        (jobs_dir / "job-1" / "metadata.json").write_text(json.dumps({
            "entered_task_center": True,
            "title": "原始视频",
        }), encoding="utf-8")
        (jobs_dir / "job-1" / "highlights.json").write_text(json.dumps({"clips": [{
            "id": "clip-1",
            "title": "金句片段",
            "start": 3,
            "end": 12,
            "export_file": "clips/exports/quote/clip.mp4",
        }]}), encoding="utf-8")

        with (
            patch.object(app, "PUBLISH_LOCAL_ASSETS_PATH", local_assets_path),
            patch.object(app, "JOBS_DIR", jobs_dir),
            patch.object(app, "OUTPUTS_DIR", root / "outputs"),
        ):
            assets = app.list_publish_assets()

        self.assertEqual([asset["asset_id"] for asset in assets], ["local-complete-video"])
        self.assertEqual(assets[0]["origin"], "local")

    def test_create_publish_tasks_keeps_platform_specific_payloads(self):
        video = Path(self.tempdir.name) / "clip.mp4"
        video.write_bytes(b"video")
        asset = {
            "asset_id": "asset-platform-fields",
            "job_id": "job-1",
            "clip_id": "clip-1",
            "file": video.name,
            "file_path": str(video),
            "title": "成片默认标题",
        }
        payload = {
            "asset_ids": [asset["asset_id"]],
            "platforms": ["douyin", "channels", "xiaohongshu"],
            "platform_payloads": {
                "douyin": {"title": "抖音标题", "description": "抖音文案", "hashtags": "抖音话题", "schedule": "manual_review"},
                "channels": {"description": "视频号描述", "short_title": "视频号短标题", "hashtags": "视频号话题", "schedule": "manual_review"},
                "xiaohongshu": {"title": "小红书标题", "content": "小红书正文", "hashtags": "小红书话题", "schedule": "publish_now"},
            },
        }
        with (
            patch.object(app, "list_publish_assets", return_value=[asset]),
            patch.object(app, "_adapter_diagnostics", return_value={"ready": True}),
        ):
            tasks = app.create_publish_tasks(payload)

        by_platform = {task["platform"]: task for task in tasks}
        self.assertEqual(by_platform["douyin"]["title"], "抖音标题")
        self.assertEqual(by_platform["douyin"]["description"], "抖音文案")
        self.assertEqual(by_platform["channels"]["description"], "视频号描述")
        self.assertEqual(by_platform["channels"]["platform_payload"]["short_title"], "视频号短标题")
        self.assertEqual(by_platform["xiaohongshu"]["title"], "小红书标题")
        self.assertEqual(by_platform["xiaohongshu"]["description"], "小红书正文")

    def test_channels_command_passes_description_and_short_title_separately(self):
        video = Path(self.tempdir.name) / "clip.mp4"
        video.write_bytes(b"video")
        task = {
            "platform": "channels",
            "file_path": str(video),
            "title": "短标题",
            "description": "视频号描述",
            "hashtags": ["话题"],
            "platform_payload": {"short_title": "自定义短标题"},
            "schedule": "manual_review",
        }
        completed = MagicMock(returncode=0, stdout="opened", stderr="")
        with (
            patch.object(app, "_publish_login_state", return_value={"saved": True}),
            patch.object(app, "_login_environment", return_value={}),
            patch.object(app.subprocess, "run", return_value=completed) as run,
        ):
            app._run_publisher_task(task)

        command = run.call_args.args[0]
        self.assertIn("--title", command)
        self.assertIn("视频号描述", command)
        self.assertIn("--short-title", command)
        self.assertIn("自定义短标题", command)

    def test_multiple_publish_workers_wait_for_the_active_browser_window(self):
        task_ids = ["publish-parallel-1", "publish-parallel-2"]
        for task_id, platform in zip(task_ids, ("douyin", "channels")):
            app.PUBLISH_TASKS[task_id] = {
                "task_id": task_id,
                "platform": platform,
                "platform_name": platform,
                "status": "planned",
                "schedule": "manual_review",
            }
        started = []
        started_lock = threading.Lock()
        first_started = threading.Event()
        both_started = threading.Event()
        release = threading.Event()

        def fake_run(task):
            with started_lock:
                started.append(task["task_id"])
                if len(started) == 1:
                    first_started.set()
                if len(started) == 2:
                    both_started.set()
            release.wait(2)
            return {"output": "opened"}

        with (
            patch.object(app, "_publish_login_state", return_value={"saved": True}),
            patch.object(app, "_run_publisher_task", side_effect=fake_run),
        ):
            app.execute_publish_tasks(task_ids)
            self.assertTrue(first_started.wait(1))
            self.assertFalse(both_started.wait(0.15), "第二个平台应等待当前发布窗口完成")
            release.set()
            self.assertTrue(both_started.wait(1))
            deadline = time.time() + 2
            while time.time() < deadline and any(app.PUBLISH_TASKS[item]["status"] == "running" for item in task_ids):
                time.sleep(0.02)

    def test_publishers_do_not_fall_back_to_playwright_managed_browsers(self):
        publisher_sources = [
            app.PUBLISHERS_DIR / "douyin-auto-publish" / "scripts" / "dy_video_publish.py",
            app.PUBLISHERS_DIR / "auto-weixin-video" / "scripts" / "get_cookie.py",
            app.PUBLISHERS_DIR / "auto-weixin-video" / "scripts" / "publish.py",
        ]
        for path in publisher_sources:
            source = path.read_text(encoding="utf-8")
            self.assertIn("不会回退到 Edge 或 Playwright 浏览器", source)
        xhs_source = (app.PUBLISHERS_DIR / "xhs-mcp" / "dist" / "core" / "login-session.js").read_text(encoding="utf-8")
        self.assertIn("XHS_MCP_CHROME_EXECUTABLE", xhs_source)
        self.assertIn("executablePath: chromeExecutable", xhs_source)
        self.assertIn("ignoreDefaultArgs: PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE", xhs_source)

    def test_xhs_launchers_share_the_direct_chrome_window_policy(self):
        xhs_root = app.PUBLISHERS_DIR / "xhs-mcp" / "src"
        constants_source = (xhs_root / "xhs" / "clients" / "constants.ts").read_text(encoding="utf-8")
        browser_args_source = constants_source.split("PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE", 1)[0]
        self.assertIn("--window-position=60,40", browser_args_source)
        self.assertIn("--window-size=1280,900", browser_args_source)
        self.assertNotIn("--proxy-server", browser_args_source)
        for argument in ("--no-sandbox", "--disable-gpu", "--enable-unsafe-swiftshader"):
            self.assertNotIn(argument, browser_args_source)
            self.assertIn(argument, constants_source)

        launcher_sources = [
            xhs_root / "core" / "login-session.ts",
            xhs_root / "xhs" / "clients" / "context.ts",
            xhs_root / "xhs" / "clients" / "services" / "publish.ts",
        ]
        for path in launcher_sources:
            source = path.read_text(encoding="utf-8")
            self.assertIn("executablePath: chromeExecutable", source)
            self.assertIn("ignoreDefaultArgs: PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE", source)
            self.assertNotIn("proxy:", source)

        publish_source = launcher_sources[-1].read_text(encoding="utf-8")
        self.assertIn("prepareSingleVisiblePage", publish_source)
        self.assertIn("keepOnlyPage", publish_source)
        self.assertIn("restoreVisibleWindow", publish_source)

    def test_direct_chrome_policy_filters_proxy_sandbox_and_gpu_bypasses(self):
        runtime = load_chrome_runtime()
        launch_args = runtime.CHROME_LAUNCH_ARGS
        self.assertFalse(any(argument.startswith("--proxy-server") for argument in launch_args))
        for argument in (
            "--no-sandbox",
            "--disable-gpu",
            "--in-process-gpu",
            "--disable-software-rasterizer",
            "--enable-unsafe-swiftshader",
        ):
            self.assertNotIn(argument, launch_args)
            self.assertIn(argument, runtime.PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE)
        self.assertIn("--window-position=60,40", launch_args)
        self.assertIn("--window-size=1280,900", launch_args)

    def test_direct_chrome_runtime_reuses_one_page_and_closes_extras(self):
        runtime = load_chrome_runtime()
        blank_page = MagicMock()
        blank_page.url = "about:blank"
        blank_page.is_closed.return_value = False
        extra_page = MagicMock()
        extra_page.url = "https://example.com/"
        extra_page.is_closed.return_value = False
        context = MagicMock()
        context.pages = [blank_page, extra_page]

        with patch.object(runtime, "restore_visible_window", return_value=True):
            page = runtime.prepare_single_visible_page(
                context,
                "https://creator.douyin.com/creator-micro/content/upload",
            )

        self.assertIs(page, blank_page)
        context.new_page.assert_not_called()
        extra_page.close.assert_called_once()

    def test_direct_chrome_runtime_restores_current_window_to_visible_bounds(self):
        runtime = load_chrome_runtime()
        session = MagicMock()
        session.send.side_effect = [{"windowId": 42}, {}, {}]
        context = MagicMock()
        context.new_cdp_session.return_value = session
        page = MagicMock()
        page.context = context

        self.assertTrue(runtime.restore_visible_window(page))
        self.assertEqual(
            session.send.call_args_list[1].args,
            ("Browser.setWindowBounds", {"windowId": 42, "bounds": {"windowState": "normal"}}),
        )
        self.assertEqual(
            session.send.call_args_list[2].args,
            (
                "Browser.setWindowBounds",
                {"windowId": 42, "bounds": {"left": 60, "top": 40, "width": 1280, "height": 900}},
            ),
        )


if __name__ == "__main__":
    unittest.main()
