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
            {"Name": "Vinyl A", "Code": "VA", "Quantity": 10,
             "Cost": 2000000, "Sales": 3500000, "Profit": 1500000},
            {"Name": "Vinyl B", "Code": "VB", "Quantity": 4,
             "Cost": 700000, "Sales": 1200000, "Profit": 500000}]))
    out = await tools.get_sales_summary(client, date_from="2026-06-23", date_to="2026-06-29")
    assert out["total_qty"] == 14
    assert out["total_net_sales"] == 4700000
    assert out["top_item"]["Name"] == "Vinyl A"
    assert out["total_cost"] == 2700000
    assert out["total_profit"] == 2000000
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
        return_value=httpx.Response(200, json={
            "DataArray": [{"Name": "Vinyl A", "Code": "VA"}], "RecordsCount": -1}))
    out = await tools.list_products(client, name="Vinyl", compact=False)
    assert out[0]["Code"] == "VA"
    q = route.calls[0].request.url.params
    assert q["PageNumber"] == "1" and q["PageSize"] == "500" and q["Name"] == "Vinyl"


@respx.mock
async def test_list_products_unwraps_dataarray_envelope(client):
    _token()
    respx.get("https://doubledeer.dealpos.co.id/api/v3/Product").mock(
        return_value=httpx.Response(200, json={
            "DataArray": [{"Code": "A"}, {"Code": "B"}], "RecordsCount": -1}))
    out = await tools.list_products(client, compact=False)
    assert [p["Code"] for p in out] == ["A", "B"]


@respx.mock
async def test_list_products_paginates_past_full_page(client):
    _token()
    route = respx.get("https://doubledeer.dealpos.co.id/api/v3/Product").mock(
        side_effect=[
            httpx.Response(200, json={"DataArray": [{"Code": str(i)} for i in range(500)],
                                       "RecordsCount": -1}),
            httpx.Response(200, json={"DataArray": [{"Code": "500"}], "RecordsCount": -1}),
        ])
    out = await tools.list_products(client)
    assert len(out) == 501
    assert route.call_count == 2
    assert route.calls[1].request.url.params["PageNumber"] == "2"


@respx.mock
async def test_get_product_by_code(client):
    _token()
    respx.get("https://doubledeer.dealpos.co.id/api/v3/Product/Code").mock(
        return_value=httpx.Response(200, json={"Name": "Vinyl A", "Code": "VA"}))
    out = await tools.get_product(client, code="VA")
    assert out["Name"] == "Vinyl A"


# --- get_variant_detail ---
#
# get_product's Variants[] is compact and does not carry Type or Components -- the exact
# fields that silently failed to apply on 2026-08-13 (a composite conversion left
# Type=Standard while Components stuck). That bug was only caught by shelling out to a
# raw script three times that day. This is the tool that should have existed already.

@respx.mock
async def test_get_variant_detail_by_code():
    _token()
    c = DealPOSClient(Settings(subdomain="doubledeer.dealpos.co.id", client_id="cid",
                               client_secret="sec", _env_file=None))
    respx.get(f"{BASE}/api/v3/Variant/Detail").mock(return_value=httpx.Response(200, json={
        "Code": "SYIN200PAIR-CW", "Type": "Composite", "Weight": 0,
        "Components": [{"Code": "SYIN200-CW", "Qty": 2}], "OutletPrice": []}))
    out = await tools.get_variant_detail(c, code="SYIN200PAIR-CW")
    assert out["Type"] == "Composite"
    assert out["Components"] == [{"Code": "SYIN200-CW", "Qty": 2}]


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


# ═══════════════════════════════════════════════════════
# NEW TOOLS — expansion (2026-07-09)
# ═══════════════════════════════════════════════════════

import json as _json


BASE = "https://doubledeer.dealpos.co.id"


# --- list_inventory exposed ---

@respx.mock
async def test_list_inventory_returns_rows(client):
    _token()
    respx.get(f"{BASE}/api/v3/Inventory").mock(
        return_value=httpx.Response(200, json=[
            {"Code": "A", "I": {"Available": 10}},
            {"Code": "B", "I": {"Available": 0}},
        ]))
    out = await tools.list_inventory(client)
    assert len(out) == 2
    assert out[0]["Code"] == "A"


@respx.mock
async def test_list_inventory_category_param(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Inventory").mock(
        return_value=httpx.Response(200, json=[]))
    await tools.list_inventory(client, category="Music/Vinyl")
    assert route.calls[0].request.url.params["Category"] == "Music/Vinyl"


@respx.mock
async def test_list_inventory_paginates_past_full_page(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Inventory").mock(
        side_effect=[
            httpx.Response(200, json=[{"Code": str(i)} for i in range(500)]),
            httpx.Response(200, json=[{"Code": "500"}]),
        ])
    out = await tools.list_inventory(client)
    assert len(out) == 501
    assert route.call_count == 2
    assert route.calls[1].request.url.params["PageNumber"] == "2"


# --- list_customers ---

@respx.mock
async def test_list_customers_returns_rows(client):
    _token()
    respx.get(f"{BASE}/api/v3/Customer").mock(
        return_value=httpx.Response(200, json=[{"Code": "C001", "Name": "Alice"}]))
    out = await tools.list_customers(client)
    assert out[0]["Code"] == "C001"


@respx.mock
async def test_list_customers_name_filter(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Customer").mock(
        return_value=httpx.Response(200, json=[]))
    await tools.list_customers(client, name="Alice")
    assert route.calls[0].request.url.params["Name"] == "Alice"


_CUSTOMERS = [
    {"Code": "C1", "Name": "Alice", "Email": "Alice@Test.com", "Mobile": "+62 812-1111"},
    {"Code": "C2", "Name": "Bob", "Email": "bob@test.com", "Mobile": "0813-2222"},
    {"Code": "C3", "Name": "Cy", "Email": None, "Mobile": None},
]


