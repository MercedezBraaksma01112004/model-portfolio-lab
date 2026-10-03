"""Screen every listing the site knows about and keep the universe honest.

For all ~1,100 listings in the search index (ASX companies over $300m, the S&P 500, Australian ETFs) plus
anything already in the universe, build a scorecard from the pre-computed listing data and the research feed:
size, 1/3/5/10 year returns, volatility, worst fall, yield, analyst consensus. Score 0 to 100. Then:

* a listing that clears the bar (score and size) and is not in the universe is added as a satellite, so the
  model portfolios can reach for it when it fits a profile;
* an active universe holding that fails badly (negative over three and five years and below its 200 day
  average, or consensus Sell with a falling price) is moved to the watchlist with the reason, never deleted;
* the whole scorecard is written to config/universe_scorecard.csv so every decision can be checked.

Without --apply the script only writes the scorecard and prints what it would change; the daily workflow applies
the changes once a week so the models do not churn on every wobble. Hand-set rows (ESG substitutes, unlisted
funds, cash) are untouched. Run after build_listing_data.py."""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from portfolio_engine.config import guess_currency, guess_region  # noqa: E402
from scripts.build_listing_data import sector_group  # noqa: E402

LISTINGS = ROOT / "site" / "data" / "listings"
ADD_SCORE = 68          # a listing needs this score to be added
ADD_CAP_AUD = 8e9       # and this market capitalisation (shares only)
MAX_ADDED = 80          # at most this many additions per run, best scores first
DROP_SCORE = 20         # an active universe share below this with a falling price moves to the watchlist
NEVER = {"AMC.AX", "AMCR"}   # Amcor: excluded by standing instruction
KEEP = set(pd.read_csv(ROOT / "config" / "universe.csv", dtype=str).fillna("").query("notes.str.contains('Pinned by Mercedez')", engine="python")["ticker"])   # pinned: the screen never moves these


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def score_row(d: dict, cap_aud: float | None, cons: str, is_fund: bool) -> tuple[float, list[str]]:
    r1, r3, r5, r10 = d.get("return_1y_pct"), d.get("return_3y_pct_pa"), d.get("return_5y_pct_pa"), d.get("return_10y_pct_pa")
    vol, dd, hist = d.get("volatility_1y_pct"), d.get("max_drawdown_1y_pct"), d.get("history_years") or 0
    pts, why = 0.0, []
    # long-run record (up to 40)
    rec = 0.0
    if r10 is not None:
        rec += clip(r10 / 15.0, -1, 1) * 20
    elif r5 is not None:
        rec += clip(r5 / 15.0, -1, 1) * 14
    if r5 is not None:
        rec += clip(r5 / 15.0, -1, 1) * 12
    if r3 is not None:
        rec += clip(r3 / 15.0, -1, 1) * 8
    pts += rec
    why.append(f"5y {r5:+.0f}% a year" if r5 is not None else "no 5 year record")
    if r10 is not None:
        why.append(f"10y {r10:+.0f}%")
    # risk (up to 25)
    if vol is not None:
        pts += clip((45.0 - vol) / 25.0, -1, 1) * 15
        why.append(f"±{vol:.0f}%")
    if dd is not None:
        pts += clip((dd + 40.0) / 30.0, -1, 1) * 10
    # recent (up to 15)
    if r1 is not None:
        pts += clip(r1 / 25.0, -1, 1) * 10
    # size (up to 15)
    if cap_aud:
        pts += 15 if cap_aud >= 50e9 else 12 if cap_aud >= 20e9 else 9 if cap_aud >= 8e9 else 6 if cap_aud >= 3e9 else 2
    elif is_fund:
        pts += 8
    # consensus (up to 10)
    pts += {"Strong Buy": 10, "Buy": 7, "Hold": 4, "Underperform": 0, "Sell": -8}.get(cons, 3)
    if cons and cons != "no coverage":
        why.append(f"consensus {cons}")
    if hist and hist < 3:
        pts = min(pts, 35)
        why.append("under 3 years listed")
    return round(clip(pts, 0, 100), 1), why


