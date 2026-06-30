# DealPOS MCP

Local [MCP](https://modelcontextprotocol.io) server giving Claude read/write access to
DealPOS (Medium Format). Lane 1 of the DealPOS integration — interactive control.

## Tools

| Tool | Action |
|------|--------|
| `get_sales_summary` | Qty + net sales + top item between two dates |
| `get_daily_sales` | Daily sales for a whole year (trend) |
| `check_low_stock` | Items at/below reorder threshold |
| `list_products` | List catalogue (filter by name/category) |
| `get_product` | One product by Code (price + details) |
| `create_product` | Add a single-variant product (write) |
| `update_product_price` | Reprice a product (write) |
| `create_customer` | Add a customer/contact (write) |

## Setup

1. Install:
   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install -e .
   ```
2. Copy `.env.example` to `.env`. In DealPOS → **Setup/Settings**, issue OAuth2
   **Client ID** and **Client Secret**, paste them into `.env`. **Never commit `.env`.**

## Register with Claude Code

Add to your Claude Code MCP config (via `claude mcp add` or settings JSON):

```json
{
  "mcpServers": {
    "dealpos": {
      "command": "C:\\Users\\SER5 MAX\\dealpos-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "dealpos_mcp.server"],
      "cwd": "C:\\Users\\SER5 MAX\\dealpos-mcp"
    }
  }
}
```

Restart Claude Code; the `dealpos` tools appear. Then ask things like
*"Using dealpos, what's low on stock?"* or *"add this vinyl: …"*.

## Tests

```bash
.venv/Scripts/python -m pytest -q
```

All HTTP is mocked — tests need no credentials or network.

## Scope

- **Lane 1 (this repo):** interactive MCP control.
- **Lane 2 (separate):** Google Apps Script for scheduled reports + low-stock alerts.
- **Phase 2 (later):** returns, supplier/purchase orders — added as new tools.
