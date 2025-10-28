
import argparse
import asyncio
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
import yaml
import pandas as pd
from bs4 import BeautifulSoup

TAKE_FUNCS = {
    "first": lambda vals: vals[0] if vals else None,
    "min": lambda vals: min(vals) if vals else None,
    "max": lambda vals: max(vals) if vals else None,
    "avg": lambda vals: sum(vals)/len(vals) if vals else None,
}

def _to_float(s: str) -> Optional[float]:
    try:
        s = s.replace(",", ".")
        return float(s)
    except Exception:
        return None

async def fetch_text(client: httpx.AsyncClient, url: str, timeout: float = 20.0) -> str:
    r = await client.get(url, timeout=timeout, headers={
        "User-Agent": "Mozilla/5.0 (compatible; LoanRatesBot/1.0)"
    })
    r.raise_for_status()
    return r.text

def extract_from_html_css(html: str, selector: str, value_pattern: Optional[str]) -> List[float]:
    soup = BeautifulSoup(html, "lxml")
    # naive CSS: BeautifulSoup doesn't support :contains, so handle manually
    values = []
    if ":contains(" in selector:
        # crude contains handling for demo
        m = re.match(r"(.+):contains\\(['\\\"](.+?)['\\\"]\\)", selector)
        if m:
            base_sel, needle = m.group(1).strip(), m.group(2)
            nodes = soup.select(base_sel) if base_sel else [soup]
            texts = []
            for n in nodes:
                if n and needle.lower() in n.get_text(" ", strip=True).lower():
                    texts.append(n.get_text(" ", strip=True))
            if value_pattern:
                rx = re.compile(value_pattern, re.I)
                for t in texts:
                    for g in rx.findall(t):
                        num = _to_float(g if isinstance(g, str) else g[0])
                        if num is not None:
                            values.append(num)
            else:
                # fallback: pull any numbers with %
                rx = re.compile(r"(\\d+[\\.,]?\\d*)\\s*%")
                for t in texts:
                    for g in rx.findall(t):
                        num = _to_float(g)
                        if num is not None:
                            values.append(num)
            return values

    nodes = soup.select(selector) if selector else [soup]
    texts = [n.get_text(" ", strip=True) for n in nodes if n]
    if value_pattern:
        rx = re.compile(value_pattern, re.I)
        for t in texts:
            for g in rx.findall(t):
                if isinstance(g, tuple):
                    g = g[0]
                num = _to_float(g)
                if num is not None:
                    values.append(num)
    else:
        rx = re.compile(r"(\\d+[\\.,]?\\d*)\\s*%")
        for t in texts:
            for g in rx.findall(t):
                num = _to_float(g)
                if num is not None:
                    values.append(num)
    return values

def extract_with_regex(html: str, pattern: str) -> List[float]:
    rx = re.compile(pattern, re.I | re.S)
    values = []
    for g in rx.findall(html):
        if isinstance(g, tuple):
            g = g[0]
        num = _to_float(g)
        if num is not None:
            values.append(num)
    return values

def numbers_postprocess(vals: List[float], percent_format: str) -> List[float]:
    if percent_format == "basis":
        return [v * 100.0 for v in vals]
    return vals

async def scrape_bank(client: httpx.AsyncClient, bank_cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = bank_cfg["source_url"]
    html = await fetch_text(client, url)
    for extractor in bank_cfg.get("extractors", []):
        etype = extractor["type"]
        try:
            if etype == "html_css":
                vals = extract_from_html_css(
                    html=html,
                    selector=extractor.get("selector","body"),
                    value_pattern=extractor.get("value_pattern"),
                )
            elif etype == "regex":
                vals = extract_with_regex(html, extractor["pattern"])
            elif etype == "json_api":
                # naive JSON fetch (if the page itself is JSON)
                # In practice, you'd pass a separate URL. For demo we try parsing 'html' as JSON first.
                try:
                    data = httpx.Response(200, text=html).json()
                except Exception:
                    # if not JSON, skip this extractor
                    continue
                # field mapping: e.g., {"field": "rates.0.apr", "multiplier": 100}
                field = extractor.get("field")
                if not field:
                    continue
                cur = data
                for part in field.split("."):
                    if isinstance(cur, list):
                        try:
                            idx = int(part)
                            cur = cur[idx]
                        except Exception:
                            cur = None
                            break
                    else:
                        cur = cur.get(part) if isinstance(cur, dict) else None
                if cur is None:
                    vals = []
                else:
                    if isinstance(cur, list):
                        nums = []
                        for item in cur:
                            try:
                                nums.append(float(item))
                            except Exception:
                                pass
                        vals = nums
                    else:
                        try:
                            vals = [float(cur)]
                        except Exception:
                            vals = []
                mult = extractor.get("multiplier", 1.0)
                vals = [v * mult for v in vals]
            else:
                continue

            vals = numbers_postprocess(vals, extractor.get("percent_format", "plain"))
            vals = [v for v in vals if 0.0 < v < 200.0]  # drop nonsense
            if not vals:
                continue

            take = extractor.get("take", "min")
            agg_func = TAKE_FUNCS.get(take, TAKE_FUNCS["min"])
            apr = agg_func(vals)
            if apr is None:
                continue

            return {
                "bank": bank_cfg["bank"],
                "country": bank_cfg.get("country",""),
                "product": bank_cfg.get("product",""),
                "term": bank_cfg.get("term",""),
                "currency": bank_cfg.get("currency",""),
                "apr": float(apr),
                "source_url": url,
                "fetched_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
        except Exception:
            # try next extractor if this one fails
            continue
    return None

async def run(config_path: str) -> List[Dict[str, Any]]:
    cfg = yaml.safe_load(open(config_path, "r", encoding="utf-8"))
    banks = cfg.get("banks", [])
    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [scrape_bank(client, b) for b in banks]
        for coro in asyncio.as_completed(tasks):
            rec = await coro
            if rec:
                results.append(rec)
    return results

def as_table(df: pd.DataFrame) -> str:
    # Simple aligned table for console
    return df.to_string(index=False, formatters={"apr": "{:.2f}%".format})

def main():
    ap = argparse.ArgumentParser(description="Global Loan Rates Scraper")
    ap.add_argument("--config", required=True, help="Path to YAML config")
    ap.add_argument("--out", default="", help="Path to output CSV/JSON (by extension)")
    ap.add_argument("--format", choices=["table","csv","json"], default="table")
    args = ap.parse_args()

    results = asyncio.run(run(args.config))
    if not results:
        print("No rates collected. Try adjusting selectors or adding more banks.")
        return

    df = pd.DataFrame(results).sort_values("apr", ascending=True).reset_index(drop=True)

    if args.out:
        ext = pathlib.Path(args.out).suffix.lower()
        os.makedirs(str(pathlib.Path(args.out).parent), exist_ok=True)
        if ext == ".csv":
            df.to_csv(args.out, index=False)
        elif ext == ".json":
            df.to_json(args.out, orient="records", force_ascii=False, indent=2)
        else:
            # default to CSV
            df.to_csv(args.out if ext else f"{args.out}.csv", index=False)

    if args.format == "table":
        print(as_table(df))
    elif args.format == "csv":
        print(df.to_csv(index=False))
    else:
        print(df.to_json(orient="records", force_ascii=False, indent=2))

if __name__ == "__main__":
    main()
