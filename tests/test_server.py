import os

# server.py builds Settings() at import time — provide dummy creds before importing.
os.environ.setdefault("DEALPOS_SUBDOMAIN", "example.dealpos.co.id")
os.environ.setdefault("DEALPOS_CLIENT_ID", "test-id")
os.environ.setdefault("DEALPOS_CLIENT_SECRET", "test-secret")

from dealpos_mcp import server  # noqa: E402


WRITE_TOOLS = {"create_product", "update_product", "update_product_price",
               "set_variant_weights", "upsert_pricebook", "create_composite_variant",
               "set_variant_composite", "create_customer", "adjust_stock",
               "reject_adjustment"}


async def test_every_read_tool_has_a_live_call():
    """Mocked tests can't see dead endpoints; every read tool needs a row in READS
    (tests/test_contract_live.py). get_pricebook is exempt: it needs a name to look up."""
    from tests.test_contract_live import READS
    registered = {t.name for t in await server.mcp.list_tools()}
    uncovered = registered - WRITE_TOOLS - set(READS) - {"get_pricebook"}
    assert not uncovered, f"read tools with no live call in READS: {sorted(uncovered)}"
    assert not (set(READS) - registered), "READS names a tool that is not registered"


async def test_all_expected_tools_registered():
    names = {t.name for t in await server.mcp.list_tools()}
    assert {"get_sales_summary", "get_daily_sales", "check_low_stock",
            "list_products", "get_product", "create_product",
            "update_product_price", "create_customer"} <= names


async def test_create_inbound_logistic_is_not_registered():
    """Removed 2026-11-13: off-spec (no Number/FulfillmentOutlet) and MF has no POs."""
    names = {t.name for t in await server.mcp.list_tools()}
    assert "create_inbound_logistic" not in names
