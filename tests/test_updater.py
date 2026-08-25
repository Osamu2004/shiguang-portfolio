import importlib.util
import unittest
from unittest import mock
from pathlib import Path

spec = importlib.util.spec_from_file_location("updater", Path(__file__).parents[1] / "updater.py")
updater = importlib.util.module_from_spec(spec); spec.loader.exec_module(updater)


class UpdaterTest(unittest.TestCase):
    def test_semantic_versions_are_compared_numerically(self):
        self.assertGreater(updater._version_tuple("v0.10.0"), updater._version_tuple("0.9.9"))

    def test_invalid_version_is_not_new(self):
        self.assertEqual(updater._version_tuple("preview"), (0,))

    def test_network_error_has_readable_message(self):
        with mock.patch.object(updater.urllib.request, "urlopen", side_effect=updater.urllib.error.URLError("TLS failed")):
            with self.assertRaisesRegex(ValueError, "更新服务网络连接失败"):
                updater._request("https://example.invalid", "token")


if __name__ == "__main__": unittest.main()
