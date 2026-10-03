"""Pull holding changes queued on the website into the local config, then mark them applied.
Run by run_build.sh before every build. Needs .netlify/edit_pin (the same PIN the website asks for)."""
from __future__ import annotations
import csv, json, sys, urllib.request
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SITE = (ROOT / ".netlify" / "site_url").read_text().strip() if (ROOT / ".netlify" / "site_url").exists() else ""
PIN = (ROOT / ".netlify" / "edit_pin").read_text().strip() if (ROOT / ".netlify" / "edit_pin").exists() else ""

def main() -> int:
    if not SITE:
        print("sync: no .netlify/site_url; skipping"); return 0
    url = SITE.rstrip("/") + "/.netlify/functions/changes"
    try:
        state = json.load(urllib.request.urlopen(url, timeout=30))
    except Exception as e:  # noqa: BLE001
        print(f"sync: could not fetch changes ({e})"); return 0
    pending = state.get("pending", [])
    if not pending:
        print("sync: no pending changes"); return 0
    uni_path = ROOT / "config" / "universe.csv"
    uni = pd.read_csv(uni_path, dtype={"notes": str}).fillna({"notes": ""})
    if "status" not in uni.columns:
        uni["status"] = "active"
    mine_path = ROOT / "data" / "my_holdings.csv"
    mine_lines = mine_path.read_text().splitlines() if mine_path.exists() else ["ticker,asset_class,vehicle,role,min_tier,weight_hint,notes"]
    done = []
    for c in pending:
        t = c["ticker"].upper()
        if c["action"] == "remove":
            if t in set(uni["ticker"]):
                uni.loc[uni["ticker"] == t, "status"] = "watchlist"
                uni.loc[uni["ticker"] == t, "notes"] = f"Moved to watchlist from the website {c.get('requested_at', '')[:10]}"
            mine_lines = [l for l in mine_lines if not l.upper().startswith(t + ",")]
            print(f"sync: removed {t}")
        elif c["action"] == "add":
            if t in set(uni["ticker"]):
                uni.loc[uni["ticker"] == t, "status"] = "active"
                uni.loc[uni["ticker"] == t, "notes"] = f"Activated from the website {c.get('requested_at', '')[:10]}"
            elif not any(l.upper().startswith(t + ",") for l in mine_lines):
                mine_lines.append(",".join([t, c.get("asset_class", ""), c.get("vehicle", ""), c.get("role", "satellite"),
                                            c.get("min_tier", "core"), str(c.get("weight_hint", 3)), (c.get("note") or "added from the website").replace(",", ";")]))
            print(f"sync: added {t} ({c.get('asset_class')})")
        done.append(c["id"])
    uni.to_csv(uni_path, index=False)
    mine_path.write_text("\n".join(mine_lines) + "\n")
    if PIN:
        req = urllib.request.Request(url, data=json.dumps({"pin": PIN, "action": "applied", "ids": done}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=30)
        except Exception as e:  # noqa: BLE001
            print(f"sync: applied locally but could not mark on the site ({e})")
    else:
        print("sync: no .netlify/edit_pin, changes applied locally but not marked on the site")
    return 0

if __name__ == "__main__":
    sys.exit(main())
