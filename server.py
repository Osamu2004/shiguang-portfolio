#!/usr/bin/env python3
"""拾光投资 - 零依赖的本地投资组合服务。"""
import base64
import cgi
import hashlib
import json
import mimetypes
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
UPLOADS = DATA / "uploads"
DB = DATA / "portfolio.db"
MAX_IMAGE = 8 * 1024 * 1024
ALLOWED = {"image/jpeg", "image/png", "image/webp"}


def db():
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE IF NOT EXISTS holdings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, name TEXT NOT NULL,
      category TEXT NOT NULL DEFAULT '宽基指数', market_value TEXT NOT NULL,
      cost TEXT NOT NULL DEFAULT '0', updated_at TEXT NOT NULL,
      UNIQUE(code), UNIQUE(name)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS imports (
      id TEXT PRIMARY KEY, created_at TEXT NOT NULL, image_path TEXT,
      status TEXT NOT NULL, result_json TEXT NOT NULL
    )""")
    return conn


def money(value):
    try:
        result = Decimal(str(value).replace(",", "").replace("¥", "").strip())
        if result < 0 or result > Decimal("100000000000"):
            raise ValueError()
        return str(result.quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        raise ValueError("金额格式不正确")


def normalize_name(value):
    return re.sub(r"[\s·・()（）\-_]", "", value or "").lower()


def clean_item(raw):
    name = str(raw.get("name", "")).strip()[:80]
    if not name:
        raise ValueError("缺少基金名称")
    code = re.sub(r"\D", "", str(raw.get("code", "")))[:6]
    confidence = str(raw.get("confidence", "low")).lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "low"
    return {"code": code, "name": name, "market_value": money(raw.get("market_value", 0)),
            "confidence": confidence}


def parse_model_json(text):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("视觉模型未返回JSON")
    payload = json.loads(text[start:end + 1])
    return [clean_item(item) for item in payload.get("holdings", [])]


def scan_with_vision(blob, mime):
    key = os.getenv("VISION_API_KEY", "").strip()
    if not key:
        return [
            {"code": "000001", "name": "演示·宽基指数联接A", "market_value": "3280.50", "confidence": "high"},
            {"code": "000002", "name": "演示·红利低波联接C", "market_value": "1680.00", "confidence": "medium"},
        ], True
    endpoint = os.getenv("VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
    model = os.getenv("VISION_MODEL", "qwen-vl-max")
    prompt = """你是金融持仓截图转写器。只转写截图中每一只真实基金的名称、六位代码和当前持有市值；跳过总资产、总收益等汇总行。
