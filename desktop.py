"""Windows/macOS desktop entry point. Falls back to the system browser."""
import os
import platform
import threading
import webbrowser
from pathlib import Path
from http.server import ThreadingHTTPServer

system = platform.system()
if system == "Darwin":
    data_dir = Path.home() / "Library" / "Application Support" / "Shiguang"
elif system == "Windows":
    data_dir = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "Shiguang"
else:
    data_dir = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "shiguang"
data_dir.mkdir(parents=True, exist_ok=True)
os.environ["SHIGUANG_DATA_DIR"] = str(data_dir)

from server import Handler, db


def main():
    db().close()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = "http://127.0.0.1:%d" % httpd.server_port
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        import webview
        webview.create_window("拾光·个人管理", url, width=1280, height=820, min_size=(900, 640))
        webview.start(private_mode=False)
    except ImportError:
        webbrowser.open(url)
        input("拾光已在浏览器打开，按回车退出…")
    finally:
        httpd.shutdown()


if __name__ == "__main__": main()
