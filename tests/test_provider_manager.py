import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class ProviderManagerTests(unittest.TestCase):
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
