"""Pre-compute the data the builder page needs for every listing in the search index, so a visitor can add
any of them without the website calling a price feed at run time (Yahoo Finance refuses requests from
data-centre addresses, so the on-demand function cannot be relied on).

Writes site/data/listings/<SYMBOL>.json, one file per listing, in the same shape as
netlify/functions/history.mjs returns: name, currency, latest price, trailing dividend yield, ten years of
month-end total returns in Australian dollars, a year of daily returns in the listing's own currency, and
trailing 1/3/5/10 year returns. Also writes site/data/listings/index.json (built date and symbol count).

Run by the daily workflow after the engine build. Takes a few minutes for ~1,100 listings."""
from __future__ import annotations

import json
import logging
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from portfolio_engine.config import guess_currency, load_settings  # noqa: E402
from portfolio_engine.market_data import fx_tickers_for, _quotes_foreign_per_aud  # noqa: E402

OUT = ROOT / "site" / "data" / "listings"
CHUNK = 150
log = logging.getLogger("listings")


def download(tickers: list[str], **kw) -> pd.DataFrame:
    import yfinance as yf
    frames = []
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        for attempt in range(3):
            try:
                df = yf.download(chunk, progress=False, group_by="ticker", threads=True, auto_adjust=True, **kw)
                frames.append(df)
                break
            except Exception as e:  # noqa: BLE001
                log.warning("chunk %d attempt %d failed: %s", i, attempt, e)
                time.sleep(5 * (attempt + 1))
        time.sleep(1)
    return pd.concat(frames, axis=1) if frames else pd.DataFrame()


SECTOR_GROUPS = [  # first match wins; GICS industry groups (ASX directory) and Wikipedia sectors (S&P 500)
    ("food", "Consumer staples"), ("beverage", "Consumer staples"), ("household", "Consumer staples"), ("consumer staples", "Consumer staples"),
    ("consumer discretionary", "Consumer discretionary"), ("retail", "Consumer discretionary"), ("automobile", "Consumer discretionary"), ("consumer durables", "Consumer discretionary"), ("consumer services", "Consumer discretionary"),
    ("bank", "Financials"), ("financial", "Financials"), ("insurance", "Financials"), ("materials", "Materials"), ("energy", "Energy"),
    ("health", "Healthcare"), ("pharma", "Healthcare"), ("software", "Technology"), ("technology", "Technology"), ("semiconductor", "Technology"),
    ("media", "Communication"), ("telecommunication", "Communication"), ("communication", "Communication"),
    ("capital goods", "Industrials"), ("transportation", "Industrials"), ("commercial", "Industrials"), ("industrial", "Industrials"),
    ("utilities", "Utilities"), ("real estate", "Real estate"),
]


def sector_group(raw: str, kind: str) -> str:
    if kind == "ETF":
        return "Diversified fund"
    r = (raw or "").lower()
    for key, grp in SECTOR_GROUPS:
        if key in r:
            return grp
    return "Other"


