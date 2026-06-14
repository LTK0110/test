"""レート制限とリトライ付きの HTTP クライアント.

SEC EDGAR は秒間リクエスト数の上限 (約 10 req/s) と User-Agent を要求するため、
スレッド間で共有できるトークン制御を内蔵する。テスト時は ``transport`` を
差し替えることでネットワーク無しに動作を検証できる。
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

import requests


class RateLimiter:
    """単純なスレッドセーフのレートリミッタ (最小リクエスト間隔を保証)."""

    def __init__(self, per_second: float):
        self.min_interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_allowed = max(now, self._next_allowed) + self.min_interval


# transport は (url, params, headers, timeout) -> requests.Response 相当を返す callable。
Transport = Callable[[str, Optional[Dict[str, Any]], Dict[str, str], float], Any]


class HttpClient:
    """JSON 取得に特化した HTTP クライアント."""

    def __init__(
        self,
        user_agent: str,
        rate_limit_per_sec: float = 8.0,
        timeout: float = 30.0,
        max_retries: int = 3,
        transport: Optional[Transport] = None,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries
        self.limiter = RateLimiter(rate_limit_per_sec)
        self._session = requests.Session()
        self._transport = transport or self._default_transport

    def _default_transport(self, url, params, headers, timeout):
        return self._session.get(url, params=params, headers=headers, timeout=timeout)

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET してパースした JSON を返す。失敗時は指数バックオフでリトライ。"""
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            self.limiter.acquire()
            try:
                resp = self._transport(url, params, headers, self.timeout)
                status = getattr(resp, "status_code", 200)
                if status == 404:
                    return None
                if status == 429 or status >= 500:
                    raise requests.HTTPError(f"HTTP {status} for {url}")
                if status >= 400:
                    raise requests.HTTPError(f"HTTP {status} for {url}: {getattr(resp, 'text', '')[:200]}")
                return resp.json()
            except Exception as exc:  # noqa: BLE001 - リトライ対象として捕捉
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
        assert last_exc is not None
        raise last_exc
