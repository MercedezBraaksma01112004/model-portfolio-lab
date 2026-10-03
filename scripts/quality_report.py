"""Render the holding quality review as a standalone page (output/quality_review.html), combining
the written verdicts in config/quality_review.csv with the latest research figures."""
from __future__ import annotations
import csv, glob, html, json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLASS_LABELS = {"aus_equity": "Australian equities", "intl_equity": "International equities", "infrastructure": "Property and infrastructure",
                "alternatives": "Alternatives", "fixed_income": "Fixed income", "credit": "Credit and hybrids", "cash": "Cash"}
ORDER = ["core", "satellite", "speculative", "not recommended", "data check"]
CHIP = {"core": "good", "satellite": "neutral", "speculative": "serious", "not recommended": "critical", "data check": "neutral"}

CSS = """
:root{color-scheme:light;--bg:#f4f5f3;--surface:#fdfdfc;--line:#dfe2de;--text:#101311;--muted:#4f5652;--faint:#858c88;--accent:#1f3a5f;--accent-soft:#e3eaf4;
--good:#1a7f37;--neutral:#6b7280;--serious:#b45309;--critical:#b42318;--good-bg:#e6f4ea;--neutral-bg:#eceef1;--serious-bg:#fdf0e0;--critical-bg:#fde8e6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121413;--surface:#1b1e1c;--line:#303532;--text:#f3f4f2;--muted:#b9bfba;--faint:#828985;--accent:#8fb3e6;--accent-soft:#1f2c3d;
--good:#4ade80;--neutral:#a1a1aa;--serious:#fbbf24;--critical:#f87171;--good-bg:#12291a;--neutral-bg:#26292e;--serious-bg:#33260c;--critical-bg:#3a1512}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121413;--surface:#1b1e1c;--line:#303532;--text:#f3f4f2;--muted:#b9bfba;--faint:#828985;--accent:#8fb3e6;--accent-soft:#1f2c3d;
--good:#4ade80;--neutral:#a1a1aa;--serious:#fbbf24;--critical:#f87171;--good-bg:#12291a;--neutral-bg:#26292e;--serious-bg:#33260c;--critical-bg:#3a1512}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 "IBM Plex Sans",-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:980px;margin:0 auto;padding:28px 24px 60px}
.hero{background:linear-gradient(135deg,#16304f 0%,#1f3a5f 55%,#2a4d7a 100%);color:#fff;margin:-28px -24px 24px;padding:26px 24px}.hero h1{color:#fff}.hero .lede,.hero .meta{color:rgba(255,255,255,.78)}
.nav{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px;font-size:14px}.nav a{color:rgba(255,255,255,.85);text-decoration:none;padding:9px 14px;border-radius:999px;border:1px solid rgba(255,255,255,.22);display:inline-flex;align-items:center;min-height:40px}.nav a[aria-current="page"]{background:#fff;color:#1f3a5f;border-color:#fff;font-weight:600}.nav a:hover{background:rgba(255,255,255,.14)}.nav a[aria-current="page"]:hover{background:#fff}
.tile{border-top:3px solid var(--accent)}.card{box-shadow:0 1px 2px rgba(16,19,17,.04),0 8px 24px -18px rgba(16,19,17,.25);border-radius:14px}
h1{font-family:"IBM Plex Serif",Georgia,serif;font-weight:600;font-size:28px;margin:0 0 6px;letter-spacing:-.01em;text-wrap:balance}
h2{font-family:"IBM Plex Serif",Georgia,serif;font-weight:600;font-size:20px;margin:34px 0 10px}
.lede{color:var(--muted);max-width:70ch;margin:0 0 6px}.meta{font-size:12.5px;color:var(--faint)}
.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px}.tile .k{font-size:12.5px;color:var(--muted)}.tile .v{font-size:22px;font-family:"IBM Plex Mono",ui-monospace,monospace}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0;display:grid;grid-template-columns:1fr 240px;gap:14px}
@media(max-width:760px){.card{grid-template-columns:1fr}}
.card h3{margin:0 0 6px;font-size:16px;font-weight:600}.card .mono{font-family:"IBM Plex Mono",ui-monospace,monospace;color:var(--faint);font-size:12px;font-weight:400}
.chip{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:500;white-space:nowrap;vertical-align:middle;margin-left:6px}
.chip.good{background:var(--good-bg);color:var(--good)}.chip.neutral{background:var(--neutral-bg);color:var(--neutral)}.chip.serious{background:var(--serious-bg);color:var(--serious)}.chip.critical{background:var(--critical-bg);color:var(--critical)}
.note{color:var(--text);margin:0}.kv{display:grid;grid-template-columns:1fr auto;gap:3px 12px;font-size:12.5px;margin:0;align-content:start}.kv dt{color:var(--muted);margin:0}.kv dd{margin:0;text-align:right;font-family:"IBM Plex Mono",ui-monospace,monospace}
.verdicts{margin:14px 0 0;color:var(--muted);max-width:75ch}.verdicts b{color:var(--text)}
.essay{max-width:72ch;color:var(--text)}.essay p{margin:0 0 12px}
@media print{body{background:#fff;color:#000}.card{break-inside:avoid;border-color:#bbb}}
"""

