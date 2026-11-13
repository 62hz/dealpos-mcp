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
    compact=True (default) keeps only a whitelist of fields (ID, Category, Name, Brand,
    SupplierName, Released, Discontinued, Variants) — dropping everything else, including
    Description/ImageURL/ThumbnailURL, to save tokens on full-catalog pulls. Set
    compact=False when you need the raw product record."""
    return await tools.list_products(_client, name, category, compact=compact)


@mcp.tool()
async def get_product(code: str) -> dict:
    """Get one product by its PRODUCT code (the `Code` on a list_products row; price +
    details). A variant code (Variants[].Code) is rejected: use get_variant_detail."""
    return await tools.get_product(_client, code)


@mcp.tool()
async def get_variant_detail(code: str) -> dict:
    """Get one variant by its VARIANT code (Variants[].Code), including Type/Components/Weight -- fields
    get_product's compact Variants[] omits. Use to verify a composite conversion or
    weight write actually landed, rather than trusting the write tool's own response."""
    return await tools.get_variant_detail(_client, code)


@mcp.tool()
async def create_product(name: str, code: str, category: str, brand: str,
                         unit_price: float, unit_cost: float = 0, image_url: str = "") -> dict:
    """Create a single-variant product. Confirm details with the user before calling."""
    return await tools.create_product(_client, name=name, code=code, category=category,
                                      brand=brand, unit_price=unit_price,
                                      unit_cost=unit_cost, image_url=image_url)


@mcp.tool()
async def set_variant_weights(items: list[dict]) -> list[dict]:
    """Set shipping weight in grams on variants. items: [{code, grams}] — MUST be a
    JSON array of objects, never a comma-separated string.
    Weight is required before a product can be uploaded to a marketplace channel via
    Omnichannel. Preserves composite components and outlet prices via read-modify-write.
    Confirm the weights with the user before calling."""
    return await tools.set_variant_weights(_client, items)


@mcp.tool()
async def upsert_pricebook(name: str, variants: list[dict], minimum_quantity: int = 0,
                           outlets: list[str] | None = None, start_date: str | None = None,
                           expiration: str | None = None,
                           description: str | None = None) -> dict:
    """Create or update a pricebook by exact name. variants: [{code, original_price, price}]
    — MUST be a JSON array of objects, never a comma-separated string. outlets, if given,
    MUST also be a JSON array of outlet names, e.g. ["MF Store"], never a comma-separated string.
    minimum_quantity defaults to 0, which keeps the pricebook inert at the POS counter —
    required when the pricebook is a marketplace channel's price source, so the online price
    cannot leak into in-store sales. Only raise it for a real wholesale/qty promotion.
    Confirm prices with the user before calling."""
    return await tools.upsert_pricebook(
        _client, name=name, variants=variants, minimum_quantity=minimum_quantity,
        outlets=outlets, start_date=start_date, expiration=expiration,
        description=description)


@mcp.tool()
async def get_pricebook(name: str) -> dict:
    """Read a pricebook's full detail by name. Use to verify a pricebook write."""
    return await tools.get_pricebook(_client, name)


@mcp.tool()
async def create_composite_variant(product_code: str, variant_code: str, model: str,
                                   price: float, components: list[dict],
                                   outlet: str | None = None) -> dict:
    """Add a Composite (bundle) variant to an existing product. It holds no stock of its
    own — selling it draws down its components, so bundle and parts share one pool.
    components: [{code, qty}] — MUST be a JSON array of objects, never a comma-separated
    string. Confirm components and price with the user before calling."""
    return await tools.create_composite_variant(
        _client, product_code=product_code, variant_code=variant_code, model=model,
        price=price, components=components, outlet=outlet)


@mcp.tool()
async def set_variant_composite(variant_code: str, price: float, components: list[dict],
                                outlet: str | None = None) -> dict:
    """Retry converting a variant to Composite when create_composite_variant's conversion
    didn't stick (Components applied but Type stayed Standard). PUT-only, no Variant/Add —
    safe to call on a variant that already exists. components: [{code, qty}] — MUST be a
    JSON array of objects, never a comma-separated string.
    Confirm with the user before calling."""
    return await tools.set_variant_composite(
        _client, variant_code=variant_code, price=price, components=components, outlet=outlet)


