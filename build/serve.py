"""本地预览服务器：只读托管 public/，顺手打印局域网地址方便手机看。

用法：
    python build/serve.py            # http://127.0.0.1:8765
    python build/serve.py --port 9000 --host 0.0.0.0
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socket
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"

NO_STORE = (".html", ".json", ".js", ".css", ".webmanifest")


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        path = self.path.split("?", 1)[0]
        if path.endswith(NO_STORE) or path == "/":
            self.send_header("Cache-Control", "no-store, must-revalidate")
        else:
            self.send_header("Cache-Control", "public, max-age=3600")
        super().end_headers()

    def log_message(self, fmt, *args):  # 安静一点
        sys.stderr.write("  %s\n" % (fmt % args))


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--open", action="store_true")
    args = ap.parse_args()

    handler = functools.partial(Handler, directory=str(PUBLIC))

    port = args.port
    httpd = None
    for candidate in range(port, port + 12):
        try:
            httpd = socketserver.ThreadingTCPServer((args.host, candidate), handler)
            httpd.allow_reuse_address = True
            port = candidate
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit(f"端口 {args.port}-{args.port + 11} 都被占用了")

    url = f"http://127.0.0.1:{port}/"
    print(f"连板天梯  →  {url}")
    if args.host in ("0.0.0.0", ""):
        print(f"手机同 Wi-Fi 打开  →  http://{lan_ip()}:{port}/")
    print("Ctrl+C 停止")
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
