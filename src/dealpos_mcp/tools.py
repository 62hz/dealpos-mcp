from .client import DealPOSClient, DealPOSError


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# --- sales reports ---

_PRODUCT_SOLD_CAP = 100  # Report/ProductSold returns at most 100 rows and ignores paging


async def _product_sold_chunked(client: DealPOSClient, date_from: str, date_to: str,
                                outlet: str | None, _depth: int = 0) -> tuple[list[dict], bool]:
    """Fetch Report/ProductSold, splitting the date range around the 100-row cap.

    The endpoint silently truncates at 100 rows and IGNORES PageNumber/PageSize
    (verified 2026-08-02: PageSize=500 and page=2/3 all return the identical
    first 100 rows). Splitting the date range is the only way to see everything.

    Returns (rows, truncated). `truncated` is True only if a single day still
    hits the cap, which no split can fix.
    """
    from datetime import date, timedelta

    params: dict = {"From": date_from, "To": date_to}
    if outlet:
        params["Outlet"] = outlet
    rows = await client.request("GET", "/api/v3/Report/ProductSold", params=params)
    rows = rows if isinstance(rows, list) else []

    if len(rows) < _PRODUCT_SOLD_CAP:
        return rows, False

    try:
        d0 = date.fromisoformat(date_from)
        d1 = date.fromisoformat(date_to)
    except ValueError:
        return rows, True
    if d0 >= d1 or _depth >= 12:
        # A single day at the cap cannot be split further.
        return rows, True

    mid = d0 + (d1 - d0) // 2
    left, t_l = await _product_sold_chunked(client, d0.isoformat(), mid.isoformat(),
                                            outlet, _depth + 1)
    right, t_r = await _product_sold_chunked(client, (mid + timedelta(days=1)).isoformat(),
                                             d1.isoformat(), outlet, _depth + 1)

    merged: dict[str, dict] = {}
    for r in left + right:
        key = str(r.get("Code") or r.get("Name") or id(r))
        if key in merged:
            m = merged[key]
            for f in ("Quantity", "Sales", "Cost", "Profit"):
                if f in r or f in m:
                    m[f] = _num(m.get(f)) + _num(r.get(f))
        else:
            merged[key] = dict(r)
    return list(merged.values()), (t_l or t_r)


async def get_sales_summary(client: DealPOSClient, date_from: str, date_to: str,
                            outlet: str | None = None) -> dict:
    """Product-sold summary between two YYYY-MM-DD dates (inclusive).

    Auto-splits the range to work around the endpoint's silent 100-row cap.
    """
    rows, truncated = await _product_sold_chunked(client, date_from, date_to, outlet)
    total_qty = sum(_num(r.get("Quantity")) for r in rows)
    # Report/ProductSold returns Sales/Cost/Profit. An earlier version summed
    # "NetSales", a field this endpoint never returns, so every summary reported
    # Rp0 revenue while listing non-zero line items. Verified 2026-08-02 against
    # the live API: keys are Name, Code, Quantity, Cost, Sales, Profit.
    total_net = sum(_num(r.get("Sales")) for r in rows)
    total_cost = sum(_num(r.get("Cost")) for r in rows)
    total_profit = sum(_num(r.get("Profit")) for r in rows)
    top = max(rows, key=lambda r: _num(r.get("Quantity")), default=None)
    out = {"date_from": date_from, "date_to": date_to, "total_qty": total_qty,
           "total_net_sales": total_net, "total_cost": total_cost,
           "total_profit": total_profit, "top_item": top, "items": rows}
    if truncated:
        out["truncated"] = True
        out["warning"] = ("A single day hit the 100-row cap, so these totals are "
                          "INCOMPLETE and under-report actual sales.")
    return out


async def get_daily_sales(client: DealPOSClient, year: int, outlet: str | None = None) -> dict:
    """Daily sales for a whole year (trend)."""
    body: dict = {"Year": year}
    if outlet:
        body["Outlet"] = [outlet]
    data = await client.request("POST", "/api/v3/Report/DailySales", json=body)
    return {"year": year, "data": data}


# --- inventory ---

async def list_inventory(client: DealPOSClient, page_size: int = 500,
                         outlet: str | None = None, category: str | None = None) -> list[dict]:
    """Fetch all inventory rows, auto-paginating past the API's per-page cap."""
    page_size = min(page_size, 500)
    all_rows: list[dict] = []
    page = 1
    while True:
        params: dict = {"PageNumber": page, "PageSize": page_size}
        if outlet:
            params["ListOutlet"] = outlet
        if category:
            params["Category"] = category
        rows = await client.request("GET", "/api/v3/Inventory", params=params)
        rows = rows if isinstance(rows, list) else []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        page += 1
    return all_rows


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

