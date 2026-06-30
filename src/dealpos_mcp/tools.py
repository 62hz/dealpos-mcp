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


# --- products write ---

async def create_product(client: DealPOSClient, name: str, code: str, category: str,
                         brand: str, unit_price: float, unit_cost: float = 0,
                         stock: float = 0, image_url: str = "",
                         model: str = "Standard") -> dict:
    """Create a single-variant product. unit_price is required.

    Note: ``stock`` is accepted for a forward-compatible signature but opening stock
    is set via a separate inventory adjustment endpoint (deferred), so it is not yet sent.
    """
    if unit_price is None:
        raise DealPOSError("unit_price is required to create a product.")
    body = {
        "Category": category, "Name": name, "Brand": brand, "Code": code,
        "Discontinued": False, "ImageURL": image_url,
        "Variants": [{"Model": model, "Code": code, "UnitCost": unit_cost,
                      "UnitPrice": unit_price, "Discontinued": False}],
    }
    return await client.request("POST", "/api/v3/Product", json=body)


async def update_product_price(client: DealPOSClient, code: str, new_price: float,
                               variant_code: str | None = None) -> dict:
    """Reprice a product: fetch it, set the variant UnitPrice, PUT it back (update by Code)."""
    product = await get_product(client, code)
    variants = product.get("Variants") or []
    if not variants:
        raise DealPOSError(f"Product {code} has no variants to reprice.")
    target = variant_code or code
    changed = False
    for v in variants:
        if variant_code is None or v.get("Code") == target:
            v["UnitPrice"] = new_price
            changed = True
    if not changed:
        raise DealPOSError(f"Variant {variant_code} not found on product {code}.")
    return await client.request("PUT", "/api/v3/Product", json=product)


# --- customers write ---

async def create_customer(client: DealPOSClient, name: str, email: str,
                          mobile_phone: str, code: str | None = None) -> dict:
    """Create a customer. Required by the API: ID, Code, Email, MobilePhone, Name, Status."""
    if not code:
        nc = await client.request("GET", "/api/v3/Customer/NewCode")
        code = nc.get("Code") if isinstance(nc, dict) else str(nc)
    body = {"ID": "", "Code": code, "Email": email, "MobilePhone": mobile_phone,
            "Name": name, "Status": "Active"}
    return await client.request("POST", "/api/v3/Customer", json=body)
