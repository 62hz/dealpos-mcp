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


# --- create product (plan Task 8) ---

@respx.mock
async def test_create_product_builds_required_body(client):
    _token()
    route = respx.post("https://doubledeer.dealpos.co.id/api/v3/Product").mock(
        return_value=httpx.Response(200, json={"Code": "VINYL-001"}))
    out = await tools.create_product(client, name="New Vinyl", code="VINYL-001",
                                     category="Music/Vinyl", brand="Double Deer",
                                     unit_price=350000, unit_cost=200000, stock=20)
    assert out["Code"] == "VINYL-001"
    body = route.calls[0].request.content.decode()
    assert '"Name":"New Vinyl"' in body or '"Name": "New Vinyl"' in body
    assert "Variants" in body


async def test_create_product_requires_price():
    c = DealPOSClient(Settings(subdomain="x", client_id="a", client_secret="b"))
    with pytest.raises(DealPOSError):
        await tools.create_product(c, name="x", code="y", category="c", brand="b",
                                   unit_price=None)  # type: ignore[arg-type]


# --- update product price (plan Task 9) ---

@respx.mock
async def test_update_product_price_sends_full_product_body(client):
    _token()
    respx.get("https://doubledeer.dealpos.co.id/api/v3/Product/Code").mock(
        return_value=httpx.Response(200, json={
            "Category": "Music/Vinyl", "Name": "Vinyl A", "Brand": "DD", "Code": "VA",
            "Discontinued": False, "ImageURL": "",
            "Variants": [{"Model": "Standard", "Code": "VA", "UnitCost": 100000,
                          "UnitPrice": 300000, "Discontinued": False}]}))
    route = respx.put("https://doubledeer.dealpos.co.id/api/v3/Product").mock(
        return_value=httpx.Response(200, json={"Code": "VA"}))
    out = await tools.update_product_price(client, code="VA", new_price=420000)
    assert out["Code"] == "VA"
    body = route.calls[0].request.content.decode()
    assert "420000" in body


# --- create customer (plan Task 10) ---

@respx.mock
async def test_create_customer_fetches_newcode_when_missing(client):
    _token()
    respx.get("https://doubledeer.dealpos.co.id/api/v3/Customer/NewCode").mock(
        return_value=httpx.Response(200, json={"Code": "CUST-009"}))
    route = respx.post("https://doubledeer.dealpos.co.id/api/v3/Customer").mock(
        return_value=httpx.Response(200, json={"Code": "CUST-009", "Name": "Rian"}))
    out = await tools.create_customer(client, name="Rian", email="rian@example.com",
                                      mobile_phone="08123456789")
    assert out["Code"] == "CUST-009"
    body = route.calls[0].request.content.decode()
    assert "CUST-009" in body and "Active" in body
