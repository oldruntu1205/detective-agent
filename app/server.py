"""零依赖 HTTP 服务：静态页 + /api/check。"""

from __future__ import annotations

import json
import mimetypes
import pathlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import settings as settings_store
from .config import ROOT, config
from .pipeline import check, domains, samples
from .share import fingerprint, render_html
from .version import VERSION_HISTORY, __version__

MAX_BODY = 8 * 1024

WEB_DIR = ROOT / "web"
DOCS_DIR = ROOT / "docs"

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
        if route in ("/pitch", "/pitch.html"):
            # 路演页：自包含单文件，不依赖 /static
            self._static(DOCS_DIR / "pitch.html")
            return
        if route == "/api/health":
            self._json(200, {
                "ok": True,
                "version": __version__,
                "version_notes": VERSION_HISTORY[-1] if VERSION_HISTORY else {},
                "provider": config.resolved_provider,
                "has_wsa": config.has_wsa,
                "secret_id_masked": settings_store.mask_secret_id(config.secret_id),
                "provider_setting": config.provider,
                "stance_engine": config.resolved_stance_engine,
                "has_llm": config.has_llm,
                "mode": config.mode,
                "cnt": config.cnt,
            })
            return
        if route == "/api/settings":
            # 只读状态：脱敏 SecretId、SecretKey 只报「是否已保存」
            self._json(200, settings_store.status())
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

    # ---------- 元宝搜索设置 ----------
    def _read_json(self) -> tuple[dict, str]:
        """只收本站发来的小体量 JSON。

        三道闸门，防的是「别的网页偷偷往 localhost 发 POST 改配置」这种顺手攻击：
        必须是 application/json（跨站想躲预检只能发 text/plain 之类的简单请求）、
        Origin 必须与 Host 一致、体积不超过 8KB。
        """
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return {}, "请求必须是 application/json"

        origin = (self.headers.get("Origin") or "").strip()
        if origin:
            parsed = urlparse(origin)
            if parsed.netloc.lower() != (self.headers.get("Host") or "").lower():
                return {}, "拒绝跨站请求"

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}, "Content-Length 无效"
        if length <= 0:
            return {}, "请求体为空"
        if length > MAX_BODY:
            return {}, "请求体过大"

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}, "请求体不是合法 JSON"
        if not isinstance(payload, dict):
            return {}, "请求体必须是 JSON 对象"
        return payload, ""

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        if route == "/api/settings":
            self._handle_settings()
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def _handle_settings(self) -> None:
        payload, err = self._read_json()
        if err:
            self._json(400, {"ok": False, "error": err})
            return

        action = str(payload.get("action") or "save").strip().lower()
        sid = str(payload.get("secret_id") or "").strip()
        skey = str(payload.get("secret_key") or "").strip()

        if action == "clear":
            result = settings_store.clear()
            self._json(200, {"ok": True, "action": "clear", **result})
            return

        if action == "test":
            # 没填就用已保存的那一对——「刚保存完想再验一次」是最常见的用法
            test_sid = sid or config.secret_id
            test_skey = skey or config.secret_key
            if not test_sid or not test_skey:
                self._json(400, {"ok": False, "error": "还没有可测试的密钥，先填写或保存一次"})
                return
            probe = settings_store.probe(test_sid, test_skey)
            self._json(200, {
                "ok": bool(probe.get("ok")),
                "action": "test",
                "probe": probe,
                "tested_saved": not sid and not skey,
                "status": settings_store.status(),
            })
            return

        if action != "save":
            self._json(400, {"ok": False, "error": f"未知动作：{action}"})
            return

        if not sid or not skey:
            self._json(400, {"ok": False, "error": "SecretId 和 SecretKey 要一起填"})
            return
        if len(sid) > settings_store.MAX_LEN or len(skey) > settings_store.MAX_LEN:
            self._json(400, {"ok": False, "error": "密钥长度异常，检查是不是粘多了内容"})
            return

        result = settings_store.save(sid, skey)
        warning = "" if settings_store.looks_like_secret_id(sid) else (
            "SecretId 通常以 AKID 开头，格式看着不太对，保存是成功的，建议点「测试连接」确认"
        )
        self._json(200, {
            "ok": True,
            "action": "save",
            "warning": warning,
            **result,
        })


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
    print("  密钥：  页面右上角「元宝搜索设置」直接填，或手改项目根目录 .env")
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
