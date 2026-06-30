import httpx
import pytest
import respx

from dealpos_mcp import tools
from dealpos_mcp.client import DealPOSClient, DealPOSError
from dealpos_mcp.config import Settings


def _token():
    respx.post("https://doubledeer.dealpos.co.id/api/v3/Token/OAuth2").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 1000}))


# --- sales reports (plan Task 5) ---

@respx.mock
async def test_get_sales_summary_returns_totals_and_top(client):
    _token()
    respx.get("https://doubledeer.dealpos.co.id/api/v3/Report/ProductSold").mock(
        return_value=httpx.Response(200, json=[
            {"Variant": "Vinyl A", "Code": "VA", "Quantity": 10, "NetSales": 3500000},
            {"Variant": "Vinyl B", "Code": "VB", "Quantity": 4, "NetSales": 1200000}]))
    out = await tools.get_sales_summary(client, date_from="2026-06-23", date_to="2026-06-29")
    assert out["total_qty"] == 14
    assert out["total_net_sales"] == 4700000
    assert out["top_item"]["Variant"] == "Vinyl A"
    assert len(out["items"]) == 2


# --- low-stock inventory (plan Task 6) ---

@respx.mock
async def test_check_low_stock_uses_threshold_then_fallback(client):
    _token()
    respx.get("https://doubledeer.dealpos.co.id/api/v3/Inventory").mock(
        return_value=httpx.Response(200, json=[
            {"Product": "Record X", "Code": "RX", "I": {"Available": 2, "Threshold": 5}},
            {"Product": "Record Y", "Code": "RY", "I": {"Available": 9, "Threshold": 5}},
            {"Product": "Record Z", "Code": "RZ", "I": {"Available": 3, "Threshold": 0}}]))
    out = await tools.check_low_stock(client)
    codes = {i["Code"] for i in out["low_stock"]}
    assert codes == {"RX", "RZ"}   # RX below threshold; RZ below fallback(5); RY ok


# --- products read (plan Task 7) ---

@respx.mock
async def test_list_products_passes_required_paging(client):
    _token()
    route = respx.get("https://doubledeer.dealpos.co.id/api/v3/Product").mock(
        return_value=httpx.Response(200, json=[{"Name": "Vinyl A", "Code": "VA"}]))
    out = await tools.list_products(client, name="Vinyl")
    assert out[0]["Code"] == "VA"
    q = route.calls[0].request.url.params
    assert q["PageNumber"] == "1" and q["PageSize"] == "50" and q["Name"] == "Vinyl"


@respx.mock
async def test_get_product_by_code(client):
    _token()
    respx.get("https://doubledeer.dealpos.co.id/api/v3/Product/Code").mock(
        return_value=httpx.Response(200, json={"Name": "Vinyl A", "Code": "VA"}))
    out = await tools.get_product(client, code="VA")
    assert out["Name"] == "Vinyl A"
