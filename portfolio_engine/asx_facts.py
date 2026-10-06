"""Facts from the ASX's own data feed for every ASX listing in the universe.

For each code: the most recent dividend or distribution and the share of it that was franked, its ex and pay dates, the
annual yield, P/E and earnings per share, the 52 week range, the security type (share, ETF, hybrid, government bond),
the security's own description (for notes and hybrids this carries the margin and the maturity or call date), the
issuer's description, sector and listing date.

The daily build uses them to replace guessed franking with the franking of the last dividend actually paid, to fill a
yield the price feed lacks, and to name holdings added by code. The website shows them on each holding's fact sheet and
in the Daily brief's ASX lookup. Cached in data/cache/asx_facts.json for 20 hours; a code the ASX cannot answer keeps its
last good facts."""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

API = "https://asx.api.markitdigital.com/asx-research/1.0"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
           "Accept": "application/json"}
ISSUE_TYPES = {"CS": "share", "ETF": "ETF", "PR": "hybrid or preference security", "FLC": "listed note", "FRG": "government bond",
               "UT": "unit trust", "SP": "stapled security"}


def _get(session, path: str) -> dict:
    try:
        r = session.get(f"{API}/{path}", headers=HEADERS, timeout=12)
        return (r.json() or {}).get("data") or {} if r.status_code == 200 else {}
    except Exception as e:  # noqa: BLE001
        log.debug("ASX %s failed: %s", path, e)
        return {}


def fetch_one(code: str, session=None, about: bool = True) -> dict:
    """The facts for one ASX code (without .AX), in the shape the website uses. Empty when the ASX does not know it."""
    import requests
    s = session or requests.Session()
    c = code.lower()
    k, h = _get(s, f"companies/{c}/key-statistics"), _get(s, f"companies/{c}/header")
    a = _get(s, f"companies/{c}/about") if about else {}
    if not (k or h):
        return {}
    num = lambda v: None if v in (None, -32768) else v   # noqa: E731  the feed uses -32768 for "not applicable"
    out = {
        "name": (h.get("displayName") or a.get("displayName") or "").strip().rstrip("."),
        "issue_type": a.get("issueType") or "", "kind": ISSUE_TYPES.get(a.get("issueType") or "", ""),
        "security": (k.get("shareDescription") or "").strip(), "description": (a.get("description") or "").strip(),
        "sector": h.get("sector") or "", "industry": h.get("industryGroup") or "", "listed": h.get("dateListed") or "",
        "isin": k.get("isin") or "", "market_cap": num(h.get("marketCap")), "price": num(h.get("priceLast")),
        "last_dividend": k.get("dividend"), "dividend_currency": k.get("dividendCurrency") or "", "dividend_type": k.get("dividendType") or "",
        "franking_pct": k.get("frankingPercent"), "ex_date": k.get("dateExDate") or "", "pay_date": k.get("datePayDate") or "",
        "yield_pct": round(k["yieldAnnual"], 2) if isinstance(k.get("yieldAnnual"), (int, float)) else None,
        "pe": round(k["priceEarningsRatio"], 1) if isinstance(k.get("priceEarningsRatio"), (int, float)) else None,
        "high_52w": num(k.get("priceFiftyTwoWeekHigh")), "low_52w": num(k.get("priceFiftyTwoWeekLow")),
        "fetched": time.strftime("%Y-%m-%d"),
    }
    if out["market_cap"] == 0:
        out["market_cap"] = None
    return {kk: v for kk, v in out.items() if v not in ("", None)}


def asx_code(ticker: str) -> str | None:
    t = ticker.upper()
    return t[:-3] if t.endswith(".AX") or t.endswith(".XA") else None


def get_asx_facts(tickers: list[str], cache_path: Path, *, max_age_hours: float = 20, offline: bool = False, workers: int = 8) -> dict[str, dict]:
    """Facts for every ASX or Cboe Australia ticker in `tickers`, from the cache when it is fresh, otherwise from the ASX.
    Cboe listings (.XA) are looked up by code; the ASX feed answers for those it also lists."""
    cache: dict[str, dict] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except (OSError, ValueError):
            cache = {}
    fresh = cache_path.exists() and time.time() - cache_path.stat().st_mtime < max_age_hours * 3600
    wanted = [t for t in tickers if asx_code(t)]
    if offline or (fresh and all(t in cache for t in wanted)):
        return {t: cache[t] for t in wanted if t in cache}
    import requests
    session = requests.Session()

    def one(t: str):
        return t, fetch_one(asx_code(t), session, about=True)

    got: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for t, f in ex.map(one, wanted):
            if f:
                got[t] = f
    merged = {**cache, **got}   # a code the ASX could not answer today keeps yesterday's facts
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(merged))
    except OSError:
        pass
    log.info("ASX facts: %d of %d listings answered", len(got), len(wanted))
    return {t: merged[t] for t in wanted if t in merged}


def apply_asx_facts(universe: pd.DataFrame, facts: dict[str, dict]) -> tuple[pd.DataFrame, list[str]]:
    """Franking from the last dividend the ASX recorded (replacing the configured guess), a yield where none is configured,
    and a name for holdings added by code. Returns the updated frame and a note per change."""
    if not facts or universe.empty:
        return universe, []
    u = universe.copy()
    notes: list[str] = []
    for i, r in u.iterrows():
        f = facts.get(r["ticker"])
        if not f:
            continue
        fr = f.get("franking_pct")
        if fr is not None and f.get("last_dividend") and f.get("dividend_currency", "AUD") == "AUD" and abs(float(r["franking"]) - float(fr)) >= 1:
            notes.append(f"{r['ticker']}: franking {float(r['franking']):.0f}% -> {float(fr):.0f}% (ASX, last dividend)")
            u.at[i, "franking"] = round(float(fr), 1)
        if float(r["yield"] or 0) == 0 and f.get("yield_pct"):
            u.at[i, "yield"] = float(f["yield_pct"])
        if str(r["name"]).strip().upper() == str(r["ticker"]).strip().upper() and f.get("name"):
            u.at[i, "name"] = f["name"].title().replace("Ltd", "Ltd").replace(" Limited", " Limited")
    return u, notes


def compact(f: dict) -> dict:
    """The fields the website shows, without the long issuer description."""
    keep = ("kind", "security", "sector", "industry", "listed", "market_cap", "last_dividend", "dividend_currency", "franking_pct",
            "ex_date", "pay_date", "yield_pct", "pe", "high_52w", "low_52w", "fetched", "description")
    out = {k: f[k] for k in keep if k in f}
    if "description" in out:
        out["description"] = out["description"][:400]
    return out
