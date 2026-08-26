import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "vendor" / "publishers" / "chrome_cdp.py"
SPEC = importlib.util.spec_from_file_location("chrome_cdp_test", MODULE_PATH)
chrome_cdp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chrome_cdp)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1/devtools/browser/test"}).encode()


class _Process:
    pid = 12345
    returncode = 0

    def poll(self):
        # The Windows Chrome launcher can exit after handing off to a child.
        return self.returncode

    def terminate(self):
        raise AssertionError("the CDP endpoint should make this launch succeed")


class ChromeCdpTests(unittest.TestCase):
    def test_launcher_exit_does_not_override_a_ready_cdp_endpoint(self):
        with tempfile.TemporaryDirectory() as tempdir:
            chrome = Path(tempdir) / "chrome.exe"
            chrome.write_bytes(b"stub")
            profile = Path(tempdir) / "profile"
            with patch.object(chrome_cdp.subprocess, "Popen", return_value=_Process()) as popen, patch.object(
                chrome_cdp.urllib.request,
                "urlopen",
                side_effect=[OSError("not ready"), _Response()],
            ) as urlopen, patch.object(chrome_cdp, "_debug_port_pid", return_value=23456):
                process, endpoint = chrome_cdp.start_visible_chrome(
                    chrome,
                    profile,
                    timeout=3,
                )

            self.assertIsInstance(process, _Process)
            self.assertTrue(endpoint.startswith("http://127.0.0.1:"))
            command = popen.call_args.args[0]
            self.assertNotIn("--no-sandbox", command)
            self.assertNotIn("--new-window", command)
            self.assertTrue(any(item.startswith("--user-data-dir=") for item in command))
            self.assertEqual(urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
