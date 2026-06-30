from .client import DealPOSClient, DealPOSError


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# --- sales reports ---

async def get_sales_summary(client: DealPOSClient, date_from: str, date_to: str,
                            outlet: str | None = None) -> dict:
    """Product-sold summary between two YYYY-MM-DD dates."""
    params = {"From": date_from, "To": date_to}
    if outlet:
        params["Outlet"] = outlet
    rows = await client.request("GET", "/api/v3/Report/ProductSold", params=params)
    rows = rows if isinstance(rows, list) else []
    total_qty = sum(_num(r.get("Quantity")) for r in rows)
    total_net = sum(_num(r.get("NetSales")) for r in rows)
    top = max(rows, key=lambda r: _num(r.get("Quantity")), default=None)
    return {"date_from": date_from, "date_to": date_to, "total_qty": total_qty,
            "total_net_sales": total_net, "top_item": top, "items": rows}


async def get_daily_sales(client: DealPOSClient, year: int, outlet: str | None = None) -> dict:
    """Daily sales for a whole year (trend)."""
    body: dict = {"Year": year}
    if outlet:
        body["Outlet"] = [outlet]
    data = await client.request("POST", "/api/v3/Report/DailySales", json=body)
    return {"year": year, "data": data}


# --- inventory ---

async def list_inventory(client: DealPOSClient, page_size: int = 200,
                         outlet: str | None = None, category: str | None = None) -> list[dict]:
    """Fetch inventory rows (capped at 500/page by the API)."""
    params: dict = {"PageNumber": 1, "PageSize": min(page_size, 500)}
    if outlet:
        params["ListOutlet"] = outlet
    if category:
        params["Category"] = category
    rows = await client.request("GET", "/api/v3/Inventory", params=params)
    return rows if isinstance(rows, list) else []


async def check_low_stock(client: DealPOSClient, fallback_threshold: int | None = None,
                          outlet: str | None = None) -> dict:
    """Return items at/below their Threshold (or the fallback when Threshold is 0/unset)."""
    fb = fallback_threshold if fallback_threshold is not None else client.s.low_stock_fallback
    rows = await list_inventory(client, outlet=outlet)
    low = []
    for r in rows:
        inv = r.get("I") or {}
        avail = _num(inv.get("Available"))
        thr = _num(inv.get("Threshold"))
        limit = thr if thr > 0 else fb
        if avail <= limit:
            low.append({"Product": r.get("Product"), "Variant": r.get("Variant"),
                        "Code": r.get("Code"), "Available": avail, "Threshold": limit})
    return {"count": len(low), "low_stock": low}


# --- products read ---

async def list_products(client: DealPOSClient, name: str | None = None,
                        category: str | None = None, page_size: int = 50) -> list[dict]:
    """List catalogue products, optionally filtered by name/category."""
    params: dict = {"PageNumber": 1, "PageSize": page_size}
    if name:
        params["Name"] = name
    if category:
        params["Category"] = category
    rows = await client.request("GET", "/api/v3/Product", params=params)
    return rows if isinstance(rows, list) else []


async def get_product(client: DealPOSClient, code: str) -> dict:
    """Get a single product by its Code."""
    return await client.request("GET", "/api/v3/Product/Code", params={"Code": code})
