"""Build data/cache/search_index.json: the list of listings the website's search box offers.
ASX companies come from the ASX directory (with market cap), US large caps from the S&P 500
list on Wikipedia, and Australian ETFs from config/etf_list.csv. Run by run_build.sh weekly;
safe to run any time. Falls back to whatever is cached if a source is unreachable."""
from __future__ import annotations
import csv, io, json, re, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cache" / "search_index.json"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
ASX_URL = "https://asx.api.markitdigital.com/asx-research/1.0/companies/directory/file?access_token=83ff96335c2d45a094df02a206a39ff4"
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
MIN_CAP = 300_000_000

def fetch(url: str) -> str:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode("utf-8", "replace")

def asx() -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(fetch(ASX_URL))))
    out = []
    for r in rows:
        try:
            cap = float(r.get("Market Cap") or 0)
        except ValueError:
            cap = 0
        if cap >= MIN_CAP:
            out.append({"symbol": r["ASX code"].strip() + ".AX", "name": r["Company name"].strip().title().replace(" Limited", " Ltd"),
                        "exchange": "ASX", "type": "EQUITY", "sector": r.get("GICs industry group", ""), "cap": cap})
    return out

def sp500() -> list[dict]:
    html = fetch(SP500_URL)
    table = html.split('id="constituents"', 1)[1].split("</table>", 1)[0]
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S)[1:]:
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 4:
            sym = cells[0].replace(".", "-")
            out.append({"symbol": sym, "name": cells[1], "exchange": "US", "type": "EQUITY", "sector": cells[3], "cap": None})
    return out

def etfs() -> list[dict]:
    p = ROOT / "config" / "etf_list.csv"
    if not p.exists():
        return []
    return [{"symbol": r["ticker"], "name": r["name"], "exchange": "ASX", "type": "ETF", "sector": r.get("asset_class", ""), "cap": None}
            for r in csv.DictReader(open(p))]

def main() -> int:
    idx = {"built": time.strftime("%Y-%m-%d"), "items": []}
    old = json.load(open(OUT)) if OUT.exists() else {"items": []}
    for name, fn in [("asx", asx), ("sp500", sp500), ("etf", etfs)]:
        try:
            items = fn()
            print(f"{name}: {len(items)}")
        except Exception as e:  # noqa: BLE001
            items = [i for i in old.get("items", []) if i.get("src") == name]
            print(f"{name}: failed ({e}); keeping {len(items)} cached")
        for i in items:
            i["src"] = name
        idx["items"].extend(items)
    seen, dedup = set(), []
    for i in idx["items"]:
        if i["symbol"] not in seen:
            seen.add(i["symbol"]); dedup.append(i)
    idx["items"] = dedup
    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(idx, open(OUT, "w"))
    print(f"wrote {len(dedup)} listings to {OUT}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
