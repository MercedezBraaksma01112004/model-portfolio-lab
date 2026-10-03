"""Extract the HUB24 managed portfolio (SMA) menu from the Platform, Invest and Adviser Fee
Calculator workbook into config/sma_menu.csv.
Usage: python scripts/import_sma_menu.py "path/to/HUB24 Platform Invest Adviser Fee Calculator.xlsx" """
import sys, warnings
from pathlib import Path
import openpyxl, pandas as pd
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
wb = openpyxl.load_workbook(sys.argv[1], data_only=True, read_only=True)
ws = wb["Managed Portfolios"]
rows = list(ws.iter_rows(values_only=True))
out = []
for r in rows[1:]:
    if not r[1] or not r[2]:
        continue
    out.append({"code": str(r[1]).strip(), "name": str(r[2]).replace("â€“", "-").strip(), "category": r[3], "manager": r[4],
                "benchmark": r[5], "inception": (r[6].date().isoformat() if hasattr(r[6], "date") else r[6]),
                "ret_1y": r[10], "ret_3y": r[11], "ret_5y": r[12], "ret_10y": r[13], "ret_inception": r[14],
                "mgmt_fee": r[15], "perf_fee": r[16], "underlying_fees": r[17], "underlying_perf_fees": r[18], "transaction_costs": r[19]})
df = pd.DataFrame(out)
for c in ["ret_1y", "ret_3y", "ret_5y", "ret_10y", "ret_inception", "mgmt_fee", "perf_fee", "underlying_fees", "underlying_perf_fees", "transaction_costs"]:
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
df["total_fee"] = df["mgmt_fee"] + df["underlying_fees"] + df["transaction_costs"]
rate_date = None
try:
    rate_date = next((r[2] for r in wb["HUB24 Rate Card"].iter_rows(values_only=True) if r[1] and "Version" in str(r[1])), None)
except Exception:
    pass
df["as_of"] = str(rate_date.date()) if hasattr(rate_date, "date") else ""
df.to_csv(ROOT / "config" / "sma_menu.csv", index=False)
print(f"Wrote {len(df)} managed portfolios to config/sma_menu.csv (performance and fees as of {df['as_of'].iloc[0] or 'unknown'})")
