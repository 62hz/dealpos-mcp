import httpx
import pytest
import respx

from dealpos_mcp.client import DealPOSError


@respx.mock
async def test_get_token_caches_until_expiry(client):
    route = respx.post("https://example.dealpos.co.id/api/v3/Token/OAuth2").mock(
        return_value=httpx.Response(200, json={
            "token_type": "Bearer", "access_token": "tok-123", "expires_in": 172800,
            "expiredAt": "2026-07-02T00:00:00Z"})
    )
    t1 = await client._get_token()
    t2 = await client._get_token()   # second call must reuse cache
    assert t1 == "tok-123"
    assert t2 == "tok-123"
    assert route.call_count == 1


def _mock_token():
    respx.post("https://example.dealpos.co.id/api/v3/Token/OAuth2").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 1000}))


@respx.mock
async def test_request_injects_bearer_and_returns_json(client):
    _mock_token()
    route = respx.get("https://example.dealpos.co.id/api/v3/Inventory").mock(
        return_value=httpx.Response(200, json=[{"Code": "A1"}]))
    out = await client.request("GET", "/api/v3/Inventory", params={"PageNumber": 1, "PageSize": 10})
    assert out == [{"Code": "A1"}]
    assert route.calls[0].request.headers["authorization"] == "Bearer tok"


def _read_only_client():
    from dealpos_mcp.client import DealPOSClient
    from dealpos_mcp.config import Settings
    return DealPOSClient(Settings(client_id="cid", client_secret="sec", read_only=True,
                                  _env_file=None))


@respx.mock
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "post"])
async def test_read_only_blocks_writes_before_any_network_call(method):
    # no routes mocked: if the guard let it through, respx would raise on the unmocked call
    with pytest.raises(DealPOSError, match="Read-only mode"):
        await _read_only_client().request(method, "/api/v3/Product", json={})


@respx.mock
async def test_read_only_allows_get_and_read_via_post():
    c = _read_only_client()
    _mock_token()
    respx.get("https://example.dealpos.co.id/api/v3/Outlet").mock(
        return_value=httpx.Response(200, json=[{"Name": "Main Store"}]))
    respx.post("https://example.dealpos.co.id/api/v3/Inventory/CodeArray").mock(
        return_value=httpx.Response(200, json=[{"Code": "A1"}]))
    assert await c.request("GET", "/api/v3/Outlet") == [{"Name": "Main Store"}]
    assert await c.request("POST", "/api/v3/Inventory/CodeArray", json={"Codes": ["A1"]}) \
        == [{"Code": "A1"}]


@respx.mock
async def test_writes_pass_when_read_only_off(client):
    _mock_token()
    respx.put("https://example.dealpos.co.id/api/v3/Product").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    assert await client.request("PUT", "/api/v3/Product", json={}) == {"ok": True}


@respx.mock
async def test_request_retries_on_429_then_succeeds(client):
    _mock_token()
    route = respx.get("https://example.dealpos.co.id/api/v3/Product").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "0"}),
                     httpx.Response(200, json={"ok": True})])
    out = await client.request("GET", "/api/v3/Product", params={"PageNumber": 1, "PageSize": 1})
    assert out == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_request_maps_400_message_to_friendly_error(client):
    _mock_token()
    respx.get("https://example.dealpos.co.id/api/v3/Inventory").mock(
        return_value=httpx.Response(400, json={"Message": "PageSize must not exceed max allowed more than 500"}))
    with pytest.raises(DealPOSError) as e:
        await client.request("GET", "/api/v3/Inventory", params={"PageNumber": 1, "PageSize": 9999})
    assert "PageSize" in str(e.value)


# --- rate limiter (DealPOS allows 50 requests / 180 s with no queue) ---

def _fake_time():
    """A clock plus a sleep that advances it, so limiter tests take no real time."""
    t = [0.0]
    sleeps: list[float] = []

    async def sleep(s):
        sleeps.append(s)
        t[0] += s

    return (lambda: t[0]), sleep, sleeps


async def test_limiter_makes_the_extra_caller_wait_for_the_window():
    from dealpos_mcp.client import _SlidingWindow
    clock, sleep, sleeps = _fake_time()
    w = _SlidingWindow(2, 10, clock, sleep)
    for _ in range(3):
        await w.acquire()
    assert sleeps == [10.0]       # third call waited until the first two aged out
    await w.acquire()             # window slid: a free slot again, no more waiting
    assert sleeps == [10.0]


async def test_limiter_zero_permits_switches_it_off():
    from dealpos_mcp.client import _SlidingWindow
    clock, sleep, sleeps = _fake_time()
    w = _SlidingWindow(0, 10, clock, sleep)
    for _ in range(100):
        await w.acquire()
    assert sleeps == []


@respx.mock
async def test_client_counts_the_token_call_and_throttles_requests(client):
    from dealpos_mcp.client import _SlidingWindow
    _mock_token()
    respx.get("https://example.dealpos.co.id/api/v3/Outlet").mock(
        return_value=httpx.Response(200, json=[]))
    clock, sleep, sleeps = _fake_time()
    client._limiter = _SlidingWindow(2, 10, clock, sleep)
    await client.request("GET", "/api/v3/Outlet")   # token + request = both permits
    assert sleeps == []
    await client.request("GET", "/api/v3/Outlet")   # token cached, but no permit left
    assert sleeps == [10.0]


TOKEN_URL = "https://example.dealpos.co.id/api/v3/Token/OAuth2"


@pytest.mark.parametrize("status, needle", [
    (429, "rate limit"), (503, "unavailable"), (401, "check DEALPOS_CLIENT_ID")])
@respx.mock
async def test_token_error_names_its_cause(client, status, needle):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(status, json={}))
    with pytest.raises(DealPOSError, match=needle):
        await client._get_token()


@respx.mock
async def test_post_transport_error_says_the_write_may_have_landed(client):
    _mock_token()
    respx.post("https://example.dealpos.co.id/api/v3/Adjustment").mock(
        side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(DealPOSError, match="may or may not"):
        await client.request("POST", "/api/v3/Adjustment", json={})


@respx.mock
async def test_get_transport_error_is_a_friendly_retry(client):
    _mock_token()
    respx.get("https://example.dealpos.co.id/api/v3/Outlet").mock(
        side_effect=httpx.ConnectError("down"))
    with pytest.raises(DealPOSError, match="retry") as e:
        await client.request("GET", "/api/v3/Outlet")
    assert "may or may not" not in str(e.value)


@respx.mock
async def test_non_json_success_body_is_returned_as_text(client):
    _mock_token()
    respx.post("https://example.dealpos.co.id/api/v3/Product").mock(
        return_value=httpx.Response(200, text="Success"))
    assert await client.request("POST", "/api/v3/Product", json={}) == "Success"


@respx.mock
async def test_every_call_identifies_the_app_in_user_agent(client):
    """DealPOS will reject calls without an identifying User-Agent from 2027."""
    token = respx.post("https://example.dealpos.co.id/api/v3/Token/OAuth2").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 1000}))
    api = respx.get("https://example.dealpos.co.id/api/v3/Inventory").mock(
        return_value=httpx.Response(200, json=[]))
    await client.request("GET", "/api/v3/Inventory")
    for route in (token, api):
        assert route.calls[0].request.headers["user-agent"].startswith("dealpos-mcp/")
