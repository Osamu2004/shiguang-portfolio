"""Signed-by-hash desktop updater backed by private GitHub Releases."""
import hashlib
import json
import os
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import certifi

VERSION = "0.5.5"
REPO = "Osamu2004/shiguang-portfolio"
SERVICE = "shiguang-updates"
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


def _token():
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
    try:
        import keyring
        return keyring.get_password(SERVICE, REPO)
    except Exception:
        pass
    return None


def store_token(token):
    import keyring
    keyring.set_password(SERVICE, REPO, token.strip())


def _request(url, token=None):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + (token or _token() or ""), "User-Agent": "shiguang-updater",
        "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
            return response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise ValueError("无法读取私有更新，请填写具有 Releases 读取权限的 GitHub Token")
        raise ValueError("检查更新失败（HTTP %s）" % exc.code)
    except urllib.error.URLError as exc:
        raise ValueError("更新服务网络连接失败：%s" % (exc.reason or "未知网络错误"))
    except (TimeoutError, socket.timeout):
        raise ValueError("更新服务连接超时，请检查网络后重试")


def _version_tuple(value):
    try: return tuple(int(x) for x in value.lstrip("v").split("."))
    except ValueError: return (0,)


def check(token=None):
    raw, _ = _request("https://api.github.com/repos/%s/releases/latest" % REPO, token)
    release = json.loads(raw)
    latest = release.get("tag_name", "").lstrip("v")
    asset_name = "Shiguang-macOS.zip" if platform.system() == "Darwin" else "Shiguang-Windows.zip"
    assets = {x["name"]: x for x in release.get("assets", [])}
    return {"current": VERSION, "latest": latest, "available": _version_tuple(latest) > _version_tuple(VERSION),
            "notes": release.get("body", ""), "asset": assets.get(asset_name), "checksum": assets.get(asset_name + ".sha256")}


def _download(asset, token, target):
    request = urllib.request.Request(asset["url"], headers={"Accept": "application/octet-stream",
        "Authorization": "Bearer " + token, "User-Agent": "shiguang-updater"})
    with urllib.request.urlopen(request, timeout=120, context=SSL_CONTEXT) as response, open(target, "wb") as output:
        shutil.copyfileobj(response, output)


def stage_and_install(token=None):
    if not getattr(sys, "frozen", False):
        raise ValueError("开发模式不执行自动替换，请使用桌面安装包")
    token = token or _token()
    info = check(token)
    if not info["available"]: return {"ok": True, "message": "已是最新版本"}
    if not info["asset"] or not info["checksum"]: raise ValueError("该版本缺少更新包或校验文件")
    root = Path(tempfile.mkdtemp(prefix="shiguang-update-")); archive = root / "update.zip"
    checksum_file = root / "update.sha256"
    _download(info["asset"], token, archive); _download(info["checksum"], token, checksum_file)
    expected = checksum_file.read_text().strip().split()[0].lower()
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if expected != actual: raise ValueError("更新包校验失败，已停止安装")
    extracted = root / "new"; extracted.mkdir(); zipfile.ZipFile(archive).extractall(extracted)
    pid = str(os.getpid())
    if platform.system() == "Windows":
        target = Path(sys.executable).parent; source = extracted / "Shiguang"
        script = root / "install.cmd"
        script.write_text('@echo off\r\ntimeout /t 2 /nobreak >nul\r\nrobocopy "{}" "{}" /MIR >nul\r\nstart "" "{}"\r\n'.format(source, target, target / "Shiguang.exe"))
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x08000000)
    elif platform.system() == "Darwin":
        target = Path(sys.executable).parents[2]; source = extracted / "Shiguang.app"
        script = root / "install.sh"
        script.write_text('#!/bin/sh\nsleep 2\nrm -rf "{0}.old"\nmv "{0}" "{0}.old"\ncp -R "{1}" "{0}"\nxattr -dr com.apple.quarantine "{0}"\nopen "{0}"\n'.format(target, source))
        script.chmod(0o700); subprocess.Popen(["/bin/sh", str(script)], start_new_session=True)
    else: raise ValueError("当前系统暂不支持自动安装")
    return {"ok": True, "message": "更新已下载，应用即将重启"}
