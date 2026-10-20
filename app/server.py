"""零依赖 HTTP 服务：静态页 + /api/check。"""

from __future__ import annotations

import json
import mimetypes
import pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from .config import ROOT, config
from .pipeline import check, domains, samples
from .share import fingerprint, render_html
from .version import VERSION_HISTORY, __version__

WEB_DIR = ROOT / "web"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = f"DetectiveAgent/{__version__}"

    def log_message(self, fmt: str, *args) -> None:  # 安静一点
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    # ---------- 基础响应 ----------
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    @staticmethod
    def _first(query: dict, key: str, default: str = "") -> str:
        return (query.get(key) or [default])[0]

    def _static(self, path: pathlib.Path) -> None:
        if not path.exists() or not path.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = MIME.get(path.suffix.lower()) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype)

    # ---------- 路由 ----------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        query = parse_qs(parsed.query)

        if route in ("/", "/index.html"):
            self._static(WEB_DIR / "index.html")
            return
        if route == "/api/health":
            self._json(200, {
                "ok": True,
                "version": __version__,
                "version_notes": VERSION_HISTORY[-1] if VERSION_HISTORY else {},
                "provider": config.resolved_provider,
                "has_wsa": config.has_wsa,
                "stance_engine": config.resolved_stance_engine,
                "has_llm": config.has_llm,
                "mode": config.mode,
                "cnt": config.cnt,
            })
            return
        if route == "/api/domains":
            self._json(200, {"domains": domains()})
            return
        if route == "/api/samples":
            self._json(200, {"samples": samples(self._first(query, "domain", "general"))})
            return
        if route == "/api/check":
            q = self._first(query, "q")
            override = self._first(query, "provider")
            domain = self._first(query, "domain", "general")
            try:
                self._json(200, check(q, override, domain))
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        if route == "/api/card":
            q = self._first(query, "q")
            override = self._first(query, "provider")
            domain = self._first(query, "domain", "general")
            want_file = self._first(query, "download") in ("1", "true", "yes")
            try:
                card = check(q, override, domain)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})
                return
            body = render_html(card).encode("utf-8")
            if want_file:
                fp = fingerprint(card)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Disposition", f'attachment; filename="card-{fp}.html"')
                self.end_headers()
                self.wfile.write(body)
            else:
                self._send(200, body, "text/html; charset=utf-8")
            return
        if route.startswith("/static/"):
            self._static(WEB_DIR / route[len("/static/"):])
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")


def serve(host: str | None = None, port: int | None = None) -> None:
    host = host or config.host
    port = port or config.port
    httpd = ThreadingHTTPServer((host, port), Handler)
    provider = config.resolved_provider
    engine = config.resolved_stance_engine
    print("=" * 62)
    print("  AI元宝大侦探 · 查得到、信得过")
    print(f"  检索层：{provider}" + ("（未检测到腾讯云密钥，已切离线样例）" if provider == "mock" else "（元宝搜索 SearchPro）"))
    print(f"  判定引擎：{engine}" + ("（未配置模型，走词典兜底）" if engine == "lexicon" else "（语义判定 + 引用逐字校验）"))
    print(f"  地址：  http://{host}:{port}/")
    print(f"  API：   http://{host}:{port}/api/check?q=微波炉加热食物会致癌吗")
    print(f"  静态卡：http://{host}:{port}/api/card?q=微波炉加热食物会致癌吗")
    print("  Ctrl+C 停止")
    print("=" * 62)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
