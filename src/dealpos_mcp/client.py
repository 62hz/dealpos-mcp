import asyncio
import collections
import time
from importlib.metadata import PackageNotFoundError, version

import httpx

from .config import Settings

try:
    USER_AGENT = f"dealpos-mcp/{version('dealpos-mcp')}"
except PackageNotFoundError:  # run from a bare source tree
    USER_AGENT = "dealpos-mcp/unknown"


class DealPOSError(Exception):
    """Friendly, user-facing DealPOS API error."""


# DealPOS uses POST for a few pure reads. Any other non-GET is a write and is
# blocked while Settings.read_only is on. A new read-via-POST endpoint must be added
# here, otherwise it fails closed with the read-only error below.
_READ_ONLY_POSTS = {"/api/v3/Report/DailySales", "/api/v3/Inventory/CodeArray"}


class _SlidingWindow:
    """At most `permits` acquisitions in any `window` seconds; extra callers wait their turn."""

    def __init__(self, permits: int, window: float, clock=time.monotonic, sleep=asyncio.sleep):
        self.permits, self.window = permits, window
        self._clock, self._sleep = clock, sleep
        self._stamps: collections.deque[float] = collections.deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self.permits <= 0:  # limiter switched off
            return
        async with self._lock:
            while True:
                now = self._clock()
                while self._stamps and now - self._stamps[0] >= self.window:
                    self._stamps.popleft()
                if len(self._stamps) < self.permits:
                    self._stamps.append(now)
                    return
                await self._sleep(self._stamps[0] + self.window - now)


class DealPOSClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._http = httpx.AsyncClient(base_url=settings.base_url, timeout=30.0,
                                       headers={"User-Agent": USER_AGENT})
        self._limiter = _SlidingWindow(settings.rate_permits, settings.rate_window)

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        await self._limiter.acquire()  # the token call counts against the API limit too
        r = await self._http.post("/api/v3/Token/OAuth2", json={
            "client_id": self.s.client_id, "client_secret": self.s.client_secret})
        if r.status_code == 429:
            raise DealPOSError("DealPOS rate limit hit on the token call (50 requests per "
                               "180 s, shared by every app on this account). Wait ~3 minutes.")
        if r.status_code >= 500:
            raise DealPOSError(f"DealPOS is unavailable (HTTP {r.status_code} on the token "
                               "call). Not a credentials problem; retry later.")
        if r.status_code != 200:
            raise DealPOSError("DealPOS auth failed — check DEALPOS_CLIENT_ID / SECRET.")
        data = r.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    async def request(self, method: str, path: str, *, params: dict | None = None,
                      json: dict | None = None, headers: dict | None = None,
                      _max_retries: int = 3):
        if self.s.read_only and method.upper() != "GET" and path not in _READ_ONLY_POSTS:
            raise DealPOSError(
                f"Read-only mode: {method.upper()} {path} writes to DealPOS and was blocked. "
                "Set DEALPOS_READ_ONLY=false to enable write tools.")
        for attempt in range(_max_retries + 1):
            token = await self._get_token()
            await self._limiter.acquire()
            try:
                r = await self._http.request(method, path, params=params, json=json,
                                             headers={**(headers or {}),
                                                      "Authorization": f"Bearer {token}"})
            except httpx.TransportError as e:
                if method.upper() == "GET":
                    raise DealPOSError(f"Network error talking to DealPOS "
                                       f"({type(e).__name__}); retry.") from e
                raise DealPOSError(
                    f"Network error during {method.upper()} {path} ({type(e).__name__}): the "
                    "write may or may not have landed. Check before retrying (e.g. "
                    "list_adjustments / get_product).") from e
            if r.status_code == 429 and attempt < _max_retries:
                await asyncio.sleep(float(r.headers.get("Retry-After", "1")))
                continue
            if r.status_code == 401:
                self._token = None  # force refresh next loop
                if attempt < _max_retries:
                    continue
            if r.status_code >= 400:
                try:
                    msg = r.json().get("Message", r.text)
                except Exception:
                    msg = r.text
                raise DealPOSError(f"DealPOS API error ({r.status_code}): {msg}")
            try:
                return r.json()
            except ValueError:  # a successful write may answer plain text
                return r.text
        raise DealPOSError("DealPOS API error: retries exhausted.")

    async def aclose(self) -> None:
        await self._http.aclose()
