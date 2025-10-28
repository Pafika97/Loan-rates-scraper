
# Global Loan Rates Scraper (extensible)

This tool collects *retail loan interest rates* from an extensible list of banks around the world and outputs a **sorted comparison table** (from the lowest rate to the highest).

> ⚠️ Important:
> - Websites change frequently. The included bank examples are **starters**; you can add or tweak banks in the YAML config without touching code.
> - Always respect websites’ Terms of Service. Prefer JSON or public endpoints when available; for pages with heavy JavaScript, add a bank’s own JSON/API endpoint where possible.
> - This tool is for **informational** purposes. Real lending APRs depend on credit profile, location, product, and fees.

## Quick start

1) Create and activate a clean virtual environment, then install deps:
```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2) Run with the included world config:
```bash
python -m src.main --config configs/world_example.yaml --out output/rates.csv
```

3) View results (sorted ascending by APR):
```bash
python -m src.main --config configs/world_example.yaml --out output/rates.csv --format table
```

## How it works

- You maintain a **YAML config** with a list of banks. Each bank has one or more **extractors**:
  - `json_api`: fetch JSON and map fields to `apr`, `currency`, `product`.
  - `html_css`: fetch HTML and select via CSS selectors.
  - `html_xpath`: fetch HTML and select via XPath.
  - `regex`: run a regex on the fetched HTML.
- Each extractor can post-process values: strip symbols, convert to float, percent-of-100 vs whole percent.
- The scraper normalizes output to the schema below.

### Output schema

| column          | description |
|-----------------|-------------|
| `bank`          | Bank or lender name |
| `country`       | ISO country or label |
| `product`       | Loan product (e.g., mortgage, personal, auto, credit_card) |
| `term`          | Human-readable term (e.g., `5y fixed`) if available |
| `currency`      | ISO currency code (e.g., USD, EUR) |
| `apr`           | Annual percentage rate (float, in percent) |
| `source_url`    | The source URL we fetched |
| `fetched_at`    | ISO datetime |

## Adding banks

Edit `configs/world_example.yaml`. Each bank block looks like this:

```yaml
- bank: Example Bank
  country: US
  product: personal
  currency: USD
  term: "varies"
  source_url: "https://example.com/rates"
  extractors:
    - type: html_css
      selector: "table#personal-loans td.rate"
      take: first
      value_pattern: "(\d+\.\d+)\s*%"
      percent_format: plain   # 'plain' (e.g., '7.5') or 'basis' (e.g., '0.075')
```

### Tips
- Use `json_api` when the bank has a public JSON endpoint.
- For HTML: try to target the **smallest stable selector** (e.g., a `data-testid` attribute).
- If a site lists a range, set `take: min` to capture the lowest advertised rate, or `avg` to average the numbers.

## License
MIT
