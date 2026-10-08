import asyncio
import time

import httpx

from .config import Settings


class DealPOSError(Exception):
    """Friendly, user-facing DealPOS API error."""


# DealPOS uses POST for a few pure reads. Any other non-GET is a write and is
# blocked while Settings.read_only is on. A new read-via-POST endpoint must be added
# here, otherwise it fails closed with the read-only error below.
_READ_ONLY_POSTS = {"/api/v3/Report/DailySales", "/api/v3/Inventory/CodeArray"}


class DealPOSClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._http = httpx.AsyncClient(base_url=settings.base_url, timeout=30.0)

    async def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        r = await self._http.post("/api/v3/Token/OAuth2", json={
            "client_id": self.s.client_id, "client_secret": self.s.client_secret})
        if r.status_code != 200:
            raise DealPOSError("DealPOS auth failed — check DEALPOS_CLIENT_ID / SECRET.")
        data = r.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    async def request(self, method: str, path: str, *, params: dict | None = None,
                      json: dict | None = None, _max_retries: int = 3):
        if self.s.read_only and method.upper() != "GET" and path not in _READ_ONLY_POSTS:
            raise DealPOSError(
                f"Read-only mode: {method.upper()} {path} writes to DealPOS and was blocked. "
                "Set DEALPOS_READ_ONLY=false to enable write tools.")
        for attempt in range(_max_retries + 1):
            token = await self._get_token()
            r = await self._http.request(method, path, params=params, json=json,
                                         headers={"Authorization": f"Bearer {token}"})
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
            return r.json()
        raise DealPOSError("DealPOS API error: retries exhausted.")

    async def aclose(self) -> None:
        await self._http.aclose()