@mcp.tool()
async def update_product_price(code: str, new_price: float, variant_code: str | None = None) -> dict:
    """Change one variant's price. `code` is the PRODUCT code; `variant_code` is required
    when the product has more than one variant (e.g. colours). Confirm the variant and
    new price with the user first."""
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
    """List all customers, or search by name (server-side), email or phone (matched here,
    since DealPOS ignores those two filters)."""
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
                          min_days_overdue: int | None = None,
                          date_from: str | None = None,
                          date_to: str | None = None) -> dict:
    """Unpaid and partly-paid invoices over a window (default: last 365 days, YYYY-MM-DD
    dates). min_days_overdue keeps only invoices past due (skips ones with no due date).
    Includes pending TikTok/Shopee settlements and internal 'MF DISPLAY/B-STOCK' entries:
    group by Customer to separate them from real customer debts."""
    return await tools.get_receivables(_client, outlet=outlet,
                                       min_days_overdue=min_days_overdue,
                                       date_from=date_from, date_to=date_to)


@mcp.tool()
async def get_writeoffs(date_from: str, date_to: str,
                        outlet: str | None = None) -> dict:
    """List write-offs (TikTok admin fees, discounts) between two YYYY-MM-DD dates."""
    return await tools.get_writeoffs(_client, date_from, date_to, outlet=outlet)


@mcp.tool()
async def list_invoices(date_from: str, date_to: str,
                        customer_code: str | None = None,
                        outlet: str | None = None) -> dict:
    """List invoices/transactions in a date range. Both dates are REQUIRED
    (the DealPOS endpoint 500s without them). Pages automatically; each row has
    Amount, Payment (Paid/Unpaid/Partial/Exceed), Delivery, Fulfillment. If the
    result has `truncated`, total_net is partial: narrow the range."""
    return await tools.list_invoices(_client, date_from=date_from, date_to=date_to,
                                     customer_code=customer_code, outlet=outlet)


@mcp.tool()
async def update_product(code: str, fields: dict) -> dict:
    """Update product-level fields (Name, Brand, Category, Description...). Pass only the
    fields to change; Code, ID and Variants are refused. Confirm changes with the user
    before calling."""
    return await tools.update_product(_client, code, fields)


@mcp.tool()
async def get_inventory_by_codes(codes: list[str],
                                  outlet: str | None = None) -> list[dict]:
    """Batch stock lookup for multiple product codes — single API call.
    codes MUST be a JSON array, e.g. ["ABC123", "XYZ789"], never a comma-separated string."""
    return await tools.get_inventory_by_codes(_client, codes, outlet=outlet)


@mcp.tool()
async def get_inventory_log(code: str, date_from: str | None = None,
                             date_to: str | None = None,
                             outlet: str | None = None) -> list[dict]:
    """Stock movement history for ONE variant. `code` is a VARIANT code (required);
    optionally narrow by outlet name and YYYY-MM-DD date range."""
    return await tools.get_inventory_log(_client, code=code, date_from=date_from,
                                          date_to=date_to, outlet=outlet)


@mcp.tool()
async def list_adjustments(date_from: str | None = None, date_to: str | None = None,
                           outlet: str | None = None, state: str | None = None,
                           adjustment_type: str | None = None) -> dict:
    """List stock adjustments, filtered by YYYY-MM-DD dates. state: Draft, InReview,
    Pending, Rejected or Accepted. adjustment_type: Adjust (quantity delta) or Count
    (stock take). Check the State of a fresh adjust_stock here."""
    return await tools.list_adjustments(_client, date_from=date_from, date_to=date_to,
                                        outlet=outlet, state=state,
                                        adjustment_type=adjustment_type)


@mcp.tool()
async def get_adjustment(adjustment_id: str | None = None, number: str | None = None,
                         outlet: str | None = None) -> dict:
    """One adjustment with its line items. Pass adjustment_id (from list_adjustments), or
    number together with its outlet name. Use to verify an adjustment after adjust_stock."""
    return await tools.get_adjustment(_client, number=number, adjustment_id=adjustment_id,
                                      outlet=outlet)


@mcp.tool()
async def adjust_stock(items: list[dict], notes: str | None = None) -> dict:
    """Create stock adjustment. items: [{code, qty, reason?}] — MUST be a JSON array
    of objects, never a comma-separated string.
    Positive qty = add, negative = remove.
    Confirm quantities with the user before calling."""
    return await tools.adjust_stock(_client, items, notes=notes)


@mcp.tool()
async def get_inbound_logistics(date_from: str | None = None,
                                date_to: str | None = None) -> list[dict]:
    """List past PO deliveries."""
    return await tools.get_inbound_logistics(_client, date_from=date_from,
                                              date_to=date_to)


def main() -> None:
    mcp.run()    # stdio transport


if __name__ == "__main__":
    main()
