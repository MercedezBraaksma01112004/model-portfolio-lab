"""Import holdings from a HUB24 model workbook (the "Holdings — Accumulation Portfolio"
layout with section headers) into config/universe.csv.

Usage:
    python scripts/import_hub24.py path/to/model.xlsx [--sheet "Sheet name"] [--keep-additions]

The importer maps the workbook's section headers to engine asset classes, converts HUB24
codes to Yahoo Finance tickers, and writes weight hints from the model's allocation
percentages. Holdings the engine cannot price from a market feed (term deposits, unlisted
funds, notes, platform cash) are written with a manual code and added to
data/manual_prices.csv if they are not already there.

Engine additions (low cost index ETFs with role "fallback": the builder uses them only for the
starter tier, or when an asset class has no eligible model holding for a tier) are kept unless --drop-additions is passed."""
from __future__ import annotations

import argparse
import re
import sys
import warnings
from pathlib import Path

import openpyxl
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SECTION_MAP = {
    "AU EQUITIES": ("aus_equity", None),
    "AU FUNDS": ("aus_equity", None),
    "INTERNATIONAL EQUITIES": ("intl_equity", None),
    "INTERNATIONAL FUNDS": ("intl_equity", None),
    "INFRASTRUCTURE": ("infrastructure", None),
    "ALTERNATIVES": ("alternatives", None),
    "FIXED INCOME — CREDIT": ("credit", None),
    "FIXED INCOME - CREDIT": ("credit", None),
    "FIXED INCOME": ("fixed_income", None),
    "HYBRIDS": ("__by_type__", None),
    "CASH": ("cash", None),
}

# Codes that no market feed prices. Everything else is converted by suffix.
MANUAL_CODES = {"TD", "CMA", "SPPHA"}
EXCHANGE_SUFFIX = {"ASX": ".AX", "CXA": ".XA", "NAS": "", "NYS": "", "ARC": "", "BZX": "", "LSE": ".L", "TSX": ".TO"}
USD_EXCHANGES = {"NAS", "NYS", "ARC", "BZX"}

# Engine additions: cheap index building blocks so every tier can be implemented.
ENGINE_ADDITIONS = [
    # ticker, name, class, vehicle, role, ccy, mer, yield, franking, hint, min_tier, max_w, priority, notes
    ("VAS.AX", "Vanguard Australian Shares ETF", "aus_equity", "etf", "fallback", "AUD", 0.07, 3.8, 75, 30, "starter", 60, 1, "Engine addition: low cost core for small balances"),
    ("VGS.AX", "Vanguard MSCI Index International Shares ETF", "intl_equity", "etf", "fallback", "AUD", 0.18, 2.0, 0, 30, "starter", 70, 1, "Engine addition (also in model as VGS.ASX)"),
    ("VAP.AX", "Vanguard Australian Property Securities ETF", "infrastructure", "etf", "fallback", "AUD", 0.23, 3.5, 0, 25, "starter", 60, 1, "Engine addition: listed property core"),
    ("IFRA.AX", "VanEck FTSE Global Infrastructure (Hedged) ETF", "infrastructure", "etf", "fallback", "AUD", 0.52, 3.2, 0, 25, "starter", 60, 1, "Engine addition"),
    ("GOLD.AX", "Global X Physical Gold", "alternatives", "etf", "fallback", "AUD", 0.40, 0.0, 0, 30, "starter", 100, 1, "Engine addition: only liquid alternative for small balances"),
    ("VAF.AX", "Vanguard Australian Fixed Interest ETF", "fixed_income", "etf", "fallback", "AUD", 0.10, 3.6, 0, 30, "starter", 100, 1, "Engine addition"),
    ("CRED.AX", "BetaShares Australian Investment Grade Corporate Bond ETF", "credit", "etf", "fallback", "AUD", 0.25, 5.2, 0, 30, "starter", 100, 1, "Engine addition"),
    ("AAA.AX", "BetaShares Australian High Interest Cash ETF", "cash", "etf", "fallback", "AUD", 0.18, 4.3, 0, 20, "core", 60, 2, "Engine addition"),
]

MAX_WEIGHT_BY_VEHICLE = {"cash": 100, "td": 50, "etf": 25, "fund": 20, "lic": 20, "lit": 10, "hybrid": 10, "direct": 6}
TIER_BY_VEHICLE = {"etf": "starter", "fund": "starter", "lic": "starter", "lit": "core", "cash": "starter",
                   "direct": "core", "hybrid": "core", "td": "starter"}


def convert_code(code: str) -> tuple[str, str, bool]:
    """Return (engine ticker, currency, is_manual)."""
    code = str(code).strip()
    if code in MANUAL_CODES or re.fullmatch(r"[A-Z]{3}\d{4}AU", code):
        return code, "AUD", True
    if "." in code:
        base, exch = code.rsplit(".", 1)
        suffix = EXCHANGE_SUFFIX.get(exch)
        if suffix is None:
            return code, "AUD", True
        return base + suffix, ("USD" if exch in USD_EXCHANGES else "AUD"), False
    # Bare ASX code (for example AYUPA)
    return code + ".AX", "AUD", False


