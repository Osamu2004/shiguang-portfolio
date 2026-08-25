"""Encrypted, local-first GitHub sync for Shiguang.

GitHub only receives one AES-256-GCM encrypted blob. The passphrase never leaves
the device and the GitHub token is delegated to the OS credential store.
"""
import base64
import json
import os
import shutil
import sqlite3
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import certifi
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.getenv("SHIGUANG_DATA_DIR", str(ROOT / "data"))) / "sync-config.json"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
MAGIC = "SGV1"
AAD = b"shiguang-vault-v1"
ITERATIONS = 600_000


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
        for name in ("accounts", "holdings", "holding_snapshots", "fund_market_daily", "fund_strategies", "user_preferences", "health_daily", "portfolio_snapshots", "coins", "coin_collection", "graded_coins", "scholar_profiles", "scholar_snapshots", "scholar_papers", "scholar_paper_snapshots", "audit_logs", "deleted_records"):
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
            tables[name] = [dict(r) for r in conn.execute("SELECT * FROM " + name)] if exists else []
        return {"schemaVersion": 1, "updatedAt": datetime.now(timezone.utc).isoformat(), "tables": tables}
    finally:
        conn.close()


def _record_key(table, row):
    if table in ("health_daily", "portfolio_snapshots"):
        return str(row["day"])
    if table == "holding_snapshots": return str(row["day"]) + ":" + str(row["holding_key"])
    if table == "fund_market_daily": return str(row["code"]) + ":" + str(row["day"])
    if table == "fund_strategies": return str(row["code"])
    if table == "user_preferences": return str(row["id"])
    if table in ("coins", "graded_coins"): return str(row["id"])
    if table == "scholar_profiles": return str(row["profile_id"])
    if table == "scholar_snapshots": return str(row["profile_id"])+":"+str(row["day"])
    if table == "scholar_papers": return str(row["profile_id"])+":"+str(row["paper_id"])
    if table == "scholar_paper_snapshots": return str(row["profile_id"])+":"+str(row["paper_id"])+":"+str(row["day"])
    if table == "coin_collection": return str(row["coin_id"])
    if table == "audit_logs": return str(row["id"])
    if table == "deleted_records": return str(row["table_name"]) + ":" + str(row["record_key"])
    return str(row.get("code") or "name:" + row["name"])


def merge_vaults(local, remote):
    if not remote:
        return local
    result = {"schemaVersion": 1, "updatedAt": max(local.get("updatedAt", ""), remote.get("updatedAt", "")), "tables": {}}
    for table in ("accounts", "holdings", "holding_snapshots", "fund_market_daily", "fund_strategies", "user_preferences", "health_daily", "portfolio_snapshots", "coins", "coin_collection", "graded_coins", "scholar_profiles", "scholar_snapshots", "scholar_papers", "scholar_paper_snapshots", "audit_logs", "deleted_records"):
        merged = {}
        for source in (remote, local):
            for row in source.get("tables", {}).get(table, []):
                key = _record_key(table, row)
                previous = merged.get(key)
                stamp = row.get("updated_at") or row.get("created_at") or row.get("deleted_at") or source.get("updatedAt", "")
                old_stamp = (previous or {}).get("updated_at") or (previous or {}).get("created_at") or (previous or {}).get("deleted_at") or ""
                if previous is None or stamp >= old_stamp:
                    merged[key] = row
        result["tables"][table] = list(merged.values())
    return result