@respx.mock
async def test_list_customers_filters_email_and_phone_client_side(client):
    """Regression: DealPOS ignores Email/MobilePhone (returned all 168 live), and the
    phone column is `Mobile`. The filters must be applied here."""
    _token()
    route = respx.get(f"{BASE}/api/v3/Customer").mock(
        return_value=httpx.Response(200, json=_CUSTOMERS))
    assert [r["Code"] for r in await tools.list_customers(client, email="ALICE@test")] == ["C1"]
    assert [r["Code"] for r in await tools.list_customers(client, phone="0812 1111")] == []
    assert [r["Code"] for r in await tools.list_customers(client, phone="812-1111")] == ["C1"]
    p = route.calls[0].request.url.params
    assert "Email" not in p and "MobilePhone" not in p


@respx.mock
async def test_list_customers_pages_until_short_page(client):
    """Regression: only page 1 of 50 was read, hiding 118 of 168 customers."""
    _token()
    pages = {"1": [{"Code": "A"}, {"Code": "B"}], "2": [{"Code": "C"}]}
    route = respx.get(f"{BASE}/api/v3/Customer").mock(
        side_effect=lambda req: httpx.Response(200, json=pages.get(req.url.params["PageNumber"], [])))
    out = await tools.list_customers(client, page_size=2)
    assert [r["Code"] for r in out] == ["A", "B", "C"]
    assert [c.request.url.params["PageNumber"] for c in route.calls] == ["1", "2"]


@respx.mock
async def test_list_customers_non_list_response(client):
    _token()
    respx.get(f"{BASE}/api/v3/Customer").mock(
        return_value=httpx.Response(200, json={}))
    out = await tools.list_customers(client)
    assert out == []


# --- list_categories, list_outlets, list_suppliers ---

@respx.mock
async def test_list_categories(client):
    _token()
    respx.get(f"{BASE}/api/v3/Category").mock(
        return_value=httpx.Response(200, json=[{"ID": 1, "Name": "Vinyl"}]))
    out = await tools.list_categories(client)
    assert out[0]["Name"] == "Vinyl"


@respx.mock
async def test_list_outlets(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Outlet").mock(
        return_value=httpx.Response(200, json=[
            {"ID": "410ba2b7-8eff-4759-b5f1-cf47b33ef1cc", "Name": "MF Store",
             "Code": "B1", "Suspended": False}]))
    out = await tools.list_outlets(client)
    assert out[0]["Name"] == "MF Store"
    # bare GET 400s: Suspended is required and must be a bool-ish string
    assert route.calls[0].request.url.params["Suspended"] == "false"


@respx.mock
async def test_list_suppliers(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Supplier").mock(
        return_value=httpx.Response(200, json=[{"Code": "S01", "Name": "Distro"}]))
    out = await tools.list_suppliers(client)
    assert out[0]["Code"] == "S01"
    # Regression: the API 500s unless both paging params are sent.
    p = route.calls[0].request.url.params
    assert p["PageNumber"] == "1" and p["PageSize"] == "100"


@respx.mock
async def test_list_suppliers_paginates_until_a_short_page(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Supplier").mock(side_effect=[
        httpx.Response(200, json=[{"Code": "S01"}, {"Code": "S02"}]),
        httpx.Response(200, json=[{"Code": "S03"}]),
    ])
    out = await tools.list_suppliers(client, page_size=2)
    assert [s["Code"] for s in out] == ["S01", "S02", "S03"]
    assert route.calls[1].request.url.params["PageNumber"] == "2"


# --- get_writeoffs ---

@respx.mock
async def test_get_writeoffs_sums_total(client):
    _token()
    respx.get(f"{BASE}/api/v3/WriteOff/Invoice").mock(
        return_value=httpx.Response(200, json=[
            {"Amount": 10000, "Tag": "Biaya Admin Tiktok"}, {"Amount": 5000, "Tag": "Bad Debt"}]))
    out = await tools.get_writeoffs(client, "2026-01-01", "2026-06-30")
    assert out["total"] == 15000.0
    assert out["count"] == 2
    assert out["date_from"] == "2026-01-01"


@respx.mock
async def test_get_writeoffs_empty(client):
    _token()
    respx.get(f"{BASE}/api/v3/WriteOff/Invoice").mock(
        return_value=httpx.Response(200, json=[]))
    out = await tools.get_writeoffs(client, "2026-01-01", "2026-06-30")
    assert out["total"] == 0.0
    assert out["items"] == []


@respx.mock
async def test_get_writeoffs_date_params(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/WriteOff/Invoice").mock(
        return_value=httpx.Response(200, json=[]))
    await tools.get_writeoffs(client, "2026-06-01", "2026-06-30")
    p = route.calls[0].request.url.params
    assert p["From"] == "2026-06-01" and p["To"] == "2026-06-30"


# --- get_sales_summary: 100-row cap splitting and the request budget ---

def _product_sold_route(rows_for):
    """ProductSold mock: rows_for(day_count) -> the rows the API would return."""
    from datetime import date

    def handler(req):
        p = req.url.params
        days = (date.fromisoformat(p["To"]) - date.fromisoformat(p["From"])).days + 1
        return httpx.Response(200, json=rows_for(days))
    return respx.get(f"{BASE}/api/v3/Report/ProductSold").mock(side_effect=handler)


def _sold(n, qty=1):
    return [{"Code": f"C{i}", "Name": f"N{i}", "Quantity": qty, "Sales": 10 * qty,
             "Cost": 5 * qty, "Profit": 5 * qty} for i in range(n)]


@respx.mock
async def test_sales_summary_splits_a_capped_range_and_merges_by_code(client):
    _token()
    # Any multi-day range hits the 100-row cap; a single day has just 2 products.
    route = _product_sold_route(lambda days: _sold(100) if days > 1 else _sold(2))
    out = await tools.get_sales_summary(client, "2026-06-01", "2026-06-04")
    assert "truncated" not in out
    assert route.call_count == 7             # 1 + 2 + 4: whole range, halves, single days
    by_code = {r["Code"]: r["Quantity"] for r in out["items"]}
    assert by_code == {"C0": 4, "C1": 4}     # four days merged per code