不要推测被遮挡的数字。仅返回JSON：{"holdings":[{"code":"","name":"","market_value":0,"confidence":"high|medium|low"}]}。"""
    body = json.dumps({"model": model, "temperature": 0.1, "messages": [
        {"role": "system", "content": prompt},
        {"role": "user", "content": [{"type": "text", "text": "请识别这张持仓截图"},
                                     {"type": "image_url", "image_url": {"url": "data:%s;base64,%s" % (mime, base64.b64encode(blob).decode())}}]}
    ]}).encode()
    request = urllib.request.Request(endpoint + "/chat/completions", data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read())
    return parse_model_json(payload["choices"][0]["message"]["content"]), False


def diff_holdings(current, parsed):
    by_code = {r["code"]: r for r in current if r["code"]}
    by_name = {normalize_name(r["name"]): r for r in current}
    matched = set()
    result = []
    for item in parsed:
        old = by_code.get(item["code"]) if item["code"] else None
        old = old or by_name.get(normalize_name(item["name"]))
        if old:
            matched.add(old["id"])
            action = "unchanged" if Decimal(old["market_value"]) == Decimal(item["market_value"]) else "update"
            result.append({**item, "action": action, "old_value": old["market_value"], "holding_id": old["id"]})
        else:
            result.append({**item, "action": "new", "old_value": "0.00", "holding_id": None})
    for old in current:
        if old["id"] not in matched:
            result.append({"code": old["code"] or "", "name": old["name"], "market_value": "0.00",
                           "confidence": "medium", "action": "missing", "old_value": old["market_value"],
                           "holding_id": old["id"]})
    return result


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        clean = path.split("?", 1)[0].lstrip("/") or "index.html"
        return str(STATIC / clean)

    def json_response(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > 1024 * 1024:
            raise ValueError("请求过大")
        return json.loads(self.rfile.read(size) or b"{}")

    def do_GET(self):
        if self.path == "/api/state":
            with db() as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM holdings ORDER BY market_value + 0 DESC")]
            total = sum(Decimal(r["market_value"]) for r in rows)
            self.json_response({"holdings": rows, "total": str(total), "demoVision": not bool(os.getenv("VISION_API_KEY"))})
            return
        super().do_GET()

    def do_POST(self):
        try:
            if self.path == "/api/holdings":
                item = clean_item(self.read_json())
                now = datetime.now().isoformat(timespec="seconds")
                with db() as conn:
                    conn.execute("INSERT INTO holdings(code,name,category,market_value,cost,updated_at) VALUES(?,?,?,?,?,?)",
                                 (item["code"] or None, item["name"], "宽基指数", item["market_value"], item["market_value"], now))
                self.json_response({"ok": True})
                return
            if self.path == "/api/import/scan":
                self.handle_scan()
                return
            if self.path == "/api/import/confirm":
                self.handle_confirm()
                return
            self.json_response({"error": "未知接口"}, 404)
        except Exception as exc:
            self.json_response({"error": str(exc)}, 400)

    def handle_scan(self):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("请上传图片")
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers,
                                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type})
        field = form["image"] if "image" in form else None
        if field is None or not getattr(field, "file", None):
            raise ValueError("未选择截图")
        blob = field.file.read(MAX_IMAGE + 1)
        mime = field.type or mimetypes.guess_type(field.filename or "")[0] or ""
        if mime not in ALLOWED or len(blob) > MAX_IMAGE or len(blob) < 32:
            raise ValueError("仅支持8MB以内的 JPG、PNG 或 WebP")
        import_id = hashlib.sha256(blob + os.urandom(12)).hexdigest()[:16]
        UPLOADS.mkdir(parents=True, exist_ok=True)
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[mime]
        image_path = UPLOADS / (import_id + suffix)
        image_path.write_bytes(blob)
        parsed, demo = scan_with_vision(blob, mime)
        with db() as conn:
            current = [dict(r) for r in conn.execute("SELECT * FROM holdings")]
            changes = diff_holdings(current, parsed)
            conn.execute("INSERT INTO imports VALUES(?,?,?,?,?)", (import_id, datetime.now().isoformat(), str(image_path), "review", json.dumps(changes, ensure_ascii=False)))
        self.json_response({"importId": import_id, "changes": changes, "demo": demo})

    def handle_confirm(self):
        payload = self.read_json()
        import_id = str(payload.get("importId", ""))
        items = payload.get("items", [])
        now = datetime.now().isoformat(timespec="seconds")
        with db() as conn:
            record = conn.execute("SELECT * FROM imports WHERE id=? AND status='review'", (import_id,)).fetchone()
            if not record:
                raise ValueError("导入不存在或已确认")
            for raw in items:
                if not raw.get("apply", True):
                    continue
                action = raw.get("action")
                if action == "missing":
                    if raw.get("archive", False):
                        conn.execute("DELETE FROM holdings WHERE id=?", (raw.get("holding_id"),))
                    continue
                item = clean_item(raw)
                old_id = raw.get("holding_id")
                if old_id:
                    conn.execute("UPDATE holdings SET code=?,name=?,market_value=?,updated_at=? WHERE id=?",
                                 (item["code"] or None, item["name"], item["market_value"], now, old_id))
                else:
                    conn.execute("INSERT INTO holdings(code,name,market_value,cost,updated_at) VALUES(?,?,?,?,?)",
                                 (item["code"] or None, item["name"], item["market_value"], item["market_value"], now))
            conn.execute("UPDATE imports SET status='confirmed' WHERE id=?", (import_id,))
        if payload.get("deleteImage", True) and record["image_path"]:
            Path(record["image_path"]).unlink(missing_ok=True)
        self.json_response({"ok": True})


def main():
    port = int(os.getenv("PORT", "8787"))
    db().close()
    print("拾光投资已启动: http://127.0.0.1:%d" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
