"""Encrypted, local-first GitHub sync for Shiguang.

GitHub only receives one AES-256-GCM encrypted blob. The passphrase never leaves
the device and the GitHub token is delegated to the OS credential store.
"""
import base64
import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.getenv("SHIGUANG_DATA_DIR", str(ROOT / "data"))) / "sync-config.json"
MAGIC = "SGV1"
AAD = b"shiguang-vault-v1"
ITERATIONS = 600_000
SERVICE = "shiguang-portfolio"


def _key(password, salt, iterations=ITERATIONS):
    if not password:
        raise ValueError("同步密码不能为空")
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=iterations, backend=default_backend()).derive(password.encode("utf-8"))


def encrypt_vault(payload, password):
    salt, nonce = os.urandom(16), os.urandom(12)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    cipher = AESGCM(_key(password, salt)).encrypt(nonce, raw, AAD)
    return json.dumps({"magic": MAGIC, "kdf": "PBKDF2-SHA256", "iterations": ITERATIONS,
      "salt": base64.b64encode(salt).decode(), "nonce": base64.b64encode(nonce).decode(),
      "ciphertext": base64.b64encode(cipher).decode()}, separators=(",", ":")).encode()


def decrypt_vault(blob, password):
    try:
        envelope = json.loads(blob)
        if envelope.get("magic") != MAGIC:
            raise ValueError("不支持的保险库格式")
        salt = base64.b64decode(envelope["salt"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        cipher = base64.b64decode(envelope["ciphertext"], validate=True)
        raw = AESGCM(_key(password, salt, int(envelope["iterations"]))).decrypt(nonce, cipher, AAD)
        return json.loads(raw)
    except InvalidTag:
        raise ValueError("同步密码错误或数据已损坏")
    except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith(("同步", "不支持")):
            raise
        raise ValueError("保险库文件已损坏")


def export_data(db_path):
    conn = sqlite3.connect(str(db_path)); conn.row_factory = sqlite3.Row
    try:
        tables = {}
        for name in ("holdings", "health_daily", "portfolio_snapshots", "coins", "coin_collection"):
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            tables[name] = [dict(r) for r in conn.execute("SELECT * FROM " + name)] if exists else []
        return {"schemaVersion": 1, "updatedAt": datetime.now(timezone.utc).isoformat(), "tables": tables}
    finally:
        conn.close()


def _record_key(table, row):
    if table in ("health_daily", "portfolio_snapshots"):
        return str(row["day"])
    if table == "coins": return str(row["id"])
    if table == "coin_collection": return str(row["coin_id"])
    return str(row.get("code") or "name:" + row["name"])


def merge_vaults(local, remote):
    if not remote:
        return local
    result = {"schemaVersion": 1, "updatedAt": max(local.get("updatedAt", ""), remote.get("updatedAt", "")), "tables": {}}
    for table in ("holdings", "health_daily", "portfolio_snapshots", "coins", "coin_collection"):
        merged = {}
        for source in (remote, local):
            for row in source.get("tables", {}).get(table, []):
                key = _record_key(table, row)
                previous = merged.get(key)
                stamp = row.get("updated_at") or row.get("created_at") or source.get("updatedAt", "")
                old_stamp = (previous or {}).get("updated_at") or (previous or {}).get("created_at") or ""
                if previous is None or stamp >= old_stamp:
                    merged[key] = row
        result["tables"][table] = list(merged.values())
    return result


def import_data(db_path, payload):
    conn = sqlite3.connect(str(db_path))
    try:
        for row in payload["tables"].get("holdings", []):
            existing = conn.execute("SELECT id FROM holdings WHERE code=? OR name=? LIMIT 1",
                                    (row.get("code"), row["name"])).fetchone()
            values = (row.get("code"), row["name"], row.get("category", "未分类"),
                      row["market_value"], row.get("cost", "0"), row["updated_at"])
            if existing:
                conn.execute("UPDATE holdings SET code=?,name=?,category=?,market_value=?,cost=?,updated_at=? WHERE id=?",
                             values + (existing[0],))
            else:
                conn.execute("INSERT INTO holdings(code,name,category,market_value,cost,updated_at) VALUES(?,?,?,?,?,?)", values)
        for row in payload["tables"].get("health_daily", []):
            conn.execute("INSERT OR REPLACE INTO health_daily VALUES(?,?,?,?,?,?,?,?)", tuple(row.get(k) for k in
              ("day","steps","sleep_minutes","resting_heart_rate","active_energy","weight","source","updated_at")))
        for row in payload["tables"].get("portfolio_snapshots", []):
            conn.execute("INSERT OR REPLACE INTO portfolio_snapshots VALUES(?,?,?,?)", tuple(row.get(k) for k in
              ("day","market_value","source","created_at")))
        for row in payload["tables"].get("coins", []):
            conn.execute("INSERT OR REPLACE INTO coins VALUES(?,?,?,?,?,?,?,?,?,?)",tuple(row.get(k) for k in ("id","name","series","issue_year","face_value","material","image_path","image_source","image_license","updated_at")))
        for row in payload["tables"].get("coin_collection", []):
            conn.execute("INSERT OR REPLACE INTO coin_collection VALUES(?,?,?,?,?,?,?,?)",tuple(row.get(k) for k in ("coin_id","quantity","grade","purchase_price","estimated_value","storage_location","notes","updated_at")))
        conn.commit()
    finally:
        conn.close()


class GitHubVault:
    def __init__(self, repo, token, branch="main", path="vault.enc"):
        if "/" not in repo or not token:
            raise ValueError("请配置 owner/repository 和 GitHub 令牌")
        self.url = "https://api.github.com/repos/%s/contents/%s" % (repo.strip("/"), path)
        self.token, self.branch = token, branch

    def _request(self, method="GET", data=None):
        request = urllib.request.Request(self.url + "?ref=" + self.branch if method == "GET" else self.url,
          data=json.dumps(data).encode() if data else None, method=method,
          headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
                   "User-Agent": "shiguang-desktop"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and method == "GET": return None
            raise ValueError("GitHub同步失败（HTTP %s）" % exc.code)

    def download(self):
        result = self._request()
        return (base64.b64decode(result["content"]), result["sha"]) if result else (None, None)

    def upload(self, blob, sha=None):
        data = {"message": "sync: update encrypted vault", "content": base64.b64encode(blob).decode(), "branch": self.branch}
        if sha: data["sha"] = sha
        return self._request("PUT", data)


def load_config():
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else {"repo": "", "branch": "main", "path": "vault.enc"}


def save_config(config):
    CONFIG.parent.mkdir(exist_ok=True)
    safe = {"repo": str(config.get("repo", "")), "branch": str(config.get("branch", "main")), "path": "vault.enc"}
    CONFIG.write_text(json.dumps(safe, ensure_ascii=False, indent=2))
    return safe


def store_token(repo, token):
    import keyring
    keyring.set_password(SERVICE, repo, token)


def get_token(repo):
    import keyring
    return keyring.get_password(SERVICE, repo)


def sync(db_path, password, token=None):
    config = load_config(); token = token or get_token(config["repo"])
    github = GitHubVault(config["repo"], token, config["branch"], config["path"])
    local = export_data(db_path); remote_blob, sha = github.download()
    remote = decrypt_vault(remote_blob, password) if remote_blob else None
    merged = merge_vaults(local, remote)
    import_data(db_path, merged)
    github.upload(encrypt_vault(merged, password), sha)
    return {"ok": True, "records": sum(len(v) for v in merged["tables"].values()), "at": merged["updatedAt"]}
