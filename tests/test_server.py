import os

# server.py builds Settings() at import time — provide dummy creds before importing.
os.environ.setdefault("DEALPOS_SUBDOMAIN", "doubledeer.dealpos.co.id")
os.environ.setdefault("DEALPOS_CLIENT_ID", "test-id")
os.environ.setdefault("DEALPOS_CLIENT_SECRET", "test-secret")

from dealpos_mcp import server  # noqa: E402


async def test_all_expected_tools_registered():
    names = {t.name for t in await server.mcp.list_tools()}
    assert {"get_sales_summary", "get_daily_sales", "check_low_stock",
            "list_products", "get_product", "create_product",
            "update_product_price", "create_customer"} <= names
