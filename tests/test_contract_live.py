"""Live contract tests — the ONLY tests that can catch a wrong endpoint or field name.

Why this file exists
--------------------
Every other test in this suite mocks HTTP. On 2026-08-02 four defects were found
that mocked tests structurally could not catch, because each mock was authored
from the same wrong assumption as the code it tested:

  * get_sales_summary summed "NetSales" — a field Report/ProductSold never
    returns. The mock invented "NetSales" too, so the test asserted the code
    agreed with the mock while production silently reported Rp0 revenue.
  * get_writeoffs called /api/v3/InvoiceWriteOff — 404. Real path: /WriteOff/Invoice.
  * list_invoices called /api/v3/Invoice — that is the POST create endpoint; GET 415s.
  * list_outlets called /api/v3/Outlet bare — 400, "Suspended" is required.

A mock proves the code agrees with our beliefs. Only a live call proves our
beliefs agree with DealPOS.

Running
-------
Skipped by default (needs credentials + network). Run this file ON ITS OWN —
respx's global interception from the mocked tests leaks into these and breaks
auth if the whole suite runs together:

    DEALPOS_LIVE_CONTRACT=1 uv run pytest tests/test_contract_live.py -v

The API allows 50 requests per 180 s. The client limiter (45 per 180 s) is pooled across
this file's tests, so a full run may pause for the window; it takes about six minutes.

Read-only: GET only, no POST/PUT/DELETE. Safe against production.
"""
import os
import pytest

from dealpos_mcp import tools
from dealpos_mcp.client import DealPOSClient
from dealpos_mcp.config import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("DEALPOS_LIVE_CONTRACT") != "1",
    reason="live contract test; set DEALPOS_LIVE_CONTRACT=1 to run",
)

WINDOW = ("2026-06-01", "2026-06-30")  # a month known to contain sales


_shared_limiter = None  # the API's 50 requests / 180 s is per credential, not per client


@pytest.fixture
async def live():
    # read_only=True is forced (init kwargs beat env/.env), so this file can never write
    # even if DEALPOS_READ_ONLY=false is set for real use.
    global _shared_limiter
    c = DealPOSClient(Settings(read_only=True))
    # Every test builds its own client; pool one limiter across them so the whole file
    # paces itself under the API limit instead of tripping 429s partway through.
    if _shared_limiter is None:
        _shared_limiter = c._limiter
    c._limiter = _shared_limiter
    try:
        yield c
    finally:
        await c.aclose()


# One live call per read tool. A new read tool must be added here: test_server.py's
# test_every_read_tool_has_a_live_call fails if it isn't, so a tool can't ship without
# a live call. get_pricebook is the one exception: it needs a pricebook name no read
# tool can list.
READS = {
    "get_sales_summary": lambda c, s: tools.get_sales_summary(c, *WINDOW),
    "get_daily_sales": lambda c, s: tools.get_daily_sales(c, 2026),
    "check_low_stock": lambda c, s: tools.check_low_stock(c),
    "list_products": lambda c, s: tools.list_products(c, name=s["product"]),
    "get_product": lambda c, s: tools.get_product(c, s["product"]),
    "get_variant_detail": lambda c, s: tools.get_variant_detail(c, s["variant"]),
    "list_inventory": lambda c, s: tools.list_inventory(c),
    "list_customers": lambda c, s: tools.list_customers(c),
    "list_categories": lambda c, s: tools.list_categories(c),
    "list_outlets": lambda c, s: tools.list_outlets(c),
    "list_suppliers": lambda c, s: tools.list_suppliers(c),
    "get_receivables": lambda c, s: tools.get_receivables(c),
    "get_writeoffs": lambda c, s: tools.get_writeoffs(c, *WINDOW),
    "list_invoices": lambda c, s: tools.list_invoices(c, *WINDOW),
    "get_inventory_by_codes": lambda c, s: tools.get_inventory_by_codes(c, [s["variant"]]),
    "get_inventory_log": lambda c, s: tools.get_inventory_log(c, code=s["variant"]),
    "get_inbound_logistics": lambda c, s: tools.get_inbound_logistics(c, *WINDOW),
    "list_adjustments": lambda c, s: tools.list_adjustments(c, "2026-10-01", "2026-10-31"),
    "get_adjustment": lambda c, s: tools.get_adjustment(c, adjustment_id=s["adjustment_id"]),
}


async def test_every_read_tool_succeeds_live(live):
    """Catches dead endpoints and missing required params, which mocks cannot.

    One test on purpose, not one per tool: the API allows only 50 requests per 180 s
    with no queue (GET /api/v3/ratelimit), so a per-tool test that re-authenticates and
    re-discovers a sample each time exhausts the budget. All failures are reported together.
    """
    # Discover a real product/variant code once instead of hardcoding one.
    prods = await tools.list_products(live, compact=False)
    p = next((p for p in prods if p.get("Code") and p.get("Variants")), None)
    assert p, "no product with a Code and variants found; cannot pick a sample"
    adjs = (await tools.list_adjustments(live, "2026-01-01", "2026-12-31"))["adjustments"]
    assert adjs, "no adjustments this year; cannot pick a sample for get_adjustment"
    sample = {"product": p["Code"], "variant": p["Variants"][0]["Code"],
              "adjustment_id": adjs[0]["ID"]}

    failures = []
    for name in sorted(READS):
        try:
            result = await READS[name](live, sample)
            if not isinstance(result, (dict, list)):
                failures.append(f"{name}: returned {type(result).__name__}")
        except Exception as e:  # noqa: BLE001 - we want every tool's failure, not the first
            failures.append(f"{name}: {type(e).__name__}: {str(e)[:160]}")
    assert not failures, "read tools failing against the live API:\n  " + "\n  ".join(failures)


