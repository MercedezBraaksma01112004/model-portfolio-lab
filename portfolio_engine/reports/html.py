"""Self-contained HTML dashboard ("Model Portfolio Lab"). All data is embedded as JSON; the page
needs no network access except Google Fonts (falls back to system fonts). A visitor answers
three questions, reads a plain-English summary, drills into any holding's fact sheet, and can
print the holdings page."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..builder import Portfolio
from ..config import Profiles
from ..market_data import MarketData
from ..signals import TacticalView

# Categorical palette in fixed order per asset class (validated reference palette, light and dark steps).
PALETTE_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"]
PALETTE_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"]

TEMPLATE = r"""<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model Portfolio Lab</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root {
  color-scheme: light;
  --bg:#f4f5f3; --surface:#fdfdfc; --surface-2:#eef0ee; --line:#dfe2de; --text:#101311; --muted:#4f5652; --faint:#858c88;
  --accent:#1f3a5f; --accent-ink:#ffffff; --accent-soft:#e3eaf4;
  --warn-bg:#fff3cc; --warn-text:#5c4300; --good:#1a7f37; --neutral:#6b7280; --serious:#b45309; --critical:#b42318;
  --good-bg:#e6f4ea; --neutral-bg:#eceef1; --serious-bg:#fdf0e0; --critical-bg:#fde8e6;
  __LIGHT_VARS__
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg:#121413; --surface:#1b1e1c; --surface-2:#242826; --line:#303532; --text:#f3f4f2; --muted:#b9bfba; --faint:#828985;
    --accent:#8fb3e6; --accent-ink:#0f1a2a; --accent-soft:#1f2c3d;
    --warn-bg:#3a3010; --warn-text:#ffe08a; --good:#4ade80; --neutral:#a1a1aa; --serious:#fbbf24; --critical:#f87171;
    --good-bg:#12291a; --neutral-bg:#26292e; --serious-bg:#33260c; --critical-bg:#3a1512;
    __DARK_VARS__
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg:#121413; --surface:#1b1e1c; --surface-2:#242826; --line:#303532; --text:#f3f4f2; --muted:#b9bfba; --faint:#828985;
  --accent:#8fb3e6; --accent-ink:#0f1a2a; --accent-soft:#1f2c3d;
  --warn-bg:#3a3010; --warn-text:#ffe08a; --good:#4ade80; --neutral:#a1a1aa; --serious:#fbbf24; --critical:#f87171;
  --good-bg:#12291a; --neutral-bg:#26292e; --serious-bg:#33260c; --critical-bg:#3a1512;
  __DARK_VARS__
}
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior:auto; } * { transition:none !important; } }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 "IBM Plex Sans", -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
.num, td.num, th.num, .mono { font-family:"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace; font-variant-numeric:tabular-nums; }
a { color:var(--accent); }
button { font:inherit; cursor:pointer; }
button:focus-visible, tr[tabindex]:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.wrap { max-width:1240px; margin:0 auto; padding:0 24px; }
.nav { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:18px; font-size:14px; }
.nav a { color:rgba(255,255,255,.85); text-decoration:none; padding:9px 14px; border-radius:999px; border:1px solid rgba(255,255,255,.22); min-height:40px; display:inline-flex; align-items:center; transition:background .12s; }
.nav a[aria-current="page"] { background:#fff; color:#1f3a5f; border-color:#fff; font-weight:600; }
.nav a:hover { background:rgba(255,255,255,.14); }
.nav a[aria-current="page"]:hover { background:#fff; }
.dstack { display:flex; height:18px; border-radius:5px; overflow:hidden; gap:2px; background:var(--line); margin-top:8px; }
.dstack span { display:block; height:100%; min-width:2px; }
.dlegend { display:flex; flex-wrap:wrap; gap:4px 14px; margin-top:8px; font-size:12.5px; color:var(--muted); }
.dlegend i { display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:5px; vertical-align:-1px; }
.flag { display:inline-block; background:var(--serious-bg); color:var(--serious); padding:3px 9px; border-radius:999px; font-size:12.5px; margin:4px 6px 0 0; }
header { padding:26px 0 26px; border-bottom:1px solid var(--line); background:linear-gradient(135deg, #16304f 0%, #1f3a5f 55%, #2a4d7a 100%); color:#fff; }
header .meta, header .lede { color:rgba(255,255,255,.78); }
header a { color:#fff; }
h1 { margin:0; font-family:"IBM Plex Serif", Georgia, serif; font-weight:600; font-size:34px; letter-spacing:-0.01em; text-wrap:balance; }
.lede { margin:10px 0 0; max-width:68ch; font-size:16px; }
.meta { margin-top:10px; font-size:12.5px; color:var(--faint); }
.banner { background:var(--warn-bg); color:var(--warn-text); padding:10px 0; font-weight:500; }
h2 { margin:0 0 6px; font-family:"IBM Plex Serif", Georgia, serif; font-weight:600; font-size:19px; letter-spacing:-0.005em; text-wrap:balance; }
.eyebrow { font-size:11.5px; letter-spacing:.08em; text-transform:uppercase; color:var(--accent); font-weight:600; margin-bottom:6px; }
.sub { color:var(--muted); max-width:70ch; }
.sub p { margin:0 0 10px; }
main { padding:28px 0 70px; display:grid; grid-template-columns:minmax(0,1fr); gap:24px; }
main > *, .two > * { min-width:0; }
section { background:var(--surface); border:1px solid var(--line); border-radius:16px; padding:24px 26px; box-shadow:0 1px 2px rgba(16,19,17,.04), 0 8px 24px -18px rgba(16,19,17,.25); }
@media (max-width: 700px) { section { padding:18px 16px; border-radius:12px; } }
.two { display:grid; grid-template-columns:1fr 1fr; gap:22px; }
@media (max-width: 960px) { .two { grid-template-columns:1fr; } }

/* selector */
.q { display:grid; grid-template-columns:220px minmax(0,1fr); gap:10px 22px; align-items:start; padding:16px 0; border-top:1px solid var(--line); }
.q.first { border-top:0; }
.q .label { font-weight:600; font-size:15.5px; }
.q .hint { display:block; font-weight:400; font-size:12.5px; color:var(--faint); margin-top:2px; }
.seg { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; min-width:0; }
.two > * { min-width:0; }
.seg button { position:relative; border:1.5px solid var(--line); background:var(--surface); color:var(--text); padding:12px 14px 12px 38px; border-radius:12px; font-size:14.5px; font-weight:500; line-height:1.25; text-align:left; min-height:52px; transition:background .12s, border-color .12s, transform .08s, box-shadow .12s; }
.seg button::before { content:""; position:absolute; left:13px; top:50%; width:16px; height:16px; margin-top:-8px; border-radius:50%; border:1.5px solid var(--faint); background:var(--surface); }
.seg button:hover { border-color:var(--accent); box-shadow:0 2px 10px -4px rgba(31,58,95,.35); }
.seg button:active { transform:scale(.985); }
.seg button small { display:block; color:var(--faint); font-size:12px; font-weight:400; margin-top:2px; }
.seg button[aria-pressed="true"] { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); box-shadow:0 6px 18px -8px rgba(31,58,95,.6); }
.seg button[aria-pressed="true"]::before { background:#fff; border-color:#fff; box-shadow:inset 0 0 0 4px var(--accent); }
.seg button[aria-pressed="true"] small { color:var(--accent-ink); opacity:.85; }
@media (max-width: 700px) { .q { grid-template-columns:1fr; } .seg { grid-template-columns:1fr 1fr; } }
@media (max-width: 440px) { .seg { grid-template-columns:1fr; } }
.readout { margin-top:18px; padding:18px 20px; background:var(--accent-soft); border-left:4px solid var(--accent); border-radius:12px; font-size:16.5px; line-height:1.55; }
.readout b { font-weight:600; }

/* tiles */
.btchart{margin-top:12px;background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:8px}.btchart svg{display:block}td.actions{white-space:nowrap}
.recs{margin:0 0 12px}.recrow{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0 8px}.reclist{display:grid;gap:6px;font-size:13px}.reclist .chip{margin-right:4px}.recitem{white-space:nowrap}.mult{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11px;margin-left:4px;color:var(--faint)}.mult.pos{color:var(--good)}.mult.neg{color:var(--serious)}
.corrmap td.num,.corrmap th.num{font-size:12px;padding:6px 8px;text-align:center}.corrmap th{font-size:12px;white-space:nowrap}.corrmap tbody th{text-align:left}
.betalist{display:grid;gap:5px;margin-top:6px}.betarow{display:grid;grid-template-columns:minmax(0,1fr) 120px 48px;gap:10px;align-items:center;font-size:12.5px}.betarow .n{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.betarow .bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;display:block}.betarow .bar i{display:block;height:100%}.betarow .v{text-align:right}
.tiles { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:12px; margin-top:12px; }
.tile { padding:14px 16px; border:1px solid var(--line); border-top:3px solid var(--accent); border-radius:12px; background:var(--surface); }
.tile .k { font-size:12.5px; color:var(--muted); }
.tile .v { font-size:26px; font-weight:500; margin-top:4px; font-family:"IBM Plex Mono", ui-monospace, monospace; font-variant-numeric:tabular-nums; letter-spacing:-.01em; }
.tile .s { font-size:12.5px; color:var(--faint); margin-top:2px; }

/* allocation */
.stack { display:flex; height:26px; border-radius:6px; overflow:hidden; gap:2px; background:var(--line); margin-top:10px; }
.stack span { display:block; height:100%; min-width:2px; }
.legend { display:flex; flex-wrap:wrap; gap:8px 16px; margin-top:10px; font-size:13px; }
.legend i, .dot { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:-1px; }
table { width:100%; border-collapse:collapse; font-size:13.5px; }
th, td { text-align:left; padding:9px 9px; border-bottom:1px solid var(--line); vertical-align:middle; }
th { color:var(--muted); font-weight:600; font-size:12px; letter-spacing:.02em; position:sticky; top:0; background:var(--surface); z-index:1; }
td.num, th.num { text-align:right; }
.tscroll { overflow-x:auto; max-width:100%; -webkit-overflow-scrolling:touch; }
table.htable { min-width:1180px; }
table.htable td:first-child, table.htable th:first-child { white-space:nowrap; min-width:230px; max-width:320px; overflow:hidden; text-overflow:ellipsis; }
table.htable td:nth-child(2) { white-space:nowrap; }
.two { align-items:start; }
.why { margin:12px 0 0; padding-left:18px; font-size:14px; color:var(--muted); }
.why li { margin:4px 0; }

/* holdings */
tr.row { cursor:pointer; }
tr.row:hover td { background:var(--surface-2); }
tr.row.active td { background:var(--accent-soft); }
.chip { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; font-weight:500; white-space:nowrap; }
.chip.good { background:var(--good-bg); color:var(--good); }
.chip.neutral { background:var(--neutral-bg); color:var(--neutral); }
.chip.serious { background:var(--serious-bg); color:var(--serious); }
.chip.critical { background:var(--critical-bg); color:var(--critical); }
.chip.none { background:transparent; color:var(--faint); border:1px dashed var(--line); }
.bar { position:relative; height:12px; background:var(--line); border-radius:3px; overflow:hidden; min-width:90px; }
.bar span { position:absolute; left:0; top:0; bottom:0; border-radius:0 3px 3px 0; }
svg.spark { display:block; width:110px; height:28px; }
.pos { color:var(--good); } .neg { color:var(--critical); }

/* fact sheet */
.sheet { border-top:1px solid var(--line); margin-top:16px; padding-top:16px; }
.sheet-head { display:flex; flex-wrap:wrap; justify-content:space-between; gap:10px; align-items:baseline; }
.sheet-head h3 { margin:0; font-size:18px; font-weight:600; }
.sheet-grid { display:grid; grid-template-columns:2fr 1fr; gap:20px; margin-top:12px; }
@media (max-width: 900px) { .sheet-grid { grid-template-columns:1fr; } }
.kv { display:grid; grid-template-columns:1fr auto; gap:6px 14px; font-size:13.5px; margin:0; }
.kv dt { color:var(--muted); margin:0; } .kv dd { margin:0; text-align:right; font-family:"IBM Plex Mono", ui-monospace, monospace; font-variant-numeric:tabular-nums; }
.range { position:relative; height:8px; background:var(--line); border-radius:4px; margin:8px 0 4px; }
.range i { position:absolute; top:-3px; width:14px; height:14px; border-radius:50%; background:var(--accent); transform:translateX(-50%); }
.range-l { display:flex; justify-content:space-between; font-size:12px; color:var(--faint); }
svg.spark-big { width:100%; height:120px; display:block; }
.summary { font-size:14px; color:var(--muted); max-width:72ch; margin:6px 0 10px; }
.note { background:var(--warn-bg); color:var(--warn-text); padding:8px 12px; border-radius:8px; margin:6px 0; font-size:13.5px; }
details { border-top:1px solid var(--line); padding:10px 0; }
details summary { cursor:pointer; font-weight:600; }
details p, details li { color:var(--muted); font-size:14px; }
.toolbar { display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin-top:12px; }
.btn { border:1.5px solid var(--line); background:var(--surface); color:var(--text); padding:10px 16px; border-radius:10px; font-weight:500; min-height:44px; display:inline-flex; align-items:center; gap:6px; transition:background .12s, border-color .12s, transform .08s, box-shadow .12s; }
.btn:hover { border-color:var(--accent); box-shadow:0 2px 10px -4px rgba(31,58,95,.35); }
.btn:active { transform:scale(.985); }
.btn.primary { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); box-shadow:0 6px 18px -8px rgba(31,58,95,.6); }
.btn.primary:hover { filter:brightness(1.08); }
a.btn { text-decoration:none; }
.tip { position:fixed; pointer-events:none; background:var(--text); color:var(--bg); padding:6px 9px; border-radius:6px; font-size:12px; display:none; z-index:10; }
.print-only { display:none; }
.editrow { display:flex; gap:10px; flex-wrap:wrap; }
.editrow input { font:inherit; font-size:15px; padding:12px 14px; border:1.5px solid var(--line); border-radius:10px; background:var(--bg); color:var(--text); flex:1; min-width:220px; min-height:46px; }
.editrow input:focus { outline:2px solid var(--accent); outline-offset:1px; border-color:transparent; }
.results { border:1px solid var(--line); border-radius:8px; margin-top:8px; overflow:hidden; }
.result { display:grid; grid-template-columns: 1fr auto auto; gap:10px; align-items:center; padding:11px 14px; border-top:1px solid var(--line); font-size:13.5px; }
.result:hover { background:var(--surface-2); }
.result:first-child { border-top:0; }
.result select { font:inherit; font-size:13px; padding:5px 8px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--text); }
.btn.small { padding:6px 12px; font-size:13px; min-height:34px; border-radius:8px; }
.btn.danger { color:var(--critical); }
.pend { display:flex; gap:10px; align-items:center; padding:6px 0; font-size:13.5px; border-top:1px solid var(--line); }
.preview-tag { display:inline-block; background:var(--warn-bg); color:var(--warn-text); font-size:11px; padding:1px 6px; border-radius:4px; margin-left:6px; }

/* print: the holdings page */
@media print {
  @page { size:A4; margin:14mm; }
  body { background:#fff; color:#000; font-size:11px; }
  header, .banner, #selector, #signals, #review, #glossary, .toolbar, .tip, .no-print, .nav { display:none !important; }
  section { box-shadow:none; }
  .print-only { display:block; }
  main { padding:0; gap:10px; }
  section { border:0; padding:0 0 8px; border-radius:0; break-inside:avoid; }
  .two { grid-template-columns:1fr; }
  .tiles { grid-template-columns:repeat(3, 1fr); }
  .tile { border:1px solid #bbb; }
  .stack, .bar span, .legend i, .dot, .chip, .range i { -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  table { font-size:10.5px; } th, td { padding:4px 5px; }
  .sheet { break-inside:avoid; page-break-inside:avoid; }
  #sheets .sheet:nth-child(3n+1) { break-before:page; }
  svg.spark { width:80px; height:20px; }
}
</style>
</head>
<body>
<header><div class="wrap">
  <nav class="nav no-print"><a href="/" aria-current="page">Model portfolios</a><a href="/builder.html">Build your own portfolio</a><a href="/quality.html">Holdings quality review</a></nav>
  <h1>Model Portfolio Lab</h1>
  <p class="lede">Pick a risk appetite, a stage of life and an account size. A rules engine turns that into a model portfolio built from
  live ASX and US prices, shows you every holding, and explains why each weight is what it is.</p>
  <div class="meta" id="meta"></div>
  <div class="meta no-print" id="qlink"></div>
  <div class="meta">Personal learning project. Illustrative portfolios only: not financial advice, not a recommendation to buy or sell anything,
  and not associated with any licensee. Past returns are history, not forecasts.</div>
</div></header>
<div class="banner" id="banner" hidden><div class="wrap"></div></div>
<main class="wrap">

<section id="selector">
  <div class="eyebrow">Start here</div>
  <h2>Who is this portfolio for?</h2>
  <div class="q first"><div class="label">Appetite for risk<span class="hint">How much of a fall you could sit through without selling</span></div><div class="seg" id="seg-profile"></div></div>
  <div class="q"><div class="label">Stage of life<span class="hint">Sets the cash buffer, the income tilt and the most aggressive profile allowed</span></div><div class="seg" id="seg-stage"></div></div>
  <div class="q"><div class="label">Amount invested<span class="hint">Decides how many holdings make sense; small balances use a few broad ETFs</span></div><div class="seg" id="seg-tier"></div></div>
  <div class="q"><div class="label">ESG screen<span class="hint">On: excludes fossil fuels, tobacco, gambling, weapons, alcohol production and adult entertainment, and swaps unscreened index funds for screened ones</span></div><div class="seg" id="seg-esg"></div><div class="hint" id="esg-note" style="grid-column:2"></div></div>
  <div class="q"><div class="label">How it is built<span class="hint">Individual holdings, or one diversified managed portfolio (SMA) from the platform menu; the SMA route is offered for the smaller balances</span></div><div class="seg" id="seg-impl"></div><div class="hint" id="impl-note" style="grid-column:2"></div></div>
  <div class="readout" id="readout"></div>
</section>

<section id="portfolio">
  <div class="eyebrow">The portfolio</div>
  <h2 id="title"></h2>
  <div class="print-only meta" id="print-meta"></div>
  <div class="tiles" id="tiles"></div>
  <div class="tiles" id="rtiles" style="margin-top:12px"></div>
  <p class="muted" id="rnote" style="font-size:12.5px;margin:8px 0 0">Weighted returns are the weight-times-return average of the holdings, the way a model spreadsheet does it, not a backtest of this exact mix.
  A holding younger than the period uses its asset class index ETF in its place; those cells are marked † in the table below. Past returns are not forecasts.</p>
  <div id="warnings" style="margin-top:10px"></div>
  <div class="toolbar no-print" style="margin-top:14px">
    <label style="font-size:13.5px;color:var(--muted)">Your balance <input id="balance" type="text" inputmode="numeric" placeholder="e.g. 437,000" style="font:inherit;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--text);width:140px;margin-left:6px"></label>
    <button class="btn" id="apply-balance" type="button">Calculate for this balance</button>
    <button class="btn" id="reset-balance" type="button" hidden>Back to the model balance</button>
    <span class="muted" id="balance-note" style="font-size:12.5px"></span>
  </div>
  <div class="toolbar no-print">
    <button class="btn primary" id="print" type="button">Print holdings page</button>
    <label style="font-size:13.5px;color:var(--muted)"><input type="checkbox" id="print-sheets" checked> include a fact sheet for every holding</label>
    <button class="btn" id="xlsx" type="button">Download this portfolio as Excel</button>
    <a class="btn" id="xlsx-all" href="/model_portfolios_latest.xlsx" download style="text-decoration:none">Download the full workbook (every tier)</a>
  </div>
</section>

<div class="two">
  <section>
    <div class="eyebrow">Where the money goes</div>
    <h2>Asset allocation</h2>
    <div class="stack" id="stack"></div>
    <div class="legend" id="legend"></div>
    <div class="tscroll"><table style="margin-top:12px"><thead><tr><th>Asset class</th><th class="num">Long-run target</th><th class="num">Today's tilt</th><th class="num">Actual</th><th class="num">Dollars</th></tr></thead><tbody id="alloc"></tbody></table></div>
    <ul class="why" id="why"></ul>
  </section>
  <section>
    <div class="eyebrow">Plain English</div>
    <h2>What you are looking at</h2>
    <div class="sub" id="explain"></div>
  </section>
</div>

<section id="backtest">
  <div class="eyebrow">Looking back</div>
  <h2 id="bt-title">If this balance had been invested ten years ago</h2>
  <p class="sub">The holdings and weights shown above, held for the whole period and rebalanced back to those weights every month, with dividends reinvested and USD holdings converted to Australian dollars. This is hindsight, not a forecast: the weights were chosen today, with today's information, and no fees, tax or brokerage are deducted. Where a holding is younger than the window, its asset class index ETF stands in for the months before it listed.</p>
  <div class="tiles" id="bttiles"></div>
  <div class="btchart" id="btchart"></div>
  <div class="legend" id="btlegend"></div>
  <p class="muted" id="btnote" style="font-size:12.5px;margin:8px 0 0"></p>
</section>

<section id="risk">
  <div class="eyebrow">Risk</div>
  <h2>How much it moves with the market, and how well spread it is</h2>
  <p class="sub">Beta says how far the portfolio tends to move for a 1% move in the share market; a beta of 0.6 to the ASX 200 means a 10% fall there has historically meant about a 6% fall here. Correlation says how closely it tracks (1 is lock-step, 0 is unrelated). All figures are from the last year of daily prices, and every holding is measured in its own currency.</p>
  <div class="tiles" id="risktiles"></div>
  <p class="muted" id="risknote" style="font-size:12.5px;margin:8px 0 0" hidden>Recalculated on this page from the embedded year of daily returns for the holdings and weights shown (a holding added here that has no price history yet stands in with its asset class index ETF until the next rebuild).</p>
  <div class="two" style="margin-top:14px">
    <div>
      <div class="eyebrow">How the asset classes moved together over the last year</div>
      <div class="tscroll"><table id="corrmap" class="corrmap"></table></div>
      <p class="muted" style="font-size:12.5px">Each cell is the correlation of daily returns between the two asset classes' index ETFs. Low or negative numbers are what diversification looks like; the closer the grid is to 1 everywhere, the less the mix protects you in a bad month.</p>
    </div>
    <div>
      <div class="eyebrow">Each holding's beta to the ASX 200</div>
      <div id="betalist" class="betalist"></div>
    </div>
  </div>
</section>

<section id="diversification">
  <div class="eyebrow">Spread</div>
  <h2>How spread out it is</h2>
  <p class="sub">Diversification is not the number of lines on the statement. Four world index funds are one bet; a bank, a miner, a healthcare company and a retailer are four. This panel looks through to sector and country, counts the holdings as if they were equally weighted (the "effective" number), and flags concentrations against the engine's own rules.</p>
  <div class="tiles" id="divtiles"></div>
  <div class="two" style="margin-top:14px">
    <div><div class="eyebrow">By sector</div><div class="dstack" id="secstack"></div><div class="dlegend" id="seclegend"></div></div>
    <div><div class="eyebrow">By country or region</div><div class="dstack" id="regstack"></div><div class="dlegend" id="reglegend"></div></div>
  </div>
  <div id="divflags" style="margin-top:8px"></div>
</section>

<section id="holdings-section">
  <div class="eyebrow">Holdings</div>
  <h2>Every holding, and why it is there</h2>
  <p class="sub no-print">Click a row for the fact sheet: what the business does, how it has performed, and what the analysts covering it think on average.</p>
  <div class="recs" id="recs"></div>
  <div class="recs" id="esgchanges"></div>
  <div class="tscroll"><table class="htable"><thead><tr><th>Holding</th><th>Asset class</th><th class="num">Weight</th><th></th><th>Analyst view</th><th>ESG</th><th class="num">Dollars</th><th class="num">Units</th><th class="num">Price</th><th>Last 12 months</th><th class="num">1y</th><th class="num">3y pa</th><th class="num">5y pa</th><th class="num">10y pa</th><th class="num">Yield</th><th class="num">Beta</th><th class="no-print">Documents</th><th class="no-print"></th></tr></thead><tbody id="holdings"></tbody></table></div>
  <p class="muted no-print" style="font-size:12.5px;margin:6px 0 0">Scroll the table sideways for more columns; click a row for its fact sheet.</p>
  <p class="muted" style="font-size:12.5px">† return of the asset class index ETF used because the holding is younger than the period. Yields marked ° are from the price feed (trailing 12 months); others are the configured figure.</p>
  <div id="sheet" class="sheet no-print" hidden></div>
  <div id="sheets" class="print-only"></div>
  <div class="edit no-print" id="edit">
    <div class="eyebrow" style="margin-top:18px">Edit this portfolio</div>
    <div id="editoff" class="muted" hidden></div>
    <div id="editon">
      <div class="editrow">
        <input id="q" type="search" placeholder="Search a company or ETF, e.g. BHP, Vanguard, Apple" autocomplete="off">
        <input id="pin" type="password" placeholder="edit PIN" style="max-width:120px" autocomplete="off">
      </div>
      <div id="results"></div>
      <div id="pending" style="margin-top:10px"></div>
      <p class="muted" style="font-size:12.5px;margin-top:8px">Adding or removing shows a preview here straight away and queues the change; the portfolios are rebuilt properly with live data within the hour and published. Weights in the preview are approximate until then.</p>
    </div>
  </div>
</section>

<section id="review">
  <div class="eyebrow">Holding review</div>
  <h2>What the screen is saying today</h2>
  <p class="sub" id="reviewmeta"></p>
  <div id="reviewlist"></div>
  <details><summary>How the review works</summary>
    <p>Every active holding is checked for <b>strikes</b>: price below its 200 day average; 12-1 month momentum well behind its asset class index;
    a fall of more than a third from its one-year high; an analyst consensus of Underperform or Sell; market value below the size floor.
    Three strikes make it a removal candidate. Every watchlist name is checked for <b>merits</b>: above its 200 day average, momentum ahead of its index,
    a Buy consensus, adequate size and volatility no worse than its peers; three merits with no strikes make it an addition candidate.
    Proposals are written here and in the workbook; nothing changes in the portfolios until they are applied, and at most two changes are made at a
    time with a 90 day cooling-off so a name cannot bounce in and out. Price screens are late by nature, which is why they propose rather than act.</p>
  </details>
</section>

<section id="signals">
  <div class="eyebrow">Under the bonnet</div>
  <h2>Today's market signals</h2>
  <p class="sub" id="sigmeta"></p>
  <div class="tscroll"><table><thead><tr><th>Asset class</th><th class="num">Trend</th><th class="num">Momentum</th><th class="num">Vol spike</th><th class="num">Score</th><th class="num">Tilt</th><th>Status</th></tr></thead><tbody id="sigtable"></tbody></table></div>
  <details><summary>How the tilts work</summary>
    <p>Each asset class has a long-run target weight. Three signals nudge it: <b>trend</b> (is the price above its 200 day average?),
    <b>momentum</b> (how did it do over the last year, ignoring the most recent month, compared with cash?) and a <b>volatility spike</b> penalty
    (are the last 20 days much rougher than the last year?). The combined score moves the class by at most 5 percentage points, the total
    shift between growth and defensive assets is also capped at 5 points, and a tilt only changes when the new value differs by more than 1 point,
    so the portfolio does not fidget. The defensive classes absorb whatever the growth classes take or give back.</p>
  </details>
  <details><summary>How the analyst view is used</summary>
    <p>The analyst view is Yahoo Finance's average of the brokers covering each holding, from Strong Buy to Sell, with the number of analysts.
    It scales a holding's weight <i>within its asset class</i> by at most a quarter either way and flags Sell-leaning names for review.
    It never removes a holding on its own: sell-side ratings are mostly Buy, they change late, and the people issuing them have conflicts.</p>
  </details>
</section>

<section id="glossary">
  <div class="eyebrow">Glossary</div>
  <h2>Terms used on this page</h2>
  <details><summary>Growth and defensive assets</summary><p>Growth assets (shares, property, infrastructure, alternatives) are owned for capital growth and bounce around. Defensive assets (bonds, credit, cash) are owned for stability and income. The split between them is the single biggest decision in a portfolio.</p></details>
  <details><summary>Realised volatility</summary><p>How much the portfolio's value actually moved over the last year, annualised, using the way the holdings move together. A 6% figure means a typical year saw swings of roughly plus or minus 6%; a bad year can be two or three times that. It is a measure of the past, not a promise about the future.</p></details>
  <details><summary>MER and total cost</summary><p>The management expense ratio is what the fund managers charge inside each holding. Direct shares cost nothing to hold. The platform fee is what the administration platform charges on the whole account, from its published rate card. Total ongoing cost adds the two.</p></details>
  <details><summary>Franking</summary><p>Australian companies that have paid company tax attach franking credits to dividends. For a retiree paying no tax those credits are refunded in cash, which is why fully franked income is worth more to a pension account than the same yield unfranked.</p></details>
  <details><summary>Reviewed verdicts</summary><p><b>Core</b>: a holding that can anchor its asset class at full weight. <b>Satellite</b>: acceptable at a limited weight around the core. <b>Speculative</b>: high volatility or valuation; growth profiles only, sized so that losing half of it does not matter. <b>Not recommended</b>: should not be in a model portfolio; moved to the watchlist. These are written opinions from a review of the research data and the business itself, dated on each note.</p></details>
  <details><summary>ESG screen and reviews</summary><p>With the screen on, holdings involved in fossil fuels (including coal), tobacco, gambling, weapons, alcohol production or adult entertainment are left out, and index funds that hold such companies are swapped for the issuer's screened equivalent (VAS for VETH, VGS for VESG, VAF for VEFI, QUAL for ESGI, NDQ for ETHI, VSO for FAIR). Managed portfolios are limited to those labelled ethical, sustainable or ESG. Each holding carries a written review band: Leader, Acceptable, Watch (kept, with a controversy worth knowing), Unscreened fund (swapped), Excluded, or Screened fund. These are dated opinions by the author, written from public information, because no free ratings feed is available; a provider rating (MSCI, Sustainalytics) can be added to config/esg_review.csv when you have access to one. Screening has a cost: fewer holdings, higher fund fees and a different return path, which the page shows when you compare the two settings.</p></details>
  <details><summary>Beta and correlation</summary><p>Beta measures how far a holding or portfolio tends to move when the market moves 1%: a beta of 1.2 rises and falls more than the index, 0.5 less, and a negative beta moves the other way. It is estimated from the last year of daily prices against the ASX 200 ETF (VAS) or the world index ETF (VGS), each holding in its own currency. Correlation, between -1 and 1, is how consistently two things move together regardless of size. The diversification ratio is the weighted average of the holdings' volatilities divided by the portfolio's actual volatility: the further above 1, the more the mix is dampening the swings of its parts.</p></details>
  <details><summary>Investment menus (Choice, Core, Discover)</summary><p>The platform prices administration by menu. Anything holding listed shares or ETFs sits on the Choice menu (tiered percentage fee, minimum $350 a year, plus an account keeping fee). An account holding only managed portfolios uses the Core menu (same tiers, $150 minimum, no account keeping fee), or the Discover menu under $100,000, which has no administration or account keeping fee and charges only the manager's own fee. The rates are from the platform's adviser fee calculator dated on the Assumptions sheet; the Discover menu's underlying fees come from its investment booklet.</p></details>
  <details><summary>Managed portfolio (SMA)</summary><p>A separately managed account: a model portfolio designed by a professional manager that the platform implements in your name. You own the underlying holdings, the manager decides the mix and the platform rebalances automatically. One line on the account, one fee, no brokerage on entry. The trade-off is less control and less transparency day to day.</p></details>
  <details><summary>Tier, tilt, target</summary><p>The balance tier decides how many holdings make sense for the account size. The long-run target is the strategic allocation for the risk profile. The tilt is today's bounded adjustment from market signals. The actual weight is what you get after rounding to whole units.</p></details>
</section>
</main>
<div class="tip" id="tip"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<script>
const DATA = __DATA__;
const CLASSES = DATA.classes, COLORS = DATA.colors, R = DATA.research;
const fmtP = (x, d=1) => (x==null||isNaN(x)) ? "–" : x.toFixed(d) + "%";
const fmtS = (x, d=1) => (x==null||isNaN(x)) ? "–" : (x>0?"+":"") + x.toFixed(d) + "%";
const fmtM = x => (x==null||isNaN(x)) ? "–" : "$" + Math.round(x).toLocaleString("en-AU");
const fmtBig = x => x==null ? "–" : x >= 1e9 ? "$" + (x/1e9).toFixed(1) + " bn" : x >= 1e6 ? "$" + (x/1e6).toFixed(0) + " m" : fmtM(x);
const fmtN = x => (x==null||isNaN(x)) ? "–" : (Number.isInteger(x) ? x.toLocaleString("en-AU") : x.toFixed(2));
const cssColor = k => getComputedStyle(document.documentElement).getPropertyValue(COLORS[k]).trim();
const sel = id => document.getElementById(id);
const label = (list, key) => (list.find(x => x.key===key) || {}).label || key;
const state = { profile: DATA.defaults.profile, stage: DATA.defaults.stage, tier: DATA.defaults.tier, impl: "direct", ticker: null, balance: null, esg: false };
function docLink(l, long){ const d = DATA.pds[l.ticker]; if (!d) return long ? '<span class="muted">no link on file</span>' : ""; return `<a href="${d.url}" target="_blank" rel="noopener" title="${d.label}">${long ? d.label : "PDS"}</a>`; }
function betaCell(pf, l){ const hb = (pf.metrics.holding_beta_asx200 || {})[l.ticker]; if (hb != null) return hb.toFixed(2); if (l.vehicle === "cash" || l.priced_from === "manual") return "0.00"; return "–"; }
function corrColor(v){ if (v == null) return "transparent"; const t = Math.max(-1, Math.min(1, v)); return t >= 0 ? `rgba(180,35,24,${(0.08 + 0.55*t).toFixed(2)})` : `rgba(26,127,55,${(0.08 + 0.55*(-t)).toFixed(2)})`; }
function seriesFor(l){ const R0 = DATA.returns || {}; if (!R0.series) return null;
  if (l.vehicle === "cash" || l.priced_from === "manual") return null;   // zero volatility
  if (R0.series[l.ticker]) return R0.series[l.ticker];
  const px = (R0.class_proxy||{})[l.asset_class]; return px && R0.series[px] ? R0.series[px] : null; }
function recomputeRisk(p){
  // Covariance-based risk from the embedded year of daily returns; mirrors builder.compute_metrics.
  const R0 = DATA.returns || {}; if (!R0.series || p.implementation === "sma") return;
  const rows = p.lines.map(l => [l, seriesFor(l)]).filter(x => x[1]); if (rows.length < 2) return;
  const n = R0.dates.length, w = rows.map(([l]) => l.weight_pct/100), S = rows.map(x => x[1]);
  const mean = a => a.reduce((s,v) => s + v, 0) / a.length;
  const cov = (a, b) => { const ma = mean(a), mb = mean(b); let s = 0; for (let i = 0; i < n; i++) s += (a[i]-ma)*(b[i]-mb); return s / (n - 1); };
  const port = new Array(n).fill(0); rows.forEach(([l, sr], k) => { for (let i = 0; i < n; i++) port[i] += w[k]*sr[i]; });
  const vols = S.map(sr => Math.sqrt(cov(sr, sr)*252));
  let pv = 0; const C = S.map(a => S.map(b => cov(a, b)));
  for (let i = 0; i < w.length; i++) for (let j = 0; j < w.length; j++) pv += w[i]*w[j]*C[i][j]*252;
  const m = p.metrics; const pvol = Math.sqrt(Math.max(pv, 0))*100;
  m.realised_volatility_pct = +pvol.toFixed(2); const avg = w.reduce((s,wi,i) => s + wi*vols[i], 0)*100; m.weighted_avg_holding_vol_pct = +avg.toFixed(2);
  m.diversification_ratio = +(avg / Math.max(pvol, 1e-9)).toFixed(2);
  m.trailing_1y_return_pct = +((port.reduce((g, r) => g*(1+r), 1) - 1)*100).toFixed(2);
  let sum = 0, cnt = 0; for (let i = 0; i < w.length; i++) for (let j = 0; j < w.length; j++) if (i !== j) { const d = Math.sqrt(C[i][i]*C[j][j]); if (d > 0) { sum += C[i][j]/d; cnt++; } }
  m.avg_pairwise_correlation = cnt ? +(sum/cnt).toFixed(2) : null;
  for (const [k, t] of [["asx200", "VAS.AX"], ["world", "VGS.AX"]]) { const b = R0.series[t]; if (!b) continue; const vb = cov(b, b); if (vb <= 0) continue;
    m["beta_" + k] = +(cov(port, b)/vb).toFixed(2); m["correlation_" + k] = +(cov(port, b)/Math.sqrt(vb*cov(port, port))).toFixed(2); }
  const b = R0.series["VAS.AX"]; m.holding_beta_asx200 = {}; if (b) { const vb = cov(b, b); rows.forEach(([l, sr]) => { m.holding_beta_asx200[l.ticker] = +(cov(sr, b)/vb).toFixed(2); }); }
  m.risk_recomputed = true;
}
function tierFor(bal){ let t = DATA.tiers[0].key; for (const x of DATA.tiers) if (bal >= x.min_balance) t = x.key; return t; }
function menuFor(bal, impl, hasListed){ const c = DATA.platform; if (!c || !c.menus) return "choice";
  if (impl === "sma" || !hasListed) return (c.menus.discover && bal < (c.discover_max_balance||0)) ? "discover" : "core"; return "choice"; }
function menuLabel(key){ const c = DATA.platform; return (c && c.menus && c.menus[key] && c.menus[key].label) || key; }
function platformFee(bal, menu){ let c = DATA.platform; if (!c) return 0; if (c.menus) c = c.menus[menu] || c.menus.choice; if (!c || !c.bands) return 0; let fee = 0, lower = 0;
  for (const b of c.bands) { const upper = b.up_to == null ? Infinity : b.up_to; fee += Math.max(0, Math.min(bal, upper) - lower) * b.rate; lower = upper; if (bal <= upper) break; }
  fee = Math.min(Math.max(fee, c.min_admin_fee||0), c.max_admin_fee||Infinity); fee += c.account_keeping_fee||0; fee += Math.min(bal*(c.expense_recovery_rate||0), c.expense_recovery_cap||0); return fee; }
function scaleToBalance(pf, bal){
  // Same weights, exact dollars: whole units for listed holdings, residual to cash, fees from the rate card.
  const p = JSON.parse(JSON.stringify(pf)); p.balance = bal; p.scaled = true;
  let spent = 0; const cash = p.lines.find(l => l.asset_class==="cash" && l.vehicle==="cash");
  for (const l of p.lines) { if (l === cash) continue; const d = l.weight_pct/100*bal;
    if (l.priced_from !== "manual" && l.vehicle !== "sma" && l.price_aud) { l.units = Math.floor(d / l.price_aud); l.dollars = l.units * l.price_aud; } else { l.dollars = d; l.units = l.price_aud ? d / l.price_aud : null; }
    spent += l.dollars; }
  if (cash) { cash.dollars = Math.max(0, bal - spent); cash.units = cash.dollars; }
  for (const l of p.lines) l.weight_pct = l.dollars / bal * 100;
  const m = p.metrics; const W = l => l.weight_pct/100; const T = DATA.tiers.find(t => t.key===p.tier) || {};
  m.weighted_mer_pct = +p.lines.reduce((s,l) => s + W(l)*l.mer_pct, 0).toFixed(3);
  if (p.implementation !== "sma") { m.weighted_yield_pct = +p.lines.reduce((s,l) => s + W(l)*l.yield_pct, 0).toFixed(2);
    const credits = p.lines.reduce((s,l) => s + W(l)*l.yield_pct*(l.franking_pct||0)/100*(30/70), 0);
    m.grossed_up_yield_pct = +(m.weighted_yield_pct + credits).toFixed(2); m.franking_credits_per_year = Math.round(credits/100*bal);
    m.income_per_year = Math.round(m.weighted_yield_pct/100*bal); }
  m.platform_menu = menuFor(bal, p.implementation, p.lines.some(l => l.vehicle !== "sma" && l.vehicle !== "cash"));
  m.investment_fees_per_year = Math.round(m.weighted_mer_pct/100*bal); m.platform_admin_fee_per_year = Math.round(platformFee(bal, m.platform_menu));
  m.total_ongoing_cost_pct = +(m.weighted_mer_pct + m.platform_admin_fee_per_year/bal*100).toFixed(3);
  m.initial_brokerage = p.lines.filter(l => l.priced_from !== "manual" && l.vehicle !== "sma").length * (T.brokerage||0);
  const cw = {}; p.lines.forEach(l => cw[l.asset_class] = (cw[l.asset_class]||0) + l.weight_pct); p.class_weights = p.implementation==="sma" ? p.class_weights : cw;
  recomputeRisk(p);
  return p;
}
function parseBalance(v){ const n = parseFloat(String(v).replace(/[^0-9.]/g, "")); return isFinite(n) && n >= 1000 ? n : null; }
const ESGS = [{key:false, label:"Off", sub:"standard universe"}, {key:true, label:"On", sub:"exclusions applied, funds swapped"}];
const IMPLS = [{key:"direct", label:"Individual holdings", sub:"shares, ETFs and funds chosen one by one"}, {key:"sma", label:"Managed portfolio (SMA)", sub:"one diversified portfolio run by a manager"}];
const tip = sel("tip");
function showTip(e, html){ tip.innerHTML = html; tip.style.display="block"; moveTip(e); }
function moveTip(e){ tip.style.left = (e.clientX+12)+"px"; tip.style.top = (e.clientY+12)+"px"; }
function hideTip(){ tip.style.display="none"; }
try { const saved = JSON.parse(localStorage.getItem("mpl-state")||"null"); if (saved) Object.assign(state, saved, {ticker:null}); } catch(e){}

function seg(id, items, key){
  const el = sel(id); el.innerHTML = "";
  items.forEach(it => { const b = document.createElement("button"); b.type="button"; b.innerHTML = it.label + (it.sub ? `<small>${it.sub}</small>` : "");
    b.setAttribute("aria-pressed", String(state[key]===it.key)); b.onclick = () => { state[key]=it.key; state.ticker=null; render(); }; el.appendChild(b); });
}
function find(){
  if (state.balance) state.tier = tierFor(state.balance);
  const isEsg = x => !!(x.esg && x.esg.screened);
  const base = x => (x.profile_requested===state.profile || (x.requested_aliases||[]).includes(state.profile)) && x.life_stage===state.stage && x.tier===state.tier;
  return DATA.portfolios.find(x => base(x) && (x.implementation||"direct")===state.impl && isEsg(x)===state.esg)
      || DATA.portfolios.find(x => base(x) && (x.implementation||"direct")===state.impl && !isEsg(x))
      || DATA.portfolios.find(x => base(x) && !isEsg(x))
      || DATA.portfolios[0];
}
function retCell(r, key, period){
  if (!r || r[key]==null) return "–";
  const px = r.return_proxy && r.return_proxy[period];
  return `<span title="${px ? "index stand-in: " + px : ""}">${fmtS(r[key])}${px ? "†" : ""}</span>`;
}
const QCLS = {core:"good", satellite:"neutral", speculative:"serious", "not recommended":"critical", "data check":"neutral"};
const ECLS = {leader:"good", acceptable:"neutral", watch:"serious", substituted:"critical", excluded:"critical", screened_fund:"good"};
const ELABEL = {leader:"Leader", acceptable:"Acceptable", watch:"Watch", substituted:"Unscreened fund", excluded:"Excluded", screened_fund:"Screened fund"};
function esgChip(t){ const e = DATA.esg.review[t]; if (!e) return `<span class="chip none" title="No written ESG review yet">not reviewed</span>`;
  return `<span class="chip ${ECLS[e.band]||"neutral"}" title="${(e.note||"").replace(/"/g,"&quot;")}">${ELABEL[e.band]||e.band}</span>`; }
function qualityChip(t){ const q = DATA.quality[t]; return q ? `<span class="chip ${QCLS[q.verdict]||"neutral"}" title="${(q.note||"").replace(/"/g,"&quot;")}">${q.verdict}</span>` : ""; }
function classChip(k){ return `<span class="dot" style="background:${cssColor(k)}"></span>`; }
function consensusChip(r){
  if (!r || !r.consensus_label || r.consensus_label==="no coverage") return `<span class="chip none">no coverage</span>`;
  if (r.consensus_label==="thin coverage") return `<span class="chip none">thin coverage</span>`;
  const cls = r.consensus_label.includes("Buy") ? "good" : r.consensus_label==="Hold" ? "neutral" : r.consensus_label==="Underperform" ? "serious" : "critical";
  return `<span class="chip ${cls}" title="${r.analysts} analysts, mean ${r.consensus_mean.toFixed(1)} on a 1 to 5 scale">${r.consensus_label} · ${r.analysts}</span>`;
}
function spark(arr, color, w=110, h=28, big=false){
  if (!arr || arr.length < 2) return "";
  const min = Math.min(...arr), max = Math.max(...arr), span = (max-min)||1, pad = 3;
  const pts = arr.map((v,i) => [pad + i/(arr.length-1)*(w-2*pad), pad + (1 - (v-min)/span)*(h-2*pad)]);
  const d = pts.map((p,i) => (i?"L":"M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const area = d + ` L${pts[pts.length-1][0].toFixed(1)} ${h} L${pts[0][0].toFixed(1)} ${h} Z`;
  const base = pad + (1 - (100-min)/span)*(h-2*pad);
  const last = pts[pts.length-1];
  return `<svg class="${big?"spark-big":"spark"}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <path d="${area}" fill="${color}" opacity="0.12"/>
    ${(base>0 && base<h) ? `<line x1="0" x2="${w}" y1="${base.toFixed(1)}" y2="${base.toFixed(1)}" stroke="currentColor" opacity="0.25" stroke-dasharray="2 3"/>` : ""}
    <path d="${d}" fill="none" stroke="${color}" stroke-width="${big?2:1.5}" vector-effect="non-scaling-stroke"/>
    <circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="${big?3.5:2.5}" fill="${color}" stroke="var(--surface)" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
}

function render(){
  try { localStorage.setItem("mpl-state", JSON.stringify({profile:state.profile, stage:state.stage, tier:state.tier, impl:state.impl})); } catch(e){}
  const smaOk = DATA.sma.enabled && DATA.sma.tiers.includes(state.tier);
  if (!smaOk && state.impl === "sma") state.impl = "direct";
  seg("seg-profile", DATA.profiles, "profile"); seg("seg-stage", DATA.stages, "stage"); seg("seg-tier", DATA.tiers, "tier");
  seg("seg-impl", smaOk ? IMPLS : [IMPLS[0]], "impl");
  seg("seg-esg", DATA.esg.enabled ? ESGS : [ESGS[0]], "esg");
  sel("impl-note").textContent = smaOk ? "" : "The managed portfolio route is shown for " + DATA.sma.tiers.map(t => label(DATA.tiers, t).toLowerCase()).join(" and ") + " balances, where holding a single diversified portfolio is cheaper than buying 20 holdings.";
  const pf0 = find(); if (!pf0) return;
  sel("esg-note").textContent = state.esg && !(pf0.esg && pf0.esg.screened) ? "No screened version exists for this combination (no ethical or sustainable managed portfolio in this category), so the standard version is shown." : ""; const pf = state.balance ? scaleToBalance(applyPreview(pf0), state.balance) : applyPreview(pf0);
  sel("reset-balance").hidden = !state.balance;
  sel("balance-note").textContent = state.balance ? `Exact figures for ${fmtM(state.balance)}: ${label(DATA.tiers, pf.tier)} tier weights, whole units, ${menuLabel(pf.metrics.platform_menu)} platform fee from the rate card.` : "Figures shown are for the tier's model balance. Enter your own balance for exact dollars, units and fees.";
  const P = label(DATA.profiles, pf.profile_used), S = label(DATA.stages, pf.life_stage), T = DATA.tiers.find(x=>x.key===pf.tier);
  const m = pf.metrics, cw = pf.class_weights;
  const capped = state.profile !== pf.profile_used;
  const isSma = pf.implementation === "sma";
  const smaC = isSma ? pf.sma.chosen : null;
  sel("readout").innerHTML = isSma
    ? `Someone in <b>${S.toLowerCase()}</b> with a <b>${P}</b> appetite for risk and about <b>${fmtM(pf.balance)}</b> invested holds ${pf.lines.filter(x=>x.vehicle==="sma").length > 1 ? "two diversified managed portfolios split evenly, " : "one diversified managed portfolio, "}
    ${pf.lines.filter(x=>x.vehicle==="sma").map(x => `<b>${x.name}</b>`).join(" and ")}, targeting about <b>${fmtP(m.growth_pct,0)} growth assets</b>, plus a cash buffer.
    It would cost about <b>${fmtM(m.investment_fees_per_year + m.platform_admin_fee_per_year)} a year</b> (${fmtP(m.total_ongoing_cost_pct,2)} of the balance) with no brokerage on the way in.`
    : `Someone in <b>${S.toLowerCase()}</b> with a <b>${P}</b> appetite for risk and about <b>${fmtM(pf.balance)}</b> invested gets
    <b>${fmtP(m.growth_pct,0)} growth assets</b> across <b>${m.holdings} holdings</b>. It would cost about <b>${fmtM(m.investment_fees_per_year + m.platform_admin_fee_per_year)} a year</b>
    (${fmtP(m.total_ongoing_cost_pct,2)} of the balance) and pay roughly <b>${fmtM(m.income_per_year)} a year</b> in income.`;
  sel("readout").innerHTML +=
    capped ? `<br><b>Note:</b> ${label(DATA.profiles, state.profile)} was asked for, but the rules cap ${S.toLowerCase()} at ${P}, so that is what was built.` : "";
  sel("title").textContent = `${P} · ${S} · ${T.label}` + (isSma ? " · managed portfolio" : "") + (pf.esg && pf.esg.screened ? " · ESG screened" : "");
  sel("print-meta").textContent = `Model Portfolio Lab. Balance ${fmtM(pf.balance)}. Prices as of ${pf.as_of}. Illustrative only, not advice.`;
  sel("tiles").innerHTML = [
    ["Growth / defensive", `${fmtP(m.growth_pct,0)} / ${fmtP(m.defensive_pct,0)}`, "shares and property versus bonds and cash"],
    isSma ? ["Holdings", `${pf.lines.filter(x=>x.vehicle==="sma").length} + cash`, `${pf.lines.filter(x=>x.vehicle==="sma").length > 1 ? "two managed portfolios, different managers," : "one managed portfolio"} and a cash account`] : ["Holdings", m.holdings, `${pf.lines.filter(l=>l.vehicle==="direct").length} direct shares, ${pf.lines.filter(l=>l.vehicle!=="direct").length} funds, ETFs or cash`],
    ["Cost per year", fmtM(m.investment_fees_per_year + m.platform_admin_fee_per_year), `${fmtP(m.weighted_mer_pct,2)} ${isSma?"manager and underlying fees":"in funds"} + ${fmtM(m.platform_admin_fee_per_year)} platform (${menuLabel(m.platform_menu)})`],
    isSma ? ["Reported return", fmtS(smaC.ret_1y*100), `manager's 1 year figure to ${pf.sma.as_of}`] : ["Income per year", fmtM(m.income_per_year), `${fmtP(m.weighted_yield_pct,2)} cash yield` + (m.franking_credits_per_year ? ` + ${fmtM(m.franking_credits_per_year)} franking credits (${fmtP(m.grossed_up_yield_pct,2)} grossed up)` : "")],
    ["A typical year moved", "±" + fmtP(m.realised_volatility_pct,0), isSma ? "proxy: this risk profile held in ETFs" : "realised volatility over the last year"],
    ["Last 12 months", fmtS(m.trailing_1y_return_pct), isSma ? "proxy mix of ETFs; history, not a forecast" : "what this mix returned; history, not a forecast"],
  ].map(([k,v,s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  const px10 = m.weighted_return_10y_proxy_share_pct || 0, px5 = m.weighted_return_5y_proxy_share_pct || 0, px3 = m.weighted_return_3y_proxy_share_pct || 0;
  sel("rtiles").innerHTML = isSma ? "" : [
    ["Weighted 3 year return p.a.", fmtS(m.weighted_return_3y_pct), px3 ? `${px3.toFixed(0)}% stand-ins; own records only: ${fmtS(m.weighted_return_3y_own_pct)}` : "average of the holdings' own returns"],
    ["Weighted 5 year return p.a.", fmtS(m.weighted_return_5y_pct), px5 ? `${px5.toFixed(0)}% stand-ins; own records only: ${fmtS(m.weighted_return_5y_own_pct)}` : "average of the holdings' own returns"],
    ["Weighted 10 year return p.a.", fmtS(m.weighted_return_10y_pct), px10 ? `${px10.toFixed(0)}% stand-ins; own records only: ${fmtS(m.weighted_return_10y_own_pct)}` : "average of the holdings' own returns"],
    ["Weighted yield", fmtP(m.weighted_yield_pct,2), `${pf.lines.filter(l=>l.yield_source==="live").length} of ${pf.lines.length} holdings on live trailing yields`],
  ].map(([k,v,s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  sel("rnote").hidden = isSma;
  renderRisk(pf);
  renderDiversification(pf);
  renderBacktest(pf);
  (() => { const ws = pf.warnings.filter(w => !w.startsWith("Requested")); const left = ws.filter(w => / left out: /.test(w)), rev = ws.filter(w => /review this holding/.test(w)), other = ws.filter(w => !left.includes(w) && !rev.includes(w));
    const notes = [...other];
    if (left.length) notes.push(`${left.length} holding${left.length > 1 ? "s" : ""} left out because the share would be under the ${fmtM(T.min_holding)} minimum at this balance: ${left.map(w => w.split(" left out")[0]).join(", ")}.`);
    if (rev.length) notes.push(`Analyst consensus leans negative on ${rev.map(w => w.split(":")[0]).join(", ")}; kept at a trimmed weight and flagged for review.`);
    sel("warnings").innerHTML = notes.map(w => `<div class="note">${w}</div>`).join(""); })();

  sel("stack").innerHTML = CLASSES.filter(c => (cw[c.key]||0) > 0).map(c =>
    `<span style="width:${cw[c.key]}%;background:${cssColor(c.key)}" data-l="${c.label}: ${fmtP(cw[c.key])}"></span>`).join("");
  sel("stack").querySelectorAll("span").forEach(el => { el.onmousemove = e => showTip(e, el.dataset.l); el.onmouseleave = hideTip; });
  sel("legend").innerHTML = CLASSES.map(c => `<span><i style="background:${cssColor(c.key)}"></i>${c.label} <span class="mono">${fmtP(cw[c.key]||0)}</span></span>`).join("");
  sel("alloc").innerHTML = CLASSES.map(c => `<tr><td>${classChip(c.key)}${c.label}</td><td class="num">${fmtP(pf.saa[c.key])}</td>
    <td class="num">${(pf.tilts[c.key]>=0?"+":"")+pf.tilts[c.key].toFixed(1)} pp</td><td class="num">${fmtP(cw[c.key]||0)}</td><td class="num">${fmtM((cw[c.key]||0)/100*pf.balance)}</td></tr>`).join("");

  const why = [];
  if (isSma) {
    const mgrs = pf.lines.filter(x=>x.vehicle==="sma").map(x => (pf.sma.shortlist.find(y=>y.code===x.ticker)||{}).manager||"").map(x => x.replace(/ \(MF\)$/, ""));
    why.push(`A managed portfolio is one line on the account that holds a diversified mix chosen by <b>${mgrs.join("</b> and <b>")}</b>; the allocation above is the long-run target for this risk profile, and the managers' actual mixes will differ a little.`);
    if (mgrs.length > 1) why.push(`Above $50,000 the account is split evenly across <b>two managers</b>, so one manager's process is not the whole result.`);
    why.push(`Picked from ${pf.sma.shortlist.length} options in the platform's "${pf.sma.category}" category with at least ${DATA.sma.min_track_record_years} years of history, ranked by total fee. Click a managed portfolio to see the other options and swap one in.`);
    why.push(`${S} keeps <b>${fmtP(DATA.stage_rules[pf.life_stage].cash_floor_pp,0)} in cash</b> outside the managed portfolio as a spending buffer; the manager holds a little more inside it.`);
    why.push(`Market-signal tilts are not applied: the manager sets the tactical allocation inside the portfolio.`);
  }
  const biggest = CLASSES.map(c => [c, pf.tilts[c.key]||0]).sort((a,b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
  if (isSma) {} else if (DATA.tactical.enabled && Math.abs(biggest[1]) >= 0.5) why.push(`Market signals moved <b>${biggest[0].label.toLowerCase()}</b> ${biggest[1]>0?"up":"down"} by ${Math.abs(biggest[1]).toFixed(1)} points from its long-run target; the defensive classes absorbed the difference.`);
  else if (!isSma) why.push(`Market signals are close to neutral today, so the weights sit near the long-run targets.`);
  const st = DATA.stage_rules[pf.life_stage];
  if (!isSma && st.cash_floor_pp > 0 && (cw.cash||0) >= st.cash_floor_pp - 0.5) why.push(`${S} keeps at least <b>${st.cash_floor_pp}% in cash</b> as a spending buffer.`);
  if (!isSma && st.home_bias_pp > 0) why.push(`${st.home_bias_pp} points moved from international to <b>Australian shares</b>: a pension account pays no tax, so franking credits are refunded in cash and a 4% fully franked dividend is worth 5.7% to it.`);
  if (!isSma && st.income_preference > 0) why.push(`Within each class, holdings are weighted by <b>grossed-up yield</b> (cash dividend plus franking credit), so franked income ranks ahead of unfranked and ahead of price growth${st.min_equity_yield_pct ? `; equity holdings yielding under ${st.min_equity_yield_pct}% grossed up are left out` : ""}.`);
  if (!isSma) why.push(`At ${T.label.toLowerCase()} balances the rules allow up to <b>${T.max_holdings} holdings</b> with at least ${fmtM(T.min_holding)} each, so brokerage does not eat the return.`);
  sel("why").innerHTML = why.map(w => `<li>${w}</li>`).join("");

  sel("explain").innerHTML = `<p>This is a <b>${P.toLowerCase()}</b> portfolio: the long-run target is ${fmtP(DATA.saa[pf.profile_used].growth,0)} growth assets, which historically means
    deeper falls in bad years in exchange for higher returns over ${DATA.saa[pf.profile_used].horizon}+ years. ${st.blurb}</p>
    <p>Over the last year this mix moved about ±${fmtP(m.realised_volatility_pct,0)}. A simple average of the holdings' own volatilities would say
    ${fmtP(m.weighted_avg_holding_vol_pct,0)}; the difference is diversification, because the holdings do not all move together.</p>
    <p>Costs are ${fmtP(m.total_ongoing_cost_pct,2)} a year all-in${m.total_ongoing_cost_pct > 1.5 ? ", which is high: at this balance the platform's fixed fees dominate and a simpler structure would be cheaper" : ""}.
    ${isSma ? "There is no brokerage on the way in: the manager trades inside the portfolio and those costs are in the fee above." : `Buying every holding from scratch would cost about ${fmtM(m.initial_brokerage)} in brokerage.`}</p>
    ${isSma ? `<p>Compare it with the "Individual holdings" route for the same balance: the managed portfolio is simpler and rebalanced for you, but you cannot see or change what is inside it day to day, and the manager's reported returns (to ${pf.sma.as_of}) come from the platform menu rather than a live feed.</p>` : ""}`;

  const maxW = Math.max(...pf.lines.map(l => l.weight_pct));
  const classLabel = k => k === "__sma__" ? "Diversified (managed)" : label(CLASSES, k);
  const classColor = k => k === "__sma__" ? "var(--accent)" : cssColor(k);
  sel("holdings").innerHTML = pf.lines.map(l => { const r = R[l.ticker] || {}; const col = classColor(l.asset_class);
    return `<tr class="row ${state.ticker===l.ticker?"active":""}" tabindex="0" data-t="${l.ticker}"><td><b>${l.name}</b><br><span class="mono" style="font-size:11.5px;color:var(--faint)">${l.ticker} · ${l.vehicle}</span> ${qualityChip(l.ticker)}</td>
      <td><span class="dot" style="background:${col}"></span>${classLabel(l.asset_class)}</td><td class="num">${fmtP(l.weight_pct,1)}</td>
      <td><div class="bar"><span style="width:${l.weight_pct/maxW*100}%;background:${col}"></span></div></td>
      <td>${consensusChip(r)}${l.consensus_multiplier && Math.abs(l.consensus_multiplier-1) >= 0.01 ? `<span class="mult ${l.consensus_multiplier>1?"pos":"neg"}" title="weight scaled within its asset class by the analyst consensus">${l.consensus_multiplier>1?"+":""}${Math.round((l.consensus_multiplier-1)*100)}% weight</span>` : ""}</td>
      <td>${esgChip(l.ticker)}</td>
      <td class="num">${fmtM(l.dollars)}</td><td class="num">${fmtN(l.units)}</td><td class="num">${l.price_aud==null?"–":"$"+l.price_aud.toFixed(2)}</td>
      <td>${spark(r.sparkline, col)}</td><td class="num ${r.return_1y_pct>0?"pos":r.return_1y_pct<0?"neg":""}">${fmtS(r.return_1y_pct)}</td>
      <td class="num">${retCell(r, "return_3y_pct_pa", "3y")}</td><td class="num">${retCell(r, "return_5y_pct_pa", "5y")}</td><td class="num">${retCell(r, "return_10y_pct_pa", "10y")}</td>
      <td class="num">${fmtP(l.yield_pct,1)}${l.yield_source==="live"?"°":""}</td><td class="num">${betaCell(pf, l)}</td><td class="no-print">${docLink(l)}</td>
      <td class="no-print actions">${l.preview ? '<span class="preview-tag">preview</span>' : ''}${FN && !isSma && l.asset_class!=="cash" ? `<button type="button" class="btn small danger" data-remove="${l.ticker}" title="Remove from the portfolio">remove</button>` : ""}</td></tr>`; }).join("");
  renderRecs(pf);
  renderEsgChanges(pf);
  sel("holdings").querySelectorAll("button[data-remove]").forEach(b => { b.onclick = e => { e.stopPropagation(); removeHolding(b.dataset.remove); }; });
  sel("holdings").querySelectorAll("tr.row").forEach(tr => { const open = () => { state.ticker = (state.ticker===tr.dataset.t) ? null : tr.dataset.t; renderSheet(pf); };
    tr.onclick = open; tr.onkeydown = e => { if (e.key==="Enter"||e.key===" ") { e.preventDefault(); open(); } }; });
  renderSheet(pf);
  sel("sheets").innerHTML = pf.lines.map(l => sheetHtml(l, pf)).join("");

  const cands = DATA.review.filter(x => x.action.endsWith("candidate"));
  sel("reviewmeta").textContent = cands.length
    ? `${cands.filter(x=>x.action==="remove candidate").length} removal and ${cands.filter(x=>x.action==="add candidate").length} addition proposal(s). These are proposals only; the portfolios above are unchanged until they are applied.`
    : "No changes proposed: no active holding has reached three strikes and no watchlist name clears the bar for addition.";
  const cls = a => a==="remove candidate" ? "critical" : a==="add candidate" ? "good" : "neutral";
  const shown = cands.length ? cands : DATA.review.filter(x => x.reasons.length || x.positives.length).sort((a,b) => b.reasons.length - a.reasons.length).slice(0, 6);
  sel("reviewlist").innerHTML = `<div class="tscroll"><table><thead><tr><th>Verdict</th><th>Holding</th><th>Asset class</th><th>Strikes</th><th>Merits</th><th class="no-print"></th></tr></thead><tbody>` +
    shown.map(x => `<tr><td><span class="chip ${cls(x.action)}">${x.action}</span></td><td><b>${x.name}</b><br><span class="mono" style="font-size:11.5px;color:var(--faint)">${x.ticker} · ${x.status}</span></td>
      <td>${label(CLASSES, x.asset_class)}</td><td style="color:var(--critical)">${x.reasons.map(r=>"· "+r).join("<br>")||"–"}</td><td style="color:var(--good)">${x.positives.map(r=>"· "+r).join("<br>")||"–"}</td>
      <td class="no-print">${FN ? (x.action==="remove candidate" ? `<button type="button" class="btn small danger" data-rv-remove="${x.ticker}">Remove from portfolios</button>` : x.action==="add candidate" ? `<button type="button" class="btn small primary" data-rv-add="${x.ticker}" data-cls="${x.asset_class}" data-name="${x.name}">Add to portfolios</button>` : "") : ""}</td></tr>`).join("") + `</tbody></table></div>` +
    (cands.length ? "" : `<p class="muted" style="font-size:12.5px">Showing the holdings with the most strikes so you can see what the screen is watching.</p>`);
  sel("reviewlist").querySelectorAll("button[data-rv-remove]").forEach(b => b.onclick = () => removeHolding(b.dataset.rvRemove));
  sel("reviewlist").querySelectorAll("button[data-rv-add]").forEach(b => b.onclick = () => addHolding({symbol:b.dataset.rvAdd, name:b.dataset.name, type:"EQUITY"}, b.dataset.cls));
  sel("sigmeta").textContent = isSma ? "Signals are shown for information; they are not applied to a managed portfolio, whose manager sets its own tactical allocation." : DATA.tactical.enabled
    ? `Signals as of ${DATA.tactical.as_of}. Each class can move at most ${DATA.tactical.max_tilt_pp} points; the growth-versus-defensive shift is capped at ${DATA.tactical.max_growth_shift_pp} points; tilts change only when the new value differs by more than ${DATA.tactical.hysteresis_pp} point.`
    : "Tactical tilts are switched off; the portfolio sits on its long-run targets.";
  sel("sigtable").innerHTML = CLASSES.map(c => { const s = DATA.tactical.signals[c.key]; if (!s) return "";
    return `<tr><td>${classChip(c.key)}${c.label}</td><td class="num">${s.trend==null?"–":fmtS(s.trend*100)}</td><td class="num">${s.momentum==null?"–":fmtS(s.momentum*100)}</td>
      <td class="num">${s.volatility==null?"–":fmtS(s.volatility*100)}</td><td class="num">${s.score.toFixed(2)}</td><td class="num">${(pf.tilts[c.key]>=0?"+":"")+(pf.tilts[c.key]||0).toFixed(1)} pp</td><td style="color:var(--muted)">${s.note}</td></tr>`; }).join("");
}

function smaSheetHtml(l, pf){
  const c = pf.sma.shortlist.find(a => a.code===l.ticker) || pf.sma.chosen; const pct = x => (x==null||x===0) ? "–" : fmtS(x*100);
  const inUse = new Set(pf.lines.filter(x => x.vehicle==="sma").map(x => x.ticker));
  const alt = pf.sma.shortlist.map(a => `<tr${a.code===c.code?' style="font-weight:600"':''}><td>${a.code}</td><td>${a.name}</td><td>${a.manager.replace(/ \(MF\)$/, "")}</td>
      <td class="num">${fmtP(a.total_fee*100,2)}</td><td class="num">${pct(a.ret_1y)}</td><td class="num">${pct(a.ret_3y)}</td><td class="num">${pct(a.ret_5y)}</td><td class="num">${a.track_record_years}</td>
      <td class="no-print">${a.code===c.code ? '<span class="chip neutral">in use</span>' : inUse.has(a.code) ? '<span class="chip neutral">other slot</span>' : `<button type="button" class="btn" style="padding:3px 9px;font-size:12px" data-swap="${a.code}" data-from="${l.ticker}">use this</button>`}</td></tr>`).join("");
  return `<div class="sheet">
    <div class="sheet-head"><h3>${c.name} <span class="mono" style="font-weight:400;color:var(--faint);font-size:14px">${c.code}</span></h3>
      <div><span class="dot" style="background:var(--accent)"></span>Diversified managed portfolio · ${fmtP(l.weight_pct,1)} of the account (${fmtM(l.dollars)})</div></div>
    <div class="sheet-grid">
      <div>
        <div class="eyebrow" style="margin-top:6px">${c.category} · ${c.manager.replace(/ \(MF\)$/, "")}</div>
        <p class="summary">A managed portfolio (separately managed account) is a model run by a professional manager. The platform buys the underlying holdings
        in your name and rebalances them whenever the manager changes the model, so one line on the account gives a whole diversified mix.
        Benchmark: ${c.benchmark || "not stated"}. Running since ${c.inception ? c.inception.slice(0,10) : "n/a"}.</p>
        <div class="eyebrow">Options in the same category, ranked by total fee. Pick a different one to see the effect on cost.</div>
        <div class="tscroll"><table><thead><tr><th>Code</th><th>Portfolio</th><th>Manager</th><th class="num">Total fee</th><th class="num">1y</th><th class="num">3y pa</th><th class="num">5y pa</th><th class="num">Years</th><th class="no-print"></th></tr></thead><tbody>${alt}</tbody></table></div>
        <p class="summary" style="margin-top:8px">Fees and returns are the platform's published figures as of ${pf.sma.as_of}; they are not refreshed daily like the listed holdings.${c.fee_basis ? " " + c.fee_basis + "." : ""} ${docLink(l, true)}</p>
      </div>
      <dl class="kv">
        <dt>Management fee</dt><dd>${fmtP(c.mgmt_fee*100,2)}</dd>
        <dt>Underlying fund costs</dt><dd>${fmtP(c.underlying_fees*100,2)}</dd>
        <dt>Transaction costs</dt><dd>${fmtP(c.transaction_costs*100,2)}</dd>
        <dt>Total</dt><dd>${fmtP(c.total_fee*100,2)}</dd>
        <dt>Reported 1 year</dt><dd>${pct(c.ret_1y)}</dd>
        <dt>Reported 3 years, per year</dt><dd>${pct(c.ret_3y)}</dd>
        <dt>Reported 5 years, per year</dt><dd>${pct(c.ret_5y)}</dd>
        <dt>Since inception, per year</dt><dd>${pct(c.ret_inception)}</dd>
        ${(() => { const u = (pf.sma.underlying||{})[c.code]; if (!u) return ""; return `<dt style="margin-top:6px"><b>Live, from the underlying ETFs</b></dt><dd style="font-family:inherit;color:var(--faint);text-align:right">${u.source}</dd>
        <dt>1 year</dt><dd class="${u.return_1y_pct>0?"pos":u.return_1y_pct<0?"neg":""}">${fmtS(u.return_1y_pct)}</dd>
        <dt>3 years, per year</dt><dd>${fmtS(u.return_3y_pct_pa)}</dd><dt>5 years, per year</dt><dd>${fmtS(u.return_5y_pct_pa)}</dd><dt>10 years, per year</dt><dd>${fmtS(u.return_10y_pct_pa)}</dd>`; })()}
        <dt>Amount held</dt><dd>${fmtM(l.dollars)}</dd>
        <dt>Data</dt><dd style="font-family:inherit;color:var(--faint)">HUB24 menu · ${pf.sma.as_of}${(pf.sma.underlying||{})[c.code] ? "; live figures to " + pf.as_of : ""}</dd>
      </dl>
    </div></div>`;
}
function sheetHtml(l, pf){
  if (l.vehicle === "sma") return smaSheetHtml(l, pf);
  const r = R[l.ticker] || {}; const col = cssColor(l.asset_class);
  const pos = (r.week52_low!=null && r.week52_high!=null && r.price!=null && r.week52_high>r.week52_low) ? Math.max(0, Math.min(100, (r.price-r.week52_low)/(r.week52_high-r.week52_low)*100)) : null;
  const role = l.role==="fallback" ? "low cost core building block" : l.role==="core" ? "core holding" : "satellite holding";
  const ccy = r.price_currency && r.price_currency!=="AUD" ? ` (${r.price_currency})` : "";
  const sentences = r.summary ? r.summary.split(". ") : [];
  const blurb = sentences.length ? sentences.slice(0,4).join(". ") + (sentences.length>4 ? "." : "") : (l.priced_from==="manual" ? "Unlisted holding: no public data feed. Price and description are entered by hand." : "No description available from the data feed.");
  return `<div class="sheet">
    <div class="sheet-head"><h3>${l.name} <span class="mono" style="font-weight:400;color:var(--faint);font-size:14px">${l.ticker}</span></h3>
      <div>${classChip(l.asset_class)}${label(CLASSES, l.asset_class)} · ${role} · ${fmtP(l.weight_pct,1)} of the portfolio (${fmtM(l.dollars)})</div></div>
    <div class="sheet-grid">
      <div>
        ${r.sector ? `<div class="eyebrow" style="margin-top:6px">${r.sector}${r.industry?" · "+r.industry:""}</div>` : ""}
        ${DATA.quality[l.ticker] ? `<div class="note" style="background:var(--accent-soft);color:var(--text)"><b>Reviewed verdict: ${DATA.quality[l.ticker].verdict}.</b> ${DATA.quality[l.ticker].note} <span class="muted">(${DATA.quality[l.ticker].reviewed}; opinion, not advice)</span></div>` : ""}
        <p class="summary">${blurb}</p>
        ${r.sparkline && r.sparkline.length ? `<div class="eyebrow">Last 12 months, dividends reinvested, rebased to 100</div>${spark(r.sparkline, col, 600, 120, true)}` : ""}
        ${pos!=null ? `<div class="eyebrow" style="margin-top:10px">52 week range${ccy}</div><div class="range"><i style="left:${pos.toFixed(1)}%"></i></div><div class="range-l"><span>${r.week52_low.toFixed(2)}</span><span>now ${r.price.toFixed(2)}</span><span>${r.week52_high.toFixed(2)}</span></div>` : ""}
      </div>
      <dl class="kv">
        <dt>Analyst view</dt><dd>${consensusChip(r)}</dd>
        ${r.target_mean!=null ? `<dt>Mean price target${ccy}</dt><dd>${r.target_mean.toFixed(2)} (${fmtS(r.target_upside_pct)})</dd>` : ""}
        <dt>Weight adjustment from analysts</dt><dd>×${(l.consensus_multiplier||1).toFixed(2)}</dd>
        <dt>1 year return</dt><dd class="${r.return_1y_pct>0?"pos":r.return_1y_pct<0?"neg":""}">${fmtS(r.return_1y_pct)}</dd>
        <dt>3 years, per year</dt><dd>${fmtS(r.return_3y_pct_pa)}${r.return_proxy && r.return_proxy["3y"] ? "†" : ""}</dd>
        <dt>5 years, per year</dt><dd>${fmtS(r.return_5y_pct_pa)}${r.return_proxy && r.return_proxy["5y"] ? "†" : ""}</dd>
        <dt>10 years, per year</dt><dd>${fmtS(r.return_10y_pct_pa)}${r.return_proxy && r.return_proxy["10y"] ? "†" : ""}</dd>
        ${r.return_proxy && Object.keys(r.return_proxy).length ? `<dt>Index stand-in used</dt><dd style="font-family:inherit;color:var(--faint)">${Object.entries(r.return_proxy).map(([k,v]) => k + ": " + v).join(", ")} (history ${r.history_years} years)</dd>` : ""}
        <dt>Worst fall in the last year</dt><dd>${fmtP(r.max_drawdown_1y_pct)}</dd>
        <dt>Volatility (1y)</dt><dd>${fmtP(r.volatility_1y_pct)}</dd>
        <dt>Dividend yield</dt><dd>${fmtP(l.yield_pct,2)}${l.yield_source==="live"?"° ("+(r.yield_basis||"trailing 12 months")+")":" (configured)"}</dd>
        ${r.data_flags && r.data_flags.length ? `<dt>Data caution</dt><dd style="font-family:inherit;color:var(--serious);text-align:right">${r.data_flags.join("; ")}</dd>` : ""}
        <dt>Franking (estimate)</dt><dd>${fmtP(l.franking_pct,0)}</dd>
        ${r.pe_trailing!=null ? `<dt>Price to earnings</dt><dd>${r.pe_trailing.toFixed(1)}${r.pe_forward?" / fwd "+r.pe_forward.toFixed(1):""}</dd>` : ""}
        ${r.market_cap!=null ? `<dt>${r.quote_type==="ETF"?"Fund size":"Market cap"}${ccy}</dt><dd>${fmtBig(r.market_cap)}</dd>` : ""}
        <dt>Management cost</dt><dd>${fmtP(l.mer_pct,2)}</dd>
        <dt>Beta to ASX 200 (1y)</dt><dd>${betaCell(pf, l)}</dd>
        <dt>ESG review</dt><dd style="font-family:inherit;text-align:right">${esgChip(l.ticker)}${DATA.esg.review[l.ticker] && DATA.esg.review[l.ticker].involvement ? ` <span class="muted">(${DATA.esg.exclusions[DATA.esg.review[l.ticker].involvement]||DATA.esg.review[l.ticker].involvement})</span>` : ""}</dd>
        ${DATA.esg.review[l.ticker] ? `<dt></dt><dd style="font-family:inherit;text-align:right;color:var(--muted);font-size:12.5px">${DATA.esg.review[l.ticker].note} <span class="muted">(reviewed ${DATA.esg.review[l.ticker].reviewed}; written opinion, not a data feed)</span></dd>` : ""}
        <dt>Documents</dt><dd style="font-family:inherit">${docLink(l, true)}</dd>
        <dt>Units held</dt><dd>${fmtN(l.units)} @ $${(l.price_aud||0).toFixed(2)}</dd>
        <dt>Data</dt><dd style="font-family:inherit;color:var(--faint)">${r.source||l.priced_from}${r.fetched?" · "+r.fetched:""}</dd>
      </dl>
    </div></div>`;
}
function renderEsgChanges(pf){
  const el = sel("esgchanges"); const ch = (pf.esg && (pf.esg.shared_changes ? DATA.esg.shared_changes : pf.esg.changes)) || [];
  if (!(pf.esg && pf.esg.screened)) { el.innerHTML = ""; return; }
  const ex = ch.filter(c => c.action === "excluded"), sub = ch.filter(c => c.action === "substituted"), other = ch.filter(c => c.action !== "excluded" && c.action !== "substituted");
  el.innerHTML = `<div class="eyebrow">What the ESG screen changed</div><div class="reclist">` +
    (ex.length ? `<div><span class="chip critical">Excluded</span> ${ex.map(c => `<span class="recitem" title="${(c.reason||"").replace(/"/g,"&quot;")}">${c.name}${c.involvement ? ` <span class="muted">(${DATA.esg.exclusions[c.involvement]||c.involvement})</span>` : ""}</span>`).join(", ")}</div>` : "") +
    (sub.length ? `<div><span class="chip serious">Swapped</span> ${sub.map(c => `<span class="recitem" title="${(c.reason||"").replace(/"/g,"&quot;")}">${c.name} → ${c.replacement}</span>`).join(", ")}</div>` : "") +
    other.map(c => `<div><span class="chip neutral">${c.action}</span> ${c.reason}</div>`).join("") +
    `</div><p class="muted" style="font-size:12.5px;margin:6px 0 0">Verdicts are written reviews dated on each fact sheet, not a ratings feed: Yahoo Finance no longer supplies Sustainalytics scores, so there is no automated ESG score behind this page. Hover a name for the reason. Compare cost, yield and the backtest with the screen off to see what the exclusions give up.</p>`;
}
function renderRecs(pf){
  const el = sel("recs"); if (pf.implementation === "sma") { el.innerHTML = ""; return; }
  const order = ["Strong Buy", "Buy", "Hold", "Underperform", "Sell"]; const cls = {"Strong Buy":"good", "Buy":"good", "Hold":"neutral", "Underperform":"serious", "Sell":"critical"};
  const groups = {}; let covered = 0, wCovered = 0;
  for (const l of pf.lines) { const r = R[l.ticker] || {}; const lab = r.consensus_label; if (!order.includes(lab)) continue; (groups[lab] = groups[lab] || []).push(l); covered++; wCovered += l.weight_pct; }
  if (!covered) { el.innerHTML = `<div class="muted" style="font-size:12.5px">No analyst coverage on these holdings: index ETFs and listed investment companies are not rated by brokers.</div>`; return; }
  const extra = pf.lines.filter(l => (l.consensus_multiplier||1) > 1.005).length, trimmed = pf.lines.filter(l => (l.consensus_multiplier||1) < 0.995).length;
  el.innerHTML = `<div class="eyebrow">Analyst recommendations (Yahoo Finance consensus of covering brokers)</div>
    <div class="recrow">${order.filter(k => groups[k]).map(k => `<span class="chip ${cls[k]}">${k} · ${groups[k].length}</span>`).join("")}
      <span class="muted" style="font-size:12.5px">${covered} of ${pf.lines.length} holdings (${fmtP(wCovered,0)} of the portfolio) are rated; ${extra} carry extra weight because the average rating leans toward Buy, ${trimmed} are trimmed because it leans toward Sell (a Hold sits either side of the midpoint). The scaling is capped at a quarter either way and never removes a holding.</span></div>
    <div class="reclist">${order.filter(k => groups[k]).map(k => `<div><span class="chip ${cls[k]}">${k}</span> ${groups[k].map(l => { const r = R[l.ticker]; const mlt = l.consensus_multiplier||1; return `<span class="recitem" title="${r.analysts} analysts, mean ${r.consensus_mean.toFixed(1)}${r.target_upside_pct!=null ? "; mean target " + fmtS(r.target_upside_pct) + " from here" : ""}">${l.name}${Math.abs(mlt-1) >= 0.01 ? ` <span class="mult ${mlt>1?"pos":"neg"}">${mlt>1?"+":""}${Math.round((mlt-1)*100)}%</span>` : ""}</span>`; }).join(", ")}</div>`).join("")}</div>`;
}
function historyKey(pf, l){ const hk = (pf.sma && pf.sma.history_key) || {}; return hk[l.ticker] || l.ticker; }
function computeBacktest(pf, bal){
  const H = DATA.history; if (!H || !H.months || !H.months.length) return null;
  const n = H.months.length, S = H.series, cp = H.class_proxy || {};
  const rows = pf.lines.map(l => { const k = historyKey(pf, l); let sr = S[k], key = k, whole = false;
    if (!sr && l.vehicle !== "cash") { key = cp[l.asset_class]; sr = S[key]; whole = !!sr; }
    return { w: l.weight_pct/100, sr: sr || null, key, whole, name: l.name, ticker: l.ticker }; });
  const values = []; let v = bal, peak = bal, mdd = 0;
  const fb = pf.lines.map(l => S[cp[l.asset_class]] || null);
  for (let i = 0; i < n; i++) { let r = 0; rows.forEach((x, k) => { if (!x.sr) return; let y = x.sr[i]; if (y == null) y = (fb[k] && fb[k][i] != null) ? fb[k][i] : 0; r += x.w * y; }); v *= 1 + r; values.push(v); if (v > peak) peak = v; mdd = Math.min(mdd, v/peak - 1); }
  const yrs = n/12, cagr = Math.pow(v/bal, 1/yrs) - 1;
  const tw = []; for (let i = 12; i < n; i++) tw.push(values[i]/values[i-12] - 1);
  const sim = H.stand_in_months || {};
  const standShare = rows.reduce((s, x) => s + x.w * (x.whole ? n : (sim[x.key] || 0)), 0) / n * 100;
  const standIns = rows.filter(x => x.whole || (H.stand_in||{})[x.key]).map(x => ({ name: x.name, proxy: x.whole ? x.key : H.stand_in[x.key], months: x.whole ? n : sim[x.key] }));
  return { values, end: v, cagr, mdd, best: tw.length ? Math.max(...tw) : null, worst: tw.length ? Math.min(...tw) : null, years: yrs, standShare, standIns };
}
function seriesGrowth(key, bal){ const sr = (DATA.history.series||{})[key]; if (!sr) return null; let v = bal; return sr.map(r => v *= 1 + (r||0)); }
function renderBacktest(pf){
  const H = DATA.history; const bal = pf.balance; const bt = computeBacktest(pf, bal);
  if (!bt) { sel("bttiles").innerHTML = ""; sel("btchart").innerHTML = `<div class="muted">No price history embedded in this build.</div>`; return; }
  sel("bt-title").textContent = `If ${fmtM(bal)} had been invested ${Math.round(bt.years)} years ago`;
  sel("bttiles").innerHTML = [
    ["Worth today", fmtM(bt.end), `from ${fmtM(bal)} in ${H.months[0]}`],
    ["Per year", fmtS(bt.cagr*100), "compound annual growth, dividends reinvested, before fees and tax"],
    ["Worst fall", fmtP(bt.mdd*100,0), "largest peak-to-trough drop along the way"],
    ["Best 12 months", fmtS((bt.best||0)*100), "and worst: " + fmtS((bt.worst||0)*100)],
    ["On stand-ins", fmtP(bt.standShare,0), bt.standShare > 0 ? "share of the result that came from index ETFs standing in for younger holdings" : "every holding has its own full history"],
  ].map(([k,v,s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  const asx = seriesGrowth("VAS.AX", bal), cash = seriesGrowth(H.class_proxy && H.class_proxy.cash, bal), world = seriesGrowth("VGS.AX", bal);
  const lines = [["This portfolio", bt.values, "var(--accent)", 2.4], ["Australian shares (VAS)", asx, cssColor("aus_equity"), 1.3], ["World shares (VGS)", world, cssColor("intl_equity"), 1.3], ["Cash ETF", cash, cssColor("cash"), 1.3]].filter(x => x[1]);
  const W = 900, Hh = 300, padL = 64, padR = 16, padT = 12, padB = 28, n = H.months.length;
  const all = lines.flatMap(x => x[1]); const lo = Math.min(bal, ...all) * 0.95, hi = Math.max(...all) * 1.03;
  const X = i => padL + i/(n-1)*(W-padL-padR), Y = v => padT + (1 - (v-lo)/(hi-lo))*(Hh-padT-padB);
  const raw = (hi-lo)/5, mag = Math.pow(10, Math.floor(Math.log10(raw))), step = [1,2,2.5,5,10].map(x => x*mag).find(x => x >= raw);
  let grid = ""; for (let v = Math.ceil(lo/step)*step; v <= hi; v += step) { grid += `<line x1="${padL}" x2="${W-padR}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)" stroke-width="1"/><text x="${padL-6}" y="${Y(v)+4}" text-anchor="end" font-size="11" fill="var(--faint)">${fmtM(v)}</text>`; }
  let xl = ""; for (let i = 0; i < n; i += 12) xl += `<text x="${X(i)}" y="${Hh-8}" text-anchor="middle" font-size="11" fill="var(--faint)">${H.months[i].slice(0,4)}</text>`;
  const paths = lines.map(([name, vals, col, sw]) => `<path d="${vals.map((v,i) => (i?"L":"M") + X(i).toFixed(1) + " " + Y(v).toFixed(1)).join(" ")}" fill="none" stroke="${col}" stroke-width="${sw}" stroke-linejoin="round"/>`).join("");
  sel("btchart").innerHTML = `<svg viewBox="0 0 ${W} ${Hh}" width="100%" role="img" aria-label="Growth of ${fmtM(bal)} over ${Math.round(bt.years)} years">${grid}${xl}${paths}</svg>`;
  sel("btlegend").innerHTML = lines.map(([name, vals, col]) => `<span><i style="background:${col}"></i>${name}: ${fmtM(vals[vals.length-1])}</span>`).join("");
  sel("btnote").innerHTML = (bt.standIns.length ? `Stand-ins: ${bt.standIns.map(x => `${x.name} used ${x.proxy} for ${x.months} of ${n} months`).join("; ")}. ` : "") +
    (pf.implementation === "sma" ? "For a managed portfolio the line is its listed twin ETF where one exists, otherwise the risk profile's strategic mix held in asset class ETFs; the manager's own track record is shorter and is shown on the fact sheet. " : "") +
    "The comparison lines put the same balance into a single ETF with no rebalancing.";
}
const SECTOR_COLORS = ["#2a78d6","#eb6834","#1baf7a","#eda100","#e87ba4","#008300","#4a3aa7","#0e9aa7","#8a5a2b","#c2185b","#5c6bc0","#7cb342","#f4511e","#00897b","#6d4c41","#9e9d24"];
function diversification(pf){
  const lines = pf.lines.filter(l => l.vehicle !== "sma");
  const sec = {}, reg = {}; let direct = 0, dsum = 0; const dsec = {};
  for (const l of lines) { const sk = l.sector || (l.vehicle === "direct" ? "Other" : l.asset_class === "cash" ? "Cash" : "Diversified fund"), rk = l.region || "Other";
    sec[sk] = (sec[sk]||0) + l.weight_pct; reg[rk] = (reg[rk]||0) + l.weight_pct;
    if (l.vehicle === "direct") { direct++; dsum += l.weight_pct; dsec[sk] = (dsec[sk]||0) + l.weight_pct; } }
  const sorted = o => Object.entries(o).sort((a,b) => b[1]-a[1]);
  const hhi = lines.reduce((s,l) => s + Math.pow(l.weight_pct/100, 2), 0);
  const top = [...lines].sort((a,b) => b.weight_pct - a.weight_pct);
  const flags = []; const rules = DATA.diversification || {};
  const ds = sorted(dsec);
  if (direct >= 4 && ds.length && ds[0][1]/dsum > 0.4 && ds[0][1] > 5) flags.push(`${ds[0][0]} is ${Math.round(ds[0][1]/dsum*100)}% of the single-company holdings`);
  const rs = sorted(reg); if (rs.length && rs[0][1] > 70 && rs[0][0] !== "Australia") flags.push(`${Math.round(rs[0][1])}% of the portfolio is exposed to ${rs[0][0]}`);
  if (top[0] && top[0].vehicle === "direct" && top[0].weight_pct > (rules.max_single_holding_pct||10)) flags.push(`${top[0].name} is ${top[0].weight_pct.toFixed(1)}% of the portfolio`);
  const nsec = Object.keys(dsec).length; if (direct >= 3 && nsec < (rules.min_sectors_direct||3)) flags.push(`the single companies span only ${nsec} sector(s)`);
  return { sector: sorted(sec), region: sorted(reg), direct, directShare: dsum, directSectors: nsec, effective: hhi > 0 ? 1/hhi : null, top: top[0], top5: top.slice(0,5).reduce((s,l) => s + l.weight_pct, 0), flags };
}
function renderDiversification(pf){
  if (pf.implementation === "sma") { sel("divtiles").innerHTML = `<div class="muted" style="font-size:13px">Not available for a managed portfolio: the manager's holdings are not in the data feed.</div>`; sel("secstack").innerHTML = sel("regstack").innerHTML = sel("seclegend").innerHTML = sel("reglegend").innerHTML = sel("divflags").innerHTML = ""; return; }
  const d = diversification(pf);
  sel("divtiles").innerHTML = [
    ["Effective holdings", d.effective == null ? "–" : d.effective.toFixed(1), `${pf.lines.length} lines, counted as if equally weighted`],
    ["Largest holding", fmtP(d.top ? d.top.weight_pct : null, 1), d.top ? d.top.name : ""],
    ["Top five", fmtP(d.top5, 0), "share of the portfolio in the five largest lines"],
    ["Single companies", `${d.direct}`, `${fmtP(d.directShare, 0)} of the portfolio, across ${d.directSectors} sector${d.directSectors === 1 ? "" : "s"}`],
    ["Sectors and regions", `${d.sector.length} / ${d.region.length}`, "distinct sectors (funds count as one) and countries or regions"],
  ].map(([k,v,s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  const draw = (id, lid, items) => { sel(id).innerHTML = items.map(([k,v],i) => `<span style="width:${v}%;background:${SECTOR_COLORS[i % SECTOR_COLORS.length]}" data-l="${k}: ${fmtP(v)}"></span>`).join("");
    sel(id).querySelectorAll("span").forEach(el => { el.onmousemove = e => showTip(e, el.dataset.l); el.onmouseleave = hideTip; });
    sel(lid).innerHTML = items.map(([k,v],i) => `<span><i style="background:${SECTOR_COLORS[i % SECTOR_COLORS.length]}"></i>${k} <span class="mono">${fmtP(v)}</span></span>`).join(""); };
  draw("secstack", "seclegend", d.sector); draw("regstack", "reglegend", d.region);
  sel("divflags").innerHTML = d.flags.length ? d.flags.map(f => `<span class="flag">${f}</span>`).join("") : `<span class="chip good">No concentration flags against the engine's rules</span>`;
}
function renderRisk(pf){
  const m = pf.metrics, isSma = pf.implementation === "sma";
  const dr = m.diversification_ratio, apc = m.avg_pairwise_correlation;
  sel("risktiles").innerHTML = [
    ["Beta to the ASX 200", m.beta_asx200 == null ? "–" : m.beta_asx200.toFixed(2), m.beta_asx200 == null ? "not enough price history" : `a 10% fall in Australian shares has meant about ${fmtP(Math.abs(m.beta_asx200)*10,0)} here`],
    ["Beta to world shares", m.beta_world == null ? "–" : m.beta_world.toFixed(2), "against the developed-world index ETF (VGS), unhedged"],
    ["Correlation to the ASX 200", m.correlation_asx200 == null ? "–" : m.correlation_asx200.toFixed(2), m.correlation_asx200 > 0.85 ? "moves almost in lock-step with the local market" : m.correlation_asx200 > 0.6 ? "tracks the local market fairly closely" : "only loosely tied to the local market"],
    ["Correlation between holdings", apc == null ? "–" : apc.toFixed(2), apc == null ? "" : apc > 0.5 ? "the holdings tend to rise and fall together" : apc > 0.25 ? "moderately related; some genuine diversification" : "largely independent of each other"],
    ["Diversification ratio", dr == null ? "–" : dr.toFixed(2), dr == null ? "" : `the holdings' average volatility (${fmtP(m.weighted_avg_holding_vol_pct,0)}) divided by the portfolio's (${fmtP(m.realised_volatility_pct,0)}); above 1 is the benefit of mixing`],
    ["Realised volatility", "±" + fmtP(m.realised_volatility_pct,0), isSma ? "proxy: this risk profile held in ETFs" : "one standard deviation of yearly moves, from daily prices"],
  ].map(([k,v,s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  sel("risknote").hidden = !m.risk_recomputed;
  const cc = DATA.class_corr;
  if (cc && cc.classes && cc.classes.length) {
    const short = k => label(CLASSES, k).replace("Property and infrastructure", "Property and infra").replace("Credit and hybrids", "Credit");
    sel("corrmap").innerHTML = `<thead><tr><th></th>${cc.classes.map(c => `<th class="num" title="${cc.proxies[c]||""}">${short(c)}</th>`).join("")}</tr></thead><tbody>` +
      cc.classes.map((r,i) => `<tr><th>${short(r)}</th>${cc.classes.map((c,j) => { const v = cc.matrix[i][j]; return `<td class="num" style="background:${i===j?"transparent":corrColor(v)}">${v==null?"–":v.toFixed(2)}</td>`; }).join("")}</tr>`).join("") + `</tbody>`;
  } else sel("corrmap").innerHTML = "";
  const hb = m.holding_beta_asx200 || {};
  const rows = pf.lines.filter(l => hb[l.ticker] != null).map(l => [l, hb[l.ticker]]).sort((a,b) => b[1] - a[1]);
  const maxB = Math.max(1, ...rows.map(r => Math.abs(r[1])));
  sel("betalist").innerHTML = rows.length ? rows.map(([l,b]) => `<div class="betarow"><span class="n">${l.name}</span><span class="bar"><i style="width:${Math.abs(b)/maxB*100}%;background:${b<0?"var(--good)":cssColor(l.asset_class)}"></i></span><span class="v mono">${b.toFixed(2)}</span></div>`).join("")
    : `<div class="muted">${isSma ? "Not available for a managed portfolio: the manager's underlying holdings are not in the price feed, so the portfolio figures above use the risk profile's ETF proxies." : "No price history yet."}</div>`;
}
function renderSheet(pf){
  const box = sel("sheet");
  sel("holdings").querySelectorAll("tr.row").forEach(tr => tr.classList.toggle("active", tr.dataset.t===state.ticker));
  const l = pf.lines.find(x => x.ticker===state.ticker);
  if (!l) { box.hidden = true; box.innerHTML = ""; return; }
  box.hidden = false; box.innerHTML = sheetHtml(l, pf);
  box.querySelectorAll("button[data-swap]").forEach(b => b.onclick = () => swapSma(pf, b.dataset.from, b.dataset.swap));
}
function swapSma(pf, fromCode, toCode){
  const a = pf.sma.shortlist.find(x => x.code===toCode); const line = pf.lines.find(x => x.ticker===fromCode);
  if (!a || !line) return;
  line.ticker = a.code; line.name = a.name; line.mer_pct = a.total_fee*100;
  const m = pf.metrics; const smaLines = pf.lines.filter(x => x.vehicle==="sma");
  m.weighted_mer_pct = +smaLines.reduce((t,x) => t + x.mer_pct*x.weight_pct/100, 0).toFixed(3);
  m.investment_fees_per_year = Math.round(m.weighted_mer_pct/100*pf.balance);
  m.total_ongoing_cost_pct = +(m.weighted_mer_pct + m.platform_admin_fee_per_year/pf.balance*100).toFixed(3);
  pf.sma.chosen = a; pf.sma.picks = smaLines.map(x => pf.sma.shortlist.find(y => y.code===x.ticker));
  state.ticker = a.code; render();
}
// ------------------------------------------------------------ editing (live site only)
const FN = (() => { const h = location.hostname; if (h.endsWith("netlify.app") || (DATA.site_url && location.origin === DATA.site_url)) return "/.netlify/functions"; return null; })();
const previews = {};   // portfolio id -> {adds:[line], removes:Set}
let pendingChanges = [];
function pinValue(){ const v = sel("pin").value.trim(); try { if (v) localStorage.setItem("mpl-pin", v); } catch(e){} return v; }
try { sel("pin").value = localStorage.getItem("mpl-pin") || ""; } catch(e){}
async function api(path, opts){ const r = await fetch(FN + path, opts); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || r.statusText); return j; }
function searchIndex(q){
  const ql = q.toLowerCase(); const idx = DATA.search_index || []; if (!idx.length) return [];
  const score = i => { const s = i.s.toLowerCase(), n = i.n.toLowerCase(); const code = s.replace(/\.(ax|xa)$/, "");
    if (code === ql) return 100; if (code.startsWith(ql)) return 80; if (n.startsWith(ql)) return 70; if (n.split(/\s+/).some(w => w.startsWith(ql))) return 50; if (n.includes(ql)) return 30; return 0; };
  return idx.map(i => [score(i), i]).filter(x => x[0] > 0).sort((a,b) => b[0] - a[0]).slice(0, 10)
    .map(([_, i]) => ({ symbol: i.s, name: i.n, exchange: i.e, type: i.t, sector: i.c }));
}
function guessClass(sym, name, sector){
  if (sector && CLASSES.some(c => c.key === sector)) return sector;
  const sec = (sector||"").toLowerCase();
  if (/real estate|reit/.test(sec)) return "infrastructure"; if (/utilities|transportation/.test(sec)) return "infrastructure"; const n = (name||"").toLowerCase();
  if (/bond|fixed|treasury|government/.test(n)) return "fixed_income"; if (/credit|hybrid|subordinated|floating/.test(n)) return "credit";
  if (/property|reit|infrastructure|real estate|toll|airport/.test(n)) return "infrastructure"; if (/gold|commodit|private equity|alternative/.test(n)) return "alternatives";
  if (/cash|high interest/.test(n)) return "cash"; return sym.endsWith(".AX") || sym.endsWith(".XA") ? (/international|global|world|s&p 500|nasdaq|emerging|asia|us /.test(n) ? "intl_equity" : "aus_equity") : "intl_equity"; }
function guessVehicle(sym, type){ return type === "ETF" ? "etf" : "direct"; }
let qTimer;
function wireEdit(){
  if (!FN) { sel("editon").hidden = true; sel("editoff").hidden = false;
    sel("editoff").innerHTML = DATA.site_url ? `Adding and removing holdings works on the live site: <a href="${DATA.site_url}">${DATA.site_url.replace(/^https?:\/\//,"")}</a>` : "Adding and removing holdings works on the published site."; return; }
  sel("q").oninput = () => { clearTimeout(qTimer); const q = sel("q").value.trim(); if (q.length < 2) { sel("results").innerHTML = ""; return; }
    qTimer = setTimeout(async () => {
      const local = searchIndex(q);
      if (local.length) { renderResults(local); return; }
      try { const d = await api("/search?q=" + encodeURIComponent(q)); renderResults(d.results || []); }
      catch(e) { sel("results").innerHTML = `<div class="muted">No matches in the index (ASX companies over $300m, S&P 500 and major Australian ETFs). Try the ASX code or the company name.</div>`; } }, 250); };
  refreshPending();
}
function renderResults(rs){
  const pf = find(); const held = new Set(pf.lines.map(l => l.ticker));
  const opts = CLASSES.map(c => `<option value="${c.key}">${c.label}</option>`).join("");
  sel("results").innerHTML = rs.length ? `<div class="results">` + rs.map((r,i) => `<div class="result"><div><b>${r.name}</b> <span class="mono" style="color:var(--faint);font-size:12px">${r.symbol} · ${r.exchange} · ${r.type}</span></div>
    <select id="cls${i}">${opts}</select>${held.has(r.symbol) ? '<span class="chip neutral">already held</span>' : `<button type="button" class="btn small primary" data-add="${i}">Add</button>`}</div>`).join("") + `</div>` : `<div class="muted">No listed matches.</div>`;
  rs.forEach((r,i) => { const cls = sel("cls"+i); if (cls) cls.value = guessClass(r.symbol, r.name, r.sector); });
  sel("results").querySelectorAll("button[data-add]").forEach(b => b.onclick = () => addHolding(rs[+b.dataset.add], sel("cls"+b.dataset.add).value));
}
async function addHolding(r, cls){
  const pin = pinValue(); if (!pin) { alert("Enter the edit PIN first."); return; }
  const pf = find(); if (pf.implementation === "sma") { alert("Switch to Individual holdings to edit holdings."); return; }
  let q = { name: r.name, currency: (r.symbol.endsWith(".AX") || r.symbol.endsWith(".XA")) ? "AUD" : "USD", price: null, yield_pct: 0, return_1y_pct: null, spark: [] };
  try { const live = await api("/quote?symbol=" + encodeURIComponent(r.symbol)); if (live && live.price) q = live; } catch(e) { /* priced at the next rebuild */ }
  const vehicle = guessVehicle(r.symbol, r.type);
  try { pendingChanges = (await api("/changes", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ pin, action:"add", ticker:r.symbol, asset_class:cls, name:q.name||r.name, vehicle, role:"satellite", min_tier:"core", weight_hint:3, note:"added from the website" }) })).pending; }
  catch(e) { alert("Not saved: " + e.message); return; }
  const fxMap = DATA.fx_aud_per || {USD: DATA.fx_aud_per_usd || 1.5}; const priceAud = q.price == null ? null : q.price * (q.currency === "AUD" ? 1 : (fxMap[q.currency] || (q.currency === "USD" ? 1.5 : 1)));
  const line = { ticker:r.symbol, name:q.name||r.name, asset_class:cls, vehicle, role:"satellite", currency:q.currency||"AUD", source:"website", weight_pct:0, dollars:0, price_aud:priceAud, units:0,
    mer_pct: vehicle==="etf" ? 0.2 : 0, yield_pct:q.yield_pct||0, yield_source:"live", franking_pct:0, priced_from:"yahoo (preview)", consensus_label:"", consensus_multiplier:1, weight_hint:3, preview:true };
  R[r.symbol] = R[r.symbol] || { ticker:r.symbol, name:line.name, sparkline:q.spark||[], return_1y_pct:q.return_1y_pct, dividend_yield_pct:q.yield_pct, price:q.price, price_currency:q.currency, source:"yahoo (preview)", consensus_label:"no coverage", return_proxy:{} };
  const pv = previews[pf.id] = previews[pf.id] || { adds:[], removes:new Set() }; pv.removes.delete(r.symbol); if (!pv.adds.some(x => x.ticker===r.symbol)) pv.adds.push(line);
  sel("q").value = ""; sel("results").innerHTML = ""; state.ticker = r.symbol; render();
}
async function removeHolding(ticker){
  const pin = pinValue(); if (!pin) { alert("Enter the edit PIN first."); return; }
  const pf = find();
  try { pendingChanges = (await api("/changes", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ pin, action:"remove", ticker }) })).pending; }
  catch(e) { alert("Not saved: " + e.message); return; }
  const pv = previews[pf.id] = previews[pf.id] || { adds:[], removes:new Set() }; pv.adds = pv.adds.filter(x => x.ticker!==ticker); pv.removes.add(ticker);
  if (state.ticker===ticker) state.ticker = null; render();
}
async function cancelChange(id){ const pin = pinValue(); try { pendingChanges = (await api("/changes", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ pin, action:"cancel", id }) })).pending; } catch(e) { alert(e.message); } renderPending(); }
async function refreshPending(){ try { pendingChanges = (await api("/changes")).pending || []; } catch(e) { pendingChanges = []; } renderPending(); }
function renderPending(){
  const el = sel("pending"); if (!el) return;
  el.innerHTML = pendingChanges.length ? `<div class="eyebrow">Queued for the next rebuild</div>` + pendingChanges.map(c => `<div class="pend"><span class="chip ${c.action==="add"?"good":"critical"}">${c.action}</span><b>${c.name||c.ticker}</b><span class="mono" style="color:var(--faint);font-size:12px">${c.ticker}${c.asset_class?" · "+label(CLASSES,c.asset_class):""}</span><span style="flex:1"></span><button type="button" class="btn small" data-cancel="${c.id}">cancel</button></div>`).join("") : "";
  el.querySelectorAll("button[data-cancel]").forEach(b => b.onclick = () => cancelChange(b.dataset.cancel));
}
function applyPreview(pf){
  const pv = previews[pf.id]; if (!pv || pf.implementation==="sma") return pf;
  const p = JSON.parse(JSON.stringify(pf)); p.preview = true;
  p.lines = p.lines.filter(l => !pv.removes.has(l.ticker));
  // removed weight is spread across the survivors of the same class, else to cash
  for (const t of pv.removes) { const orig = pf.lines.find(l => l.ticker===t); if (!orig) continue;
    const same = p.lines.filter(l => l.asset_class===orig.asset_class); const tgt = same.length ? same : p.lines.filter(l => l.asset_class==="cash");
    const tot = tgt.reduce((s,l) => s + l.weight_pct, 0) || 1; tgt.forEach(l => l.weight_pct += orig.weight_pct * l.weight_pct / tot); }
  for (const add of pv.adds) { if (p.lines.some(l => l.ticker===add.ticker)) continue;
    const same = p.lines.filter(l => l.asset_class===add.asset_class); const classW = same.reduce((s,l) => s + l.weight_pct, 0);
    const hints = same.reduce((s,l) => s + (l.weight_hint||2), 0) + (add.weight_hint||2);
    if (classW > 0) { const w = classW * (add.weight_hint||2) / hints; same.forEach(l => l.weight_pct *= (classW - w) / classW); p.lines.push({...add, weight_pct:w}); }
    else { const w = Math.min(4, p.lines.reduce((s,l) => s + l.weight_pct, 0) * 0.04); p.lines.forEach(l => l.weight_pct *= (100 - w) / 100); p.lines.push({...add, weight_pct:w}); } }
  p.lines.forEach(l => { l.dollars = l.weight_pct/100*p.balance; l.units = l.price_aud ? l.dollars/l.price_aud : (l.preview ? null : l.units); });
  const m = p.metrics; const W = l => l.weight_pct/100;
  m.holdings = p.lines.length; m.weighted_mer_pct = +p.lines.reduce((s,l) => s + W(l)*l.mer_pct, 0).toFixed(3); m.weighted_yield_pct = +p.lines.reduce((s,l) => s + W(l)*l.yield_pct, 0).toFixed(2);
  m.income_per_year = Math.round(m.weighted_yield_pct/100*p.balance); m.investment_fees_per_year = Math.round(m.weighted_mer_pct/100*p.balance);
  m.total_ongoing_cost_pct = +(m.weighted_mer_pct + m.platform_admin_fee_per_year/p.balance*100).toFixed(3);
  const cw = {}; p.lines.forEach(l => cw[l.asset_class] = (cw[l.asset_class]||0) + l.weight_pct); p.class_weights = cw;
  m.growth_pct = +CLASSES.filter(c => c.kind==="growth").reduce((s,c) => s + (cw[c.key]||0), 0).toFixed(2); m.defensive_pct = +(100 - m.growth_pct).toFixed(2);
  p.warnings = [...p.warnings, "Preview: holdings changed on this page; weights are approximate until the next rebuild (within the hour)."];
  recomputeRisk(p);
  return p;
}
sel("apply-balance").onclick = () => { const b = parseBalance(sel("balance").value); if (!b) { alert("Enter a balance of at least $1,000."); return; } state.balance = b; state.ticker = null; render(); };
sel("balance").addEventListener("keydown", e => { if (e.key === "Enter") sel("apply-balance").onclick(); });
sel("reset-balance").onclick = () => { state.balance = null; sel("balance").value = ""; render(); };
sel("xlsx").onclick = () => {
  if (typeof XLSX === "undefined") { alert("The spreadsheet library did not load (this viewer may block downloads). Use the full workbook link or open the site directly."); return; }
  const pf0 = find(); const pf = state.balance ? scaleToBalance(applyPreview(pf0), state.balance) : applyPreview(pf0); const m = pf.metrics;
  const P = label(DATA.profiles, pf.profile_used), S = label(DATA.stages, pf.life_stage);
  const wb = XLSX.utils.book_new();
  const summary = [["Model Portfolio Lab", ""], ["Risk profile", P], ["Life stage", S], ["Balance tier", label(DATA.tiers, pf.tier)], ["Implementation", pf.implementation==="sma" ? "Managed portfolio (SMA)" : "Individual holdings"], ["ESG screen", pf.esg && pf.esg.screened ? "on" : "off"],
    ["Balance", pf.balance], ["Prices as of", pf.as_of], ["Growth %", m.growth_pct/100], ["Defensive %", m.defensive_pct/100], ["Holdings", m.holdings],
    ["Weighted MER", m.weighted_mer_pct/100], ["Investment fees p.a.", m.investment_fees_per_year], ["Platform menu", menuLabel(m.platform_menu)], ["Platform fee p.a.", m.platform_admin_fee_per_year], ["Total ongoing cost %", m.total_ongoing_cost_pct/100],
    ["Initial brokerage", m.initial_brokerage], ["Cash yield", (m.weighted_yield_pct||0)/100], ["Income p.a.", m.income_per_year||0], ["Franking credits p.a.", m.franking_credits_per_year||0], ["Grossed-up yield", (m.grossed_up_yield_pct||0)/100],
    ["Weighted 3y return p.a.", (m.weighted_return_3y_pct||0)/100], ["Weighted 5y return p.a.", (m.weighted_return_5y_pct||0)/100], ["Weighted 10y return p.a.", (m.weighted_return_10y_pct||0)/100],
    ["10y stand-in share", (m.weighted_return_10y_proxy_share_pct||0)/100], ["Realised volatility (1y)", (m.realised_volatility_pct||0)/100], ["Trailing 1y return", (m.trailing_1y_return_pct||0)/100],
    ["Backtest: worth today if invested " + (m.backtest_years||10) + " years ago", m.backtest_end_value||""], ["Backtest annualised return", (m.backtest_cagr_pct||0)/100], ["Backtest worst fall", (m.backtest_max_drawdown_pct||0)/100], ["Backtest share on stand-ins", (m.backtest_stand_in_share_pct||0)/100],
    ["Beta to ASX 200 (1y)", m.beta_asx200==null?"":m.beta_asx200], ["Beta to world shares (1y)", m.beta_world==null?"":m.beta_world], ["Correlation to ASX 200", m.correlation_asx200==null?"":m.correlation_asx200], ["Average correlation between holdings", m.avg_pairwise_correlation==null?"":m.avg_pairwise_correlation], ["Diversification ratio", m.diversification_ratio==null?"":m.diversification_ratio],
    ["", ""], ["Illustrative only; not financial advice. Returns are history, not forecasts.", ""]];
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(summary), "Summary");
  const alloc = [["Asset class", "Long-run target", "Tilt (pp)", "Actual", "Dollars"]].concat(CLASSES.map(c => [c.label, pf.saa[c.key]/100, pf.tilts[c.key], (pf.class_weights[c.key]||0)/100, (pf.class_weights[c.key]||0)/100*pf.balance]));
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(alloc), "Allocation");
  const hold = [["Ticker", "Holding", "Asset class", "Vehicle", "Weight", "Dollars", "Units", "Price (AUD)", "MER", "Yield", "Franking", "Income p.a.", "Franking credits p.a.", "1y", "3y pa", "5y pa", "10y pa", "Stand-ins", "Beta ASX 200", "Analyst view", "Verdict", "ESG review", "Documents"]]
    .concat(pf.lines.map(l => { const r = R[l.ticker]||{}; const q = DATA.quality[l.ticker]||{}; return [l.ticker, l.name, l.asset_class==="__sma__" ? "Diversified (managed)" : label(CLASSES, l.asset_class), l.vehicle, l.weight_pct/100, l.dollars, l.units, l.price_aud, l.mer_pct/100, l.yield_pct/100, (l.franking_pct||0)/100,
      l.dollars*l.yield_pct/100, l.dollars*l.yield_pct/100*(l.franking_pct||0)/100*(30/70), r.return_1y_pct==null?null:r.return_1y_pct/100, r.return_3y_pct_pa==null?null:r.return_3y_pct_pa/100, r.return_5y_pct_pa==null?null:r.return_5y_pct_pa/100, r.return_10y_pct_pa==null?null:r.return_10y_pct_pa/100,
      r.return_proxy ? Object.entries(r.return_proxy).map(([k,v]) => k+": "+v).join(", ") : "", (m.holding_beta_asx200||{})[l.ticker] ?? "", r.consensus_label||"", q.verdict||"", (DATA.esg.review[l.ticker]||{}).band||"", (DATA.pds[l.ticker]||{}).url||""]; }));
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(hold), "Holdings");
  // Every tier for the same profile and stage, so the balance bands stay in the file.
  for (const t of DATA.tiers) { const req = x => x.profile_requested===state.profile || (x.requested_aliases||[]).includes(state.profile); const esgOf = x => !!(x.esg && x.esg.screened);
    const tp = DATA.portfolios.find(x => req(x) && x.life_stage===state.stage && x.tier===t.key && (x.implementation||"direct")===state.impl && esgOf(x)===state.esg) || DATA.portfolios.find(x => req(x) && x.life_stage===state.stage && x.tier===t.key && !esgOf(x));
    if (!tp) continue; const rows = [[`${label(DATA.tiers,t.key)} · model balance`, tp.balance], ["Ticker", "Holding", "Asset class", "Weight", "Dollars", "Units", "Yield"]].concat(tp.lines.map(l => [l.ticker, l.name, l.asset_class==="__sma__" ? "Diversified (managed)" : label(CLASSES, l.asset_class), l.weight_pct/100, l.dollars, l.units, l.yield_pct/100]));
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(rows), `Tier ${t.key}`.slice(0,31)); }
  XLSX.writeFile(wb, `portfolio_${pf.profile_used}_${pf.life_stage}_${Math.round(pf.balance)}.xlsx`);
};
sel("print").onclick = () => { sel("sheets").style.display = sel("print-sheets").checked ? "" : "none"; window.print(); };
window.addEventListener("afterprint", () => { sel("sheets").style.display = ""; });
sel("meta").textContent = DATA.meta;
if (Object.keys(DATA.quality||{}).length) sel("qlink").innerHTML = `Every holding has a written quality verdict (core, satellite, speculative, not recommended): shown on each fact sheet, and collected on the <a href="${FN ? "/quality.html" : (DATA.site_url ? DATA.site_url + "/quality.html" : "#")}">Holdings Quality Review</a> page.`;
if (DATA.banner) { sel("banner").querySelector(".wrap").textContent = DATA.banner; sel("banner").hidden = false; }
render();
wireEdit();
</script>
</body>
</html>
"""


STAGE_BLURBS = {
    "early_accumulation": "With decades before the money is needed, short-term falls are an opportunity to keep buying, so the rules allow the most aggressive mix.",
    "mid_accumulation": "There is still a long runway, but the balance is large enough that a bad year hurts, so the default steps down one notch and a small income tilt begins.",
    "pre_retirement": "Sequencing risk bites hardest in the years either side of retirement: a big fall just before drawdowns start cannot be recovered by future contributions, so the cap tightens and the cash buffer grows.",
    "retirement": "Income and stability matter more than growth now. The rules cap the profile at Balanced, hold a spending buffer in cash, and build the equity sleeves for franked income: Australian shares over international, grossed-up yield over price growth, and no holdings that pay nothing.",
}


def write_dashboard(path: Path, portfolios: list[Portfolio], profiles: Profiles, md: MarketData, view: TacticalView | None,
                    research: dict | None = None, universe: pd.DataFrame | None = None, review: list | None = None,
                    settings_site_url: str = "", quality: dict | None = None, platform_cfg: dict | None = None,
                    class_corr: dict | None = None, pds: dict | None = None, history: dict | None = None, esg: dict | None = None) -> Path:
    classes = [{"key": k, "label": v["label"], "kind": v["kind"]} for k, v in profiles.asset_classes.items()]
    colors = {c["key"]: f"--series-{i + 1}" for i, c in enumerate(classes)}
    light_vars = " ".join(f"--series-{i + 1}:{PALETTE_LIGHT[i % len(PALETTE_LIGHT)]};" for i in range(len(classes)))
    dark_vars = " ".join(f"--series-{i + 1}:{PALETTE_DARK[i % len(PALETTE_DARK)]};" for i in range(len(classes)))
    tactical = {"enabled": bool(view and view.enabled), "as_of": view.as_of if view else "",
                "max_tilt_pp": profiles.tactical.get("max_tilt_pp", 0),
                "max_growth_shift_pp": profiles.tactical.get("max_growth_shift_pp", profiles.tactical.get("max_tilt_pp", 0)),
                "hysteresis_pp": profiles.tactical.get("hysteresis_pp", 0),
                "signals": (view.to_dict()["signals"] if view else {})}
    growth = profiles.growth_classes
    saa = {k: {"growth": sum(v["saa"][c] for c in growth), "horizon": v.get("min_horizon_years", 5)} for k, v in profiles.risk_profiles.items()}
    stage_rules = {k: {"cash_floor_pp": v["cash_floor_pp"], "home_bias_pp": v["home_bias_pp"], "income_preference": v["income_preference"],
                       "min_equity_yield_pct": v.get("min_equity_yield_pct", 0), "blurb": STAGE_BLURBS.get(k, "")} for k, v in profiles.life_stages.items()}
    research_json = {t: dict(r.__dict__) for t, r in (research or {}).items()}
    tiers = sorted(profiles.balance_tiers.items(), key=lambda kv: kv[1]["order"])

    def split(lbl: str) -> tuple[str, str]:
        return (lbl.split(" (")[0], lbl.split(" (")[1].rstrip(")")) if " (" in lbl else (lbl, "")

    data = {
        "meta": f"Built {datetime.now():%d %B %Y %H:%M}. Prices as of {md.as_of.date()}; AUD/USD {1 / md.fx_aud_per_usd:.4f}. "
                f"Sources: {', '.join(sorted(set(md.source_by_ticker.values())))}. Rebuilt automatically each weekday evening.",
        "banner": "SYNTHETIC DATA: this page was built in offline test mode. Every number is a placeholder." if md.synthetic else "",
        "classes": classes, "colors": colors,
        "profiles": [{"key": k, "label": v["label"], "sub": f"{saa[k]['growth']:.0f}% growth"} for k, v in sorted(profiles.risk_profiles.items(), key=lambda kv: kv[1]["order"])],
        "stages": [{"key": k, "label": split(v["label"])[0], "sub": split(v["label"])[1]} for k, v in sorted(profiles.life_stages.items(), key=lambda kv: kv[1]["order"])],
        "tiers": [{"key": k, "label": split(v["label"])[0], "sub": split(v["label"])[1], "balance": v["representative_balance"], "min_balance": v["min_balance"],
                   "max_holdings": v["max_holdings"], "min_holding": v["min_holding_dollars"], "brokerage": v["brokerage_dollars"]} for k, v in tiers],
        "platform": platform_cfg or {}, "class_corr": class_corr or {}, "pds": pds or {},
        "defaults": {"profile": "balanced", "stage": "mid_accumulation", "tier": tiers[1][0] if len(tiers) > 1 else tiers[0][0]},
        "saa": saa, "stage_rules": stage_rules,
        "tactical": tactical, "research": research_json,
        "review": [r.__dict__ for r in (review or [])],
        "site_url": (settings_site_url or ""), "fx_aud_per_usd": md.fx_aud_per_usd, "fx_aud_per": md.fx_aud_per, "quality": quality or {},
        "search_index": _load_search_index(),
        "review_rules": {k: v for k, v in (profiles and {} or {}).items()},
        "diversification": getattr(profiles, "diversification", {}) or {},
        "sma": {"enabled": bool(profiles.sma.get("enabled")), "tiers": profiles.sma.get("tiers", []), "count_by_tier": profiles.sma.get("count_by_tier", {}),
                "min_track_record_years": profiles.sma.get("min_track_record_years", 0)},
        "portfolios": _compact_portfolios(portfolios),
        "returns": _daily_returns(md, universe, profiles),
        "history": history or {},
        "esg": {"enabled": bool(esg), "review": (esg or {}).get("review", {}), "shared_changes": _esg_shared_changes(portfolios), "bands": (esg or {}).get("bands", {}),
                "exclusions": {k: v.get("label", k) for k, v in (esg or {}).get("exclusions", {}).items()},
                "substitutions": (esg or {}).get("substitutions", {})},
    }
    html = (TEMPLATE.replace("__LIGHT_VARS__", light_vars).replace("__DARK_VARS__", dark_vars)
            .replace("__DATA__", json.dumps(_clean(data), default=str)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


def _compact_portfolios(portfolios: list[Portfolio]) -> list[dict]:
    """One object per portfolio id (a capped request reuses the built portfolio and is listed as an alias), ESG change
    lists stored once per implementation, and floats trimmed, to keep the page small."""
    out: dict[str, dict] = {}
    for pf in portfolios:
        d = pf.to_dict()
        if d["id"] in out:
            al = out[d["id"]].setdefault("requested_aliases", [])
            if d["profile_requested"] not in al and d["profile_requested"] != out[d["id"]]["profile_requested"]:
                al.append(d["profile_requested"])
            continue
        if d.get("esg", {}).get("screened") and d.get("implementation", "direct") == "direct":
            d["esg"] = {"screened": True, "shared_changes": True}
        out[d["id"]] = d
    return list(out.values())


def _esg_shared_changes(portfolios: list[Portfolio]) -> list[dict]:
    for pf in portfolios:
        if pf.esg.get("screened") and pf.implementation == "direct":
            return pf.esg.get("changes", [])
    return []


def _daily_returns(md: MarketData, universe: pd.DataFrame | None, profiles: Profiles) -> dict:
    """Last year of daily simple returns for every priced holding and the asset class proxy ETFs, so the page
    can recompute beta, correlation and volatility itself when holdings or weights change."""
    proxies = profiles.tactical.get("proxies", {})
    wanted = set(universe["ticker"]) if universe is not None else set()
    for ps in proxies.values():
        wanted |= set(ps)
    wanted |= {"VAS.AX", "VGS.AX"}
    cols = [t for t in wanted if t in md.prices.columns]
    if not cols:
        return {}
    rets = md.prices[cols].ffill().pct_change().iloc[-252:].fillna(0.0)
    series = {t: [round(float(v), 5) for v in rets[t]] for t in cols}
    if universe is not None and "twin" in universe.columns:   # unlisted funds borrow their listed twin's daily returns
        for t, tw in zip(universe["ticker"], universe["twin"]):
            if tw and t not in series and tw in series:
                series[t] = series[tw]
    return {"dates": [d.strftime("%Y-%m-%d") for d in rets.index],
            "series": series,
            "class_proxy": {c: next((t for t in ps if t in md.prices.columns), None) for c, ps in proxies.items()}}


def _load_search_index() -> list[dict]:
    from ..config import PROJECT_ROOT
    p = PROJECT_ROOT / "data" / "cache" / "search_index.json"
    if not p.exists():
        return []
    try:
        items = json.load(open(p)).get("items", [])
    except Exception:  # noqa: BLE001
        return []
    import html as _h
    return [{"s": i["symbol"], "n": _h.unescape(i["name"]), "e": i["exchange"], "t": i["type"], "c": i.get("sector", "")} for i in items]


def _clean(o):
    """Replace NaN with None recursively so the embedded JSON is valid."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return None if math.isnan(o) else (round(o, 4) if abs(o) < 1e6 else round(o, 2))
    return o
