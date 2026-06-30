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
async def list_products(name: str | None = None, category: str | None = None) -> list[dict]:
    """List catalogue products, optionally filtered by name or category."""
    return await tools.list_products(_client, name, category)


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


def main() -> None:
    mcp.run()    # stdio transport


if __name__ == "__main__":
    main()
