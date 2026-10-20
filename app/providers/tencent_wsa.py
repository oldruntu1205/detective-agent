"""元宝搜索（腾讯云 wsa）的 SearchPro 调用。

接口事实（来自官方文档，2026-10 核对）：
  域名    wsa.tencentcloudapi.com
  Action  SearchPro
  Version 2025-05-08
  入参    Query(必填) / Mode / Site / Cnt / Industry / Freshness / Deeplinks
  出参    Response.Pages 为字符串数组，每个元素是一条结果的 JSON 字符串
  鉴权    TC3-HMAC-SHA256

这里用标准库手写签名，避免为了跑一个 demo 去装 SDK。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ..models import SearchHit
from .base import Provider, SearchError

HOST = "wsa.tencentcloudapi.com"
ACTION = "SearchPro"
VERSION = "2025-05-08"
SERVICE = "wsa"
CONTENT_TYPE = "application/json; charset=utf-8"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def build_headers(secret_id: str, secret_key: str, payload: str, region: str = "") -> dict[str, str]:
    now = int(time.time())
    date = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")

    signed_headers = "content-type;host"
    canonical_headers = f"content-type:{CONTENT_TYPE}\nhost:{HOST}\n"
    canonical_request = "\n".join([
        "POST", "/", "", canonical_headers, signed_headers, _sha256_hex(payload.encode("utf-8")),
    ])
    scope = f"{date}/{SERVICE}/tc3_request"
    string_to_sign = "\n".join([
        "TC3-HMAC-SHA256", str(now), scope, _sha256_hex(canonical_request.encode("utf-8")),
    ])
    k_date = _hmac(("TC3" + secret_key).encode("utf-8"), date)
    k_service = _hmac(k_date, SERVICE)
    k_signing = _hmac(k_service, "tc3_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    headers = {
        "Authorization": (
            f"TC3-HMAC-SHA256 Credential={secret_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
        "Content-Type": CONTENT_TYPE,
        "Host": HOST,
        "X-TC-Action": ACTION,
        "X-TC-Version": VERSION,
        "X-TC-Timestamp": str(now),
    }
    if region:
        headers["X-TC-Region"] = region
    return headers


def _to_hit(item: dict) -> SearchHit:
    level = item.get("authority_level")
    try:
        level_int = int(level) if level is not None else None
    except (TypeError, ValueError):
        level_int = None
    try:
        score = float(item.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return SearchHit(
        title=str(item.get("title") or "").strip(),
        url=str(item.get("url") or "").strip(),
        site=str(item.get("site") or "").strip(),
        date=str(item.get("date") or "").strip(),
        passage=str(item.get("passage") or "").strip(),
        content=str(item.get("content") or "").strip(),
        score=score,
        authority_level=level_int,
        favicon=str(item.get("favicon") or "").strip(),
    )


class TencentWsaProvider(Provider):
    name = "wsa"

    def __init__(self, secret_id: str, secret_key: str, *, region: str = "", mode: int = 2,
                 cnt: int = 10, freshness: str = "", industry: str = "", timeout: int = 15) -> None:
        if not secret_id or not secret_key:
            raise SearchError("缺少 TENCENTCLOUD_SECRET_ID / TENCENTCLOUD_SECRET_KEY，无法调用元宝搜索")
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.region = region
        self.mode = mode
        self.cnt = cnt
        self.freshness = freshness
        self.industry = industry
        self.timeout = timeout

    def _payload(self, query: str) -> dict:
        payload: dict = {"Query": query}
        if self.mode in (0, 1, 2):
            payload["Mode"] = self.mode
        if self.cnt in (10, 20, 30, 40, 50):
            payload["Cnt"] = self.cnt
        if self.freshness:
            payload["Freshness"] = self.freshness
        if self.industry:
            payload["Industry"] = self.industry
        return payload

    def search(self, query: str, domain: str = "") -> list[SearchHit]:
        body = json.dumps(self._payload(query), ensure_ascii=False)
        url = f"https://{HOST}/"
        request = urllib.request.Request(
            url, data=body.encode("utf-8"), method="POST",
            headers=build_headers(self.secret_id, self.secret_key, body, self.region),
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise SearchError(f"元宝搜索 HTTP {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise SearchError(f"无法连接元宝搜索：{exc.reason}") from exc
        except TimeoutError as exc:
            raise SearchError("元宝搜索请求超时") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SearchError(f"元宝搜索返回非 JSON：{raw[:200]}") from exc

        response = data.get("Response") or {}
        if "Error" in response:
            err = response["Error"]
            raise SearchError(
                f"元宝搜索错误 {err.get('Code')}：{err.get('Message')}"
                f"（RequestId: {response.get('RequestId', '-')}）"
            )

        pages = response.get("Pages") or []
        hits: list[SearchHit] = []
        for page in pages:
            try:
                item = json.loads(page) if isinstance(page, str) else page
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                hits.append(_to_hit(item))
        if not hits:
            raise SearchError(
                f"元宝搜索返回 0 条结果（Version={response.get('Version')}, Msg={response.get('Msg')}）"
            )
        return hits