def vehicle_from_type(t: str, asset_class: str) -> str:
    t = str(t).strip().lower()
    if t in {"etf", "fund", "lic", "lit", "direct", "cash", "td"}:
        return t
    if "sub debt" in t or "hybrid" in t or "note" in t:
        return "hybrid"
    return "direct"


def parse_workbook(path: Path, sheet: str | None) -> list[dict]:
    warnings.filterwarnings("ignore")
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header_idx = next(i for i, r in enumerate(rows) if r and r[0] == "#")
    header = [str(h).strip() if h else "" for h in rows[header_idx]]
    col = {h: i for i, h in enumerate(header)}
    section = None
    out = []
    for r in rows[header_idx + 1:]:
        if not r or all(v is None for v in r):
            continue
        first, second = r[0], r[1]
        if first is None and isinstance(second, str) and "TOTAL" in second.upper():
            break
        if isinstance(first, str) and first.isupper() and second is None:
            key = first.strip()
            section = next((v for k, v in SECTION_MAP.items() if key.startswith(k)), None)
            if section is None:
                # HYBRIDS & CASH style: decide per row from the Type column
                section = ("__by_type__", None)
            continue
        if not isinstance(first, (int, float)):
            continue
        code = r[col["Code"]]
        vtype = r[col["Type"]]
        asset_class = section[0] if section else "aus_equity"
        if asset_class == "__by_type__":
            asset_class = "cash" if str(vtype).lower() == "cash" else "credit"
        ticker, ccy, manual = convert_code(code)
        vehicle = vehicle_from_type(vtype, asset_class)
        mer = float(r[col["MER %"]] or 0) * 100
        yld = float(r[col["Yield %"]] or 0) * 100
        alloc = float(r[col["Alloc %"]] or 0) * 100
        role = "core" if vehicle in {"etf", "fund", "lic", "cash", "td"} else "satellite"
        min_tier = "established" if (vehicle == "direct" and ccy == "USD") else TIER_BY_VEHICLE.get(vehicle, "core")
        if manual and vehicle not in {"cash", "td"}:
            min_tier = "established"  # unlisted funds and notes carry minimums; keep them for larger balances
        out.append({
            "ticker": ticker,
            "name": str(r[col["Holding"]]).strip(),
            "asset_class": asset_class,
            "vehicle": vehicle,
            "role": role,
            "currency": ccy,
            "mer": round(mer, 3),
            "yield": round(yld, 2),
            "franking": 0,
            "weight_hint": alloc,
            "min_tier": min_tier,
            "max_weight": MAX_WEIGHT_BY_VEHICLE.get(vehicle, 10),
            "priority": 2 if role == "core" else 3,
            "notes": f"HUB24 model ({code}); " + ("manual price" if manual else ""),
            "source": "hub24_model",
            "hub24_code": code,
            "manual": manual,
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workbook")
    ap.add_argument("--sheet", default=None)
    ap.add_argument("--drop-additions", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "config" / "universe.csv"))
    args = ap.parse_args()

    rows = parse_workbook(Path(args.workbook), args.sheet)
    if not args.drop_additions:
        model_tickers = {r["ticker"] for r in rows}
        for add in ENGINE_ADDITIONS:
            if add[0] in model_tickers:
                continue
            rows.append(dict(zip(
                ["ticker", "name", "asset_class", "vehicle", "role", "currency", "mer", "yield", "franking",
                 "weight_hint", "min_tier", "max_weight", "priority", "notes"], add)) | {"source": "engine_addition", "hub24_code": "", "manual": False})

    df = pd.DataFrame(rows)
    cols = ["ticker", "name", "asset_class", "vehicle", "role", "currency", "mer", "yield", "franking",
            "weight_hint", "min_tier", "max_weight", "priority", "notes", "source", "hub24_code"]
    df[cols].to_csv(args.out, index=False)
    print(f"Wrote {len(df)} holdings to {args.out}")

    # Manual price file: add any manual-priced tickers that are missing.
    mp_path = ROOT / "data" / "manual_prices.csv"
    existing = pd.read_csv(mp_path) if mp_path.exists() else pd.DataFrame(columns=["ticker", "price", "as_of", "note"])
    new = [r for r in rows if r["manual"] and r["ticker"] not in set(existing["ticker"])]
    if new:
        add = pd.DataFrame([{"ticker": r["ticker"], "price": 1.00, "as_of": pd.Timestamp.today().date(),
                             "note": f"{r['name']} - enter latest unit price from HUB24"} for r in new])
        pd.concat([existing, add]).to_csv(mp_path, index=False)
        print(f"Added {len(new)} manual-priced holdings to {mp_path}: {[r['ticker'] for r in new]}")
    print("\nReview config/universe.csv: franking is set to 0 for every holding (the model does not record it);")
    print("min_tier and max_weight are defaults you should adjust.")


if __name__ == "__main__":
    main()
