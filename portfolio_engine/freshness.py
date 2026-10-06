"""Is every holding's data up to date? One row per holding in the universe, checked at each build.

Prices: a listed price older than four calendar days (a long weekend) is stale; more than ten days is badly stale (the
feed has stopped answering for it or it has been suspended or delisted). A price that came from yesterday's cache
because every source failed today is flagged even if the date looks recent. Unlisted funds and term deposits carry the
unit price and date entered in config/unlisted_funds.csv or data/manual_prices.csv: older than 35 days is stale, and a
unit price of exactly 1.00 on anything but cash is a notional placeholder, not the fund's real price (harmless for
sizing, since unlisted funds trade in dollars, but it must not be quoted as a price). Credit and cash funds that hold
their unit price at 1.00 are not flagged.

Other daily data: the ASX facts (dividends, franking) are refreshed every 20 hours; analyst research every day; the
managers' own published returns for unlisted funds monthly. Each is flagged when it falls behind.

The result is written to output/freshness.json and shown at the top of the Daily brief."""
from __future__ import annotations

from datetime import date

import pandas as pd

STALE_LISTED_DAYS = 4
VERY_STALE_DAYS = 10
STALE_UNLISTED_DAYS = 35
STALE_RETURNS_MONTHS = 2


def _days(a: date, b: str | date | None) -> int | None:
    if not b:
        return None
    try:
        return (a - pd.Timestamp(b).date()).days
    except (ValueError, TypeError):
        return None


def data_freshness(universe: pd.DataFrame, md, manual: dict[str, float], manual_dates: dict[str, str], unlisted: pd.DataFrame,
                   research: dict, asx_facts: dict, in_models: set[str], house: set[str]) -> dict:
    today = md.as_of.date()
    unl = unlisted.set_index("ticker") if len(unlisted) else pd.DataFrame()
    rows = []
    for _, r in universe.drop_duplicates("ticker").iterrows():
        t, veh = str(r["ticker"]), str(r["vehicle"])
        row = {"ticker": t, "name": str(r["name"]), "vehicle": veh, "in_model": t in in_models, "house": t in house,
               "watchlist": str(r.get("status", "") or "") == "watchlist", "issues": []}
        src = md.source_by_ticker.get(t, "")
        if veh == "cash":
            row.update(price_source="cash account", price_date=str(today), status="ok")
        elif t in md.prices.columns and md.prices[t].dropna().shape[0]:
            d = md.prices[t].last_valid_index().date()
            age = (today - d).days
            row.update(price_source={"yfinance": "price feed", "cache": "price feed (cached today)", "stale-cache": "yesterday's cache: every source failed",
                                     "stooq": "Stooq", "synthetic": "synthetic"}.get(src, src or "price feed"), price_date=str(d), price_age=age)
            if src == "stale-cache":
                row["issues"].append("no source answered at this build; the last cached price is used")
            if age > VERY_STALE_DAYS:
                row["issues"].append(f"last price is {age} days old: suspended, delisted, or the feed has stopped answering")
            elif age > STALE_LISTED_DAYS:
                row["issues"].append(f"last price is {age} days old")
        elif t in md.spot:
            f = asx_facts.get(t, {})
            row.update(price_source="ASX last price (no history)" + (", kept from an earlier day" if src == "asx-stale" else ""),
                       price_date=f.get("fetched", ""), price_age=_days(today, f.get("fetched")))
            if src == "asx-stale":
                row["issues"].append("the ASX did not answer at this build; the last good price is used")
        elif t in manual:
            pdate = manual_dates.get(t) or (str(unl.loc[t, "price_date"]) if t in unl.index else "")
            age = _days(today, pdate)
            row.update(price_source="entered unit price", price_date=pdate, price_age=age, unit_price=manual[t])
            # A credit or cash fund can genuinely hold its unit price at 1.00; a share or infrastructure fund cannot.
            if abs(manual[t] - 1.0) < 1e-9 and veh != "td" and str(r["asset_class"]) in ("aus_equity", "intl_equity", "infrastructure", "property", "alternatives"):
                row["issues"].append("unit price is a notional 1.00, not the fund's real price: enter it in config/unlisted_funds.csv if it is ever quoted")
            elif age is None:
                row["issues"].append("no date on the entered unit price")
            elif age > STALE_UNLISTED_DAYS and veh != "td":
                row["issues"].append(f"entered unit price is {age} days old")
        else:
            row.update(price_source="none", price_date="")
            row["issues"].append("no price from any source: the engine holds its weight in cash")
        if t in unl.index:
            ra = str(unl.loc[t, "returns_as_at"] or "")
            if veh != "td" and ra:
                months = (today.year - int(ra[:4])) * 12 + today.month - int(ra[5:7]) if len(ra) >= 7 and ra[:4].isdigit() else None
                row["returns_as_at"] = ra
                if months is not None and months > STALE_RETURNS_MONTHS:
                    row["issues"].append(f"manager's published returns are as at {ra}")
            elif veh != "td":
                row["issues"].append("no published returns entered; history comes from the listed stand-in")
        f = asx_facts.get(t)
        if f:
            row["asx_fetched"] = f.get("fetched", "")
            a = _days(today, f.get("fetched"))
            if a is not None and a > 3:
                row["issues"].append(f"ASX dividend and franking facts are {a} days old")
        res = research.get(t)
        if res is not None and getattr(res, "fetched", ""):
            row["research_fetched"] = res.fetched
            a = _days(today, res.fetched)
            if a is not None and a > 3 and t not in unl.index:
                row["issues"].append(f"analyst research is {a} days old")
        row["status"] = "ok" if not row["issues"] else ("notional" if all("notional" in i for i in row["issues"]) else "stale")
        rows.append(row)
    rows.sort(key=lambda x: (x["status"] == "ok", not x["house"], not x["in_model"], x["ticker"]))
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("ok", "stale", "notional")}
    return {"as_of": str(today), "synthetic": bool(md.synthetic), "total": len(rows), "counts": counts,
            "in_models": {k: sum(1 for r in rows if r["in_model"] and r["status"] == k) for k in ("ok", "stale", "notional")},
            "rows": rows}
