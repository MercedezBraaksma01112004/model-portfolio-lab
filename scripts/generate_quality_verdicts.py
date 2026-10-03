"""Give every holding in the universe a quality verdict. Hand-written verdicts in config/quality_review.csv are
never touched; holdings without one get a verdict derived from the research feed (size, history, returns,
volatility, drawdown, analyst view, cost) with a note that says exactly which numbers produced it, and a
"reviewed" stamp marking it as generated so a hand review can replace it later. Run after a build, before
scripts/quality_report.py. Pass --refresh-generated to regenerate the generated ones from today's data."""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = "generated from the data feed"


def money(x: float | None) -> str:
    if not x:
        return "size unknown"
    return f"${x / 1e9:.0f} bn" if x >= 1e9 else f"${x / 1e6:.0f} m"


def pct(x, d=1):
    return "–" if x is None else f"{x:+.{d}f}%"


def verdict_for(u: dict, r: dict, fx: dict) -> tuple[str, str]:
    veh, cls, name = u["vehicle"], u["asset_class"], u["name"]
    mer = float(u.get("mer") or 0)
    cap = r.get("market_cap")
    cap_aud = (cap or 0) * fx.get(str(r.get("price_currency", "AUD")).upper(), 1.0)
    r5, r10, r1 = r.get("return_5y_pct_pa"), r.get("return_10y_pct_pa"), r.get("return_1y_pct")
    vol, dd = r.get("volatility_1y_pct"), r.get("max_drawdown_1y_pct")
    hist = r.get("history_years") or 0
    cons = r.get("consensus_label") or "no coverage"
    yld = r.get("dividend_yield_pct")
    bits = []
    if veh in ("etf", "lic", "lit", "fund"):
        broad = any(k in name.lower() for k in ["index", "australia 200", "asx 200", "s&p 500", "all-world", "world", "international shares", "aggregate", "composite", "core", "total market", "msci"])
        thematic = any(k in name.lower() for k in ["cyber", "robot", "genomic", "pharma", "moat", "crypto", "lithium", "uranium", "battery", "video", "cloud", "semiconductor", "silver", "metaverse", "hydrogen"])
        if mer > 0.9:
            v = "satellite"; bits.append(f"a {mer:.2f}% cost is high for a fund, so it has to earn its place")
        elif thematic:
            v = "satellite"; bits.append("a single theme, so it concentrates rather than spreads risk")
        elif broad and mer <= 0.3:
            v = "core"; bits.append(f"broad exposure at {mer:.2f}% a year")
        else:
            v = "satellite"; bits.append(f"{mer:.2f}% a year")
        if cls in ("fixed_income", "credit", "cash") and (vol or 0) > 12:
            v = "satellite"; bits.append(f"moves ±{vol:.0f}% a year, more than a defensive holding should")
    else:
        v = "satellite"
        if cap_aud >= 50e9 and (r5 is None or r5 > 0) and (vol or 0) < 35:
            v = "core"; bits.append(f"{money(cap_aud)} market leader")
        else:
            bits.append(f"{money(cap_aud)} company" if cap_aud else "size not on the feed")
        if (vol or 0) >= 45 or (dd or 0) <= -40:
            v = "speculative"; bits.append(f"a typical year moves ±{vol:.0f}% with a {dd:.0f}% fall in the last year" if vol and dd else "very volatile")
        if hist and hist < 3:
            v = "data check"; bits.append(f"only {hist} years of listed history")
        if r5 is not None and r5 < 0 and r1 is not None and r1 < 0:
            v = "not recommended" if v != "data check" else v; bits.append(f"negative over 1 and 5 years ({pct(r1)} and {pct(r5)} a year)")
        if cons in ("Underperform", "Sell"):
            bits.append(f"analyst consensus {cons}")
            if v == "core":
                v = "satellite"
    bits.append(f"5 year {pct(r5)} a year, 10 year {pct(r10)} a year" + (f"; yield {yld:.1f}%" if yld else "; no dividend"))
    if vol is not None and v != "speculative":
        bits.append(f"typical year ±{vol:.0f}%")
    note = f"{u.get('sector') or ''}{', ' if u.get('sector') else ''}{u.get('region') or ''}: " + "; ".join(bits) + "."
    return v, note[0].upper() + note[1:]


def main() -> int:
    refresh = "--refresh-generated" in sys.argv
    qpath = ROOT / "config" / "quality_review.csv"
    rows = list(csv.DictReader(open(qpath)))
    have = {r["ticker"]: r for r in rows}
    uni = list(csv.DictReader(open(ROOT / "config" / "universe.csv")))
    files = sorted((ROOT / "output").glob("portfolios_2*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        print("no build output; run the build first")
        return 1
    d = json.load(open(files[-1]))
    research = {r["ticker"]: r for r in d.get("research", [])}
    fx = {"AUD": 1.0, "USD": 1.5, "EUR": 1.7, "GBP": 2.0, "CAD": 1.1, "CHF": 1.9, "NZD": 0.9}
    try:
        from portfolio_engine.config import load_settings
        from portfolio_engine.market_data import get_market_data
        md = get_market_data(load_settings(), [])
        fx.update(md.fx_aud_per)
    except Exception:  # noqa: BLE001
        pass
    added = replaced = 0
    today = time.strftime("%Y-%m-%d")
    for u in uni:
        t = u["ticker"]
        if u.get("status") == "esg" or u["vehicle"] == "cash":
            continue
        cur = have.get(t)
        if cur and not (refresh and GENERATED in cur.get("reviewed", "")):
            continue
        v, note = verdict_for(u, research.get(t, {}), fx)
        rec = {"ticker": t, "verdict": v, "note": note, "reviewed": f"{today} ({GENERATED}; not yet reviewed by hand)"}
        if cur:
            cur.update(rec); replaced += 1
        else:
            rows.append(rec); have[t] = rec; added += 1
    with open(qpath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "verdict", "note", "reviewed"])
        w.writeheader(); w.writerows(rows)
    print(f"quality verdicts: {added} added, {replaced} regenerated, {len(rows)} total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