def f(x, d=1, suf="%"):
    return "–" if x is None else f"{x:+.{d}f}{suf}" if suf == "%" and d else f"{x:.{d}f}{suf}"

def main() -> int:
    q = {r["ticker"]: r for r in csv.DictReader(open(ROOT / "config" / "quality_review.csv"))}
    uni = {r["ticker"]: r for r in csv.DictReader(open(ROOT / "config" / "universe.csv"))}
    files = sorted(glob.glob(str(ROOT / "output" / "portfolios_2*.json")), key=lambda p: Path(p).stat().st_mtime)
    research = {}
    as_of = ""
    if files:
        d = json.load(open(files[-1]))
        research = {r["ticker"]: r for r in d.get("research", [])}
        as_of = d.get("as_of", "")
    counts = {v: 0 for v in ORDER}
    for t, r in q.items():
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    out = [f"<title>Holdings Quality Review</title>",
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@600&family=IBM+Plex+Mono&display=swap">',
           f"<style>{CSS}</style>", '<div class="wrap">',
           '<div class="hero"><nav class="nav"><a href="/">Model portfolios</a><a href="/builder.html">Build your own portfolio</a><a href="/quality.html" aria-current="page">Holdings quality review</a></nav>',
           "<h1>Holdings Quality Review</h1>",
           "<p class=\"lede\">Every holding in the model universe, judged on what the business is and what the data says: ten years of returns, volatility, "
           "worst falls, valuation, yield, franking and the analyst consensus. One verdict each, with the reason written out.</p>",
           f"<div class=\"meta\">Research as of {as_of or 'latest build'}; verdicts dated on each note. Personal learning project; opinion, not financial advice. "
           f"Verdicts marked \"generated from the data feed\" were produced by rules from the research figures and have not yet been reviewed by hand.</div></div>",
           '<div class="summary">' + "".join(f'<div class="tile"><div class="k">{v.capitalize()}</div><div class="v">{counts.get(v, 0)}</div></div>' for v in ORDER if counts.get(v)) + "</div>",
           '<p class="verdicts"><b>Core</b>: can anchor its asset class at full weight. <b>Satellite</b>: fine at a limited weight around a core. '
           '<b>Speculative</b>: high volatility or valuation; growth profiles only, sized so that losing half of it does not matter. '
           '<b>Not recommended</b>: should not be in a model portfolio.</p>',
           '<h2>The short version</h2><div class="essay">',
           "<p>The cores are the index ETFs (VAS, VGS and its hedged twin, QUAL, VAF, IFRA, GOLD), the four large Australian franchises (BHP, CSL, Macquarie, Wesfarmers, with NAB for franked income) "
           "and the three US mega-caps with ten-year records above 20% a year at ordinary multiples (Microsoft, Alphabet, Amazon). Everything else is a satellite or a bet.</p>",
           "<p>The original model's Australian direct names are the weakest part of the universe: they are small and mid caps chosen individually, several with extreme valuations "
           "(TechnologyOne at 72x, Sigma at 45x, Pinnacle a leveraged bet on fund flows, Northern Star a worse way to own gold than gold). None is a bad business; the problem is that "
           "eight of them at 3% each was the core of the Australian sleeve, with no large-cap anchor. That is fixed by making VAS and the large caps the core and these the satellites.</p>",
           "<p>Two holdings should not be there and have been moved to the watchlist: the Australian Unity capital notes, which lost 20% in a year inside the fixed income sleeve, and "
           "WAM Alternatives, which returned 2.3% a year for a decade at a 1% fee. Four of my own earlier additions (Xero, WiseTech, Vertiv, Axon) and Palo Alto are speculative "
           "growth names that are down 25 to 70% from their highs. Xero and WiseTech are now on the watchlist (the screen and I agreed; the analysts did not); Vertiv, Axon and "
           "Palo Alto are restricted to the high-balance tier at 3% or less. REA stays, capped at 3%. Apple moved from the watchlist to an active core name.</p>",
           "<p>Data cautions handled: yields are now computed from dividends actually paid in the last 12 months (NAB's 8.7% was Yahoo double counting); broken forward earnings figures such as Infratil's are flagged and ignored; and every 3, 5 and 10 year figure "
           "for the young credit ETFs is a stand-in from the credit ETF with the longest record, marked as such, and every weighted return is shown both with stand-ins and on own records only.</p></div>"]
    for cls, label in CLASS_LABELS.items():
        items = [(t, q[t]) for t in q if uni.get(t, {}).get("asset_class") == cls]
        if not items:
            continue
        items.sort(key=lambda kv: (ORDER.index(kv[1]["verdict"]) if kv[1]["verdict"] in ORDER else 9, kv[0]))
        out.append(f"<h2>{label}</h2>")
        for t, v in items:
            r = research.get(t, {})
            name = html.escape(r.get("name") or uni.get(t, {}).get("name") or t)
            status = uni.get(t, {}).get("status", "")
            out.append(f'<div class="card"><div><h3>{name} <span class="mono">{t}{" · watchlist" if status == "watchlist" else ""}</span>'
                       f'<span class="chip {CHIP.get(v["verdict"], "neutral")}">{v["verdict"]}</span></h3><p class="note">{html.escape(v["note"])}</p></div>'
                       f'<dl class="kv"><dt>10 year p.a.</dt><dd>{f(r.get("return_10y_pct_pa"))}{"†" if (r.get("return_proxy") or {}).get("10y") else ""}</dd>'
                       f'<dt>5 year p.a.</dt><dd>{f(r.get("return_5y_pct_pa"))}{"†" if (r.get("return_proxy") or {}).get("5y") else ""}</dd>'
                       f'<dt>1 year</dt><dd>{f(r.get("return_1y_pct"))}</dd><dt>Volatility</dt><dd>{f(r.get("volatility_1y_pct"), 0, "%") if r.get("volatility_1y_pct") is not None else "–"}</dd>'
                       f'<dt>Worst fall (1y)</dt><dd>{f(r.get("max_drawdown_1y_pct"), 0)}</dd><dt>Yield</dt><dd>{f(r.get("dividend_yield_pct"), 1, "%") if r.get("dividend_yield_pct") is not None else "–"}</dd>'
                       f'<dt>Forward PE</dt><dd>{f(r.get("pe_forward"), 1, "x") if r.get("pe_forward") else "–"}</dd>'
                       f'<dt>Consensus</dt><dd>{html.escape(r.get("consensus_label") or "–")}{(" · " + str(r.get("analysts"))) if r.get("analysts") else ""}</dd></dl></div>')
    out.append('<p class="meta" style="margin-top:20px">† index stand-in because the holding is younger than the period. Figures from the price feed on the date above; verdicts are opinion.</p></div>')
    path = ROOT / "output" / "quality_review.html"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    print(path)
    return 0

if __name__ == "__main__":
    sys.exit(main())
