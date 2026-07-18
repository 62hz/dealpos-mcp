from mcp.server.fastmcp import FastMCP

from . import tools
from .client import DealPOSClient
from .config import Settings

mcp = FastMCP("dealpos")
_settings = Settings()           # loaded from env / .env
_client = DealPOSClient(_settings)


@mcp.tool()
async def get_sales_summary(date_from: str, date_to: str, outlet: str | None = None) -> dict:
    """Sales summary (quantity + net sales + top item) between two YYYY-MM-DD dates."""
    return await tools.get_sales_summary(_client, date_from, date_to, outlet)


@mcp.tool()
async def get_daily_sales(year: int, outlet: str | None = None) -> dict:
    """Daily sales for a full year (trend)."""
    return await tools.get_daily_sales(_client, year, outlet)


@mcp.tool()
async def check_low_stock(fallback_threshold: int | None = None, outlet: str | None = None) -> dict:
    """List products at or below their reorder threshold."""
    return await tools.check_low_stock(_client, fallback_threshold, outlet)


@mcp.tool()
async def list_products(name: str | None = None, category: str | None = None,
                        compact: bool = True) -> list[dict]:
    """List catalogue products, optionally filtered by name or category.
    compact=True (default) strips Description/ImageURL fields to save tokens on
    full-catalog pulls — set compact=False when you need the raw product record."""
    return await tools.list_products(_client, name, category, compact=compact)


@mcp.tool()
async def get_product(code: str) -> dict:
    """Get one product by its Code (price + details)."""
    return await tools.get_product(_client, code)


@mcp.tool()
async def create_product(name: str, code: str, category: str, brand: str,
                         unit_price: float, unit_cost: float = 0, image_url: str = "") -> dict:
    """Create a single-variant product. Confirm details with the user before calling."""
    return await tools.create_product(_client, name=name, code=code, category=category,
                                      brand=brand, unit_price=unit_price,
                                      unit_cost=unit_cost, image_url=image_url)


@mcp.tool()
async def update_product_price(code: str, new_price: float, variant_code: str | None = None) -> dict:
    """Change a product's price. Confirm the product and new price with the user first."""
    return await tools.update_product_price(_client, code, new_price, variant_code)


@mcp.tool()
async def create_customer(name: str, email: str, mobile_phone: str) -> dict:
    """Create a customer/contact."""
    return await tools.create_customer(_client, name, email, mobile_phone)


@mcp.tool()
async def list_inventory(outlet: str | None = None,
                         category: str | None = None) -> list[dict]:
    """List inventory levels. Filter by outlet or category."""
    return await tools.list_inventory(_client, outlet=outlet, category=category)


@mcp.tool()
async def list_customers(name: str | None = None, email: str | None = None,
                         phone: str | None = None) -> list[dict]:
    """Search customers by name, email, or phone."""
    return await tools.list_customers(_client, name=name, email=email, phone=phone)


@mcp.tool()
async def list_categories() -> list[dict]:
    """List all product categories."""
    return await tools.list_categories(_client)


@mcp.tool()
async def list_outlets() -> list[dict]:
    """List all outlets/store locations."""
    return await tools.list_outlets(_client)


@mcp.tool()
async def list_suppliers() -> list[dict]:
    """List all suppliers/vendors."""
    return await tools.list_suppliers(_client)


@mcp.tool()
async def get_receivables(outlet: str | None = None,
                          min_days_overdue: int | None = None) -> dict:
    """List outstanding receivables. min_days_overdue filters to overdue only."""
    return await tools.get_receivables(_client, outlet=outlet,
                                       min_days_overdue=min_days_overdue)


@mcp.tool()
async def get_writeoffs(date_from: str, date_to: str,
                        outlet: str | None = None) -> dict:
    """List write-offs (TikTok admin fees, discounts) between two YYYY-MM-DD dates."""
    return await tools.get_writeoffs(_client, date_from, date_to, outlet=outlet)


@mcp.tool()
async def list_invoices(date_from: str | None = None, date_to: str | None = None,
                        customer_code: str | None = None,
                        outlet: str | None = None) -> dict:
    """List invoices/transactions with optional date, customer, or outlet filter."""
    return await tools.list_invoices(_client, date_from=date_from, date_to=date_to,
                                     customer_code=customer_code, outlet=outlet)


@mcp.tool()
async def list_sales_orders(date_from: str | None = None, date_to: str | None = None,
                            status: str | None = None,
                            outlet: str | None = None) -> list[dict]:
    """List sales orders (online/marketplace). Filter by date, status, or outlet."""
    return await tools.list_sales_orders(_client, date_from=date_from, date_to=date_to,
                                          status=status, outlet=outlet)


@mcp.tool()
async def update_product(code: str, fields: dict) -> dict:
    """Update specific fields on a product. Pass only the fields to change.
    Confirm changes with the user before calling."""
    return await tools.update_product(_client, code, fields)


@mcp.tool()
async def get_inventory_by_codes(codes: list[str],
                                  outlet: str | None = None) -> list[dict]:
    """Batch stock lookup for multiple product codes — single API call."""
    return await tools.get_inventory_by_codes(_client, codes, outlet=outlet)


@mcp.tool()
async def get_inventory_log(code: str | None = None, date_from: str | None = None,
                             date_to: str | None = None) -> list[dict]:
    """Stock movement history. Filter by product code and/or date range."""
    return await tools.get_inventory_log(_client, code=code, date_from=date_from,
                                          date_to=date_to)


@mcp.tool()
async def adjust_stock(items: list[dict], notes: str | None = None) -> dict:
    """Create stock adjustment. items: [{code, qty, reason?}].
    Positive qty = add, negative = remove.
    Confirm quantities with the user before calling."""
    return await tools.adjust_stock(_client, items, notes=notes)


@mcp.tool()
async def get_inbound_logistics(date_from: str | None = None,
                                date_to: str | None = None) -> list[dict]:
    """List past PO deliveries."""
    return await tools.get_inbound_logistics(_client, date_from=date_from,
                                              date_to=date_to)


@mcp.tool()
async def create_inbound_logistic(items: list[dict], supplier_code: str | None = None,
                                   notes: str | None = None) -> dict:
    """Receive PO stock delivery. items: [{code, qty, unit_cost?}].
    Confirm with user before calling."""
    return await tools.create_inbound_logistic(_client, items,
                                               supplier_code=supplier_code, notes=notes)


def main() -> None:
    mcp.run()    # stdio transport


if __name__ == "__main__":
    main()
