import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class PackagedMediaCrawlerTests(unittest.TestCase):
    def test_frozen_runtime_receives_media_crawler_libs(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            bundled = root / "bundled-libs"
            runtime = root / "runtime"
            bundled.mkdir()
            (bundled / "douyin.js").write_text("bundled", encoding="utf-8")

            with patch.object(app, "IS_FROZEN", True), patch.object(
                app, "MEDIA_CRAWLER_BUNDLED_LIBS_DIR", bundled
            ), patch.object(app, "MEDIA_CRAWLER_RUNTIME_DIR", runtime):
                app.ensure_media_crawler_resources()

            deployed = runtime / "libs" / "douyin.js"
            self.assertEqual(deployed.read_text(encoding="utf-8"), "bundled")

    def test_missing_frozen_media_crawler_libs_is_reported(self):
        with tempfile.TemporaryDirectory() as tempdir:
            with patch.object(app, "IS_FROZEN", True), patch.object(
                app, "MEDIA_CRAWLER_BUNDLED_LIBS_DIR", Path(tempdir) / "missing"
            ):
                with self.assertRaisesRegex(RuntimeError, "MediaCrawler"):
                    app.ensure_media_crawler_resources()

    def test_media_crawler_subprocess_uses_hidden_console_kwargs(self):
        kwargs = app._hidden_console_subprocess_kwargs()
        if app.os.name == "nt":
            self.assertIn("creationflags", kwargs)
        else:
            self.assertEqual(kwargs, {})


if __name__ == "__main__":
    unittest.main()