@respx.mock
async def test_sales_summary_stops_at_the_request_budget_and_says_so(client, monkeypatch):
    """The API allows 50 requests / 180 s; a wide capped range must not fan out past it."""
    monkeypatch.setattr(tools, "_PRODUCT_SOLD_MAX_REQUESTS", 5)
    _token()
    route = _product_sold_route(lambda days: _sold(100))   # every range stays capped
    out = await tools.get_sales_summary(client, "2026-01-01", "2026-12-31")
    assert route.call_count <= 5
    assert out["truncated"] is True and "INCOMPLETE" in out["warning"]
    assert out["items"]                      # rows fetched before the budget ran out are kept


# --- list_invoices ---

def _outlets():
    """Mock the outlet lookup list_invoices needs to resolve OutletID."""
    respx.get(f"{BASE}/api/v3/Outlet").mock(
        return_value=httpx.Response(200, json=[
            {"ID": "410ba2b7-8eff-4759-b5f1-cf47b33ef1cc", "Name": "MF Store",
             "Code": "B1", "Suspended": False}]))


def _inv(n, amount, payment="Paid"):
    """Row shaped like a live Invoice/WithTotalCount row (keys checked 2026-11-08)."""
    return {"Number": f"BC.D8.0605{n:04d}", "Customer": "Walk-in", "Date": "2026-06-05T00:00:00",
            "Due": "2026-06-05T00:00:00", "Amount": amount, "Payment": payment,
            "Delivery": "Delivered", "Fulfillment": "Fulfilled", "ID": f"id-{n}"}


@respx.mock
async def test_list_invoices_sums_amount_from_envelope(client):
    """Regression: rows carry `Amount`; summing Total/GrandTotal gave total_net == 0."""
    _token(); _outlets()
    respx.get(f"{BASE}/api/v3/Invoice/WithTotalCount").mock(
        return_value=httpx.Response(200, json={
            "Data": [_inv(1, 100000), _inv(2, 50000, "Unpaid")], "TotalCount": 2}))
    out = await tools.list_invoices(client, date_from="2026-01-01", date_to="2026-06-30")
    assert out["total_net"] == 150000.0
    assert out["count"] == 2
    assert out["total_count"] == 2
    assert "truncated" not in out
    assert out["invoices"][1]["Payment"] == "Unpaid"  # rows pass through whole


@respx.mock
async def test_list_invoices_pages_until_total_count(client):
    _token(); _outlets()
    pages = {"1": [_inv(1, 10), _inv(2, 20)], "2": [_inv(3, 30)]}
    route = respx.get(f"{BASE}/api/v3/Invoice/WithTotalCount").mock(
        side_effect=lambda req: httpx.Response(200, json={
            "Data": pages.get(req.url.params["PageNumber"], []), "TotalCount": 3}))
    out = await tools.list_invoices(client, date_from="2026-06-01", date_to="2026-06-30",
                                    page_size=2)
    assert [c.request.url.params["PageNumber"] for c in route.calls] == ["1", "2"]
    assert out["count"] == 3 and out["total_net"] == 60.0
    assert "truncated" not in out


@respx.mock
async def test_list_invoices_warns_when_page_cap_hit(client):
    _token(); _outlets()
    respx.get(f"{BASE}/api/v3/Invoice/WithTotalCount").mock(
        return_value=httpx.Response(200, json={
            "Data": [_inv(1, 10), _inv(2, 20)], "TotalCount": 99}))
    out = await tools.list_invoices(client, date_from="2026-06-01", date_to="2026-06-30",
                                    page_size=2, max_pages=3)
    assert out["truncated"] is True
    assert "3 pages" in out["warning"] and "99" in out["warning"]
    assert out["count"] == 6


@respx.mock
async def test_list_invoices_sends_outlet_guid_not_name(client):
    """Regression: the endpoint 500s on an outlet NAME — it needs the GUID."""
    _token(); _outlets()
    route = respx.get(f"{BASE}/api/v3/Invoice/WithTotalCount").mock(
        return_value=httpx.Response(200, json={"Data": [], "TotalCount": 0}))
    await tools.list_invoices(client, date_from="2026-01-01", date_to="2026-06-30",
                              outlet="MF Store")
    p = route.calls[0].request.url.params
    assert p["OutletID"] == "410ba2b7-8eff-4759-b5f1-cf47b33ef1cc"
    assert "Outlet" not in p


@respx.mock
async def test_list_invoices_always_sends_paging_and_dates(client):
    """Regression: missing paging -> 400, missing dates -> 500."""
    _token(); _outlets()
    route = respx.get(f"{BASE}/api/v3/Invoice/WithTotalCount").mock(
        return_value=httpx.Response(200, json={"Data": [], "TotalCount": 0}))
    await tools.list_invoices(client, date_from="2026-06-01", date_to="2026-06-30")
    p = route.calls[0].request.url.params
    assert p["PageNumber"] == "1" and p["PageSize"] == "50"
    assert p["From"] == "2026-06-01" and p["To"] == "2026-06-30"


@respx.mock
async def test_list_invoices_unknown_outlet_raises(client):
    _token(); _outlets()
    with pytest.raises(DealPOSError, match="not found"):
        await tools.list_invoices(client, date_from="2026-06-01", date_to="2026-06-30",
                                  outlet="Nonexistent Outlet")


# --- get_receivables ---

def _recv_rows(overdue, recent):
    """Invoice rows as live Invoice/WithTotalCount returns them. Due 0001-01-01 = none."""
    none = "0001-01-01T00:00:00"
    return [
        dict(_inv(1, 500000, "Paid"), Due=overdue),       # paid: never a receivable
        dict(_inv(2, 100000, "Unpaid"), Due=overdue),
        dict(_inv(3, 200000, "Unpaid"), Due=recent),
        dict(_inv(4, 300000, "Unpaid"), Due=none),        # marketplace settlement, no due
        dict(_inv(5, 50000, "Partial"), Due=overdue),
        dict(_inv(6, 70000, "Exceed"), Due=overdue),      # overpaid: not owed to us
    ]


def _mock_invoices(rows):
    _token(); _outlets()
    return respx.get(f"{BASE}/api/v3/Invoice/WithTotalCount").mock(
        return_value=httpx.Response(200, json={"Data": rows, "TotalCount": len(rows)}))


