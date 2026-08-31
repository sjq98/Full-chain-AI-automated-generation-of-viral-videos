import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class ProviderManagerTests(unittest.TestCase):
    def test_material_form_does_not_leave_hidden_volcengine_name_required(self):
        source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
        self.assertRegex(source, re.compile(r"el\.volcProviderName\.required\s*=\s*isVolcengine"))

    def test_provider_settings_initializes_material_provider_collections(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user-settings.json"
            path.write_text(json.dumps({}), encoding="utf-8")
            with patch.object(app, "SETTINGS_PATH", path):
                saved = app.provider_settings()

        self.assertEqual(saved["pexels_providers"], [])
        self.assertEqual(saved["pixabay_providers"], [])

    def test_public_material_provider_masks_api_key_and_keeps_platform_fields(self):
        item = app.public_provider({
            "id": "pexels-1",
            "name": "Pexels 主账号",
            "api_key": "pexels-secret-key",
            "enabled": True,
            "result_limit": 12,
        }, "pexels")

        self.assertEqual(item["result_limit"], 12)
        self.assertTrue(item["has_api_key"])
        self.assertEqual(item["masked_api_key"], "pexels...-key")
        self.assertNotIn("api_key", item)

    def test_material_provider_kind_uses_its_own_collection(self):
        self.assertEqual(app.provider_collection_key("pexels"), "pexels_providers")
        self.assertEqual(app.provider_collection_key("pixabay"), "pixabay_providers")

    def test_broll_input_normalization_preserves_freeform_script(self):
        script = "开场展示工厂全景，然后切到机械臂组装产品，最后给产品细节特写。"
        self.assertEqual(app.normalize_broll_input(script), script)

    def test_broll_frontend_uses_freeform_copy_and_single_async_handler(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "static" / "app.js").read_text(encoding="utf-8")
        html = (root / "static" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("function searchBroll()", source)
        self.assertNotIn("输入每行一条分镜需求即可开始", source)
        self.assertNotIn("输入需求列表后", source)
        self.assertNotIn("输入需求列表后", html)
        self.assertNotIn("LLM 会自动拆分", source)
        self.assertNotIn("LLM 会自动拆分", html)
        self.assertIn("请粘贴已经划分好的分镜头需求", html)

    def test_broll_frontend_preserves_error_status_when_refreshing_state(self):
        source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("statusMessage", source)
        self.assertRegex(source, re.compile(r"state\.broll\.statusMessage\s*\|\|"))

    def test_analyze_polling_does_not_fail_when_task_list_refresh_is_transiently_unavailable(self):
        source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
        polling = source[source.index("async function pollAnalyzeTask"):source.index("el.analyzeButton.addEventListener", source.index("async function pollAnalyzeTask"))]
        self.assertRegex(
            polling,
            re.compile(r"await\s+refreshTasks\(\)\.catch\("),
        )
        self.assertIn("无法读取分析进度，工作台后端连接中断", polling)

    def test_material_search_urls_keep_query_and_limit(self):
        self.assertIn("query=city", app.material_search_url("pexels", "city", 8))
        self.assertIn("per_page=8", app.material_search_url("pexels", "city", 8))
        self.assertIn("q=city", app.material_search_url("pixabay", "city", 8))
        self.assertIn("per_page=8", app.material_search_url("pixabay", "city", 8))

    def test_pixabay_search_url_uses_api_minimum_per_page(self):
        self.assertIn("per_page=3", app.material_search_url("pixabay", "nature", 1))

    def test_material_requests_send_browser_user_agent_for_cloudflare_compatibility(self):
        request = app.material_search_request("pexels", "city", {"api_key": "pexels-key", "result_limit": 8})
        self.assertIn("Mozilla/5.0", request.get_header("User-agent"))
        self.assertEqual(request.get_header("Authorization"), "pexels-key")

    def test_http_opener_uses_verified_system_and_certifi_trust(self):
        previous_opener = app._NO_PROXY_OPENER
        previous_context = app._HTTPS_SSL_CONTEXT
        try:
            app._NO_PROXY_OPENER = None
            app._HTTPS_SSL_CONTEXT = None
            opener = app.http_opener()
            https_handlers = [handler for handler in opener.handlers if isinstance(handler, app.urllib.request.HTTPSHandler)]

            self.assertEqual(len(https_handlers), 1)
            self.assertEqual(https_handlers[0]._context.verify_mode, app.ssl.CERT_REQUIRED)
            self.assertTrue(https_handlers[0]._context.check_hostname)
            self.assertIsNotNone(app.certifi)
            self.assertTrue(Path(app.certifi.where()).is_file())
        finally:
            app._NO_PROXY_OPENER = previous_opener
            app._HTTPS_SSL_CONTEXT = previous_context

    def test_broll_search_reports_real_stage_progress(self):
        providers = {
            "pexels": {"id": "pexels-1", "name": "Pexels", "api_key": "key", "enabled": True},
            "pixabay": {"id": "pixabay-1", "name": "Pixabay", "api_key": "key", "enabled": True},
        }
        candidate = {
            "id": "candidate-1",
            "title": "City",
            "description": "city",
            "source": "pexels",
            "duration": 5,
            "width": 1920,
            "height": 1080,
            "matched_query": "city",
        }
        events = []
        with patch.object(app, "enabled_provider", side_effect=lambda kind: providers[kind]), \
             patch.object(app, "broll_search_queries", return_value=[{"requirement": "城市夜景", "queries": ["city"]}]), \
             patch.object(app, "search_material_provider", return_value=[dict(candidate)]), \
             patch.object(app, "broll_rank_candidates", side_effect=lambda _requirement, candidates: candidates):
            result = app.search_broll_requirements("城市夜景", progress_callback=lambda progress, message: events.append((progress, message)))

        self.assertEqual(len(result), 1)
        messages = [message for _progress, message in events]
        self.assertTrue(any("生成检索词" in message for message in messages))
        self.assertTrue(any("Pexels" in message for message in messages))
        self.assertTrue(any("Pixabay" in message for message in messages))
        self.assertTrue(any("元数据重排" in message for message in messages))
        self.assertEqual(events[-1][0], 1)

    def test_broll_search_passes_freeform_input_to_llm_planner(self):
        providers = {
            "pexels": {"id": "pexels-1", "name": "Pexels", "api_key": "key", "enabled": True},
            "pixabay": {"id": "pixabay-1", "name": "Pixabay", "api_key": "key", "enabled": True},
        }
        freeform = "开场展示工厂全景，然后切到机械臂组装产品，最后给产品细节特写。"
        with patch.object(app, "enabled_provider", side_effect=lambda kind: providers[kind]), \
             patch.object(app, "broll_search_queries", return_value=[{"requirement": "工厂全景", "queries": ["factory"]}]) as planner, \
             patch.object(app, "search_material_provider", return_value=[]), \
             patch.object(app, "broll_rank_candidates", return_value=[]):
            app.search_broll_requirements(freeform)

        planner.assert_called_once_with(freeform)

    def test_broll_query_planner_preserves_user_shot_boundaries(self):
        prompts = []
        llm_result = {
            "items": [
                {"requirement": "镜头一", "queries": ["factory exterior"]},
                {"requirement": "镜头二", "queries": ["robotic arm assembly"]},
                {"requirement": "镜头三", "queries": ["product close up"]},
            ]
        }
        with patch.object(app, "llm_json", side_effect=lambda prompt, **_kwargs: prompts.append(prompt) or llm_result):
            plans = app.broll_search_queries("镜头一\n\n镜头二\n镜头三")

        self.assertEqual(len(plans), 3)
        self.assertEqual([item["queries"] for item in plans], [["factory exterior"], ["robotic arm assembly"], ["product close up"]])
        self.assertEqual(len(prompts), 1)
        self.assertIn("不得拆分、合并或改写用户已经提供的分镜头边界", prompts[0])
        self.assertIn("输入共 3 个分镜头", prompts[0])
        self.assertNotIn("自行识别其中需要 B-roll 的镜头边界", prompts[0])

    def test_broll_worker_persists_done_results(self):
        app.BROLL_TASKS.clear()
        with patch.object(app, "search_broll_requirements", return_value=[{"requirement": "城市夜景"}]):
            app.broll_search_worker("broll-test-task", "城市夜景")

        task = app.get_broll_task("broll-test-task")
        self.assertEqual(task["status"], "done")
        self.assertEqual(task["stage"], "done")
        self.assertEqual(task["percent"], 100)
        self.assertEqual(task["results"], [{"requirement": "城市夜景"}])

    def test_provider_settings_drops_legacy_keys_without_migrating_them(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user-settings.json"
            path.write_text(json.dumps({
                "deepseek_api_key": "legacy-llm-key",
                "volcengine_api_key": "legacy-volc-key",
                "volcengine_resource_id": "legacy.resource",
                "tos_access_key": "legacy-ak",
            }), encoding="utf-8")
            with patch.object(app, "SETTINGS_PATH", path):
                saved = app.provider_settings()

            self.assertEqual(saved["llm_providers"], [])
            self.assertEqual(saved["volcengine_providers"], [])
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("deepseek_api_key", persisted)
            self.assertNotIn("volcengine_api_key", persisted)
            self.assertNotIn("tos_access_key", persisted)

    def test_volcengine_runtime_reads_only_enabled_provider_record(self):
        provider = {
            "id": "volc-1",
            "name": "火山生产",
            "api_key": "provider-key",
            "resource_id": "volc.seedasr.auc",
            "audio_url": "https://audio.example.test/file.wav",
            "poll_interval": 9,
            "tos_access_key": "provider-ak",
            "tos_secret_key": "provider-sk",
            "tos_endpoint": "tos-cn-beijing.volces.com",
            "tos_region": "cn-beijing",
            "tos_bucket": "bucket",
            "tos_prefix": "clips",
            "tos_url_expires": 600,
            "enabled": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "user-settings.json"
            path.write_text(json.dumps({"volcengine_providers": [provider]}), encoding="utf-8")
            with patch.object(app, "SETTINGS_PATH", path), patch.dict(os.environ, {
                "VOLCENGINE_API_KEY": "env-key",
                "TOS_ACCESS_KEY": "env-ak",
            }, clear=False):
                volc = app.volcengine_settings({"volcengine_api_key": "payload-key"})
                tos = app.tos_settings({"tos_access_key": "payload-ak"})

        self.assertEqual(volc["api_key"], "provider-key")
        self.assertEqual(volc["audio_url"], provider["audio_url"])
        self.assertEqual(volc["poll_interval"], 9)
        self.assertEqual(tos["access_key"], "provider-ak")
        self.assertEqual(tos["secret_key"], "provider-sk")
        self.assertEqual(tos["url_expires"], 600)

    def test_public_volcengine_provider_keeps_non_secret_runtime_fields(self):
        item = app.public_provider({
            "id": "volc-1",
            "name": "火山生产",
            "api_key": "provider-key",
            "audio_url": "https://audio.example.test/file.wav",
            "poll_interval": 7,
            "tos_access_key": "ak",
            "tos_secret_key": "sk",
            "enabled": True,
        }, "volcengine")

        self.assertEqual(item["audio_url"], "https://audio.example.test/file.wav")
        self.assertEqual(item["poll_interval"], 7)
        self.assertTrue(item["has_tos_access_key"])
        self.assertNotIn("tos_access_key", item)
        self.assertNotIn("tos_secret_key", item)

    def test_article_browser_fallback_uses_normal_browser_paths(self):
        forbidden = {
            "--no-proxy-server",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-gpu-compositing",
            "--disable-software-rasterizer",
        }
        self.assertFalse(forbidden.intersection(set(app.ARTICLE_BROWSER_LAUNCH_ARGS)))


if __name__ == "__main__":
    unittest.main()