def _compact_product(p: dict) -> dict:
    """Keep only ID, Category, Name, Brand, SupplierName, Released, Discontinued, and a
    trimmed Variants list — any other field (including Description/ImageURL/ThumbnailURL)
    is dropped."""
    return {
        "ID": p.get("ID"),
        "Category": p.get("Category"),
        "Name": p.get("Name"),
        "Brand": p.get("Brand"),
        "SupplierName": p.get("SupplierName"),
        "Released": p.get("Released"),
        "Discontinued": p.get("Discontinued"),
        "Variants": [
            {
                "ID": v.get("ID"),
                "Code": v.get("Code"),
                "Model": v.get("Model"),
                "UnitCost": v.get("UnitCost"),
                "UnitPrice": v.get("UnitPrice"),
                "Discontinued": v.get("Discontinued"),
            }
            for v in (p.get("Variants") or [])
        ],
    }


async def list_products(client: DealPOSClient, name: str | None = None,
                        category: str | None = None, page_size: int = 500,
                        compact: bool = True) -> list[dict]:
    """List all catalogue products, optionally filtered by name/category.

    The API wraps results as ``{"DataArray": [...], "RecordsCount": -1}`` rather than
    a bare list, and ``RecordsCount`` is unreliable (-1), so pagination stops on a
    short page rather than a total count.

    By default (``compact=True``) each product/variant is reduced to a whitelist of
    fields — product: ID, Category, Name, Brand, SupplierName, Released, Discontinued,
    Variants; variant: ID, Code, Model, UnitCost, UnitPrice, Discontinued. Any other
    field (including Description/ImageURL/ThumbnailURL, which make up most of the
    payload size on a full-catalog pull) is dropped. Pass ``compact=False`` to get the
    raw API objects (e.g. before calling ``update_product`` on a specific item).
    """
    page_size = min(page_size, 500)
    all_rows: list[dict] = []
    page = 1
    while True:
        params: dict = {"PageNumber": page, "PageSize": page_size}
        if name:
            params["Name"] = name
        if category:
            params["Category"] = category
        data = await client.request("GET", "/api/v3/Product", params=params)
        rows = data.get("DataArray", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        page += 1
    if compact:
        all_rows = [_compact_product(p) for p in all_rows]
    return all_rows


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


async def create_composite_variant(client: DealPOSClient, product_code: str,
                                   variant_code: str, model: str, price: float,
                                   components: list[dict],
                                   outlet: str | None = None) -> dict:
    """Add a Composite variant to an existing product — a bundle that holds no stock of
    its own and draws down its components instead (e.g. a stereo pair built from 2x the
    single speaker, so both listings share one inventory pool).

    ``components``: [{code, qty}] — variant codes of the parts, and how many of each.

    Two calls, because no single endpoint does it. POST /api/v3/Variant/Add creates the
    variant but its schema has no Type or Components field at all; only
    PUT /api/v3/Variant carries them. Verified against the OpenAPI bundle at
    https://developer.dealpos.com/_bundle/openapi/openapi.yaml on 2026-08-12 — note the
    rendered per-endpoint .md docs OMIT the request body for both PUT /api/v3/Variant and
    POST /api/v3/Product, so composite support looks absent there. It is not.

    The PUT's Standard/Composite branch requires Code, Components, and OutletPrice, so an
    outlet is mandatory; it falls back to DEALPOS_DEFAULT_OUTLET.
    """
    if not components:
        raise DealPOSError("A composite variant needs at least one component.")
    if not (outlet or client.s.default_outlet):
        raise DealPOSError(
            "Composite variants require an outlet (the API's OutletPrice field is "
            "required) and DEALPOS_DEFAULT_OUTLET is unset in .env."
        )
    await client.request("POST", "/api/v3/Variant/Add", json={
        "Code": product_code,
        "Variants": [{"Model": model, "Code": variant_code,
                      "UnitPrice": price, "Discontinued": False}],
    })
    return await set_variant_composite(client, variant_code=variant_code, price=price,
                                       components=components, outlet=outlet)


async def set_variant_composite(client: DealPOSClient, variant_code: str, price: float,
                                components: list[dict], outlet: str | None = None) -> dict:
    """PUT-only half of composite conversion — the same call create_composite_variant makes
    after adding the variant, exposed standalone so a conversion that didn't stick can be
    retried without re-running Variant/Add (which 400s on the now-existing code).

    Observed live 2026-08-13: converting a variant on a just-created product applied
    Components but left Type as Standard — a partial application on DealPOS's side. This
    function is the fix path for that: re-PUT until Type reads back as Composite.
    """
    if not components:
        raise DealPOSError("A composite variant needs at least one component.")
    outlet = outlet or client.s.default_outlet
    if not outlet:
        raise DealPOSError(
            "Composite variants require an outlet (the API's OutletPrice field is "
            "required) and DEALPOS_DEFAULT_OUTLET is unset in .env."
        )
    return await client.request("PUT", "/api/v3/Variant", json={
        "Code": variant_code,
        "Type": "Composite",
        "Components": [{"Code": c["code"], "Qty": c["qty"]} for c in components],
        "OutletPrice": [{"Outlet": outlet, "Price": price}],
    })


async def set_variant_weights(client: DealPOSClient, items: list[dict]) -> list[dict]:
    """Set shipping weight (grams) on variants. items: [{code, grams}].

    Weight is a required field for uploading a product to a marketplace channel via DealPOS
    Omnichannel, alongside SKU, image and description. MF's catalogue has it at 0
    everywhere, which is why marketplace uploads fail while inventory sync still works.

    Read-modify-write, not a bare PUT. The Standard/Composite branch of PUT /api/v3/Variant
    requires Code, Components and OutletPrice, so sending only {Code, Weight} against a
    Composite variant would strip its components — the bundle would keep selling while no
    longer drawing down its parts. Each variant is fetched, the weight replaced, and the
    rest written back unchanged.
    """
    if not items:
        raise DealPOSError("No variants given.")
    for i in items:
        if not isinstance(i.get("grams"), (int, float)) or i["grams"] <= 0:
            raise DealPOSError(
                f"Weight for {i.get('code')!r} must be a positive number of grams; "
                f"got {i.get('grams')!r}. Zero is the broken state this fixes."
            )

    results = []
    for i in items:
        code = i["code"]
        v = await client.request("GET", "/api/v3/Variant/Detail", params={"Code": code})
        body = {
            "Code": v["Code"],
            "Model": v.get("Variant") or v.get("Model") or "",
            "Type": v.get("Type") or "Standard",
            "Weight": int(i["grams"]),
            "UnitCost": v.get("UnitCost") or 0,
            "UnitPrice": v.get("UnitPrice") or 0,
            "OrderPrice": v.get("OrderPrice") or 0,
            "Taxable": v.get("Taxable", True),
            "LoyaltyPoint": v.get("LoyaltyPoint", True),
            "Discontinued": v.get("Discontinued", False),
            "Components": [{"Code": c["Code"], "Qty": c["Qty"]}
                           for c in (v.get("Components") or [])],
            "OutletPrice": [{"Outlet": o["Outlet"], "Price": o["Price"],
                             "ExtraCost": o.get("ExtraCost", 0)}
                            for o in (v.get("OutletPrice") or [])],
        }
        if v.get("Description"):
            body["VariantDescription"] = v["Description"]
        results.append(await client.request("PUT", "/api/v3/Variant", json=body))
    return results


async def _find_pricebook_id(client: DealPOSClient, name: str) -> str | None:
    """Resolve a pricebook name to its ID, or None. The Name query param is a filter, not
    an exact match, so the caller's name is compared exactly against the results — a
    substring hit would otherwise overwrite a different pricebook."""
    found = await client.request("GET", "/api/v3/Pricebook",
                                 params={"Name": name, "PageNumber": 1, "PageSize": 50})
    for p in found or []:
        if p.get("Name") == name:
            return p.get("ID")
    return None


async def upsert_pricebook(client: DealPOSClient, name: str, variants: list[dict],
                           minimum_quantity: int = 0, outlets: list[str] | None = None,
                           start_date: str | None = None, expiration: str | None = None,
                           description: str | None = None) -> dict:
    """Create or update a pricebook (POST/PUT /api/v3/Pricebook), matched by exact name.

    ``variants``: [{code, original_price, price}] — ``price`` is the pricebook price.

    ``minimum_quantity`` defaults to 0 on purpose. DealPOS Omnichannel reads a pricebook as
    a marketplace channel's price source, and a qty of 0 keeps that pricebook from also
    firing at the POS counter. It is the only thing separating the online price from the
    in-store price, so it defaults safe rather than relying on the caller to pass it.
    Raising it re-arms the pricebook as a real wholesale/qty promotion — intended for that
    use, but never for a channel pricebook.

    PUT requires ID and POST must not carry one, hence the name lookup first.
    """
    if not variants:
        raise DealPOSError("A pricebook needs at least one variant.")
    body: dict = {
        "Name": name,
        "MinimumQuantity": minimum_quantity,
        "Variants": [{"Code": v["code"], "OriginalPrice": v["original_price"],
                      "PricebookPrice": v["price"]} for v in variants],
    }
    if outlets:
        body["ListOutlets"] = outlets
    if start_date:
        body["StartDate"] = start_date
    if expiration:
        body["Expiration"] = expiration
    if description:
        body["Description"] = description

    existing = await _find_pricebook_id(client, name)
    if existing:
        body["ID"] = existing
        return await client.request("PUT", "/api/v3/Pricebook", json=body)
    return await client.request("POST", "/api/v3/Pricebook", json=body)


async def get_pricebook(client: DealPOSClient, name: str) -> dict:
    """Read a pricebook's full detail by name (list to resolve the ID, then detail-by-ID).
    Use to verify what a write actually landed."""
    pid = await _find_pricebook_id(client, name)
    if not pid:
        raise DealPOSError(f"No pricebook named {name!r}.")
    return await client.request("GET", f"/api/v3/Pricebook/ID/{pid}")


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


async def list_outlets(client: DealPOSClient, include_suspended: bool = False) -> list[dict]:
    """List outlets/locations. Returns ID (GUID), Name, Code, Suspended."""
    # /api/v3/Outlet rejects a bare GET with 400 "Suspended value is not a valid
    # Boolean" — the param is required and must be the string "true"/"false".
    params = {"Suspended": "true" if include_suspended else "false"}
    rows = await client.request("GET", "/api/v3/Outlet", params=params)
    return rows if isinstance(rows, list) else []


async def _resolve_outlet_id(client: DealPOSClient, outlet: str | None) -> str:
    """Map an outlet NAME to its GUID. Several endpoints require OutletID, not Outlet."""
    rows = await list_outlets(client)
    if not rows:
        raise DealPOSError("No outlets returned by DealPOS — cannot resolve OutletID.")
    if outlet:
        for r in rows:
            if str(r.get("Name", "")).strip().lower() == outlet.strip().lower():
                return str(r.get("ID"))
        known = ", ".join(str(r.get("Name")) for r in rows)
        raise DealPOSError(f"Outlet {outlet!r} not found. Known outlets: {known}")
    return str(rows[0].get("ID"))


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
    # Correct path is /WriteOff/Invoice. /InvoiceWriteOff 404s, and bare
    # /WriteOff returns write-off TYPES ("Bad Debt", "Biaya Admin Tiktok"),
    # not transactions. Verified 2026-08-02: rows carry Number, Outlet,
    # Customer, Created, Amount, Tag — and From/To filter correctly.
    rows = await client.request("GET", "/api/v3/WriteOff/Invoice", params=params)
    rows = rows if isinstance(rows, list) else []
    total = sum(_num(r.get("Total") or r.get("Amount") or 0) for r in rows)
    return {
        "date_from": date_from, "date_to": date_to,
        "count": len(rows), "total": total, "items": rows,
    }


async def list_invoices(client: DealPOSClient, date_from: str, date_to: str,
                        customer_code: str | None = None, outlet: str | None = None,
                        page_size: int = 50, page_number: int = 1) -> dict:
    """List invoices/transactions. date_from and date_to are REQUIRED.

    Uses /api/v3/Invoice/WithTotalCount. Bare /api/v3/Invoice is the CREATE
    endpoint (POST) and 415s on GET. Verified 2026-08-02: this endpoint needs
    all four of OutletID (a GUID, not a name), PageNumber, PageSize, From, To —
    omitting the dates gives 500 "Value cannot be null (Parameter 's')" and
    omitting paging gives 400 "Page number and row count must be greater than zero".
    """
    outlet_id = await _resolve_outlet_id(client, outlet)
    params: dict = {
        "OutletID": outlet_id,
        "PageNumber": page_number,
        "PageSize": page_size,
        "From": date_from,
        "To": date_to,
    }
    if customer_code:
        params["CustomerCode"] = customer_code
    data = await client.request("GET", "/api/v3/Invoice/WithTotalCount", params=params)
    # Response is an envelope: {"Data": [...], "TotalCount": n}
    if isinstance(data, dict):
        rows = data.get("Data") or []
        total_count = data.get("TotalCount")
    else:
        rows = data if isinstance(data, list) else []
        total_count = None
    total_net = sum(_num(r.get("Total") or r.get("GrandTotal") or 0) for r in rows)
    return {"count": len(rows), "total_count": total_count,
            "total_net": total_net, "invoices": rows}


async def list_sales_orders(client: DealPOSClient, date_from: str | None = None,
                            date_to: str | None = None, status: str | None = None,
                            outlet: str | None = None, page_size: int = 50) -> list[dict]:
    """List sales orders (online/marketplace orders)."""
    # NOT IMPLEMENTED — deliberately.
    #
    # /api/v3/SalesOrder answers OPTIONS with "Allow: DELETE, POST" only; every
    # GET variant probed on 2026-08-02 (bare, /List, /Search, /WithTotalCount,
    # /ID, /Count, /Join, /SalesOrders, /Order, /OnlineOrder) returned 404 or 405.
    # Per the DealPOS docs every SalesOrder operation is a POST, and POST to the
    # bare path CREATES a sales order — so it was not probed.
    #
    # This is not a gap in practice: marketplace/online sales DO appear in
    # Report/ProductSold. Verified 2026-08-02 — a TikTok sale (barcode
    # 371156899, Rp270.000) is present there, and ProductSold reconciles exactly
    # with Report/DailySales for the same month.
    raise DealPOSError(
        "list_sales_orders is not available: DealPOS exposes /api/v3/SalesOrder "
        "for POST/DELETE only, and POST to that path creates an order. "
        "Use get_sales_summary() instead — it already includes marketplace sales."
    )


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
    body: dict = {"Code": codes}
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
                       notes: str | None = None, reference: str | None = None) -> dict:
    """Delta stock adjustment ("Create Adjustment by Adjusting Differences" —
    POST /api/v3/Adjustment). Each item: {code, qty, reason?}.
    Positive qty = add stock; negative = remove stock.

    Verified live against https://developer.dealpos.com/openapi/openapi/inventory-adjustment/createadjustmentbyadjustingdifferences.md
    on 2026-08-11. The earlier version of this function sent "Details" and "Notes" —
    both wrong field names, silently accepted by the endpoint but ignored, which is
    why every call failed with "No item to be delivered" regardless of quantity. The
    real per-line array key is "Variants", the real note field is "Note" (singular),
    and "Date" is a required top-level field this function never sent at all.

    The API also requires Outlet and Number (a free-form reference the caller
    assigns, not a lookup against an existing order). ``reference`` lets a caller
    supply one; otherwise a timestamp-based one is generated so repeated adjustments
    never collide.
    """
    if not client.s.default_outlet:
        raise DealPOSError(
            "Adjustment requires an outlet and DEALPOS_DEFAULT_OUTLET is unset "
            "in .env — the API rejects the adjustment without one."
        )
    from datetime import date, datetime
    body: dict = {
        "Outlet": client.s.default_outlet,
        "Date": date.today().strftime("%Y/%m/%d"),
        "Number": reference or f"ADJ-{datetime.now():%Y%m%d-%H%M%S}",
        "Variants": [
            {
                "Code": i["code"],
                "Quantity": i["qty"],
                "Note": i.get("reason", notes or ""),
            }
            for i in items
        ]
    }
    if notes:
        body["Note"] = notes
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
    """Mark an EXISTING DealPOS purchase order as received. Each item: {code, qty, unit_cost?}.

    Verified live 2026-08-11: this endpoint requires a Number matching a PO already
    on file in DealPOS ("There is no order with Number ..." otherwise) — it does not
    create a new receipt out of thin air. There is no ``number`` parameter here because
    there is nothing a caller could supply that would resolve; if you have a real PO
    number, add one and pass it through.

    For an invoice with no prior PO record in DealPOS (the common case for ad-hoc
    supplier stock-ins), use ``adjust_stock`` instead — it books the received quantity
    directly as a delta.
    """
    if not client.s.default_outlet:
        raise DealPOSError(
            "InboundLogistic requires an outlet and DEALPOS_DEFAULT_OUTLET is unset "
            "in .env — the API rejects the receipt without one."
        )
    body: dict = {
        "Outlet": client.s.default_outlet,
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