def main() -> int:
    apply = "--apply" in sys.argv
    if not LISTINGS.exists():
        print("no listing data; run scripts/build_listing_data.py first")
        return 1
    uni = pd.read_csv(ROOT / "config" / "universe.csv", dtype=str).fillna("")
    research = {}
    files = sorted((ROOT / "output").glob("portfolios_2*.json"), key=lambda p: p.stat().st_mtime)
    if files:
        research = {r["ticker"]: r for r in json.load(open(files[-1])).get("research", [])}
    idx = {i["symbol"]: i for i in json.load(open(ROOT / "data" / "cache" / "search_index.json")).get("items", [])}
    caps = json.load(open(ROOT / "data" / "cache" / "caps.json")) if (ROOT / "data" / "cache" / "caps.json").exists() else {}
    fx = {"AUD": 1.0, "USD": 1.5, "EUR": 1.7, "GBP": 2.0, "CAD": 1.1, "CHF": 1.9}
    try:
        from portfolio_engine.config import load_settings
        from portfolio_engine.market_data import get_market_data
        fx.update(get_market_data(load_settings(), []).fx_aud_per)
    except Exception:  # noqa: BLE001
        pass
    have = {t: i for i, t in enumerate(uni["ticker"])}
    rows, added, dropped = [], [], []
    symbols = sorted(set(p.stem for p in LISTINGS.glob("*.json") if p.stem != "index") | set(uni["ticker"]))
    def prescore(sym):
        f = LISTINGS / f"{sym}.json"
        if not f.exists():
            return -1
        d = json.load(open(f)); r = research.get(sym, {})
        cap = r.get("market_cap") or caps.get(sym) or idx.get(sym, {}).get("cap")
        return score_row(d, float(cap) if cap else None, r.get("consensus_label", "") if r else "", d.get("type") == "ETF")[0]
    symbols.sort(key=lambda x: -prescore(x))
    for s in symbols:
        f = LISTINGS / f"{s}.json"
        d = json.load(open(f)) if f.exists() else {}
        r = research.get(s, {})
        if not d and r:
            d = {k: r.get(k) for k in ("return_1y_pct", "return_3y_pct_pa", "return_5y_pct_pa", "return_10y_pct_pa", "volatility_1y_pct", "max_drawdown_1y_pct", "history_years")}
            d["name"] = r.get("name", s); d["type"] = "ETF" if r.get("quote_type") == "ETF" else "EQUITY"
        if not d:
            continue
        in_uni = s in have
        urow = uni.iloc[have[s]] if in_uni else None
        is_fund = (urow is not None and urow["vehicle"] != "direct") or (urow is None and (d.get("type") == "ETF" or idx.get(s, {}).get("type") == "ETF"))
        cap = r.get("market_cap") or caps.get(s) or idx.get(s, {}).get("cap")
        ccy = str(r.get("price_currency") or guess_currency(s)).upper()
        cap_aud = float(cap) * fx.get(ccy, 1.0) if cap and not is_fund else None
        cons = r.get("consensus_label", "") if r else ""
        sc, why = score_row(d, cap_aud, cons, is_fund)
        decision = ""
        above = r.get("above_200dma") if r else None
        r3, r5 = d.get("return_3y_pct_pa"), d.get("return_5y_pct_pa")
        if in_uni:
            status = urow["status"]
            falling = (above is False) and (d.get("return_1y_pct") or 0) < 0
            if status == "active" and s not in KEEP and urow["vehicle"] == "direct" and urow["source"] != "unlisted_fund" and (
                    (r3 is not None and r5 is not None and r3 < 0 and r5 < 0 and falling) or (cons == "Sell" and falling) or sc < DROP_SCORE):
                decision = "moved to watchlist"
                reason = "down over 3 and 5 years and below its 200 day average" if (r3 is not None and r5 is not None and r3 < 0 and r5 < 0) else ("consensus Sell with a falling price" if cons == "Sell" else f"score {sc}")
                uni.loc[have[s], "status"] = "watchlist"
                uni.loc[have[s], "notes"] = f"Moved to watchlist {time.strftime('%Y-%m-%d')} by the screen: {reason}. " + urow["notes"]
                dropped.append((s, reason))
            else:
                decision = f"kept ({status})"
        elif s in NEVER:
            decision = "excluded by standing instruction"
        else:
            region = guess_region(s, d.get("name", ""))
            if sc >= ADD_SCORE and (is_fund or (cap_aud and cap_aud >= ADD_CAP_AUD)) and (d.get("history_years") or 0) >= 3 and region in ("Australia", "United States") and len(added) < MAX_ADDED and not is_fund:
                sec = sector_group(idx.get(s, {}).get("sector", "") or r.get("sector", ""), "ETF" if is_fund else "EQUITY")
                if sec == "Other":
                    sec = ""   # the build fills it from the research feed's sector
                cls = "aus_equity" if region == "Australia" else "intl_equity"
                if is_fund:
                    cls = idx.get(s, {}).get("sector", cls) if idx.get(s, {}).get("sector", "") in ("aus_equity", "intl_equity", "infrastructure", "alternatives", "fixed_income", "credit", "cash") else cls
                elif sec == "Real estate":
                    cls = "infrastructure"
                big = cap_aud and cap_aud >= 20e9
                row = {c: "" for c in uni.columns}
                row.update({"ticker": s, "name": d.get("name", s), "asset_class": cls, "vehicle": "etf" if is_fund else "direct", "role": "satellite",
                            "currency": ccy if not is_fund else "AUD", "mer": "0.3" if is_fund else ("0.1" if ccy == "USD" else "0"), "yield": "0",
                            "franking": "100" if (region == "Australia" and not is_fund and sec not in ("Real estate",)) else "0", "weight_hint": "3" if big else "2",
                            "min_tier": "established" if big else "high", "max_weight": "5" if big else "4", "priority": "3",
                            "notes": f"Added by the screen {time.strftime('%Y-%m-%d')}: score {sc}/100 ({'; '.join(why)}). Franking is an estimate.",
                            "source": "research_screen", "status": "active", "sector": sec, "region": region})
                uni = pd.concat([uni, pd.DataFrame([row])], ignore_index=True)
                have[s] = len(uni) - 1
                decision = "added"
                added.append((s, sc))
            else:
                decision = "not added" if sc < ADD_SCORE else "too small or outside the screened markets"
        rows.append({"ticker": s, "name": d.get("name", s), "in_universe": "yes" if in_uni else "", "score": sc, "decision": decision,
                     "market_cap_aud_bn": round(cap_aud / 1e9, 1) if cap_aud else "", "return_1y": d.get("return_1y_pct"), "return_3y_pa": r3, "return_5y_pa": r5,
                     "return_10y_pa": d.get("return_10y_pct_pa"), "volatility_1y": d.get("volatility_1y_pct"), "worst_fall_1y": d.get("max_drawdown_1y_pct"),
                     "yield": d.get("yield_pct") if d.get("yield_pct") is not None else r.get("dividend_yield_pct"), "consensus": cons, "history_years": d.get("history_years"), "why": "; ".join(why)})
    out = ROOT / "config" / "universe_scorecard.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(sorted(rows, key=lambda x: -x["score"]))
    if apply:
        uni.to_csv(ROOT / "config" / "universe.csv", index=False)
    print(f"scorecard: {len(rows)} listings scored; {len(added)} {'added to' if apply else 'proposed for'} the universe, {len(dropped)} {'moved' if apply else 'proposed'} to the watchlist; "
          f"universe {'now' if apply else 'would be'} {len(uni)}" + ("" if apply else " (pass --apply to make the changes)"))
    for s, sc in added[:40]:
        print(f"  + {s} ({sc})")
    for s, reason in dropped:
        print(f"  - {s}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
