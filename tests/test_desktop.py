"""Desktop startup must never reuse an unrelated server on the default port."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch


class DesktopStartupTest(unittest.TestCase):
    def test_occupied_default_port_uses_own_server(self):
        with tempfile.TemporaryDirectory() as data, patch.dict(os.environ, {
            "SHIGUANG_DATA_DIR": data, "SHIGUANG_HEADLESS": "1", "PORT": "8787"
        }):
            source = Path(__file__).resolve().parents[1] / "desktop.py"
            spec = importlib.util.spec_from_file_location("shiguang_desktop_test", source)
            desktop = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(desktop)
            httpd = MagicMock(server_port=18789)
            with patch.object(desktop, "db") as db, patch.object(
                desktop, "ThreadingHTTPServer", side_effect=[OSError("in use"), httpd]
            ) as server:
                desktop.main()
            db.return_value.close.assert_called_once()
            self.assertEqual(server.call_args_list, [
                call(("127.0.0.1", 8787), desktop.Handler),
                call(("127.0.0.1", 0), desktop.Handler),
            ])
            httpd.serve_forever.assert_called_once()
            httpd.server_close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