async def test_product_sold_returns_the_fields_we_sum(live):
    """Guards the Rp0-revenue bug: the summed field must actually exist."""
    out = await tools.get_sales_summary(live, *WINDOW)
    assert out["items"], "no sales in window — pick a window with data"
    row = out["items"][0]
    for field in ("Quantity", "Sales", "Cost", "Profit"):
        assert field in row, f"Report/ProductSold no longer returns {field!r}: {list(row)}"
    # The headline number must reflect the line items, not silently be zero.
    assert out["total_net_sales"] > 0
    assert out["total_net_sales"] == pytest.approx(
        sum(float(r["Sales"]) for r in out["items"]))


async def test_product_sold_reconciles_with_daily_sales(live):
    """Two independent reports must agree, or one of them is lying."""
    out = await tools.get_sales_summary(live, *WINDOW)
    daily = await tools.get_daily_sales(live, year=2026)
    rows = daily if isinstance(daily, list) else daily.get("data", [])
    june = next((m for m in rows if m.get("Month") == "June"), None)
    assert june, "June missing from DailySales"
    assert out["total_net_sales"] == pytest.approx(float(june["SalesNTax"]), rel=0.01)


async def test_outlets_requires_suspended_and_returns_guid(live):
    outlets = await tools.list_outlets(live)
    assert outlets, "no outlets returned"
    o = outlets[0]
    assert "ID" in o and "Name" in o
    assert len(str(o["ID"])) == 36, "OutletID should be a GUID; list_invoices depends on it"


async def test_writeoffs_path_returns_transactions_not_types(live):
    """/WriteOff returns TYPES ('Bad Debt'); /WriteOff/Invoice returns transactions."""
    out = await tools.get_writeoffs(live, "2026-01-01", "2026-12-31")
    assert out["count"] > 0, "no write-offs all year — verify before trusting"
    row = out["items"][0]
    assert "Amount" in row, f"expected transaction rows, got: {list(row)}"
    assert "Description" not in row or "Number" in row, "looks like the TYPE list, not transactions"
    assert out["total"] > 0


async def test_invoice_list_envelope_and_guid(live):
    out = await tools.list_invoices(live, date_from=WINDOW[0], date_to=WINDOW[1])
    assert out["count"] > 0, "no invoices in window"
    assert out["total_count"] is not None, "expected the WithTotalCount envelope"
    assert "Number" in out["invoices"][0]


async def test_invoice_total_is_the_sum_of_row_amounts(live):
    """Guards the total_net == 0 bug: rows carry `Amount`, not Total/GrandTotal."""
    out = await tools.list_invoices(live, date_from=WINDOW[0], date_to=WINDOW[1])
    assert out["invoices"], "no invoices in window"
    assert out["total_net"] > 0
    assert out["total_net"] == pytest.approx(
        sum(float(r.get("Amount") or 0) for r in out["invoices"]))


async def test_invoice_known_day_totals(live):
    """2026-06-05 had 16 invoices summing Rp12,424,000 (checked 2026-11-08). A drift here
    means invoices were voided/edited after the fact, or the sum/paging logic broke."""
    out = await tools.list_invoices(live, "2026-06-05", "2026-06-05")
    assert (out["count"], out["total_count"]) == (16, 16)
    assert out["total_net"] == 12_424_000
    assert "truncated" not in out


async def test_list_customers_reads_past_one_page(live):
    """Only page 1 of 50 was read before; the store had 168 customers on 2026-11-08."""
    assert len(await tools.list_customers(live)) > 50


async def test_compact_product_code_feeds_get_product(live):
    """list_products must keep the PRODUCT code, or get_product has nothing to take."""
    prods = await tools.list_products(live, name="KM5")
    assert prods and prods[0].get("Code"), "compact list_products rows lost their Code"
    got = await tools.get_product(live, prods[0]["Code"])
    assert got.get("Code") == prods[0]["Code"]


async def test_adjustment_reads_agree_and_number_needs_outlet(live):
    """List row, lookup by ID and lookup by Number+Outlet must describe one adjustment."""
    from dealpos_mcp.client import DealPOSError
    rows = (await tools.list_adjustments(live, "2026-01-01", "2026-12-31",
                                         adjustment_type="Adjust"))["adjustments"]
    assert rows and all(r["Type"] == "Adjust" for r in rows), "Type filter not honoured"
    r = rows[0]
    by_id = await tools.get_adjustment(live, adjustment_id=r["ID"])
    by_no = await tools.get_adjustment(live, number=r["Number"], outlet=r["Outlet"])
    assert by_id["Number"] == by_no["Number"] == r["Number"]
    assert by_id["State"] == by_no["State"] == r["State"]
    assert by_id["AdjustedInventory"], "an Adjust row should carry at least one line"
    assert "ImageUrl" not in by_id["AdjustedInventory"][0]
    with pytest.raises(DealPOSError, match="not be found"):  # why get_adjustment demands an outlet
        await live.request("GET", "/api/v3/Adjustment/Detail", params={"Number": r["Number"]})


async def test_sales_orders_is_explicitly_unavailable(live):
    """Pinned deliberately: if DealPOS ever adds a GET, this fails and we revisit."""
    from dealpos_mcp.client import DealPOSError
    with pytest.raises(DealPOSError, match="not available"):
        await tools.list_sales_orders(live)
