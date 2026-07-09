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


# --- customers read ---

async def list_customers(client: DealPOSClient, name: str | None = None,
                         email: str | None = None, phone: str | None = None,
                         page_size: int = 50) -> list[dict]:
    """List customers, optionally filtered by name, email, or phone."""
    params: dict = {"PageNumber": 1, "PageSize": page_size}
    if name:
        params["Name"] = name
    if email:
        params["Email"] = email
    if phone:
        params["MobilePhone"] = phone
    rows = await client.request("GET", "/api/v3/Customer", params=params)
    return rows if isinstance(rows, list) else []


# --- catalogue meta ---

async def list_categories(client: DealPOSClient) -> list[dict]:
    """List all product categories."""
    rows = await client.request("GET", "/api/v3/Category")
    return rows if isinstance(rows, list) else []


async def list_outlets(client: DealPOSClient) -> list[dict]:
    """List all outlets/locations."""
    rows = await client.request("GET", "/api/v3/Outlet")
    return rows if isinstance(rows, list) else []


async def list_suppliers(client: DealPOSClient) -> list[dict]:
    """List all suppliers/vendors."""
    rows = await client.request("GET", "/api/v3/Supplier")
    return rows if isinstance(rows, list) else []


# --- financial reports ---

async def get_writeoffs(client: DealPOSClient, date_from: str, date_to: str,
                        outlet: str | None = None) -> dict:
    """List invoice write-offs (platform fees, discounts) between two YYYY-MM-DD dates."""
    params: dict = {"From": date_from, "To": date_to}
    if outlet:
        params["Outlet"] = outlet
    rows = await client.request("GET", "/api/v3/InvoiceWriteOff", params=params)
    rows = rows if isinstance(rows, list) else []
    total = sum(_num(r.get("Total") or r.get("Amount") or 0) for r in rows)
    return {
        "date_from": date_from, "date_to": date_to,
        "count": len(rows), "total": total, "items": rows,
    }


async def list_invoices(client: DealPOSClient, date_from: str | None = None,
                        date_to: str | None = None, customer_code: str | None = None,
                        outlet: str | None = None, page_size: int = 50) -> dict:
    """List invoices/transactions with optional filters."""
    params: dict = {"PageNumber": 1, "PageSize": page_size}
    if date_from:
        params["From"] = date_from
    if date_to:
        params["To"] = date_to
    if customer_code:
        params["CustomerCode"] = customer_code
    if outlet:
        params["Outlet"] = outlet
    rows = await client.request("GET", "/api/v3/Invoice", params=params)
    rows = rows if isinstance(rows, list) else []
    total_net = sum(_num(r.get("NetSales") or r.get("Total") or 0) for r in rows)
    return {"count": len(rows), "total_net": total_net, "invoices": rows}


async def list_sales_orders(client: DealPOSClient, date_from: str | None = None,
                            date_to: str | None = None, status: str | None = None,
                            outlet: str | None = None, page_size: int = 50) -> list[dict]:
    """List sales orders (online/marketplace orders)."""
    params: dict = {"PageNumber": 1, "PageSize": page_size}
    if date_from:
        params["From"] = date_from
    if date_to:
        params["To"] = date_to
    if status:
        params["Status"] = status
    if outlet:
        params["Outlet"] = outlet
    rows = await client.request("GET", "/api/v3/SalesOrder", params=params)
    return rows if isinstance(rows, list) else []


async def get_receivables(client: DealPOSClient, outlet: str | None = None,
                          min_days_overdue: int | None = None) -> dict:
    """List outstanding receivables, optionally filtered by days overdue."""
    from datetime import date, datetime
    params: dict = {}
    if outlet:
        params["Outlet"] = outlet
    rows = await client.request("GET", "/api/v3/Receivable",
                                params=params if params else None)
    rows = rows if isinstance(rows, list) else []
    if min_days_overdue is not None:
        today = date.today()
        filtered = []
        for r in rows:
            due_raw = r.get("DueDate", "")
            if due_raw:
                try:
                    due = datetime.fromisoformat(due_raw[:10]).date()
                    days = (today - due).days
                    if days >= min_days_overdue:
                        filtered.append(dict(r, DaysOverdue=days))
                except ValueError:
                    pass
        rows = filtered
    total = sum(_num(r.get("Total") or r.get("Amount") or 0) for r in rows)
    return {"count": len(rows), "total": total, "receivables": rows}


# --- products write (general) ---

async def update_product(client: DealPOSClient, code: str, fields: dict) -> dict:
    """Patch specific fields on a product. Fetches current state, merges fields, PUTs back."""
    product = await get_product(client, code)
    product.update(fields)
    return await client.request("PUT", "/api/v3/Product", json=product)


# --- inventory queries ---

async def get_inventory_by_codes(client: DealPOSClient, codes: list[str],
                                  outlet: str | None = None) -> list[dict]:
    """Batch stock lookup for multiple product codes in a single API call."""
    body: dict = {"Codes": codes}
    if outlet:
        body["Outlet"] = outlet
    rows = await client.request("POST", "/api/v3/Inventory/CodeArray", json=body)
    return rows if isinstance(rows, list) else []


async def get_inventory_log(client: DealPOSClient, code: str | None = None,
                             date_from: str | None = None,
                             date_to: str | None = None,
                             page_size: int = 100) -> list[dict]:
    """Stock movement history — sales, adjustments, PO receives."""
    params: dict = {"PageNumber": 1, "PageSize": page_size}
    if code:
        params["Code"] = code
    if date_from:
        params["From"] = date_from
    if date_to:
        params["To"] = date_to
    rows = await client.request("GET", "/api/v3/Inventory/Log", params=params)
    return rows if isinstance(rows, list) else []


# --- stock adjustment ---

async def adjust_stock(client: DealPOSClient, items: list[dict],
                       notes: str | None = None) -> dict:
    """Delta stock adjustment. Each item: {code, qty, reason?}.
    Positive qty = add stock; negative = remove stock."""
    body: dict = {
        "Details": [
            {
                "Code": i["code"],
                "Quantity": i["qty"],
                "Notes": i.get("reason", notes or ""),
            }
            for i in items
        ]
    }
    if notes:
        body["Notes"] = notes
    return await client.request("POST", "/api/v3/Adjustment", json=body)


# --- logistics ---

async def get_inbound_logistics(client: DealPOSClient, date_from: str | None = None,
                                date_to: str | None = None,
                                page_size: int = 50) -> list[dict]:
    """List incoming PO deliveries."""
    params: dict = {"PageNumber": 1, "PageSize": page_size}
    if date_from:
        params["From"] = date_from
    if date_to:
        params["To"] = date_to
    rows = await client.request("GET", "/api/v3/InboundLogistic", params=params)
    return rows if isinstance(rows, list) else []


async def create_inbound_logistic(client: DealPOSClient, items: list[dict],
                                  supplier_code: str | None = None,
                                  notes: str | None = None) -> dict:
    """Receive PO stock delivery. Each item: {code, qty, unit_cost?}.
    Prefer over adjust_stock when receiving new stock from a supplier."""
    body: dict = {
        "Details": [
            {
                "Code": i["code"],
                "Quantity": i["qty"],
                "UnitCost": i.get("unit_cost", 0),
            }
            for i in items
        ]
    }
    if supplier_code:
        body["SupplierCode"] = supplier_code
    if notes:
        body["Notes"] = notes
    return await client.request("POST", "/api/v3/InboundLogistic", json=body)
