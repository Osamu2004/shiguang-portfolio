import importlib.util
import tempfile
import unittest
from pathlib import Path

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

if __name__ == "__main__": unittest.main()
