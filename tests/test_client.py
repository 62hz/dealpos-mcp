import httpx
import pytest
import respx

from dealpos_mcp.client import DealPOSError


@respx.mock
async def test_get_token_caches_until_expiry(client):
    route = respx.post("https://doubledeer.dealpos.co.id/api/v3/Token/OAuth2").mock(
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
    respx.post("https://doubledeer.dealpos.co.id/api/v3/Token/OAuth2").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 1000}))


@respx.mock
async def test_request_injects_bearer_and_returns_json(client):
    _mock_token()
    route = respx.get("https://doubledeer.dealpos.co.id/api/v3/Inventory").mock(
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
    respx.get("https://doubledeer.dealpos.co.id/api/v3/Outlet").mock(
        return_value=httpx.Response(200, json=[{"Name": "MF Store"}]))
    respx.post("https://doubledeer.dealpos.co.id/api/v3/Inventory/CodeArray").mock(
        return_value=httpx.Response(200, json=[{"Code": "A1"}]))
    assert await c.request("GET", "/api/v3/Outlet") == [{"Name": "MF Store"}]
    assert await c.request("POST", "/api/v3/Inventory/CodeArray", json={"Codes": ["A1"]}) \
        == [{"Code": "A1"}]


@respx.mock
async def test_writes_pass_when_read_only_off(client):
    _mock_token()
    respx.put("https://doubledeer.dealpos.co.id/api/v3/Product").mock(
        return_value=httpx.Response(200, json={"ok": True}))
    assert await client.request("PUT", "/api/v3/Product", json={}) == {"ok": True}


@respx.mock
async def test_request_retries_on_429_then_succeeds(client):
    _mock_token()
    route = respx.get("https://doubledeer.dealpos.co.id/api/v3/Product").mock(
        side_effect=[httpx.Response(429, headers={"Retry-After": "0"}),
                     httpx.Response(200, json={"ok": True})])
    out = await client.request("GET", "/api/v3/Product", params={"PageNumber": 1, "PageSize": 1})
    assert out == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_request_maps_400_message_to_friendly_error(client):
    _mock_token()
    respx.get("https://doubledeer.dealpos.co.id/api/v3/Inventory").mock(
        return_value=httpx.Response(400, json={"Message": "PageSize must not exceed max allowed more than 500"}))
    with pytest.raises(DealPOSError) as e:
        await client.request("GET", "/api/v3/Inventory", params={"PageNumber": 1, "PageSize": 9999})
    assert "PageSize" in str(e.value)
