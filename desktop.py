"""Windows/macOS desktop entry point. Falls back to the system browser."""
import threading
import webbrowser
from http.server import ThreadingHTTPServer
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
