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


@pytest.fixture
async def live():
    c = DealPOSClient(Settings())
    try:
        yield c
    finally:
        await c.aclose()


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


async def test_sales_orders_is_explicitly_unavailable(live):
    """Pinned deliberately: if DealPOS ever adds a GET, this fails and we revisit."""
    from dealpos_mcp.client import DealPOSError
    with pytest.raises(DealPOSError, match="not available"):
        await tools.list_sales_orders(live)