@respx.mock
async def test_get_receivables_keeps_only_unpaid_and_partial(client):
    from datetime import date, timedelta
    d = lambda n: (date.today() - timedelta(days=n)).isoformat() + "T00:00:00"
    _mock_invoices(_recv_rows(d(15), d(2)))
    out = await tools.get_receivables(client)
    assert {r["Payment"] for r in out["receivables"]} == {"Unpaid", "Partial"}
    assert out["count"] == 4
    assert out["total"] == 100000 + 200000 + 300000 + 50000
    assert "Partial" in out["note"]
    assert "truncated" not in out


@respx.mock
async def test_get_receivables_days_overdue_and_filter(client):
    from datetime import date, timedelta
    d = lambda n: (date.today() - timedelta(days=n)).isoformat() + "T00:00:00"
    _mock_invoices(_recv_rows(d(15), d(2)))
    by_amount = {r["Amount"]: r["DaysOverdue"]
                 for r in (await tools.get_receivables(client))["receivables"]}
    assert by_amount[100000] == 15 and by_amount[200000] == 2
    assert by_amount[300000] is None  # 0001-01-01 sentinel is "no due date", not 740k days
    _mock_invoices(_recv_rows(d(15), d(2)))
    out = await tools.get_receivables(client, min_days_overdue=7)
    assert sorted(r["Amount"] for r in out["receivables"]) == [50000, 100000]


@respx.mock
async def test_get_receivables_default_window_is_a_year_with_big_pages(client):
    from datetime import date, timedelta
    route = _mock_invoices([])
    await tools.get_receivables(client)
    p = route.calls[0].request.url.params
    assert p["To"] == date.today().isoformat()
    assert p["From"] == (date.today() - timedelta(days=365)).isoformat()
    assert p["PageSize"] == "500"


@respx.mock
async def test_get_receivables_passes_through_truncation_warning(client):
    _token(); _outlets()
    respx.get(f"{BASE}/api/v3/Invoice/WithTotalCount").mock(
        return_value=httpx.Response(200, json={"Data": [_inv(1, 1, "Unpaid")] * 500,
                                               "TotalCount": 99999}))
    out = await tools.get_receivables(client)
    assert out["truncated"] is True and "warning" in out


# --- update_product ---

@respx.mock
async def test_update_product_merges_and_puts(client):
    _token()
    respx.get(f"{BASE}/api/v3/Product/Code").mock(
        return_value=httpx.Response(200, json={
            "Code": "P01", "Name": "Old Name", "Brand": "DD", "Variants": []}))
    route = respx.put(f"{BASE}/api/v3/Product").mock(
        return_value=httpx.Response(200, json={"Code": "P01"}))
    out = await tools.update_product(client, "P01", {"Name": "New Name"})
    assert out["Code"] == "P01"
    body = _json.loads(route.calls[0].request.content)
    assert body["Name"] == "New Name"
    assert body["Brand"] == "DD"        # existing field preserved


# --- get_inventory_by_codes ---

@respx.mock
async def test_get_inventory_by_codes_payload(client):
    _token()
    route = respx.post(f"{BASE}/api/v3/Inventory/CodeArray").mock(
        return_value=httpx.Response(200, json=[{"Code": "A"}, {"Code": "B"}]))
    out = await tools.get_inventory_by_codes(client, ["A", "B"])
    body = _json.loads(route.calls[0].request.content)
    assert body["Code"] == ["A", "B"]
    assert len(out) == 2


@respx.mock
async def test_get_inventory_by_codes_outlet(client):
    _token()
    route = respx.post(f"{BASE}/api/v3/Inventory/CodeArray").mock(
        return_value=httpx.Response(200, json=[]))
    await tools.get_inventory_by_codes(client, ["X"], outlet="MF01")
    req = route.calls[0].request
    assert _json.loads(req.content) == {"Code": ["X"]}   # no Outlet in the body
    assert req.url.params["Outlet"] == "MF01"


# --- get_inventory_log ---

@respx.mock
async def test_get_inventory_log_sends_code_only_no_paging(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Inventory/Log").mock(
        return_value=httpx.Response(200, json=[{"Code": "A", "Change": -1}]))
    out = await tools.get_inventory_log(client, "VNL-001")
    p = route.calls[0].request.url.params
    assert p["Code"] == "VNL-001"
    assert "PageNumber" not in p and "PageSize" not in p  # endpoint has no paging
    assert len(out) == 1


async def test_get_inventory_log_requires_a_code(client):
    """Live 400: the endpoint needs Code or VariantID."""
    with pytest.raises(DealPOSError, match="variant code"):
        await tools.get_inventory_log(client, "")


@respx.mock
async def test_get_inventory_log_outlet(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Inventory/Log").mock(
        return_value=httpx.Response(200, json=[]))
    await tools.get_inventory_log(client, "VNL-001", outlet="MF Store")
    assert route.calls[0].request.url.params["Outlet"] == "MF Store"


@respx.mock
async def test_get_inventory_log_code_and_dates(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Inventory/Log").mock(
        return_value=httpx.Response(200, json=[]))
    await tools.get_inventory_log(client, code="VNL-001",
                                   date_from="2026-01-01", date_to="2026-06-30")
    p = route.calls[0].request.url.params
    assert p["Code"] == "VNL-001"
    assert p["From"] == "2026-01-01"
    assert p["To"] == "2026-06-30"


# --- list_adjustments / get_adjustment ---

def _adj(n, state="Accepted", typ="Adjust"):
    """Row shaped like a live Adjustment list row (keys checked 2026-11-08)."""
    return {"ID": f"id-{n}", "Number": f"MFS-{n}", "Date": "2026-10-01T00:00:00",
            "Outlet": "MF Store", "Type": typ, "State": state, "QuantitySUM": -1,
            "SKUCount": 1, "TotalCost": 0, "PIC": "MF Web Checkout", "Note": "x"}


