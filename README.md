# DealPOS MCP

Local [MCP](https://modelcontextprotocol.io) server that lets Claude read (and, if you
allow it, write) DealPOS data for Medium Format. Runs on your machine over stdio; there
is no hosted service.

**Unofficial.** This is an independent project. It is not made, endorsed or supported by
DealPOS (PT Generasi Inspirasi Informatika), which publishes its own MCP server at
`mcp.dealpos.app`. This one talks to the public DealPOS REST API v3 with your own client
credentials. "DealPOS" belongs to its owner.

**Read-only by default.** The 20 read tools work out of the box; 19 are called against live
DealPOS by `tests/test_contract_live.py` (`get_pricebook` needs a pricebook name, so it is
the one that is not). The 10 write tools are blocked until you set `DEALPOS_READ_ONLY=false`.

## Quick start (teammates)

You need three things:

1. [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed.
2. Access to this private repo (`gh auth login`, or any git credential that can clone it).
3. Your own DealPOS **Client ID** and **Client Secret** (DealPOS → Setup/Settings →
   OAuth2). Ask the DealPOS admin for a pair; do not share one between people, so DealPOS
   can tell who did what and one person can be revoked on their own.

Then run once (Claude Code), swapping in your two values:

```bash
claude mcp add dealpos --scope user --env DEALPOS_CLIENT_ID=YOUR_ID --env DEALPOS_CLIENT_SECRET=YOUR_SECRET -- uvx --from git+https://github.com/62hz/dealpos-mcp dealpos-mcp
```

Restart Claude Code and try: *"Using dealpos, what's low on stock?"*

Claude Desktop, Cursor, or any other MCP client: add this to its config instead.

```json
{
  "mcpServers": {
    "dealpos": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/62hz/dealpos-mcp", "dealpos-mcp"],
      "env": {
        "DEALPOS_CLIENT_ID": "YOUR_ID",
        "DEALPOS_CLIENT_SECRET": "YOUR_SECRET"
      }
    }
  }
}
```

`uvx` fetches the latest `master` on each fresh start. Credentials live in your client
config, never in the repo.

## Tools

**Read (20, always on)**

| Tool | Returns |
|------|---------|
| `get_sales_summary` | Qty, net sales, top item between two dates |
| `get_daily_sales` | Daily sales for a full year |
| `list_invoices` | Invoices in a date range (both dates required), paged; rows carry `Amount`, `Payment`, `Delivery`, `Fulfillment`. Sets `truncated` if the page cap stops it |
| `get_receivables` | Unpaid and partly-paid invoices (last 365 days by default), optional overdue filter. DealPOS has no receivables endpoint, so this is built from invoices; it includes pending TikTok/Shopee settlements and internal `MF DISPLAY/B-STOCK` entries, so group by `Customer` |
| `get_writeoffs` | Write-offs (e.g. TikTok admin fees) in a date range |
| `list_products`, `get_product`, `get_variant_detail` | Catalogue, one product, one variant (type/components/weight) |
| `get_pricebook` | One pricebook by name |
| `list_categories`, `list_outlets`, `list_suppliers`, `list_customers` | Reference data |
| `list_inventory`, `get_inventory_by_codes`, `check_low_stock` | Stock levels and low-stock list |
| `get_inventory_log` | Stock movement history for one variant (variant code required) |
| `list_adjustments`, `get_adjustment` | Stock adjustments and their lines. Filter by `state` (Draft, InReview, Pending, Rejected, Accepted) and `adjustment_type` (Adjust, Count); look one up by `adjustment_id`, or by `number` plus outlet. Use after `adjust_stock` to confirm the State |
| `get_inbound_logistics` | Past PO deliveries (MF has none in DealPOS, so normally empty) |

**Write (10, need `DEALPOS_READ_ONLY=false`)**

| Tool | Does |
|------|------|
| `create_product`, `update_product` | Add a product, or change product-level fields (`Code`, `ID`, `Variants` are refused) |
| `update_product_price` | Change one variant's price (`variant_code` required on multi-variant products) |
| `set_variant_weights` | Set shipping weight (grams) on variants |
| `upsert_pricebook` | Create or update a pricebook by name |
| `create_composite_variant`, `set_variant_composite` | Bundle variants that draw down component stock |
| `create_customer` | Add a contact (pass `code`; MF's code generator is off) |
| `adjust_stock` | Stock adjustment (+ add / - remove); returns State. With MF's approval workflow it lands as Draft (stock unmoved) unless `auto_approve=true` |
| `reject_adjustment` | Reject a **Pending** adjustment by Number (stock unchanged). A Draft is refused (400 "not in Pending State", live 2026-11-13): clear a Draft in the DealPOS UI. InReview untested |

## Enabling writes

Add `--env DEALPOS_READ_ONLY=false` to the `claude mcp add` command (or put it in the
`env` block of the JSON config), then restart the client.

While read-only is on, a write tool fails with `Read-only mode: ... was blocked` before
anything is sent to DealPOS. The guard sits in `DealPOSClient.request`, so it covers every
write, including tools added later.

Writes change live store data, and this server has no approval step of its own. Each write
tool's description tells Claude to confirm with you first, but that is a prompt, not a lock.
Keep read-only on unless you actually need to write.

## Gotchas

- List-typed arguments (`codes`, `items`, `variants`, `components`, `outlets`) must be real
  JSON arrays, never comma-separated strings.
- `list_invoices` needs both `date_from` and `date_to` or DealPOS returns a 500.
- DealPOS allows 50 requests per 180 seconds with no queue (`GET /api/v3/ratelimit`). The
  server paces itself to 45 per 180 s (`DEALPOS_RATE_PERMITS`, `DEALPOS_RATE_WINDOW`; set
  permits to `0` to turn it off), so a heavy read can pause until the window clears instead
  of failing. A call that looks hung is usually waiting for that.
- Every request sends `User-Agent: dealpos-mcp/<version>`. DealPOS says it will require an
  identifying User-Agent from 2027 and answer 400 without one.
- `get_sales_summary` spends at most 30 requests on one range. A full year took 23 live; if a
  range needs more, the result carries `truncated` and a warning, so ask for a shorter range.
- `get_inventory_log` takes one variant code (required); there is no all-variants log.
- `list_customers` filters by name on the server; email and phone are matched by the tool
  after fetching, because DealPOS ignores those two filters.
- There is no sales-order tool: DealPOS exposes `/api/v3/SalesOrder` for POST/DELETE only,
  and a POST there creates an order. Marketplace sales already show up in `get_sales_summary`.
- Environment variables always win over a `.env` file.
- A `.env` is read only from the checkout root, never from the folder the client starts in.
- A network error during a write is reported as "may or may not have landed": check
  (e.g. `list_adjustments`) before retrying, or the write can happen twice.

## Development

```bash
git clone https://github.com/62hz/dealpos-mcp && cd dealpos-mcp
uv sync --extra dev
cp .env.example .env      # fill in DEALPOS_CLIENT_ID / DEALPOS_CLIENT_SECRET; never commit .env
uv run pytest -q
```

All HTTP in the suite is mocked, so tests need no credentials or network.
`tests/test_contract_live.py` is the only file that talks to DealPOS (read-only GETs). It is
skipped by default; run it on its own with `DEALPOS_LIVE_CONTRACT=1 uv run pytest tests/test_contract_live.py -v`.
The whole file makes more than 50 requests; its tests share one rate limiter, so a full run
pauses for the window and takes about six minutes. `-k every_read_tool` is the quick smoke test.

To run from a local checkout instead of GitHub, point your client at
`uv run --directory /path/to/dealpos-mcp dealpos-mcp`; the server reads `.env` from the
checkout root.

## Scope

- **This repo:** interactive MCP control (stdio).
- **Separate:** Google Apps Script for scheduled reports and low-stock alerts.
- **Later:** returns, supplier and purchase orders, as new tools.

## Licence

MIT, see [LICENSE](LICENSE).
