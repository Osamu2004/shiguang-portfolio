import importlib.util
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

spec = importlib.util.spec_from_file_location("sync_engine", Path(__file__).parents[1] / "sync_engine.py")
sync = importlib.util.module_from_spec(spec); spec.loader.exec_module(sync)


class SyncTest(unittest.TestCase):
    def test_short_password_is_allowed(self):
        self.assertEqual(sync.decrypt_vault(sync.encrypt_vault({"ok": True}, "1"), "1"), {"ok": True})

    def test_empty_password_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不能为空"):
            sync.encrypt_vault({}, "")

    def test_encrypt_roundtrip_and_random_nonce(self):
        payload = {"schemaVersion": 1, "tables": {"holdings": []}}
        one = sync.encrypt_vault(payload, "correct horse battery staple")
        two = sync.encrypt_vault(payload, "correct horse battery staple")
        self.assertNotEqual(one, two)
        self.assertEqual(sync.decrypt_vault(one, "correct horse battery staple"), payload)

    def test_wrong_password_fails(self):
        blob = sync.encrypt_vault({"x": 1}, "correct horse battery staple")
        with self.assertRaisesRegex(ValueError, "密码错误"):
            sync.decrypt_vault(blob, "wrong password here")

    def test_merge_prefers_newer_record(self):
        old = {"updatedAt":"1","tables":{"holdings":[{"code":"1","name":"A","market_value":"10","updated_at":"2026-01-01"}]}}
        new = {"updatedAt":"2","tables":{"holdings":[{"code":"1","name":"A","market_value":"20","updated_at":"2026-02-01"}]}}
        merged = sync.merge_vaults(new, old)
        self.assertEqual(merged["tables"]["holdings"][0]["market_value"], "20")

    def test_coin_metadata_is_merged(self):
        local={"updatedAt":"2","tables":{"coins":[{"id":"coin-1","name":"A","updated_at":"2"}]}}
        merged=sync.merge_vaults(local,{"updatedAt":"1","tables":{}})
        self.assertEqual(merged["tables"]["coins"][0]["id"],"coin-1")

    def test_accounts_are_included_in_merge(self):
        local={"updatedAt":"2","tables":{"accounts":[{"name":"微信零钱","balance":"20","updated_at":"2"}]}}
        merged=sync.merge_vaults(local,{"updatedAt":"1","tables":{}})
        self.assertEqual(merged["tables"]["accounts"][0]["name"], "微信零钱")

    def test_holding_daily_snapshots_are_merged_by_day_and_code(self):
        local={"updatedAt":"2","tables":{"holding_snapshots":[
          {"day":"2026-08-25","holding_key":"050025","market_value":"1100","created_at":"2"}]}}
        merged=sync.merge_vaults(local,{"updatedAt":"1","tables":{"holding_snapshots":[
          {"day":"2026-08-25","holding_key":"050025","market_value":"1000","created_at":"1"}]}})
        self.assertEqual(len(merged["tables"]["holding_snapshots"]), 1)
        self.assertEqual(merged["tables"]["holding_snapshots"][0]["market_value"], "1100")

    def test_github_sync_uses_bundled_ca_certificates(self):
        vault = sync.GitHubVault("owner/repo", "token")
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"content":"", "sha":"x"}'
        with mock.patch.object(sync.urllib.request, "urlopen", return_value=response) as opened:
            vault.download()
        self.assertIs(opened.call_args.kwargs["context"], sync.SSL_CONTEXT)

    def test_github_connection_error_is_readable(self):
        vault = sync.GitHubVault("owner/repo", "token")
        with mock.patch.object(sync.urllib.request, "urlopen",
                               side_effect=urllib.error.URLError("TLS failed")):
            with self.assertRaisesRegex(ValueError, "GitHub同步连接失败：TLS failed"):
                vault.download()

    def test_sync_uses_github_cli_credentials(self):
        with mock.patch.object(sync.shutil, "which", return_value="/usr/local/bin/gh"), \
             mock.patch.object(sync.Path, "is_file", return_value=True), \
             mock.patch.object(sync.subprocess, "check_output", return_value="cli-token\n"):
            self.assertEqual(sync.github_cli_token(), "cli-token")

    def test_missing_github_cli_login_is_readable(self):
        with mock.patch.object(sync.shutil, "which", return_value=None), \
             mock.patch.object(sync.Path, "is_file", return_value=False):
            with self.assertRaisesRegex(ValueError, "gh auth login"):
                sync.github_cli_token()

if __name__ == "__main__": unittest.main()