@respx.mock
async def test_list_adjustments_sends_filters_and_returns_rows(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Adjustment").mock(
        return_value=httpx.Response(200, json=[_adj(1), _adj(2)]))
    out = await tools.list_adjustments(client, "2026-10-01", "2026-10-31", outlet="MF Store",
                                       state="Accepted", adjustment_type="Adjust")
    p = route.calls[0].request.url.params
    assert (p["From"], p["To"], p["Outlet"]) == ("2026-10-01", "2026-10-31", "MF Store")
    assert (p["State"], p["Type"], p["PageNumber"], p["PageSize"]) == ("Accepted", "Adjust", "1", "500")
    assert out["count"] == 2 and "truncated" not in out


@respx.mock
async def test_list_adjustments_omits_unset_filters(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Adjustment").mock(return_value=httpx.Response(200, json=[]))
    await tools.list_adjustments(client)
    p = route.calls[0].request.url.params
    assert not ({"From", "To", "Outlet", "State", "Type"} & set(p))


@respx.mock
async def test_list_adjustments_pages_and_warns_at_the_cap(client):
    _token()
    pages = {"1": [_adj(1), _adj(2)], "2": [_adj(3)]}
    respx.get(f"{BASE}/api/v3/Adjustment").mock(side_effect=lambda req: httpx.Response(
        200, json=pages.get(req.url.params["PageNumber"], [])))
    out = await tools.list_adjustments(client, page_size=2)
    assert out["count"] == 3 and "truncated" not in out
    respx.get(f"{BASE}/api/v3/Adjustment").mock(
        return_value=httpx.Response(200, json=[_adj(1), _adj(2)]))
    capped = await tools.list_adjustments(client, page_size=2, max_pages=3)
    assert capped["truncated"] is True and "3 pages" in capped["warning"]


_DETAIL = {"ID": "id-1", "Number": "MFS-1", "State": "Accepted", "Outlet": "MF Store",
           "AdjustedInventory": [{"Code": "SKU1", "Quantity": -1, "UnitCost": 5,
                                  "ImageUrl": "https://x/y.png", "ThumbnailUrl": "t",
                                  "Parents": ["p"]}],
           "CountedInventory": []}


@respx.mock
async def test_get_adjustment_by_id_strips_image_noise(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/Adjustment/Detail").mock(
        return_value=httpx.Response(200, json=_DETAIL))
    out = await tools.get_adjustment(client, adjustment_id="id-1")
    assert dict(route.calls[0].request.url.params) == {"ID": "id-1"}
    line = out["AdjustedInventory"][0]
    assert line == {"Code": "SKU1", "Quantity": -1, "UnitCost": 5}


@respx.mock
async def test_get_adjustment_by_number_sends_the_outlet(client):
    """Live: Number alone is 'could not be found'; it must travel with Outlet."""
    _token()
    route = respx.get(f"{BASE}/api/v3/Adjustment/Detail").mock(
        return_value=httpx.Response(200, json=_DETAIL))
    await tools.get_adjustment(client, number="MFS-1", outlet="MF Store")
    assert dict(route.calls[0].request.url.params) == {"Number": "MFS-1", "Outlet": "MF Store"}


async def test_get_adjustment_number_without_any_outlet_raises(monkeypatch):
    # Hermetic: the shared `client` fixture reads the real .env, which sets a default outlet.
    monkeypatch.delenv("DEALPOS_DEFAULT_OUTLET", raising=False)
    c = DealPOSClient(Settings(client_id="cid", client_secret="sec", _env_file=None))
    with pytest.raises(DealPOSError, match="outlet"):
        await tools.get_adjustment(c, number="MFS-1")


@pytest.mark.parametrize("kw", [{}, {"number": "a", "adjustment_id": "b"}])
async def test_get_adjustment_needs_exactly_one_key(client, kw):
    with pytest.raises(DealPOSError, match="exactly one"):
        await tools.get_adjustment(client, **kw)


# --- adjust_stock ---

@respx.mock
async def test_adjust_stock_payload(client):
    _token()
    route = respx.post(f"{BASE}/api/v3/Adjustment").mock(
        return_value=httpx.Response(200, json={"ID": "adj-1"}))
    items = [{"code": "VNL-001", "qty": 5, "reason": "Restock"}]
    await tools.adjust_stock(client, items, notes="Weekly restock")
    body = _json.loads(route.calls[0].request.content)
    assert body["Variants"][0]["Code"] == "VNL-001"
    assert body["Variants"][0]["Quantity"] == 5
    assert body["Variants"][0]["Note"] == "Restock"
    assert body["Note"] == "Weekly restock"
    assert "Date" in body


@respx.mock
async def test_adjust_stock_negative_qty(client):
    _token()
    route = respx.post(f"{BASE}/api/v3/Adjustment").mock(
        return_value=httpx.Response(200, json={"ID": "adj-2"}))
    await tools.adjust_stock(client, [{"code": "CD-001", "qty": -3, "reason": "Damaged"}])
    body = _json.loads(route.calls[0].request.content)
    assert body["Variants"][0]["Quantity"] == -3


@respx.mock
async def test_adjust_stock_multi_item(client):
    _token()
    route = respx.post(f"{BASE}/api/v3/Adjustment").mock(
        return_value=httpx.Response(200, json={"ID": "adj-3"}))
    items = [{"code": "A", "qty": 10}, {"code": "B", "qty": -2, "reason": "Fix"}]
    await tools.adjust_stock(client, items, notes="Batch")
    body = _json.loads(route.calls[0].request.content)
    assert len(body["Variants"]) == 2
    assert body["Variants"][1]["Code"] == "B"


@respx.mock
async def test_adjust_stock_sends_outlet_and_reference():
    _token()
    c = DealPOSClient(Settings(subdomain="doubledeer.dealpos.co.id", client_id="cid",
                               client_secret="sec", default_outlet="MF Store", _env_file=None))
    route = respx.post(f"{BASE}/api/v3/Adjustment").mock(
        return_value=httpx.Response(200, json={"ID": "adj-4"}))
    await tools.adjust_stock(c, [{"code": "A", "qty": 1}], reference="ADJ-TEST-0001")
    body = _json.loads(route.calls[0].request.content)
    assert body["Outlet"] == "MF Store"
    assert body["Number"] == "ADJ-TEST-0001"


@respx.mock
async def test_adjust_stock_generates_reference_when_omitted():
    _token()
    c = DealPOSClient(Settings(subdomain="doubledeer.dealpos.co.id", client_id="cid",
                               client_secret="sec", default_outlet="MF Store", _env_file=None))
    route = respx.post(f"{BASE}/api/v3/Adjustment").mock(
        return_value=httpx.Response(200, json={"ID": "adj-5"}))
    await tools.adjust_stock(c, [{"code": "A", "qty": 1}])
    body = _json.loads(route.calls[0].request.content)
    assert body["Number"].startswith("ADJ-")


async def test_adjust_stock_requires_default_outlet():
    c = DealPOSClient(Settings(subdomain="x", client_id="a", client_secret="b", _env_file=None))
    with pytest.raises(DealPOSError):
        await tools.adjust_stock(c, [{"code": "A", "qty": 1}])


# --- set_variant_weights ---

def _w_client():
    return DealPOSClient(Settings(subdomain="doubledeer.dealpos.co.id", client_id="cid",
                                  client_secret="sec", default_outlet="MF Store",
                                  _env_file=None))


COMPOSITE_DETAIL = {
    "Code": "PR-CW", "Variant": "Stereo Pair", "Type": "Composite", "Weight": 0,
    "UnitCost": 1307482, "UnitPrice": 2079000, "Taxable": True, "LoyaltyPoint": True,
    "Discontinued": False, "ImageURL": "", "Description": "",
    "Components": [{"Code": "SYIN200-CW", "Name": "N200 CW", "Qty": 2}],
    "OutletPrice": [{"Outlet": "MF Store", "Price": 2079000, "ExtraCost": 0}],
}


@respx.mock
async def test_set_variant_weights_preserves_composite_components():
    """The PUT's composite branch requires Components and OutletPrice. Sending only
    {Code, Weight} would strip the bundle back to an empty shell — the variant would keep
    selling while no longer drawing down its parts."""
    _token()
    respx.get(f"{BASE}/api/v3/Variant/Detail").mock(
        return_value=httpx.Response(200, json=COMPOSITE_DETAIL))
    put = respx.put(f"{BASE}/api/v3/Variant").mock(
        return_value=httpx.Response(200, json={"Message": "Variant has been updated"}))
    await tools.set_variant_weights(_w_client(), [{"code": "PR-CW", "grams": 1720}])
    body = _json.loads(put.calls[0].request.content)
    assert body["Weight"] == 1720
    assert body["Type"] == "Composite"
    assert body["Components"] == [{"Code": "SYIN200-CW", "Qty": 2}]
    assert body["OutletPrice"] == [{"Outlet": "MF Store", "Price": 2079000, "ExtraCost": 0}]


@respx.mock
async def test_set_variant_weights_preserves_prices():
    _token()
    respx.get(f"{BASE}/api/v3/Variant/Detail").mock(
        return_value=httpx.Response(200, json=COMPOSITE_DETAIL))
    put = respx.put(f"{BASE}/api/v3/Variant").mock(
        return_value=httpx.Response(200, json={"Message": "ok"}))
    await tools.set_variant_weights(_w_client(), [{"code": "PR-CW", "grams": 1720}])
    body = _json.loads(put.calls[0].request.content)
    assert body["UnitPrice"] == 2079000
    assert body["UnitCost"] == 1307482
    assert body["Discontinued"] is False


@respx.mock
async def test_set_variant_weights_standard_variant_sends_empty_components():
    _token()
    respx.get(f"{BASE}/api/v3/Variant/Detail").mock(return_value=httpx.Response(200, json={
        "Code": "STD-1", "Variant": "White", "Type": "Standard", "Weight": 0,
        "UnitCost": 100, "UnitPrice": 200, "Taxable": True, "LoyaltyPoint": True,
        "Discontinued": False, "Components": [], "OutletPrice": []}))
    put = respx.put(f"{BASE}/api/v3/Variant").mock(
        return_value=httpx.Response(200, json={"Message": "ok"}))
    await tools.set_variant_weights(_w_client(), [{"code": "STD-1", "grams": 860}])
    body = _json.loads(put.calls[0].request.content)
    assert body["Weight"] == 860 and body["Components"] == [] and body["Type"] == "Standard"


@respx.mock
async def test_set_variant_weights_handles_multiple_items():
    _token()
    respx.get(f"{BASE}/api/v3/Variant/Detail").mock(
        return_value=httpx.Response(200, json=COMPOSITE_DETAIL))
    put = respx.put(f"{BASE}/api/v3/Variant").mock(
        return_value=httpx.Response(200, json={"Message": "ok"}))
    out = await tools.set_variant_weights(
        _w_client(), [{"code": "A", "grams": 860}, {"code": "B", "grams": 1230}])
    assert len(put.calls) == 2 and len(out) == 2


async def test_set_variant_weights_rejects_non_positive():
    """0 is the broken state this tool exists to fix, so accepting it is always a mistake."""
    for grams in (0, -5):
        with pytest.raises(DealPOSError):
            await tools.set_variant_weights(_w_client(), [{"code": "A", "grams": grams}])


async def test_set_variant_weights_requires_items():
    with pytest.raises(DealPOSError):
        await tools.set_variant_weights(_w_client(), [])


# --- pricebook ---

def _pb_client():
    return DealPOSClient(Settings(subdomain="doubledeer.dealpos.co.id", client_id="cid",
                                  client_secret="sec", default_outlet="MF Store",
                                  _env_file=None))


VARIANTS = [{"code": "A1", "original_price": 100000, "price": 120000}]


@respx.mock
async def test_upsert_pricebook_creates_when_absent():
    _token()
    respx.get(f"{BASE}/api/v3/Pricebook").mock(return_value=httpx.Response(200, json=[]))
    post = respx.post(f"{BASE}/api/v3/Pricebook").mock(
        return_value=httpx.Response(200, json={"ID": "pb-1", "Message": "created"}))
    await tools.upsert_pricebook(_pb_client(), "MF Online", VARIANTS)
    body = _json.loads(post.calls[0].request.content)
    assert body["Name"] == "MF Online"
    assert "ID" not in body          # POST must not carry an ID
    assert body["Variants"] == [{"Code": "A1", "OriginalPrice": 100000,
                                 "PricebookPrice": 120000}]


@respx.mock
async def test_upsert_pricebook_updates_when_present():
    _token()
    respx.get(f"{BASE}/api/v3/Pricebook").mock(return_value=httpx.Response(
        200, json=[{"ID": "pb-9", "Name": "MF Online"}]))
    put = respx.put(f"{BASE}/api/v3/Pricebook").mock(
        return_value=httpx.Response(200, json={"ID": "pb-9"}))
    await tools.upsert_pricebook(_pb_client(), "MF Online", VARIANTS)
    body = _json.loads(put.calls[0].request.content)
    assert body["ID"] == "pb-9"      # PUT requires the ID


@respx.mock
async def test_upsert_pricebook_name_match_is_exact():
    """A substring hit must not be mistaken for the pricebook — that would overwrite
    someone else's pricebook with this one's prices."""
    _token()
    respx.get(f"{BASE}/api/v3/Pricebook").mock(return_value=httpx.Response(
        200, json=[{"ID": "pb-other", "Name": "MF Online Archive"}]))
    post = respx.post(f"{BASE}/api/v3/Pricebook").mock(
        return_value=httpx.Response(200, json={"ID": "pb-new"}))
    await tools.upsert_pricebook(_pb_client(), "MF Online", VARIANTS)
    assert post.called


@respx.mock
async def test_upsert_pricebook_defaults_minimum_quantity_to_zero():
    """qty 0 keeps the pricebook inert at the POS counter. It is the only thing stopping
    an online price reaching in-store sales, so it must not depend on the caller."""
    _token()
    respx.get(f"{BASE}/api/v3/Pricebook").mock(return_value=httpx.Response(200, json=[]))
    post = respx.post(f"{BASE}/api/v3/Pricebook").mock(
        return_value=httpx.Response(200, json={"ID": "pb-1"}))
    await tools.upsert_pricebook(_pb_client(), "MF Online", VARIANTS)
    body = _json.loads(post.calls[0].request.content)
    assert body["MinimumQuantity"] == 0


@respx.mock
async def test_upsert_pricebook_optional_fields_omitted_when_unset():
    _token()
    respx.get(f"{BASE}/api/v3/Pricebook").mock(return_value=httpx.Response(200, json=[]))
    post = respx.post(f"{BASE}/api/v3/Pricebook").mock(
        return_value=httpx.Response(200, json={"ID": "pb-1"}))
    await tools.upsert_pricebook(_pb_client(), "MF Online", VARIANTS)
    body = _json.loads(post.calls[0].request.content)
    for k in ("ListOutlets", "StartDate", "Expiration", "Description"):
        assert k not in body


async def test_upsert_pricebook_requires_variants():
    with pytest.raises(DealPOSError):
        await tools.upsert_pricebook(_pb_client(), "MF Online", [])


@respx.mock
async def test_get_pricebook_reads_detail_by_id():
    _token()
    respx.get(f"{BASE}/api/v3/Pricebook").mock(return_value=httpx.Response(
        200, json=[{"ID": "pb-9", "Name": "MF Online"}]))
    respx.get(f"{BASE}/api/v3/Pricebook/ID/pb-9").mock(return_value=httpx.Response(
        200, json={"ID": "pb-9", "Name": "MF Online", "MinimumQuantity": 0,
                   "Variants": [{"Code": "A1", "OriginalPrice": 100000,
                                 "PricebookPrice": 120000}]}))
    out = await tools.get_pricebook(_pb_client(), "MF Online")
    assert out["Variants"][0]["PricebookPrice"] == 120000


@respx.mock
async def test_get_pricebook_missing_raises():
    _token()
    respx.get(f"{BASE}/api/v3/Pricebook").mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(DealPOSError):
        await tools.get_pricebook(_pb_client(), "Nope")


# --- create_composite_variant ---

@respx.mock
async def test_create_composite_variant_two_call_payloads():
    _token()
    c = DealPOSClient(Settings(subdomain="doubledeer.dealpos.co.id", client_id="cid",
                               client_secret="sec", default_outlet="MF Store", _env_file=None))
    add = respx.post(f"{BASE}/api/v3/Variant/Add").mock(
        return_value=httpx.Response(200, json={"ID": "p-1"}))
    put = respx.put(f"{BASE}/api/v3/Variant").mock(
        return_value=httpx.Response(200, json={"Message": "Variant has been updated"}))

    await tools.create_composite_variant(
        c, product_code="SPK-SYI-N200", variant_code="SPK-SYI-N200PR-CW",
        model="Stereo Pair - Cream White", price=2079000,
        components=[{"code": "SYIN200-CW", "qty": 2}])

    # Call 1 creates the variant on the parent product.
    a = _json.loads(add.calls[0].request.content)
    assert a["Code"] == "SPK-SYI-N200"
    assert a["Variants"] == [{"Model": "Stereo Pair - Cream White",
                              "Code": "SPK-SYI-N200PR-CW",
                              "UnitPrice": 2079000,
                              "Discontinued": False}]

    # Call 2 converts it to Composite. Type/Components/OutletPrice only exist here —
    # Variant/Add has no Type or Components field at all.
    b = _json.loads(put.calls[0].request.content)
    assert b["Code"] == "SPK-SYI-N200PR-CW"
    assert b["Type"] == "Composite"
    assert b["Components"] == [{"Code": "SYIN200-CW", "Qty": 2}]
    assert b["OutletPrice"] == [{"Outlet": "MF Store", "Price": 2079000}]


@respx.mock
async def test_create_composite_variant_outlet_override():
    _token()
    c = DealPOSClient(Settings(subdomain="doubledeer.dealpos.co.id", client_id="cid",
                               client_secret="sec", default_outlet="MF Store", _env_file=None))
    respx.post(f"{BASE}/api/v3/Variant/Add").mock(
        return_value=httpx.Response(200, json={"ID": "p-1"}))
    put = respx.put(f"{BASE}/api/v3/Variant").mock(
        return_value=httpx.Response(200, json={"Message": "ok"}))
    await tools.create_composite_variant(
        c, product_code="P", variant_code="V", model="M", price=100,
        components=[{"code": "X", "qty": 2}], outlet="Other Outlet")
    b = _json.loads(put.calls[0].request.content)
    assert b["OutletPrice"] == [{"Outlet": "Other Outlet", "Price": 100}]


async def test_create_composite_variant_requires_outlet():
    c = DealPOSClient(Settings(subdomain="x", client_id="a", client_secret="b", _env_file=None))
    with pytest.raises(DealPOSError):
        await tools.create_composite_variant(
            c, product_code="P", variant_code="V", model="M", price=100,
            components=[{"code": "X", "qty": 2}])


async def test_create_composite_variant_requires_components():
    c = DealPOSClient(Settings(subdomain="x", client_id="a", client_secret="b",
                               default_outlet="MF Store", _env_file=None))
    with pytest.raises(DealPOSError):
        await tools.create_composite_variant(
            c, product_code="P", variant_code="V", model="M", price=100, components=[])


# --- set_variant_composite ---

@respx.mock
async def test_set_variant_composite_put_only():
    """Exists for the case create_composite_variant's PUT half didn't stick (observed live:
    DealPOS applied Components but left Type as Standard on a variant of a just-created
    product) — retry the conversion without re-running Variant/Add, which would 400 on the
    now-existing code."""
    _token()
    c = DealPOSClient(Settings(subdomain="doubledeer.dealpos.co.id", client_id="cid",
                               client_secret="sec", default_outlet="MF Store", _env_file=None))
    put = respx.put(f"{BASE}/api/v3/Variant").mock(
        return_value=httpx.Response(200, json={"Message": "Variant has been updated"}))
    await tools.set_variant_composite(
        c, variant_code="SYIN200PAIR-CW", price=2079000,
        components=[{"code": "SYIN200-CW", "qty": 2}])
    b = _json.loads(put.calls[0].request.content)
    assert b["Code"] == "SYIN200PAIR-CW"
    assert b["Type"] == "Composite"
    assert b["Components"] == [{"Code": "SYIN200-CW", "Qty": 2}]
    assert b["OutletPrice"] == [{"Outlet": "MF Store", "Price": 2079000}]


async def test_set_variant_composite_requires_outlet():
    c = DealPOSClient(Settings(subdomain="x", client_id="a", client_secret="b", _env_file=None))
    with pytest.raises(DealPOSError):
        await tools.set_variant_composite(
            c, variant_code="V", price=100, components=[{"code": "X", "qty": 2}])


async def test_set_variant_composite_requires_components():
    c = DealPOSClient(Settings(subdomain="x", client_id="a", client_secret="b",
                               default_outlet="MF Store", _env_file=None))
    with pytest.raises(DealPOSError):
        await tools.set_variant_composite(c, variant_code="V", price=100, components=[])


# --- get_inbound_logistics ---

@respx.mock
async def test_get_inbound_logistics_date_filter(client):
    _token()
    route = respx.get(f"{BASE}/api/v3/InboundLogistic").mock(
        return_value=httpx.Response(200, json=[{"ID": "IL-001"}]))
    out = await tools.get_inbound_logistics(client, date_from="2026-06-01",
                                             date_to="2026-06-30")
    p = route.calls[0].request.url.params
    assert p["From"] == "2026-06-01" and p["To"] == "2026-06-30"
    assert len(out) == 1


# --- list_products compact flag ---

@respx.mock
async def test_list_products_compact_strips_heavy_fields(client):
    _token()
    respx.get("https://doubledeer.dealpos.co.id/api/v3/Product").mock(
        return_value=httpx.Response(200, json={
            "DataArray": [{
                "ID": "p1", "Code": "VINYL-A", "Category": "Vinyl Import", "Name": "Vinyl A",
                "Brand": "Test Brand", "SupplierName": "Test Supplier",
                "Released": "2026-06-06T00:00:00", "Discontinued": False,
                "Description": "A" * 500,
                "ImageURL": "https://cdn.example.com/" + "x" * 200,
                "ThumbnailURL": "https://cdn.example.com/thumb/" + "x" * 200,
                "Variants": [{
                    "ID": "v1", "Code": "VA", "Model": "Default",
                    "UnitCost": 100000, "UnitPrice": 150000,
                    "Discontinued": False,
                    "Description": "variant desc " * 20,
                    "ImageURL": "https://cdn.example.com/variant/" + "y" * 200,
                }],
            }],
            "RecordsCount": -1,
        }))
    out = await tools.list_products(client)
    assert len(out) == 1
    p = out[0]
    assert p["Name"] == "Vinyl A"
    assert p["Code"] == "VINYL-A"  # product code: get_product needs it, variant code 400s
    assert p["Category"] == "Vinyl Import"
    assert p["Brand"] == "Test Brand"
    assert p["SupplierName"] == "Test Supplier"
    assert p["Released"] == "2026-06-06T00:00:00"
    assert "Description" not in p
    assert "ImageURL" not in p
    assert "ThumbnailURL" not in p
    v = p["Variants"][0]
    assert v["Code"] == "VA"
    assert v["UnitPrice"] == 150000
    assert v["UnitCost"] == 100000
    assert "Description" not in v
    assert "ImageURL" not in v


@respx.mock
async def test_list_products_compact_false_returns_raw(client):
    _token()
    respx.get("https://doubledeer.dealpos.co.id/api/v3/Product").mock(
        return_value=httpx.Response(200, json={
            "DataArray": [{
                "ID": "p1", "Category": "Vinyl Import", "Name": "Vinyl A",
                "Description": "full description", "ImageURL": "https://cdn.example.com/img.jpg",
                "Variants": [{"ID": "v1", "Code": "VA", "Description": "variant desc"}],
            }],
            "RecordsCount": -1,
        }))
    out = await tools.list_products(client, compact=False)
    assert out[0]["Description"] == "full description"
    assert out[0]["Variants"][0]["Description"] == "variant desc"