def col(df: pd.DataFrame, t: str, name: str) -> pd.Series | None:
    try:
        s = df[t][name] if isinstance(df.columns, pd.MultiIndex) else df[name]
    except KeyError:
        return None
    return s.dropna()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    idx_path = ROOT / "data" / "cache" / "search_index.json"
    if not idx_path.exists():
        print("no search index; run scripts/build_search_index.py first")
        return 0
    items = json.load(open(idx_path)).get("items", [])
    extra = ROOT / "config" / "extra_listings.csv"
    if extra.exists():
        for r in pd.read_csv(extra, dtype=str).fillna("").itertuples():
            items.append({"symbol": r.symbol.strip().upper(), "name": r.name, "exchange": getattr(r, "exchange", ""), "type": getattr(r, "type", "EQUITY") or "EQUITY", "sector": getattr(r, "sector", "")})
    seen, listings = set(), []
    for i in items:
        if i["symbol"] not in seen:
            seen.add(i["symbol"]); listings.append(i)
    symbols = [i["symbol"] for i in listings]
    settings = load_settings()
    fx_map = fx_tickers_for(settings.market_data)
    currencies = {s: guess_currency(s) for s in symbols}
    need_fx = sorted({fx_map[c] for c in set(currencies.values()) if c in fx_map})
    log.info("downloading monthly history for %d listings (+%d FX)", len(symbols), len(need_fx))
    monthly = download(symbols + need_fx, period="10y", interval="1mo")
    log.info("downloading daily history")
    daily = download(symbols + need_fx, period="1y", interval="1d", actions=True)
    fx_month, fx_invert = {}, {}
    for ccy, t in fx_map.items():
        s = col(monthly, t, "Close")
        if s is not None and len(s):
            fx_month[ccy] = s.groupby(s.index.strftime("%Y-%m")).last()
            fx_invert[ccy] = _quotes_foreign_per_aud(t)
    OUT.mkdir(parents=True, exist_ok=True)
    written = 0
    for it in listings:
        s = it["symbol"]
        mc = col(monthly, s, "Close")
        dc = col(daily, s, "Close")
        if mc is None or dc is None or len(mc) < 3 or len(dc) < 30:
            continue
        ccy = currencies[s]
        lv = mc.groupby(mc.index.strftime("%Y-%m")).last()
        if ccy != "AUD":
            f = fx_month.get(ccy)
            if f is None:
                continue
            f = f.reindex(lv.index).ffill()
            lv = (lv / f) if fx_invert.get(ccy) else (lv * f)
            lv = lv.dropna()
        months = list(lv.index)
        rets = lv.pct_change().dropna()
        n = len(lv)
        def ann(k: int):
            kk = k if n > k else (n - 1 if n - 1 >= k - 2 else None)   # the feed's "10y" window can be a month or two short
            return round(float((lv.iloc[-1] / lv.iloc[-1 - kk]) ** (12 / kk) - 1) * 100, 2) if kk else None
        dr = dc.pct_change().dropna()
        divs = col(daily, s, "Dividends")
        div_sum = float(divs.sum()) if divs is not None else 0.0
        last = float(dc.iloc[-1])
        lvl = (1 + dr).cumprod()
        mdd = float((lvl / lvl.cummax() - 1).min()) if len(lvl) else 0.0
        rec = {
            "symbol": s, "name": it.get("name", s), "currency": ccy, "price": round(last, 4), "exchange": it.get("exchange", ""), "type": it.get("type", "EQUITY"),
            "sector": it.get("sector", ""), "sector_group": sector_group(it.get("sector", ""), it.get("type", "EQUITY")),
            "yield_pct": round(div_sum / last * 100, 2) if last else 0.0,
            "return_1y_pct": round(float(dc.iloc[-1] / dc.iloc[0] - 1) * 100, 2),
            "return_3y_pct_pa": ann(36), "return_5y_pct_pa": ann(60), "return_10y_pct_pa": ann(120), "history_years": round(n / 12, 1),
            "volatility_1y_pct": round(float(dr.std() * math.sqrt(252)) * 100, 2) if len(dr) > 20 else None,
            "max_drawdown_1y_pct": round(mdd * 100, 2),
            "spark": [round(float(v / dc.iloc[0] * 100), 2) for v in dc.iloc[::max(1, len(dc) // 60)]],
            "monthly": {"months": [m for m in months[1:]], "returns": [round(float(x), 5) for x in rets]},
            "daily": {"dates": [d.strftime("%Y-%m-%d") for d in dr.index], "returns": [round(float(x), 5) for x in dr]},
            "built": time.strftime("%Y-%m-%d"),
        }
        (OUT / f"{s}.json").write_text(json.dumps(rec, separators=(",", ":")))
        written += 1
    (OUT / "index.json").write_text(json.dumps({"built": time.strftime("%Y-%m-%d"), "count": written,
                                                "symbols": sorted(p.stem for p in OUT.glob("*.json") if p.stem != "index")}))
    log.info("wrote %d listing files to %s", written, OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