def import_data(db_path, payload):
    conn = sqlite3.connect(str(db_path))
    try:
        for row in payload["tables"].get("accounts", []):
            conn.execute("""INSERT INTO accounts(name,account_type,platform,balance,updated_at)
              VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET account_type=excluded.account_type,
              platform=excluded.platform,balance=excluded.balance,updated_at=excluded.updated_at""",
              tuple(row.get(k) for k in ("name","account_type","platform","balance","updated_at")))
        for row in payload["tables"].get("holdings", []):
            existing = conn.execute("SELECT id FROM holdings WHERE code=? OR name=? LIMIT 1",
                                    (row.get("code"), row["name"])).fetchone()
            values = (row.get("code"), row["name"], row.get("category", "未分类"),
                      row["market_value"], row.get("cost", "0"), row["updated_at"], row.get("archived_at"),
                      row.get("holding_profit", "0.00"), row.get("return_rate", "0.00"))
            if existing:
                conn.execute("UPDATE holdings SET code=?,name=?,category=?,market_value=?,cost=?,updated_at=?,archived_at=?,holding_profit=?,return_rate=? WHERE id=?",
                             values + (existing[0],))
            else:
                conn.execute("INSERT INTO holdings(code,name,category,market_value,cost,updated_at,archived_at,holding_profit,return_rate) VALUES(?,?,?,?,?,?,?,?,?)", values)
        for row in payload["tables"].get("holding_snapshots", []):
            conn.execute("INSERT OR REPLACE INTO holding_snapshots VALUES(?,?,?,?,?,?,?,?,?)", tuple(row.get(k) for k in
              ("day","holding_key","code","name","market_value","holding_profit","return_rate","source","created_at")))
        for row in payload["tables"].get("fund_market_daily", []):
            conn.execute("INSERT OR REPLACE INTO fund_market_daily VALUES(?,?,?,?,?,?,?)", tuple(row.get(k) for k in
              ("code","day","unit_nav","cumulative_nav","daily_change_pct","source","fetched_at")))
        for row in payload["tables"].get("fund_strategies", []):
            conn.execute("INSERT OR REPLACE INTO fund_strategies VALUES(?,?,?,?,?,?)", tuple(row.get(k) for k in
              ("code","mode","daily_amount","per_drop_pct_amount","max_daily_amount","updated_at")))
        for row in payload["tables"].get("user_preferences", []):
            conn.execute("INSERT OR REPLACE INTO user_preferences VALUES(?,?,?,?,?)", tuple(row.get(k) for k in
              ("id","show_health","show_coins","show_research","updated_at")))
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
        for row in payload["tables"].get("graded_coins", []):
            conn.execute("INSERT OR REPLACE INTO graded_coins VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", tuple(row.get(k) for k in
              ("id","grading_company","certificate_no","coin_name","issue_year","grade","label_type","purchase_price","estimated_value","storage_location","notes","updated_at")))
        for row in payload["tables"].get("scholar_profiles", []):
            conn.execute("INSERT OR REPLACE INTO scholar_profiles VALUES(?,?,?,?,?,?)",tuple(row.get(k) for k in ("profile_id","name","affiliation","interests","profile_url","updated_at")))
        for row in payload["tables"].get("scholar_snapshots", []):
            conn.execute("INSERT OR REPLACE INTO scholar_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)",tuple(row.get(k) for k in ("profile_id","day","citations_all","citations_recent","h_index_all","h_index_recent","i10_all","i10_recent","yearly_citations","captured_at")))
        for row in payload["tables"].get("scholar_papers", []):
            conn.execute("INSERT OR REPLACE INTO scholar_papers VALUES(?,?,?,?,?,?,?,?)",tuple(row.get(k) for k in ("profile_id","paper_id","title","authors","venue","publication_year","url","updated_at")))
        for row in payload["tables"].get("scholar_paper_snapshots", []):
            conn.execute("INSERT OR REPLACE INTO scholar_paper_snapshots VALUES(?,?,?,?,?)",tuple(row.get(k) for k in ("profile_id","paper_id","day","citations","captured_at")))
        for row in payload["tables"].get("audit_logs", []):
            conn.execute("INSERT OR IGNORE INTO audit_logs VALUES(?,?,?,?,?)", tuple(row.get(k) for k in
              ("id","event_type","summary","details","created_at")))
        for row in payload["tables"].get("deleted_records", []):
            conn.execute("INSERT OR REPLACE INTO deleted_records VALUES(?,?,?)", tuple(row.get(k) for k in
              ("table_name","record_key","deleted_at")))
            if row.get("table_name") == "holding_snapshots" and ":" in row.get("record_key", ""):
                day, key = row["record_key"].split(":", 1)
                conn.execute("DELETE FROM holding_snapshots WHERE day=? AND holding_key=?", (day, key))
            if row.get("table_name") == "holdings":
                conn.execute("DELETE FROM holdings WHERE code=?", (row.get("record_key"),))
            if row.get("table_name") == "graded_coins":
                conn.execute("DELETE FROM graded_coins WHERE id=?", (row.get("record_key"),))
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
            with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404 and method == "GET": return None
            raise ValueError("GitHub同步失败（HTTP %s）" % exc.code)
        except urllib.error.URLError as exc:
            raise ValueError("GitHub同步连接失败：%s" % exc.reason)

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


def github_cli_token():
    candidates = [shutil.which("gh"), "/opt/homebrew/bin/gh", "/usr/local/bin/gh"]
    for executable in candidates:
        if not executable or not Path(executable).is_file():
            continue
        try:
            token = subprocess.check_output([executable, "auth", "token"],
                stderr=subprocess.DEVNULL, timeout=8, text=True).strip()
            if token:
                return token
        except (OSError, subprocess.SubprocessError):
            continue
    raise ValueError("未找到 GitHub 登录凭据，请先在终端执行 gh auth login")


def sync(db_path, password, token=None):
    config = load_config(); token = token or github_cli_token()
    github = GitHubVault(config["repo"], token, config["branch"], config["path"])
    local = export_data(db_path); remote_blob, sha = github.download()
    remote = decrypt_vault(remote_blob, password) if remote_blob else None
    merged = merge_vaults(local, remote)
    import_data(db_path, merged)
    github.upload(encrypt_vault(merged, password), sha)
    return {"ok": True, "records": sum(len(v) for v in merged["tables"].values()), "at": merged["updatedAt"]}
