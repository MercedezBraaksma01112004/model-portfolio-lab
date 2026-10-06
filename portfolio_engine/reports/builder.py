"""The portfolio builder page ("Build your own portfolio"). A visitor assembles a portfolio from any listed
holding (the engine's universe is offered first; anything else is fetched live through the site's
/history function), sets the weights, and sees fees, income, risk, diversification and a ten-year backtest
recalculate on the page. With accounts configured (Supabase), a signed-in visitor can save portfolios,
reopen them and share a read-only link."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..builder import Portfolio, fill_sector_region
from ..config import Profiles
from ..market_data import MarketData
from . import html as dash

TEMPLATE = r"""<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Build your own portfolio, Model Portfolio Lab</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Hanken+Grotesk:wght@400;500;600;700&display=swap">
<style>
__CSS__
#account { padding:22px 0 0; border-top:0; }
.mine:empty { display:none; }
#htable { min-width:1240px; }
.acct { display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; font-size:13.5px; }
.acct input { font:inherit; padding:7px 10px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); min-width:180px; }
.acct select { font:inherit; padding:7px 10px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); max-width:260px; }
.wrow input.w { width:84px; font:inherit; font-size:15px; padding:9px 9px; border:1.5px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); text-align:right; font-variant-numeric:tabular-nums; min-height:40px; }
.wrow input.w:focus { outline:2px solid var(--accent); outline-offset:1px; border-color:transparent; }
.wrow input.w.bad { border-color:var(--critical); }
.setup { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:14px; }
.setup label { display:block; font-size:12.5px; color:var(--muted); margin-bottom:4px; }
.setup input, .setup select { width:100%; font:inherit; font-size:15px; padding:11px 12px; border:1.5px solid var(--line); border-radius:10px; background:var(--bg); color:var(--text); min-height:46px; }
.setup input:focus, .setup select:focus { outline:2px solid var(--accent); outline-offset:1px; border-color:transparent; }
.total { font-variant-numeric:tabular-nums; font-weight:500; }
.total.bad { color:var(--critical); }
.chips { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0; }
.chips button { border:1.5px solid var(--line); background:var(--surface); color:var(--text); padding:7px 13px; border-radius:999px; font-size:13px; min-height:36px; }
.chips button:hover { border-color:var(--accent); }
.chips button[aria-pressed="true"] { background:var(--accent-soft); color:var(--text); border-color:var(--accent-line); }
.result { grid-template-columns: 1fr auto; }
.result .d { font-size:12px; color:var(--faint); }
.toast { position:fixed; bottom:18px; left:50%; transform:translateX(-50%); background:var(--text); color:var(--bg); padding:10px 16px; border-radius:10px; font-size:13.5px; display:none; z-index:20; max-width:90vw; }
.empty { padding:22px; text-align:center; color:var(--faint); border:1px dashed var(--line); border-radius:10px; }
.readonly { background:var(--accent-soft); padding:10px 14px; border-radius:10px; font-size:13.5px; margin-top:10px; }
.mine { display:grid; gap:6px; margin-top:8px; }
dialog.auth { border:1px solid var(--line); border-radius:14px; padding:0; width:min(440px, 92vw); background:var(--surface); color:var(--text); box-shadow:0 20px 60px rgba(0,0,0,.25); }
dialog.auth::backdrop { background:rgba(10,12,11,.45); }
.auth-head { display:flex; justify-content:space-between; align-items:center; padding:16px 20px 0; }
.auth-head h3 { margin:0;  font-size:19px; font-weight:600; }
.auth-close { border:0; background:transparent; font-size:22px; line-height:1; color:var(--faint); padding:4px 8px; border-radius:6px; }
.auth-close:hover { background:var(--surface-2); color:var(--text); }
.auth-tabs { display:flex; gap:4px; margin:14px 20px 0; border-bottom:1px solid var(--line); }
.auth-tabs button { border:0; background:transparent; padding:8px 10px; color:var(--muted); border-bottom:2px solid transparent; margin-bottom:-1px; font-weight:500; }
.auth-tabs button[aria-selected="true"] { color:var(--text); border-bottom-color:var(--accent); }
.auth-body { padding:16px 20px 20px; display:grid; gap:12px; }
.auth-body label { display:grid; gap:5px; font-size:13px; color:var(--muted); }
.auth-body input { font:inherit; padding:10px 12px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); width:100%; }
.auth-body input:focus { outline:2px solid var(--accent); outline-offset:1px; border-color:transparent; }
.pwrow { position:relative; }
.pwrow input { padding-right:64px; }
.pwrow button { position:absolute; right:6px; top:50%; transform:translateY(-50%); border:0; background:transparent; color:var(--accent); font-size:12.5px; font-weight:500; padding:4px 6px; }
.auth-msg { font-size:13.5px; padding:10px 12px; border-radius:8px; display:none; }
.auth-msg.err { display:block; background:var(--critical-bg); color:var(--critical); }
.auth-msg.ok { display:block; background:var(--good-bg); color:var(--good); }
.auth-msg.info { display:block; background:var(--accent-soft); color:var(--text); }
.auth-foot { font-size:12.5px; color:var(--faint); }
.auth-foot button { border:0; background:transparent; color:var(--accent); padding:0; font-size:12.5px; text-decoration:underline; }
.btn.wide { width:100%; padding:11px 14px; font-size:15px; }
.signed { display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; }
.avatar { display:inline-grid; place-items:center; width:30px; height:30px; border-radius:50%; background:var(--accent); color:var(--accent-ink); font-weight:600; font-size:13px; }
.mine .pend { display:grid; grid-template-columns:1fr auto auto auto; gap:10px; }
@media (max-width:700px) { .mine .pend { grid-template-columns:1fr; } }
.boa { display:grid; gap:12px; }
.boa-item { border:1px solid var(--line); border-radius:10px; padding:12px 14px; background:var(--surface); }
.boa-head { display:flex; flex-wrap:wrap; justify-content:space-between; gap:6px 12px; align-items:center; margin-bottom:8px; }
.boa-head b { font-size:14.5px; }
.boa-item textarea, #pnotes { width:100%; min-height:104px; font:inherit; font-size:14px; line-height:1.55; padding:10px 12px; border:1.5px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); resize:vertical; }
.boa-item textarea:focus, #pnotes:focus { outline:2px solid var(--accent); outline-offset:1px; border-color:transparent; }
.boa-state { font-size:12px; color:var(--faint); }
.boa-state.ai { color:var(--accent); font-weight:500; }
.asxbox { border-top:1px solid var(--line); margin-top:12px; padding-top:10px; }
.house-style { border:1px solid var(--line); border-radius:10px; padding:10px 14px; margin:12px 0 16px; background:var(--surface); }
.house-style summary { cursor:pointer; font-weight:600; font-size:14px; }
#hs-examples { width:100%; min-height:150px; font:inherit; font-size:13.5px; line-height:1.5; padding:10px 12px; border:1.5px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); resize:vertical; }
.sleeve { font-size:12px; color:var(--muted); }
.caveat { font-size:12.5px; margin:8px 0 0; padding:8px 12px; border-left:3px solid var(--accent); background:var(--accent-soft); border-radius:0 8px 8px 0; color:var(--text); }
.boa-state.custom { color:var(--good); font-weight:500; }
.platcmp td, .platcmp th { font-size:13px; }
.platcmp tr.on td { background:var(--accent-soft); font-weight:600; }
.btn[disabled] { opacity:.45; cursor:not-allowed; box-shadow:none; }
.custom-fee { display:none; }
.custom-fee.show { display:block; }
.setup select:disabled { opacity:.6; }
.subhead { font-size:14px; font-weight:700; color:var(--text); margin:20px 0 8px; }
.undo-group { display:inline-flex; gap:6px; padding-right:10px; margin-right:4px; border-right:1px solid var(--line); }
.find { display:grid; grid-template-columns:auto 1fr; gap:4px 12px; padding:12px 2px; border-bottom:1px solid var(--line); }
.find .sev { font-size:11.5px; font-weight:600; padding:3px 9px; border-radius:999px; height:fit-content; white-space:nowrap; }
.sev.high { background:var(--critical-bg); color:var(--critical); } .sev.medium { background:var(--serious-bg); color:var(--serious); } .sev.low { background:var(--neutral-bg); color:var(--neutral); } .sev.good { background:var(--good-bg); color:var(--good); }
.find b { font-size:14.5px; } .find .why { color:var(--muted); font-size:13.5px; margin-top:2px; } .find .acts { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; }
.ai { border:1px solid var(--line); border-radius:12px; padding:14px 16px; background:var(--surface); margin-top:12px; }
.ai h3 { margin:0 0 6px; font-size:16px; } .ai ul { margin:6px 0 0 18px; padding:0; } .ai li { margin:3px 0; }
.ai .sg { border-top:1px solid var(--line); padding:10px 0; } .ai .sg:first-of-type { border-top:0; }
.ai .lbl { font-size:13px; color:var(--muted); font-weight:600; margin-right:6px; }
</style>
</head>
<body>
<header><div class="wrap">
  <nav class="nav no-print"><a href="/">Model portfolios</a><a href="/builder.html" aria-current="page">Builder</a><a href="/compare.html">Compare</a><a href="/brief.html">Daily brief</a><a href="/quality.html">Quality review</a></nav>
  <h1>Portfolio builder</h1>
  <p class="lede">Start from a base portfolio, an Excel model or a blank page. Costs, income, risk and the check update as you change it.</p>
  <div class="meta" id="meta"></div>
  <div class="meta">Personal learning project. Illustrative only: not financial advice and not a recommendation to buy or sell anything. Past returns are history, not forecasts.</div>
</div></header>
<div class="banner" id="banner" hidden><div class="wrap"></div></div>
<main class="wrap">

<section id="account" class="no-print">
  <div class="eyebrow">Your account</div>
  <div class="acct" id="acct"></div>
  <div class="mine" id="mine"></div>
  <div class="mine" id="localmine"></div>
</section>

<section id="setup">
  <div class="eyebrow">Start here</div>
  <h2 id="ptitle">A new portfolio</h2>
  <div id="readonly" class="readonly" hidden></div>
  <div class="setup" style="margin-top:12px">
    <div><label for="pname">Portfolio name</label><input id="pname" type="text" placeholder="for example Growth with a franked income tilt" maxlength="80"></div>
    <div><label for="pbal">Balance invested ($)</label><input id="pbal" type="text" inputmode="numeric" value="250,000"></div>
    <div><label for="pref">Compare against the long-run target for</label><select id="pref"></select></div>
  </div>
  <div class="subhead">Start from a base portfolio</div>
  <div class="setup">
    <div><label for="bstage">Stage of life</label><select id="bstage"></select></div>
    <div><label for="bprof">Risk profile</label><select id="bprof"></select></div>
    <div style="display:flex;align-items:flex-end"><button class="btn" id="btn-load" type="button" style="min-height:46px;width:100%;justify-content:center">Load base portfolio</button></div>
  </div>
  <p class="muted" id="bnote" style="font-size:12.5px;margin:6px 0 0"></p>
  <div class="subhead">Or import a model you already have</div>
  <div class="setup">
    <div><label for="impfile">Excel workbook or CSV</label><input id="impfile" type="file" accept=".xlsx,.xls,.xlsm,.csv" style="padding:9px 10px"></div>
    <div><label for="impsheet">Sheet</label><select id="impsheet" disabled><option>Choose a file first</option></select></div>
    <div style="display:flex;align-items:flex-end"><button class="btn" id="btn-import" type="button" style="min-height:46px;width:100%;justify-content:center" disabled>Import this sheet</button></div>
  </div>
  <p class="muted" id="impnote" style="font-size:12.5px;margin:6px 0 0">Any sheet with a column of codes (ASX codes, tickers or HUB24 codes) and a column of weights, dollar values or units. Section headings such as "Australian equities" set the asset class. Everything is priced at today's prices; the file never leaves your browser.</p>
  <div class="subhead">Platform</div>
  <div class="setup">
    <div><label for="plat">Platform</label><select id="plat"></select></div>
    <div><label for="pacct">Account type</label><select id="pacct"></select></div>
    <div><label for="pmenu">Investment menu</label><select id="pmenu"></select></div>
    <div class="custom-fee" id="pcustom-a"><label for="pcpct">Administration fee (% a year)</label><input id="pcpct" type="text" inputmode="decimal" placeholder="for example 0.25"></div>
    <div class="custom-fee" id="pcustom-b"><label for="pcfix">Fixed fees ($ a year)</label><input id="pcfix" type="text" inputmode="numeric" placeholder="for example 300"></div>
  </div>
  <p class="muted" id="pnote" style="font-size:12.5px;margin:6px 0 0"></p>
  <div class="toolbar">
    <span class="undo-group"><button class="btn" id="btn-undo" type="button" title="Undo the last change (Ctrl or Cmd + Z)" disabled>&#8630; Undo</button><button class="btn" id="btn-redo" type="button" title="Redo (Ctrl or Cmd + Shift + Z)" disabled>&#8631; Redo</button></span>
    <button class="btn primary" id="btn-save" type="button">Save</button>
    <button class="btn" id="btn-saveas" type="button">Save as a copy</button>
    <button class="btn" id="btn-share" type="button">Share link</button>
    <button class="btn" id="btn-new" type="button">New blank portfolio</button>
    <button class="btn" id="btn-xlsx" type="button">Download as Excel</button>
    <button class="btn" id="btn-print" type="button">Print</button>
    <a class="btn" id="btn-super" href="/compare.html#super" style="text-decoration:none">Compare with super funds</a>
    <span class="muted" id="savenote" style="font-size:12.5px"></span>
  </div>
</section>

<section id="holdings-section">
  <div class="eyebrow">Holdings</div>
  <h2>What is in it</h2>
  <div class="toolbar" style="margin-top:4px">
    <span>Total weight: <span class="total" id="total">0.0%</span></span>
    <button class="btn small" id="btn-norm" type="button">Scale to 100%</button>
    <button class="btn small" id="btn-equal" type="button">Equal weight</button>
    <button class="btn small" id="btn-cash" type="button">Fill the gap with cash</button>
    <button class="btn small" id="btn-rules" type="button" title="Weights the way the engine would: by the holdings' weight hints, held to the diversification caps">Weight like the engine</button>
  </div>
  <div id="holdings-empty" class="empty">Nothing here yet. Add holdings below, or start from a model portfolio above.</div>
  <div class="tscroll"><table id="htable" class="htable" hidden><thead><tr><th>Holding</th><th>Asset class</th><th>Sector, region</th><th class="num">Weight %</th><th class="num">Dollars</th><th class="num">Units</th><th class="num">Price (AUD)</th><th>Last 12 months</th><th class="num">1y</th><th class="num">3y pa</th><th class="num">5y pa</th><th class="num">10y pa</th><th class="num">Yield</th><th class="num">Cost</th><th>Analyst view</th><th class="no-print"></th></tr></thead><tbody id="holdings"></tbody></table></div>
  <div id="sheet" class="sheet no-print" hidden></div>
  <div class="edit no-print" style="margin-top:18px">
    <div class="eyebrow">Add a holding</div>
    <div class="editrow"><input id="q" type="search" placeholder="Search any listed share, ETF or fund: BHP, Vanguard, Apple, Schneider, Lundin" autocomplete="off"></div>
    <div class="chips" id="filters"></div>
    <div id="results"></div>
    <p class="muted" style="font-size:12.5px;margin:8px 0 0">Holdings from the engine's universe (<span id="ucount"></span> names) carry research, written quality verdicts and ten years of history. Anything else is fetched live from the price feed when you add it: price, dividends, ten years of monthly history and a year of daily prices, so every figure below still works. Hover the chips for the reason behind a verdict.</p>
  </div>
</section>

<section id="summary">
  <div class="eyebrow">At a glance</div>
  <h2 id="title">Summary</h2>
  <div class="tiles" id="tiles"></div>
  <div class="tiles" id="rtiles" style="margin-top:12px"></div>
  <p class="muted" style="font-size:12.5px;margin:8px 0 0">Weighted returns are the weight-times-return average of the holdings, the way a model spreadsheet does it. A holding younger than the period uses its asset class index ETF as a stand-in (marked †). Platform fees use the rate card of the platform, account type and menu chosen above.</p>
  <div id="warnings" style="margin-top:10px"></div>
  <div class="subhead">Platform cost at this balance</div>
  <div class="tscroll"><table class="platcmp"><thead><tr><th>Platform</th><th>Menu</th><th class="num">Administration</th><th class="num">Other platform fees</th><th class="num">Total a year</th><th class="num">% a year</th><th>Rate card</th></tr></thead><tbody id="platcmp"></tbody></table></div>
  <p class="muted" id="platnote" style="font-size:12.5px;margin:6px 0 0"></p>
  <p class="caveat" id="platcaveat"><b>Your selected investments may not be available on every platform.</b> Each platform has its own investment menu, and unlisted funds, international shares, listed notes and exchange-traded bonds are the most likely to be missing. These figures compare administration costs only; check each holding against the platform's menu before relying on them.</p>
</section>

<section id="check" hidden>
  <div class="eyebrow">Review</div>
  <h2>Check this portfolio</h2>
  <p class="sub">The page's own rules look for gaps against the target allocation, concentration, cost, overlap, analyst warnings and platform savings, and say why each matters. Buttons make the change for you, and Undo takes it back. The AI review reads everything here and writes its own suggestions with reasons.</p>
  <div id="checklist"></div>
  <div class="toolbar"><button class="btn primary" id="btn-ai" type="button">Ask AI for a review</button><span class="muted" id="ainote" style="font-size:12.5px"></span></div>
  <div id="airesult"></div>
</section>

<div class="two">
  <section>
    <div class="eyebrow">Allocation</div>
    <h2>Growth and defensive mix</h2>
    <div class="stack" id="stack"></div>
    <div class="legend" id="legend"></div>
    <div class="tscroll"><table style="margin-top:12px"><thead><tr><th>Asset class</th><th class="num">Yours</th><th class="num">Target</th><th class="num">Difference</th><th class="num">Dollars</th></tr></thead><tbody id="alloc"></tbody></table></div>
    <p class="muted" id="allocnote" style="font-size:12.5px;margin:8px 0 0"></p>
  </section>
  <section id="diversification">
    <div class="eyebrow">Spread</div>
    <h2>How spread out it is</h2>
    <div class="tiles" id="divtiles"></div>
    <div style="margin-top:12px"><div class="eyebrow">By sector</div><div class="dstack" id="secstack"></div><div class="dlegend" id="seclegend"></div></div>
    <div style="margin-top:12px"><div class="eyebrow">By country or region</div><div class="dstack" id="regstack"></div><div class="dlegend" id="reglegend"></div></div>
    <div id="divflags" style="margin-top:8px"></div>
  </section>
</div>

<section id="backtest">
  <div class="eyebrow">History</div>
  <h2 id="bt-title">If this balance had been invested ten years ago</h2>
  <p class="sub">Constant mix: today's weights held for the whole window and rebalanced monthly, dividends reinvested, before fees and tax. History, not a forecast.</p>
  <div class="tiles" id="bttiles"></div>
  <div class="btchart" id="btchart"></div>
  <div class="legend" id="btlegend"></div>
  <p class="muted" id="btnote" style="font-size:12.5px;margin:8px 0 0"></p>
</section>

<section id="risk">
  <div class="eyebrow">Risk</div>
  <h2>How it moves</h2>
  <p class="sub">From the last year of daily prices, every holding in its own currency. Beta is how far the portfolio has moved for a 1% move in the market; correlation is how closely it tracks.</p>
  <div class="tiles" id="risktiles"></div>
  <div class="eyebrow" style="margin-top:14px">Beta to the ASX 200 by holding</div>
  <div id="betalist" class="betalist"></div>
</section>

<section id="boa-section" hidden>
  <div class="eyebrow">Basis of advice</div>
  <h2>Why each holding is here</h2>
  <p class="sub">Every holding gets a draft the moment it is added, set out the way a Statement of Advice sets out a recommendation: why it is recommended, its advantages, and other things to consider. It is written from the holding's own facts (role, cost, income, structure and risks), never past returns. The draft keeps up with the weights until you edit it; from then on your words are kept. Both are saved with the portfolio and go into the Excel download. A draft is a starting point: for a client it has to say why the holding suits that client's objectives, circumstances and existing investments.</p>
  <details class="house-style" id="hs-wrap"><summary>House style: write the drafts the way your Statements of Advice do</summary>
    <p class="muted" style="font-size:13px;margin:8px 0">Paste two to five basis of advice passages you have already written, with client names and figures removed. "Write with AI in house style" then drafts every holding in the same structure, headings, tone and length. The examples are kept in this browser and saved with the portfolio. Nothing is sent anywhere until you press the button (signed-in accounts only; it uses one of the day's AI reviews).</p>
    <textarea id="hs-examples" placeholder="Paste your own written examples here. For example the investment recommendations section of a Statement of Advice: the paragraph for one share, one fund and one defensive holding."></textarea>
    <div class="toolbar"><button class="btn primary" id="btn-boa-ai" type="button">Write every draft with AI in house style</button><label style="display:inline-flex;gap:6px;align-items:center;font-size:13px"><input type="checkbox" id="hs-keep" checked> Leave the ones I have written alone</label><span class="muted" id="boa-ai-note" style="font-size:12.5px"></span></div>
  </details>
  <label for="pnotes" class="subhead" style="display:block">Portfolio rationale</label>
  <textarea id="pnotes" placeholder="The strategy in your words: the objective, why this mix, what it is measured against and when it will be reviewed."></textarea>
  <div class="subhead">By holding</div>
  <div class="boa" id="boa"></div>
</section>

<section id="glossary" class="no-print">
  <div class="eyebrow">Reading the page</div>
  <h2>How the figures are worked out</h2>
  <details><summary>Where the data comes from</summary><p>Holdings in the engine's universe use the daily build's prices, dividend-adjusted returns and Yahoo Finance analyst consensus. Anything you add from outside it is fetched from the same price feed when you add it, converted to Australian dollars at today's rate for the price and at each month's rate for the history. Unlisted managed funds and term deposits in the engine's universe carry the manager's unit price and a listed stand-in for risk. ASX listings with no price history (listed notes, exchange-traded bonds) are priced from the ASX, with their asset class index standing in for risk and history.</p></details>
  <details><summary>Fees</summary><p>The cost per year is the weighted management cost of the funds plus the platform's fees for the account type and menu chosen: the tiered administration fee (with its minimum and cap), fixed account fees, expense recovery and other percentage levies, and any fee per listed holding. "Cheapest menu that fits" picks the lowest-cost menu that can hold every investment in the portfolio. Each platform's rate card is dated and linked in the comparison table; rates change, so check the current fee document before quoting a client. Brokerage is a one-off cost and is not in the running cost.</p></details>
  <details><summary>Importing, the portfolio check and the AI review</summary><p>Import reads any sheet with a column of codes (ASX codes, tickers or HUB24 codes) and a column of weights, dollar values or units; section headings such as "Australian equities" set the asset class. It is read in your browser. It understands ASX codes, tickers, exchange suffixes such as PANW.NAS, GTT.PAR, LUN.TSX and YLDX.CXA, prefixes such as NASDAQ:PANW, Bloomberg codes such as PANW US, APIR codes, HUB24 codes, CMA and TERM, and two or more portfolios set side by side on one sheet. A holding with no price feed (an unlisted fund outside the universe, a term deposit) is kept at the sheet's weight with the sheet's yield and fee, and the note lists which ones. Nothing is dropped without being listed. The portfolio check applies fixed rules and explains each finding; its buttons make the change and Undo reverses it. The AI review sends the portfolio's figures (not your name or account details) to Anthropic's Claude model and returns suggestions with reasons. It is limited per account each day, it can be wrong, and it is general information for checking your own thinking, not advice.</p></details>
  <details><summary>Undo, saving and drafts</summary><p>Undo and redo step back and forward through every change on the page: weights, holdings added or removed, base portfolios loaded, balance, platform and the basis of advice text (Ctrl or Cmd + Z, and Ctrl or Cmd + Shift + Z). Signed in, Save stores the portfolio in your account. Signed out, or if your account cannot be reached, Save keeps it in this browser instead, listed under Your account, and you can move it to your account later.</p></details>
  <details><summary>Diversification</summary><p>"Effective holdings" is one divided by the sum of squared weights: ten equal holdings score 10, while one 90% holding and nine 1% holdings score about 1.2. Sector and region look through to what each holding actually is; a world index fund is one line but hundreds of companies, so it is shown as a diversified fund rather than a sector.</p></details>
  <details><summary>Saving and sharing</summary><p>Saved portfolios live in your account only. A share link shows a read-only copy to anyone who has it; turn sharing off from the same button and the link stops working.</p></details>
</section>

</main>
<dialog class="auth" id="authdlg">
  <div class="auth-head"><h3 id="auth-title">Sign in</h3><button type="button" class="auth-close" id="auth-close" aria-label="Close">×</button></div>
  <div class="auth-tabs" role="tablist" id="auth-tabs"><button type="button" role="tab" data-mode="signin">Sign in</button><button type="button" role="tab" data-mode="signup">Create account</button><button type="button" role="tab" data-mode="link">Email me a link</button></div>
  <form class="auth-body" id="auth-form" novalidate>
    <label>Email<input id="au-email" type="email" autocomplete="email" placeholder="you@example.com" required></label>
    <label id="au-pw-wrap">Password<span class="pwrow"><input id="au-pw" type="password" autocomplete="current-password" placeholder="At least 8 characters" minlength="8"><button type="button" id="au-show">Show</button></span></label>
    <div class="auth-msg" id="au-msg"></div>
    <button class="btn primary wide" id="au-submit" type="submit">Sign in</button>
    <div class="auth-foot" id="au-foot"></div>
  </form>
</dialog>
<dialog class="auth" id="resetdlg">
  <div class="auth-head"><h3>Choose a new password</h3><button type="button" class="auth-close" id="reset-close" aria-label="Close">×</button></div>
  <form class="auth-body" id="reset-form" novalidate>
    <label>New password<span class="pwrow"><input id="rs-pw" type="password" autocomplete="new-password" placeholder="At least 8 characters" minlength="8"><button type="button" id="rs-show">Show</button></span></label>
    <div class="auth-msg" id="rs-msg"></div>
    <button class="btn primary wide" type="submit">Save password</button>
  </form>
</dialog>
<div class="tip" id="tip"></div>
<div class="toast" id="toast"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js"></script>
<script>
const DATA = __DATA__;
const VEHICLE = { etf: "ETF", lic: "listed investment company", direct: "share", fund: "managed fund", cash: "cash", sma: "managed portfolio", hybrid: "hybrid", note: "listed note", bond: "exchange-traded bond", td: "term deposit" };
const CLASSES = DATA.classes, COLORS = DATA.colors, R = DATA.research, U = DATA.universe;
const UMAP = Object.fromEntries(U.map(u => [u.ticker, u]));
const fmtP = (x, d=1) => (x==null||isNaN(x)) ? "–" : x.toFixed(d) + "%";
const fmtS = (x, d=1) => (x==null||isNaN(x)) ? "–" : (x>0?"+":"") + x.toFixed(d) + "%";
const fmtM = x => (x==null||isNaN(x)) ? "–" : "$" + Math.round(x).toLocaleString("en-AU");
const fmtN = x => (x==null||isNaN(x)) ? "–" : (Number.isInteger(x) ? x.toLocaleString("en-AU") : x.toFixed(2));
const cssColor = k => getComputedStyle(document.documentElement).getPropertyValue(COLORS[k]).trim();
const sel = id => document.getElementById(id);
const label = (list, key) => (list.find(x => x.key===key) || {}).label || key;
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
const FN = (() => { const h = location.hostname; if (h.endsWith("netlify.app") || (DATA.site_url && location.origin === DATA.site_url)) return "/.netlify/functions"; return null; })();
const tip = sel("tip");
function showTip(e, html){ tip.innerHTML = html; tip.style.display="block"; moveTip(e); }
function moveTip(e){ tip.style.left = (e.clientX+12)+"px"; tip.style.top = (e.clientY+12)+"px"; }
function hideTip(){ tip.style.display="none"; }
let toastT; function toast(msg){ const t = sel("toast"); t.textContent = msg; t.style.display = "block"; clearTimeout(toastT); toastT = setTimeout(() => t.style.display = "none", 3200); }

// ------------------------------------------------------------ state
const DEFAULT_PLATFORM = () => ({ key: DATA.default_platform || Object.keys(DATA.platforms || {})[0] || "custom", account: "super", menu: "auto", custom_pct: null, custom_fixed: null });
const state = { id: null, name: "", balance: 250000, ref: "balanced", lines: [], isPublic: false, readOnly: false, ownerId: null, ticker: null, dirty: false, platform: DEFAULT_PLATFORM(), notes: "" };
const user = { session: null };
const EXTRA = {};   // ticker -> {daily:{dates,returns}, monthly:{months,returns}} fetched live for holdings outside the universe
const HS = { text: "" };   // house style basis of advice examples (this browser, the saved portfolio, or config/boa_examples.md)

function lineFromUniverse(u){
  const r = R[u.ticker] || {};
  return { ticker: u.ticker, name: u.name, asset_class: u.asset_class, vehicle: u.vehicle, role: u.role, currency: u.currency, mer_pct: +u.mer || 0,
    yield_pct: r.dividend_yield_pct != null ? r.dividend_yield_pct : (+u.yield || 0), yield_source: r.dividend_yield_pct != null ? "live" : "config",
    franking_pct: +u.franking || 0, sector: u.sector || "", region: u.region || "", price_aud: u.price_aud, priced_from: (u.twin || u.manual) ? "manual" : (u.price_aud == null ? "unpriced" : "feed"),
    weight_pct: 0, source: "universe", liquidity: u.liquidity || "", boa: "", boa_custom: false };
}
function guessClass(sym, name, sector){
  if (sector && CLASSES.some(c => c.key === sector)) return sector;
  const sec = (sector||"").toLowerCase(), n = (name||"").toLowerCase();
  if (/real estate|reit/.test(sec) || /utilities|transportation/.test(sec)) return "infrastructure";
  if (/bond|fixed|treasury|government/.test(n)) return "fixed_income"; if (/credit|hybrid|subordinated|floating|capital notes/.test(n)) return "credit";
  if (/property|reit|infrastructure|real estate|toll|airport/.test(n)) return "infrastructure"; if (/gold|commodit|private equity|alternative/.test(n)) return "alternatives";
  if (/cash|high interest/.test(n)) return "cash";
  return (sym.endsWith(".AX") || sym.endsWith(".XA")) ? (/international|global|world|s&p 500|nasdaq|emerging|asia|us /.test(n) ? "intl_equity" : "aus_equity") : "intl_equity";
}
function guessRegion(sym, name){
  const n = (name||"").toLowerCase();
  if (sym.endsWith(".AX") || sym.endsWith(".XA")) { if (/ex-us|ex us/.test(n)) return "Global ex US"; if (/asia/.test(n)) return "Asia"; if (/emerging/.test(n)) return "Emerging markets";
    if (/nasdaq|s&p 500| us |u\.s\./.test(" " + n + " ")) return "United States"; if (/international|global|world/.test(n)) return "Global"; return "Australia"; }
  if (/\.(PA|MI|DE|AS|MC|BR|SW)$/.test(sym)) return "Europe"; if (/\.(TO|V)$/.test(sym)) return "Canada"; if (sym.endsWith(".L")) return "United Kingdom"; if (sym.endsWith(".NZ")) return "New Zealand";
  if (/\.(HK|T|SI)$/.test(sym)) return "Asia"; return "United States";
}
const SECTOR_GROUPS = [["food","Consumer staples"],["beverage","Consumer staples"],["household","Consumer staples"],["consumer staples","Consumer staples"],["consumer defensive","Consumer staples"],
  ["consumer discretionary","Consumer discretionary"],["consumer cyclical","Consumer discretionary"],["retail","Consumer discretionary"],["automobile","Consumer discretionary"],["consumer durables","Consumer discretionary"],["consumer services","Consumer discretionary"],
  ["bank","Financials"],["financial","Financials"],["insurance","Financials"],["materials","Materials"],["energy","Energy"],["health","Healthcare"],["pharma","Healthcare"],
  ["software","Technology"],["technology","Technology"],["semiconductor","Technology"],["media","Communication"],["telecommunication","Communication"],["communication","Communication"],
  ["capital goods","Industrials"],["transportation","Industrials"],["commercial","Industrials"],["industrial","Industrials"],["utilities","Utilities"],["real estate","Real estate"]];
function sectorFromIndex(sector, type){ if (type === "ETF") return "Diversified fund"; const s = (sector || "").toLowerCase(); for (const [k, g] of SECTOR_GROUPS) if (s.includes(k)) return g; return "Other"; }

async function api(path){ if (!FN) throw new Error("Live lookups only work on the published site"); const r = await fetch(FN + path); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || r.statusText); return j; }
async function addSymbol(symbol, cls, meta){
  if (state.lines.some(l => l.ticker === symbol)) { toast(symbol + " is already in the portfolio"); return; }
  if (UMAP[symbol]) { const l = lineFromUniverse(UMAP[symbol]); if (cls) l.asset_class = cls; pushLine(l); return; }
  toast("Fetching " + symbol + "…");
  try { pushLine(await fetchLiveLine(symbol, cls, meta)); } catch (e) { toast(e.message); }
}
// A holding from outside the universe: the daily build's pre-computed listing file, or the live price feed.
async function fetchLiveLine(symbol, cls, meta){
  let h = null;
  try { const r = await fetch("/data/listings/" + encodeURIComponent(symbol) + ".json", { cache: "no-cache" }); if (r.ok) h = await r.json(); } catch(e) {}
  if (!h) { try { h = await api("/history?symbol=" + encodeURIComponent(symbol)); } catch(e) { throw new Error("No data for " + symbol + ": " + e.message + ". Only listings in the search index are available offline."); } }
  const fx = DATA.fx_aud_per || {}; const rate = h.currency === "AUD" ? 1 : (fx[h.currency] || null);
  if (rate == null) throw new Error("No exchange rate for " + h.currency + "; cannot price " + symbol);
  const vehicle = (h.type === "ETF" || (meta && meta.type === "ETF")) ? "etf" : "direct";
  const sector = vehicle === "etf" ? "Diversified fund" : (h.sector_group || sectorFromIndex((meta && meta.sector) || h.sector, h.type));
  R[symbol] = { ticker: symbol, name: h.name, sparkline: h.spark || [], return_1y_pct: h.return_1y_pct, return_3y_pct_pa: h.return_3y_pct_pa, return_5y_pct_pa: h.return_5y_pct_pa, return_10y_pct_pa: h.return_10y_pct_pa,
    history_years: h.history_years, dividend_yield_pct: h.yield_pct, price: h.price, price_currency: h.currency, volatility_1y_pct: h.volatility_1y_pct, max_drawdown_1y_pct: h.max_drawdown_1y_pct,
    source: h.built ? "price feed (daily build)" : "price feed (live)", consensus_label: "no coverage", return_proxy: {}, sector: (meta && meta.sector) || h.sector || "", fetched: h.built || new Date().toISOString().slice(0,10) };
  EXTRA[symbol] = { daily: h.daily, monthly: h.monthly };
  return { ticker: symbol, name: h.name, asset_class: cls || guessClass(symbol, h.name, meta && meta.sector), vehicle, role: "satellite", currency: h.currency, mer_pct: vehicle === "etf" ? 0.2 : 0,
    yield_pct: h.yield_pct || 0, yield_source: "live", franking_pct: 0, sector, region: guessRegion(symbol, h.name), price_aud: h.price * rate, priced_from: "live", weight_pct: 0, source: "live", boa: "", boa_custom: false };
}
function pushLine(l){ state.lines.push(l); state.ticker = l.ticker; state.dirty = true; sel("q").value = ""; sel("results").innerHTML = ""; render(); toast(l.name + " added at 0%: set its weight in the table"); }
function removeLine(t){ state.lines = state.lines.filter(l => l.ticker !== t); if (state.ticker === t) state.ticker = null; state.dirty = true; render(); }

// ------------------------------------------------------------ calculations
function tierFor(bal){ let t = DATA.tiers[0].key; for (const x of DATA.tiers) if (bal >= x.min_balance) t = x.key; return t; }
// ------------------------------------------------------------ platforms
// Every platform in config/platforms.yaml: per account type (super, investment) a set of investment menus, each with a
// tiered administration fee (marginal bands, or one rate for the whole balance), a minimum and a cap, fixed dollar fees,
// percentage fees with caps (expense recovery, levies) and an optional fee per listed holding.
const PLAT = DATA.platforms || {};
const isListed = l => l.vehicle !== "cash" && l.vehicle !== "td" && (l.priced_from !== "manual" || l.listed === true);
function tieredFee(menu, bal){ const bands = menu.bands || []; let fee = 0;
  if (menu.tiering === "whole_balance") { const b = bands.find(x => x.up_to == null || bal <= x.up_to) || bands[bands.length - 1]; fee = b ? bal * b.rate : 0; }
  else { let lower = 0; for (const b of bands) { const upper = b.up_to == null ? Infinity : b.up_to; fee += Math.max(0, Math.min(bal, upper) - lower) * b.rate; lower = upper; if (bal <= upper) break; } }
  if (menu.min_admin_fee && !menu.min_includes_fixed) fee = Math.max(fee, +menu.min_admin_fee); if (menu.max_admin_fee != null) fee = Math.min(fee, +menu.max_admin_fee); return fee; }
function menuCost(menu, bal, nListed, intlValue){ let admin = tieredFee(menu, bal);
  const fixed = (menu.fixed_fees || []).reduce((s, f) => s + (+f.amount || 0), 0);
  if (menu.min_includes_fixed && menu.min_admin_fee) admin += Math.max(0, +menu.min_admin_fee - (admin + fixed));   // the minimum covers the tiered and fixed parts together
  const pct = (menu.percent_fees || []).reduce((s, f) => s + Math.min(bal * (+f.rate || 0), f.cap == null ? Infinity : +f.cap), 0);
  const per = (+menu.per_listed_holding_fee || 0) * nListed + (+menu.intl_listed_rate || 0) * (intlValue || 0);
  return { admin, other: fixed + pct + per, total: admin + fixed + pct + per }; }
function accountOf(p, acctKey){ return p.accounts[acctKey] ? [acctKey, p.accounts[acctKey]] : Object.entries(p.accounts)[0]; }
function chooseMenu(acct, bal, hasListed, nListed, wanted, intlValue){ const all = acct.menus || {};
  if (wanted && wanted !== "auto" && all[wanted]) return wanted;
  const ok = Object.entries(all).filter(([k, m]) => (!hasListed || m.allows_listed !== false) && (m.max_balance == null || bal <= m.max_balance));
  const pool = ok.length ? ok : Object.entries(all);
  pool.sort((a, b) => menuCost(a[1], bal, nListed, intlValue).total - menuCost(b[1], bal, nListed, intlValue).total); return pool.length ? pool[0][0] : null; }
const isManual = key => key === "custom" || !PLAT[key] || !!PLAT[key].manual_rate;
function platformCost(bal, lines, choice){ const c = choice || state.platform; const nListed = lines.filter(isListed).length, hasListed = nListed > 0;
  const intlValue = lines.filter(l => isListed(l) && l.currency && l.currency !== "AUD").reduce((s, l) => s + (l.dollars || 0), 0);
  if (isManual(c.key)) { const p = PLAT[c.key] || null; const entered = c.custom_pct != null || c.custom_fixed != null; const rate = (parseFloat(c.custom_pct) || 0) / 100, fixed = parseFloat(c.custom_fixed) || 0;
    const [ak, acct] = p ? accountOf(p, c.account) : ["", {}]; const m = p ? Object.values(acct.menus || {})[0] || {} : {};
    return { key: p ? c.key : "custom", label: p ? p.label : "Your own rate", product: p ? (acct.product || p.label) : "Entered rate", account: ak, accountLabel: p ? (acct.label || ak) : "", menu: "manual", menuLabel: p ? (m.label || "Entered rate") : "Entered rate",
      admin: bal * rate, other: fixed, total: bal * rate + fixed, verified: true, manual: true, entered, brokerage: null, notes: p ? (m.notes || "") : "", source: p ? (acct.source || "") : "", source_url: p ? (acct.source_url || "") : "", as_of: p ? (acct.as_of || "") : "", auto: false, listedBlocked: false }; }
  const p = PLAT[c.key]; const [ak, acct] = accountOf(p, c.account); const mk = chooseMenu(acct, bal, hasListed, nListed, c.menu, intlValue); const m = acct.menus[mk]; const cost = menuCost(m, bal, nListed, intlValue);
  return { key: c.key, label: p.label, product: acct.product || p.label, account: ak, accountLabel: acct.label || ak, menu: mk, menuLabel: m.label || mk, auto: !c.menu || c.menu === "auto", ...cost,
    verified: m.verified !== false && acct.verified !== false && p.verified !== false, brokerage: m.brokerage || acct.brokerage || p.brokerage || null, notes: m.notes || "",
    source: acct.source || p.source || "", source_url: acct.source_url || p.source_url || "", as_of: acct.as_of || p.as_of || "", listedBlocked: hasListed && m.allows_listed === false }; }
function brokerageFor(lines, pc, T){ const listed = lines.filter(l => isListed(l) && (l.weight_pct || 0) > 0);
  if (pc && pc.brokerage && pc.brokerage.rate != null) return listed.reduce((s, l) => s + Math.min(pc.brokerage.max == null ? Infinity : +pc.brokerage.max, Math.max(+pc.brokerage.min || 0, (l.dollars || 0) * pc.brokerage.rate)), 0);
  return listed.length * (T.brokerage || 0); }
function dailySeries(l){
  const R0 = DATA.returns || {}; if (l.vehicle === "cash") return null;
  if (R0.series && R0.series[l.ticker]) return R0.series[l.ticker];
  if (l.priced_from === "manual") return null;
  const ex = EXTRA[l.ticker]; if (ex && ex.daily && ex.daily.returns.length >= 60) { // align to the embedded calendar by date
    const map = {}; ex.daily.dates.forEach((d, i) => map[d] = ex.daily.returns[i]); return R0.dates.map(d => map[d] ?? 0); }
  const px = (R0.class_proxy||{})[l.asset_class]; return px && R0.series && R0.series[px] ? R0.series[px] : null; }
function monthlySeries(l){
  const H = DATA.history || {}; if (!H.months) return null;
  if (H.series && H.series[l.ticker]) return { sr: H.series[l.ticker], key: l.ticker, standIn: H.stand_in && H.stand_in[l.ticker], standMonths: (H.stand_in_months||{})[l.ticker] || 0 };
  const ex = EXTRA[l.ticker]; if (ex && ex.monthly && ex.monthly.returns.length >= 3) { const map = {}; ex.monthly.months.forEach((m, i) => map[m] = ex.monthly.returns[i]);
    const cp = (H.class_proxy||{})[l.asset_class]; const proxy = cp && H.series[cp]; let stand = 0;
    const sr = H.months.map((m, i) => { if (map[m] != null) return map[m]; stand++; return proxy ? proxy[i] : 0; });
    return { sr, key: l.ticker, standIn: stand ? cp : null, standMonths: stand }; }
  if (l.vehicle === "cash") return null;
  const cp = (H.class_proxy||{})[l.asset_class]; return cp && H.series[cp] ? { sr: H.series[cp], key: cp, standIn: cp, standMonths: H.months.length, whole: true } : null; }
function compute(){
  const bal = state.balance; const lines = state.lines; const tier = tierFor(bal); const T = DATA.tiers.find(t => t.key === tier) || {};
  const total = lines.reduce((s, l) => s + (l.weight_pct || 0), 0);
  for (const l of lines) { const d = (l.weight_pct || 0) / 100 * bal; if (l.price_aud && l.vehicle !== "cash") { l.units = Math.floor(d / l.price_aud); l.dollars = l.units * l.price_aud; } else { l.dollars = d; l.units = l.price_aud ? d / l.price_aud : null; } }
  const W = l => (l.weight_pct || 0) / 100;
  const m = {}; m.holdings = lines.length; m.total_weight = total;
  const cw = {}; lines.forEach(l => cw[l.asset_class] = (cw[l.asset_class]||0) + (l.weight_pct||0));
  m.growth_pct = CLASSES.filter(c => c.kind === "growth").reduce((s, c) => s + (cw[c.key]||0), 0); m.defensive_pct = total - m.growth_pct;
  m.weighted_mer_pct = lines.reduce((s, l) => s + W(l) * (l.mer_pct||0), 0);
  m.weighted_yield_pct = lines.reduce((s, l) => s + W(l) * (l.yield_pct||0), 0);
  const credits = lines.reduce((s, l) => s + W(l) * (l.yield_pct||0) * (l.franking_pct||0) / 100 * (30/70), 0);
  m.grossed_up_yield_pct = m.weighted_yield_pct + credits; m.franking_credits_per_year = credits / 100 * bal; m.income_per_year = m.weighted_yield_pct / 100 * bal;
  const pc = platformCost(bal, lines); m.platform = pc; m.platform_menu = pc.menu;
  m.investment_fees_per_year = m.weighted_mer_pct / 100 * bal; m.platform_admin_fee_per_year = pc.total;
  m.total_ongoing_cost_pct = m.weighted_mer_pct + m.platform_admin_fee_per_year / bal * 100; m.initial_brokerage = brokerageFor(lines, pc, T);
  for (const [period, key] of [["3y","return_3y_pct_pa"],["5y","return_5y_pct_pa"],["10y","return_10y_pct_pa"]]) { let v = 0, px = 0;
    for (const l of lines) { const r = R[l.ticker]; let x = r && r[key] != null ? r[key] : null; if (x == null) { x = l.yield_pct || 0; } else if (r.return_proxy && r.return_proxy[period]) px += W(l);
      v += W(l) * x; } m["weighted_return_" + period + "_pct"] = v; m["weighted_return_" + period + "_proxy_share_pct"] = px * 100; }
  // risk from daily returns
  const R0 = DATA.returns || {};
  if (R0.dates && lines.length) { const rows = lines.map(l => [l, dailySeries(l)]).filter(x => x[1] && x[0].weight_pct > 0);
    if (rows.length >= 1) { const n = R0.dates.length, w = rows.map(([l]) => W(l)), S = rows.map(x => x[1]);
      const mean = a => a.reduce((s,v) => s + v, 0) / a.length; const cov = (a, b) => { const ma = mean(a), mb = mean(b); let s = 0; for (let i = 0; i < n; i++) s += (a[i]-ma)*(b[i]-mb); return s / (n - 1); };
      const port = new Array(n).fill(0); rows.forEach(([l, sr], k) => { for (let i = 0; i < n; i++) port[i] += w[k]*sr[i]; });
      const vols = S.map(sr => Math.sqrt(cov(sr, sr)*252)); const C = S.map(a => S.map(b => cov(a, b))); let pv = 0;
      for (let i = 0; i < w.length; i++) for (let j = 0; j < w.length; j++) pv += w[i]*w[j]*C[i][j]*252;
      const pvol = Math.sqrt(Math.max(pv, 0))*100; m.realised_volatility_pct = pvol; const avg = w.reduce((s,wi,i) => s + wi*vols[i], 0)*100; m.weighted_avg_holding_vol_pct = avg; m.diversification_ratio = avg / Math.max(pvol, 1e-9);
      m.trailing_1y_return_pct = (port.reduce((g, r) => g*(1+r), 1) - 1)*100;
      let sum = 0, cnt = 0; for (let i = 0; i < w.length; i++) for (let j = 0; j < w.length; j++) if (i !== j) { const d = Math.sqrt(C[i][i]*C[j][j]); if (d > 0) { sum += C[i][j]/d; cnt++; } } m.avg_pairwise_correlation = cnt ? sum/cnt : null;
      for (const [k, t] of [["asx200", "VAS.AX"], ["world", "VGS.AX"]]) { const b = R0.series[t]; if (!b) continue; const vb = cov(b, b); if (vb <= 0) continue; m["beta_" + k] = cov(port, b)/vb; m["correlation_" + k] = cov(port, b)/Math.sqrt(vb*cov(port, port)); }
      const b = R0.series["VAS.AX"]; m.holding_beta_asx200 = {}; if (b) { const vb = cov(b, b); rows.forEach(([l, sr]) => { m.holding_beta_asx200[l.ticker] = cov(sr, b)/vb; }); } } }
  return { lines, metrics: m, class_weights: cw, tier, balance: bal, total };
}
function computeBacktest(pf){
  const H = DATA.history; if (!H || !H.months || !H.months.length || !pf.lines.length) return null;
  const n = H.months.length, bal = pf.balance;
  const rows = pf.lines.map(l => { const ms = monthlySeries(l); return { w: (l.weight_pct||0)/100, sr: ms ? ms.sr : null, key: ms ? ms.key : null, whole: !!(ms && ms.whole), standIn: ms && ms.standIn, standMonths: ms ? ms.standMonths : 0, name: l.name, cls: l.asset_class }; });
  const cp = H.class_proxy || {}; const values = []; let v = bal, peak = bal, mdd = 0;
  for (let i = 0; i < n; i++) { let r = 0; rows.forEach(x => { if (!x.sr) return; let y = x.sr[i]; if (y == null) { const fb = H.series[cp[x.cls]]; y = fb && fb[i] != null ? fb[i] : 0; } r += x.w * y; }); v *= 1 + r; values.push(v); if (v > peak) peak = v; mdd = Math.min(mdd, v/peak - 1); }
  const yrs = n/12, cagr = Math.pow(v/bal, 1/yrs) - 1; const tw = []; for (let i = 12; i < n; i++) tw.push(values[i]/values[i-12] - 1);
  const standShare = rows.reduce((s, x) => s + x.w * (x.whole ? n : x.standMonths), 0) / n * 100;
  const standIns = rows.filter(x => x.standIn).map(x => ({ name: x.name, proxy: x.standIn, months: x.whole ? n : x.standMonths }));
  return { values, end: v, cagr, mdd, best: tw.length ? Math.max(...tw) : null, worst: tw.length ? Math.min(...tw) : null, years: yrs, standShare, standIns };
}
const SECTOR_COLORS = ["#4a78a8","#d99a2b","#d1708a","#7c6db0","#a7c5e4","#f0d27e","#d3cec4","#6aa59b","#2f4a66","#ecb3c1","#9c8a5a","#b7aade","#8aa1b1","#c98a5e","#5d6470","#c3d39e"];
function diversification(pf){
  const lines = pf.lines.filter(l => l.weight_pct > 0); const tot = lines.reduce((s,l) => s + l.weight_pct, 0) || 1;
  const sec = {}, reg = {}; let direct = 0, dsum = 0; const dsec = {};
  for (const l of lines) { const sk = l.sector || (l.vehicle === "direct" ? "Other" : l.asset_class === "cash" ? "Cash" : "Diversified fund"), rk = l.region || "Other";
    sec[sk] = (sec[sk]||0) + l.weight_pct; reg[rk] = (reg[rk]||0) + l.weight_pct; if (l.vehicle === "direct") { direct++; dsum += l.weight_pct; dsec[sk] = (dsec[sk]||0) + l.weight_pct; } }
  const sorted = o => Object.entries(o).sort((a,b) => b[1]-a[1]);
  const hhi = lines.reduce((s,l) => s + Math.pow(l.weight_pct/tot, 2), 0); const top = [...lines].sort((a,b) => b.weight_pct - a.weight_pct);
  const rules = DATA.diversification || {}; const flags = []; const ds = sorted(dsec);
  if (direct >= 4 && ds.length && ds[0][1]/dsum > 0.4 && ds[0][1] > 5) flags.push(`${ds[0][0]} is ${Math.round(ds[0][1]/dsum*100)}% of the single-company holdings`);
  const rs = sorted(reg); if (rs.length && rs[0][1] > 70 && rs[0][0] !== "Australia") flags.push(`${Math.round(rs[0][1])}% of the portfolio is exposed to ${rs[0][0]}`);
  if (top[0] && top[0].vehicle === "direct" && top[0].weight_pct > (rules.max_single_holding_pct||10)) flags.push(`${top[0].name} is ${top[0].weight_pct.toFixed(1)}% of the portfolio: the engine caps a single company at ${rules.max_single_holding_pct||10}%`);
  const nsec = Object.keys(dsec).length; if (direct >= 3 && nsec < (rules.min_sectors_direct||3)) flags.push(`the single companies span only ${nsec} sector(s)`);
  const perClass = {}; for (const l of lines) if (l.vehicle === "direct") { const k = l.asset_class + "|" + (l.sector||"Other"); perClass[k] = (perClass[k]||0) + l.weight_pct; }
  for (const k in perClass) { const [c, s] = k.split("|"); const cwt = pf.class_weights[c] || 0; if (cwt > 0 && perClass[k] / cwt > (rules.max_sector_share_of_class||0.35) + 0.02 && perClass[k] > 3) flags.push(`${s} is ${Math.round(perClass[k]/cwt*100)}% of your ${label(CLASSES, c).toLowerCase()} sleeve (engine cap ${Math.round((rules.max_sector_share_of_class||0.35)*100)}%)`); }
  if (lines.length && lines.length < 5) flags.push("fewer than five holdings");
  return { sector: sorted(sec), region: sorted(reg), direct, directShare: dsum, directSectors: nsec, effective: hhi > 0 ? 1/hhi : null, top: top[0], top5: top.slice(0,5).reduce((s,l) => s + l.weight_pct, 0), flags };
}

// ------------------------------------------------------------ rendering
function spark(arr, color, w=110, h=28, big=false){
  if (!arr || arr.length < 2) return ""; const min = Math.min(...arr), max = Math.max(...arr), span = (max-min)||1, pad = 3;
  const pts = arr.map((v,i) => [pad + i/(arr.length-1)*(w-2*pad), pad + (1 - (v-min)/span)*(h-2*pad)]);
  const d = pts.map((p,i) => (i?"L":"M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" "); const area = d + ` L${pts[pts.length-1][0].toFixed(1)} ${h} L${pts[0][0].toFixed(1)} ${h} Z`;
  const base = pad + (1 - (100-min)/span)*(h-2*pad); const last = pts[pts.length-1];
  return `<svg class="${big?"spark-big":"spark"}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${area}" fill="${color}" opacity="0.12"/>${(base>0 && base<h) ? `<line x1="0" x2="${w}" y1="${base.toFixed(1)}" y2="${base.toFixed(1)}" stroke="currentColor" opacity="0.25" stroke-dasharray="2 3"/>` : ""}<path d="${d}" fill="none" stroke="${color}" stroke-width="${big?2:1.5}" vector-effect="non-scaling-stroke"/><circle cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="${big?3.5:2.5}" fill="${color}" stroke="var(--surface)" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
}
const QCLS = {core:"good", satellite:"neutral", speculative:"serious", "not recommended":"critical", "data check":"neutral"};
function qualityChip(t){ const q = DATA.quality[t]; return q ? `<span class="chip ${QCLS[q.verdict]||"neutral"}" title="${esc(q.note)}">${q.verdict}</span>` : ""; }
function consensusChip(r){ if (!r || !r.consensus_label || r.consensus_label==="no coverage") return `<span class="chip none">no coverage</span>`; if (r.consensus_label==="thin coverage") return `<span class="chip none">thin coverage</span>`;
  const cls = r.consensus_label.includes("Buy") ? "good" : r.consensus_label==="Hold" ? "neutral" : r.consensus_label==="Underperform" ? "serious" : "critical";
  return `<span class="chip ${cls}" title="${r.analysts} analysts, mean ${(r.consensus_mean||0).toFixed(1)} on a 1 to 5 scale">${r.consensus_label} (${r.analysts})</span>`; }
function retCell(r, key, period){ if (!r || r[key]==null) return "–"; const px = r.return_proxy && r.return_proxy[period]; return `<span title="${px ? "index stand-in: " + px : ""}">${fmtS(r[key])}${px ? "†" : ""}</span>`; }
function docLink(t){ const d = DATA.pds[t]; return d ? `<a href="${d.url}" target="_blank" rel="noopener">${esc(d.label)}</a>` : '<span class="muted">no link on file</span>'; }
function parseBalance(v){ const n = parseFloat(String(v).replace(/[^0-9.]/g, "")); return isFinite(n) && n >= 1000 ? n : null; }

function render(){
  const pf = compute(); const m = pf.metrics; const bal = pf.balance; const bad = Math.abs(pf.total - 100) > 0.05;
  sel("ptitle").textContent = state.name || (state.id ? "Untitled portfolio" : "A new portfolio");
  sel("total").textContent = fmtP(pf.total, 1); sel("total").classList.toggle("bad", bad);
  sel("title").textContent = (state.name || "Your portfolio") + ` at ${fmtM(bal)}`;
  sel("htable").hidden = !pf.lines.length; sel("holdings-empty").hidden = !!pf.lines.length;
  const maxW = Math.max(1, ...pf.lines.map(l => l.weight_pct || 0));
  sel("holdings").innerHTML = pf.lines.map(l => { const r = R[l.ticker] || {}; const col = cssColor(l.asset_class) || "var(--accent)";
    return `<tr class="row wrow ${state.ticker===l.ticker?"active":""}" data-t="${esc(l.ticker)}"><td><b>${esc(l.name)}</b><br><span class="mono" style="font-size:11.5px;color:var(--faint)">${esc(l.ticker)}, ${VEHICLE[l.vehicle] || esc(l.vehicle || "")}${l.source==="live" ? ", live" : ""}${l.priced_from==="asx" ? ", ASX price" : ""}${l.priced_from==="manual" ? (l.source==="sheet" ? ", figures from your sheet" : ", unlisted") : ""}</span> ${qualityChip(l.ticker)}${l.liquidity ? `<span class="chip neutral" title="Unlisted fund: priced by the manager; ${esc(l.liquidity)}">${esc(l.liquidity.split(" (")[0])}</span>` : ""}${l.sleeve ? `<br><span class="sleeve">${esc(l.sleeve)}</span>` : ""}</td>
      <td><select class="cls" data-t="${esc(l.ticker)}" style="font:inherit;font-size:12.5px;padding:3px 6px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--text)">${CLASSES.map(c => `<option value="${c.key}" ${c.key===l.asset_class?"selected":""}>${c.label}</option>`).join("")}</select></td>
      <td style="font-size:12.5px;color:var(--muted)">${esc(l.sector||"–")}<br>${esc(l.region||"–")}</td>
      <td class="num"><input class="w ${state.readOnly?"":""}" data-t="${esc(l.ticker)}" type="text" inputmode="decimal" value="${(l.weight_pct||0).toFixed(1)}" ${state.readOnly?"disabled":""}></td>
      <td class="num">${fmtM(l.dollars)}</td><td class="num">${fmtN(l.units)}</td><td class="num">${l.price_aud==null?"–":"$"+l.price_aud.toFixed(2)}</td>
      <td>${spark(r.sparkline, col)}</td><td class="num ${r.return_1y_pct>0?"pos":r.return_1y_pct<0?"neg":""}">${fmtS(r.return_1y_pct)}</td>
      <td class="num">${retCell(r, "return_3y_pct_pa", "3y")}</td><td class="num">${retCell(r, "return_5y_pct_pa", "5y")}</td><td class="num">${retCell(r, "return_10y_pct_pa", "10y")}</td>
      <td class="num">${fmtP(l.yield_pct,1)}${l.yield_source==="live"?"°":""}</td><td class="num">${fmtP(l.mer_pct,2)}</td><td>${consensusChip(r)}</td>
      <td class="no-print actions">${state.readOnly ? "" : `<button type="button" class="btn small danger" data-remove="${esc(l.ticker)}">remove</button>`}</td></tr>`; }).join("");
  sel("holdings").querySelectorAll("input.w").forEach(i => { i.onchange = () => { const l = state.lines.find(x => x.ticker === i.dataset.t); const v = parseFloat(i.value.replace(/[^0-9.]/g, "")); l.weight_pct = isFinite(v) && v >= 0 ? v : 0; state.dirty = true; render(); };
    i.onclick = e => e.stopPropagation(); i.onkeydown = e => { if (e.key === "Enter") i.blur(); }; });
  sel("holdings").querySelectorAll("select.cls").forEach(s => { s.onclick = e => e.stopPropagation(); s.onchange = () => { const l = state.lines.find(x => x.ticker === s.dataset.t); l.asset_class = s.value; state.dirty = true; render(); }; if (state.readOnly) s.disabled = true; });
  sel("holdings").querySelectorAll("button[data-remove]").forEach(b => b.onclick = e => { e.stopPropagation(); removeLine(b.dataset.remove); });
  sel("holdings").querySelectorAll("tr.row").forEach(tr => { tr.onclick = () => { state.ticker = state.ticker === tr.dataset.t ? null : tr.dataset.t; renderSheet(pf); }; });
  renderSheet(pf);
  const tiles = [
    ["Growth / defensive", `${fmtP(m.growth_pct,0)} / ${fmtP(m.defensive_pct,0)}`, "shares and property versus bonds and cash"],
    ["Holdings", m.holdings, `${pf.lines.filter(l=>l.vehicle==="direct").length} single companies, ${pf.lines.filter(l=>l.vehicle!=="direct").length} funds, ETFs or cash`],
    ["Cost per year", fmtM(m.investment_fees_per_year + m.platform_admin_fee_per_year), `${fmtP(m.weighted_mer_pct,2)} in funds + ${fmtM(m.platform_admin_fee_per_year)} platform (${esc(m.platform.label)}${m.platform.key === "custom" ? "" : ", " + esc(m.platform.menuLabel)}); ${fmtP(m.total_ongoing_cost_pct,2)} all-in`],
    ["Income per year", fmtM(m.income_per_year), `${fmtP(m.weighted_yield_pct,2)} cash yield` + (m.franking_credits_per_year > 0.5 ? ` + ${fmtM(m.franking_credits_per_year)} franking credits (${fmtP(m.grossed_up_yield_pct,2)} grossed up)` : "")],
    ["A typical year moved", m.realised_volatility_pct == null ? "–" : "±" + fmtP(m.realised_volatility_pct,0), "realised volatility over the last year"],
    ["Last 12 months", fmtS(m.trailing_1y_return_pct), "what this mix returned; history, not a forecast"],
  ];
  sel("tiles").innerHTML = tiles.map(([k,v,s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  sel("rtiles").innerHTML = [["3y","Weighted 3 year return p.a."],["5y","Weighted 5 year return p.a."],["10y","Weighted 10 year return p.a."]].map(([p,k]) => { const px = m["weighted_return_"+p+"_proxy_share_pct"]||0;
    return `<div class="tile"><div class="k">${k}</div><div class="v">${fmtS(m["weighted_return_"+p+"_pct"])}</div><div class="s">${px > 0.5 ? px.toFixed(0) + "% of the weight rests on index stand-ins" : "average of the holdings' own returns"}</div></div>`; }).join("") +
    `<div class="tile"><div class="k">Brokerage to buy it all</div><div class="v">${fmtM(m.initial_brokerage)}</div><div class="s">one-off, ${m.platform.brokerage && m.platform.brokerage.rate != null ? "at " + esc(m.platform.label) + "'s rate (" + fmtP(m.platform.brokerage.rate*100,2) + ", minimum " + fmtM(m.platform.brokerage.min) + " a trade)" : "at the tier's per-trade rate"}</div></div>`;
  const warn = [];
  if (pf.lines.length && bad) warn.push(`Weights add up to ${fmtP(pf.total,1)}, not 100%. Use "Scale to 100%" or "Fill the gap with cash" above; the dollar figures assume the weights as entered.`);
  const unpriced = pf.lines.filter(l => l.price_aud == null); if (unpriced.length) warn.push("No price for " + unpriced.map(l => l.ticker).join(", ") + "; shown without units.");
  const T = DATA.tiers.find(t => t.key === pf.tier) || {}; const small = pf.lines.filter(l => l.weight_pct > 0 && l.dollars < (T.min_holding||0) && l.vehicle !== "cash");
  if (small.length) warn.push(`${small.length} holding(s) are under the ${fmtM(T.min_holding)} minimum the engine uses at this balance (${small.map(l => l.ticker).join(", ")}): brokerage will eat into them.`);
  if (m.platform.listedBlocked) warn.push(`The ${esc(m.platform.menuLabel)} on ${esc(m.platform.label)} cannot hold listed shares or ETFs. Choose another menu, or "Cheapest menu that fits".`);
  if (!m.platform.verified) warn.push(`${esc(m.platform.label)}'s fees here are not yet confirmed against a current fee document. Treat the platform cost as indicative.`);
  sel("warnings").innerHTML = warn.map(w => `<div class="note">${w}</div>`).join("");
  // allocation
  const cw = pf.class_weights; const ref = DATA.saa[state.ref] || {};
  sel("stack").innerHTML = CLASSES.filter(c => (cw[c.key]||0) > 0).map(c => `<span style="width:${cw[c.key]}%;background:${cssColor(c.key)}" data-l="${c.label}: ${fmtP(cw[c.key])}"></span>`).join("");
  sel("stack").querySelectorAll("span").forEach(el => { el.onmousemove = e => showTip(e, el.dataset.l); el.onmouseleave = hideTip; });
  sel("legend").innerHTML = CLASSES.map(c => `<span><i style="background:${cssColor(c.key)}"></i>${c.label} <span class="mono">${fmtP(cw[c.key]||0)}</span></span>`).join("");
  sel("alloc").innerHTML = CLASSES.map(c => { const d = (cw[c.key]||0) - (ref[c.key]||0); return `<tr><td><span class="dot" style="background:${cssColor(c.key)}"></span>${c.label}</td><td class="num">${fmtP(cw[c.key]||0)}</td><td class="num">${fmtP(ref[c.key]||0)}</td><td class="num ${Math.abs(d)>5?"neg":""}">${(d>=0?"+":"")+d.toFixed(1)} pp</td><td class="num">${fmtM((cw[c.key]||0)/100*bal)}</td></tr>`; }).join("");
  const refG = CLASSES.filter(c => c.kind==="growth").reduce((s,c) => s + (ref[c.key]||0), 0);
  sel("allocnote").textContent = `The ${label(DATA.targets, state.ref)} long-run target is ${refG.toFixed(0)}% growth assets; yours is ${fmtP(m.growth_pct,0)}. Differences over 5 points are marked.`;
  renderDiversification(pf); renderBacktest(pf); renderRisk(pf);
  renderPlatformControls(pf); renderPlatCompare(pf); renderBoa(pf); updateBaseNote(); renderCheck(pf);
  updateSaveNote(); saveDraft(); track(); saveSummary(pf);
}
// A summary of this portfolio for the Compare page, which sets it beside super fund options.
function saveSummary(pf){ try { const m = pf.metrics; const bal = pf.balance || 1; if (!pf.lines.length) { localStorage.removeItem("mpl-portfolio-summary"); return; }
  localStorage.setItem("mpl-portfolio-summary", JSON.stringify({ name: state.name || "Your portfolio", balance: bal, growth: m.growth_pct / 100,
    r3: m.weighted_return_3y_pct / 100, r5: m.weighted_return_5y_pct / 100, r10: m.weighted_return_10y_pct / 100, fund_fee: m.weighted_mer_pct / 100,
    platform: m.platform_admin_fee_per_year / bal, total: m.total_ongoing_cost_pct / 100, platform_label: m.platform.label + (m.platform.key === "custom" ? "" : ", " + m.platform.menuLabel),
    holdings: pf.lines.length, at: new Date().toISOString() })); } catch (e) {} }
function updateSaveNote(){ const local = state.id && String(state.id).startsWith("local-");
  sel("savenote").textContent = state.readOnly ? "Read-only shared portfolio. Sign in and use \"Save as a copy\" to make it yours." : state.id ? (state.dirty ? "Unsaved changes" : (local ? "Saved in this browser" : "Saved to your account")) : (state.lines.length ? "Not saved yet" : ""); }
function saveDraft(){ try { if (!state.readOnly) localStorage.setItem("mpl-builder-draft", JSON.stringify({ name: state.name, balance: state.balance, ref: state.ref, platform: state.platform, notes: state.notes, lines: state.lines, id: state.id, extra: EXTRA, research: Object.fromEntries(state.lines.filter(l => l.source === "live").map(l => [l.ticker, R[l.ticker]])) })); } catch(e) {} }

// ------------------------------------------------------------ undo and redo
// Every change made through the page lands in a snapshot; Undo steps back through them and Redo forward again.
// Typing (names, notes, basis of advice) is grouped so one pause in typing is one step.
const HIST = { undo: [], redo: [], last: null, max: 150 };
function snap(){ return JSON.stringify({ name: state.name, balance: state.balance, ref: state.ref, platform: state.platform, notes: state.notes, lines: state.lines.map(({ units, dollars, ...rest }) => rest) }); }
function track(){ if (state.readOnly) { updateUndoButtons(); return; } const s = snap(); if (HIST.last === null) { HIST.last = s; updateUndoButtons(); return; }
  if (s === HIST.last) { updateUndoButtons(); return; } HIST.undo.push(HIST.last); if (HIST.undo.length > HIST.max) HIST.undo.shift(); HIST.redo.length = 0; HIST.last = s; updateUndoButtons(); }
let trackT; function trackSoon(){ clearTimeout(trackT); trackT = setTimeout(track, 700); }
function resetHistory(){ HIST.undo.length = 0; HIST.redo.length = 0; HIST.last = snap(); updateUndoButtons(); }
function restoreSnap(s){ const d = JSON.parse(s); state.name = d.name; state.balance = d.balance; state.ref = d.ref; state.platform = d.platform; state.notes = d.notes || ""; state.lines = d.lines; state.dirty = true;
  if (state.ticker && !state.lines.some(l => l.ticker === state.ticker)) state.ticker = null;
  sel("pname").value = state.name; sel("pbal").value = state.balance.toLocaleString("en-AU"); sel("pref").value = state.ref; sel("pnotes").value = state.notes; HIST.last = s; render(); }
function undo(){ if (state.readOnly) return; clearTimeout(trackT); track(); if (!HIST.undo.length) { toast("Nothing to undo"); return; } HIST.redo.push(snap()); restoreSnap(HIST.undo.pop()); updateUndoButtons(); toast("Undone. Redo puts it back."); }
function redo(){ if (state.readOnly) return; if (!HIST.redo.length) { toast("Nothing to redo"); return; } HIST.undo.push(snap()); restoreSnap(HIST.redo.pop()); updateUndoButtons(); toast("Redone"); }
function updateUndoButtons(){ sel("btn-undo").disabled = !HIST.undo.length || state.readOnly; sel("btn-redo").disabled = !HIST.redo.length || state.readOnly;
  sel("btn-undo").title = HIST.undo.length ? `Undo the last change (${HIST.undo.length} step${HIST.undo.length === 1 ? "" : "s"} back available). Ctrl or Cmd + Z` : "Nothing to undo yet"; }
sel("btn-undo").onclick = undo; sel("btn-redo").onclick = redo;
document.addEventListener("keydown", e => { if (!(e.metaKey || e.ctrlKey)) return; const k = e.key.toLowerCase(); if (k !== "z" && k !== "y") return;
  const a = document.activeElement; if (a && (a.tagName === "TEXTAREA" || (a.tagName === "INPUT" && a.type !== "button"))) return;   // let text boxes undo their own typing
  e.preventDefault(); if (k === "y" || e.shiftKey) redo(); else undo(); });

// ------------------------------------------------------------ platform controls and comparison
function renderPlatformControls(pf){
  const keys = Object.keys(PLAT); const c = state.platform;
  sel("plat").innerHTML = keys.map(k => `<option value="${k}">${esc(PLAT[k].label)}${PLAT[k].verified === false ? " (rates to confirm)" : ""}</option>`).join("") + `<option value="custom">Other platform or a negotiated rate</option>`;
  sel("plat").value = (c.key === "custom" || PLAT[c.key]) ? c.key : "custom";
  const manual = isManual(sel("plat").value), custom = sel("plat").value === "custom"; ["pcustom-a", "pcustom-b"].forEach(id => sel(id).classList.toggle("show", manual));
  sel("plat").disabled = state.readOnly; sel("pacct").disabled = sel("pmenu").disabled = manual || state.readOnly; sel("pcpct").disabled = sel("pcfix").disabled = state.readOnly;
  const pc = pf.metrics.platform;
  if (manual) { const p = PLAT[c.key]; const accts = p ? Object.values(p.accounts) : []; sel("pacct").innerHTML = accts.length ? accts.map(a => `<option>${esc(a.label || "")}</option>`).join("") : `<option>Not applicable</option>`; sel("pmenu").innerHTML = `<option>${p ? esc(pc.menuLabel) : "Not applicable"}</option>`;
    if (document.activeElement !== sel("pcpct")) sel("pcpct").value = c.custom_pct ?? ""; if (document.activeElement !== sel("pcfix")) sel("pcfix").value = c.custom_fixed ?? "";
    sel("pnote").innerHTML = custom ? "Enter the platform's administration fee as a percentage of the balance and any fixed dollar fees a year. Use this for a platform not listed, or a negotiated or family group rate."
      : esc(pc.notes) + (pc.entered ? ` Entered rate: ${fmtM(pc.total)} a year (${fmtP(pc.total / state.balance * 100, 2)}).` : " No rate entered yet, so the platform cost shows as nil.") + (pc.source_url ? ` <a href="${esc(pc.source_url)}" target="_blank" rel="noopener">About the service</a>` : "");
    return; }
  const p = PLAT[c.key]; const [ak, acct] = accountOf(p, c.account);
  sel("pacct").innerHTML = Object.entries(p.accounts).map(([k, a]) => `<option value="${k}">${esc(a.label || k)}</option>`).join(""); sel("pacct").value = ak;
  if (c.menu !== "auto" && !acct.menus[c.menu]) c.menu = "auto";
  sel("pmenu").innerHTML = `<option value="auto">Cheapest menu that fits${pc && pc.auto ? " (" + esc(pc.menuLabel) + ")" : ""}</option>` + Object.entries(acct.menus).map(([k, m]) => `<option value="${k}">${esc(m.label || k)}</option>`).join(""); sel("pmenu").value = c.menu || "auto";
  const bits = [`${esc(pc.product)}, ${esc(pc.menuLabel)}: ${fmtM(pc.admin)} administration${pc.other > 0.5 ? " + " + fmtM(pc.other) + " other platform fees" : ""} = ${fmtM(pc.total)} a year (${fmtP(pc.total / state.balance * 100, 2)}).`];
  if (pc.notes) bits.push(esc(pc.notes)); if (pc.as_of) bits.push(`Rate card: ${esc(pc.as_of)}.`); if (!pc.verified) bits.push("Not yet confirmed against a current fee document.");
  sel("pnote").innerHTML = bits.join(" ") + (pc.source_url ? ` <a href="${esc(pc.source_url)}" target="_blank" rel="noopener">Fee document</a>` : "");
}
function platformRows(pf){ const bal = pf.balance; const rows = [];
  for (const [k, p] of Object.entries(PLAT)) { const ak = p.accounts[state.platform.account] ? state.platform.account : Object.keys(p.accounts)[0];
    if (p.manual_rate) { const pc = platformCost(bal, pf.lines, k === state.platform.key ? state.platform : { key: k, account: ak }); if (k === state.platform.key && pc.entered) rows.push(pc); else rows.push({ ...pc, unpriced: true }); continue; }
    const pc = platformCost(bal, pf.lines, { key: k, account: ak, menu: k === state.platform.key ? state.platform.menu : "auto" }); rows.push(pc); }
  if (state.platform.key === "custom") rows.push(platformCost(bal, pf.lines, state.platform));
  return rows.sort((a, b) => (a.unpriced ? 1 : 0) - (b.unpriced ? 1 : 0) || a.total - b.total); }
function renderPlatCompare(pf){ const rows = platformRows(pf); const bal = pf.balance;
  sel("platcmp").innerHTML = rows.map(r => r.unpriced ? `<tr><td>${esc(r.label)}</td><td>${esc(r.menuLabel)}</td><td class="num" colspan="4" style="color:var(--faint)">Rate not published: choose it above and enter the client's rate</td><td style="font-size:12px">${r.source_url ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener">About the service</a>` : ""}</td></tr>` : `<tr class="${r.key === state.platform.key ? "on" : ""}"><td>${esc(r.label)}${r.verified ? "" : ' <span class="chip neutral" title="Read from the fee document through a summary; check before quoting">to confirm</span>'}</td><td>${esc(r.menuLabel)}${r.accountLabel ? '<br><span class="muted" style="font-size:11.5px">' + esc(r.accountLabel) + "</span>" : ""}</td><td class="num">${fmtM(r.admin)}</td><td class="num">${fmtM(r.other)}</td><td class="num"><b>${fmtM(r.total)}</b></td><td class="num">${fmtP(r.total / bal * 100, 2)}</td><td style="font-size:12px">${r.source_url ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener">${esc(r.as_of || "fee document")}</a>` : esc(r.as_of || "")}</td></tr>`).join("");
  const priced = rows.filter(r => !r.unpriced); const cheapest = priced[0], mine = priced.find(r => r.key === state.platform.key);
  sel("platnote").textContent = rows.length > 1 && mine && cheapest && mine.key !== cheapest.key ? `At ${fmtM(bal)} with these holdings, ${cheapest.label} would cost ${fmtM(mine.total - cheapest.total)} a year less than ${mine.label}. Platform choice also turns on the investment menu, reporting, the adviser's licensee approved product list and family group discounts, none of which is in this table.` : `Same account type on each platform, cheapest menu that fits these holdings. Family group discounts, negotiated rates and adviser fees are not included.`; }
sel("plat").onchange = () => { const v = sel("plat").value; const p = PLAT[v]; state.platform = { ...state.platform, key: v, menu: "auto", account: p && !p.accounts[state.platform.account] && state.platform.account !== "super" ? Object.keys(p.accounts)[0] : (state.platform.account || "super") }; state.dirty = true; render(); };
sel("pacct").onchange = () => { state.platform = { ...state.platform, account: sel("pacct").value, menu: "auto" }; state.dirty = true; render(); };
sel("pmenu").onchange = () => { state.platform = { ...state.platform, menu: sel("pmenu").value }; state.dirty = true; render(); };
sel("pcpct").onchange = () => { const v = parseFloat(sel("pcpct").value.replace(/[^0-9.]/g, "")); state.platform = { ...state.platform, custom_pct: isFinite(v) ? v : null }; state.dirty = true; render(); };
sel("pcfix").onchange = () => { const v = parseFloat(sel("pcfix").value.replace(/[^0-9.]/g, "")); state.platform = { ...state.platform, custom_fixed: isFinite(v) ? v : null }; state.dirty = true; render(); };

// ------------------------------------------------------------ basis of advice
const VEHICLE_WORDS = { direct: "a single company", etf: "an exchange traded fund", lic: "a listed investment company", lit: "a listed investment trust", fund: "a managed fund", hybrid: "a listed hybrid security", bond: "an exchange-traded bond", cash: "cash", td: "a term deposit", sma: "a managed portfolio" };
const CLASS_PURPOSE = {
  aus_equity: l => `It provides Australian share exposure for long-term growth${(l.franking_pct || 0) > 0 ? " and franked income" : ""}`,
  intl_equity: () => "It provides international share exposure, spreading the portfolio beyond the concentrated Australian market and adding currency diversification",
  infrastructure: () => "It provides real asset exposure, with income tied to long-term contracts and often to inflation",
  alternatives: () => "It provides a source of return that has not moved closely with shares or bonds",
  fixed_income: () => "It provides defensive income and has tended to cushion the portfolio when shares fall",
  credit: () => "It provides income above cash with less volatility than shares",
  cash: () => "It provides liquidity for fees, pension payments and rebalancing without forced selling" };
// The draft follows the way the Statement of Advice template sets out a recommendation: why it is recommended, its
// advantages, and other things to consider. It is written from the holding's own facts; it never cites past returns,
// price targets or forecasts, because past performance is not a reason to recommend a holding.
const ACTIVE_RE = /active|alpha|catalyst|long.?short|small (growth|compan)|global growth|income plus|absolute return|complex|hyperion|munro|plato|l1 |solaris|lazard|coolabah|schroder|firetrail|wam |future generation/i;
const isActive = l => l.vehicle === "fund" || l.vehicle === "lic" || (l.vehicle === "etf" && ((l.mer_pct || 0) >= 0.4 || ACTIVE_RE.test(l.name || "")));
function boaWhy(l){
  const cls = label(CLASSES, l.asset_class).toLowerCase().replace(/^australian/, "Australian");
  const role = l.sleeve ? `as ${/^(a|an|the) /i.test(l.sleeve) ? "" : "the portfolio's "}${l.sleeve.toLowerCase().replace(/\bai\b/g, "AI").replace(/\blic\b/gi, "LIC").replace(/australian/g, "Australian").replace(/new zealand/g, "New Zealand")} position` : l.role === "core" ? "as a core holding" : "as a satellite holding";
  const vehicle = VEHICLE_WORDS[l.vehicle] || l.vehicle;
  const lead = `We recommend ${l.name} (${l.ticker.replace(/\.(AX|XA)$/, "")}), ${vehicle}, ${role} in the ${cls} allocation at ${fmtP(l.weight_pct, 1)} of the portfolio (${fmtM(l.dollars)}).`;
  const p = {
    aus_equity: () => (l.vehicle === "direct" ? `It gives direct exposure to ${l.sector ? "the " + l.sector.toLowerCase() + " sector" : "one Australian business"}` : `It gives diversified Australian share exposure${/small/i.test(l.name + " " + (l.sector || "") + " " + (l.sleeve || "")) ? " to smaller companies, which the large-company indices barely hold" : /income|yield|dividend/i.test(l.name + " " + (l.sleeve || "")) ? " with a focus on income" : ""}`) + ((l.franking_pct || 0) > 0 ? ", with franked income that a low-tax or pension account can use in full" : "") + ".",
    intl_equity: () => (l.vehicle === "direct" ? `It adds a global company${l.sector ? " in " + l.sector.toLowerCase() : ""}${l.region ? " listed in " + (l.region === "United States" ? "the United States" : l.region) : ""} that the Australian market does not offer` : `It spreads the portfolio across ${/small/i.test(l.name + " " + (l.sector || "")) ? "smaller global companies" : /ex.?us/i.test(l.name) ? "developed and emerging markets outside the United States" : "global markets"} that the Australian share market does not cover`) + ", and adds currency diversification.",
    infrastructure: () => `It adds real assets${/propert|reit|real estate/i.test((l.sector || "") + " " + (l.sleeve || "") + " " + l.name) ? " (property)" : " (infrastructure)"} whose income is tied to long-term leases, contracts or regulated returns, often linked to inflation.`,
    alternatives: () => "It adds a source of return that has not moved closely with shares or bonds.",
    fixed_income: () => l.vehicle === "bond" && /^(GSB|TIB|GTP)|treasury|commonwealth|government/i.test(l.ticker + " " + l.name) ? "It is a Commonwealth Government bond: the most secure income in the portfolio, and the asset most likely to rise in value when shares fall sharply and interest rates are cut." : "It provides defensive income and has tended to cushion the portfolio when shares fall.",
    credit: () => `It provides income above the cash rate from ${/sub(ordinated)? ?debt/i.test((l.sleeve || "") + " " + l.name) ? "subordinated debt" : /mci|mutual capital/i.test((l.sleeve || "") + " " + l.name) ? "mutual capital instruments" : /note/i.test((l.sleeve || "") + " " + l.name) ? "listed notes" : l.vehicle === "hybrid" ? "a listed hybrid security" : "a diversified credit portfolio"}, with less volatility than shares.`,
    cash: () => l.vehicle === "td" || /term/i.test(l.name) ? "It locks in a known rate of interest for a fixed term and is the stable base of the defensive allocation." : "It provides liquidity for fees, pension payments and rebalancing without forced selling." }[l.asset_class];
  return [lead, p ? p() : ""].filter(Boolean).join(" "); }
function boaAdvantages(l){
  const a = []; const u = UMAP[l.ticker] || {};
  if (l.vehicle === "direct") a.push("No ongoing management fee, full transparency of what is owned, and parcels can be sold selectively to manage capital gains");
  else if (["etf", "fund", "lic", "lit"].includes(l.vehicle)) a.push(`Spreads the exposure across many underlying holdings${isActive(l) ? ", chosen by a specialist manager" : " at index cost"}${(l.mer_pct || 0) > 0 ? ` for ${fmtP(l.mer_pct, 2)} a year` : ""}`);
  if ((l.yield_pct || 0) >= 0.5 && !["cash"].includes(l.asset_class)) a.push(`Income: ${l.yield_source === "live" ? "a trailing" : l.yield_source === "sheet" ? "a stated" : "an expected"} yield of about ${fmtP(l.yield_pct, 1)}${(l.franking_pct || 0) > 0 ? `, around ${fmtP(l.franking_pct, 0)} franked` : ""}`);
  if (l.vehicle === "lic" && (l.franking_pct || 0) > 0) a.push("A listed investment company can smooth and frank its dividends from retained profits");
  if (isListed(l)) a.push("Listed: it can be bought or sold on the exchange on any trading day");
  else if (l.vehicle === "fund" && (l.liquidity || u.liquidity)) a.push(`Unlisted, with redemptions ${String(l.liquidity || u.liquidity).toLowerCase()}`);
  if (l.asset_class === "fixed_income" || (l.asset_class === "cash" && l.vehicle === "td")) a.push("Capital is repaid at maturity; the return is known in advance if held to the end");
  if (l.asset_class === "intl_equity" && l.currency && l.currency !== "AUD") a.push("Holds its value in a foreign currency, which tends to help when the Australian dollar falls in a sell-off");
  return a; }
function boaConsider(l){
  const c = []; const r = R[l.ticker] || {}; const q = DATA.quality[l.ticker]; const u = UMAP[l.ticker] || {};
  if (l.vehicle === "direct" && ["aus_equity", "intl_equity", "infrastructure"].includes(l.asset_class)) c.push("A single company: its result rests on one business, so its price can fall sharply on company-specific news. " + ((l.weight_pct || 0) <= 5 ? "It is held at a small weight for that reason" : `At ${fmtP(l.weight_pct, 1)} it is a large position for one company in a diversified portfolio`));
  if (l.asset_class === "intl_equity" && (l.currency || "AUD") !== "AUD") c.push("Returns are exposed to the Australian dollar: a rising dollar reduces them");
  if (isActive(l) && l.vehicle !== "lic") c.push(`An actively managed ${l.vehicle === "etf" ? "fund" : "fund"}: the manager may not beat its benchmark after its higher fee, and the result depends on the manager's process and people`);
  if (l.vehicle === "lic") c.push("A listed investment company can trade at a discount or premium to the value of its assets, so its price can differ from the portfolio underneath");
  if (l.vehicle === "fund" && !isListed(l)) c.push(`Unlisted: priced and redeemed on the manager's terms${l.liquidity || u.liquidity ? " (" + String(l.liquidity || u.liquidity).toLowerCase() + ")" : ""}, and it may not be on every platform's menu`);
  if (l.asset_class === "credit") c.push("Ranks behind senior debt: income can be deferred and, in a severe stress, capital can be converted or written down. Its market price can fall with shares in a crisis, and trading can be thin. Check the call or maturity date before buying");
  if (l.vehicle === "bond") c.push("A long-dated fixed-rate bond: its price falls when long-term interest rates rise, so it can lose value before maturity even though it repays face value at the end");
  if (l.asset_class === "infrastructure") c.push("Sensitive to interest rates and regulation; distributions from trusts are often unfranked");
  if (l.asset_class === "cash" && l.vehicle === "td") c.push("Money is committed until maturity; breaking the term early usually reduces the interest, and the rate on reinvestment may be lower");
  else if (l.asset_class === "cash") c.push("The return is the cash rate, which may not keep pace with inflation over time");
  if (l.priced_from === "asx" || (l.priced_from === "manual" && l.source === "sheet")) c.push("There is no long price history in the data feed for this holding, so its risk figures on this page use its asset class index");
  if (r.consensus_label && /Sell|Underperform/.test(r.consensus_label)) c.push(`Analyst consensus currently leans negative (${r.consensus_label}, ${r.analysts} analysts); confirm the view against current research`);
  if (q && /speculative|not recommended/.test(q.verdict)) c.push(`Quality review verdict: ${q.verdict}`);
  return c; }
function draftBoa(l){
  const join = a => a.length ? a.join(". ") + "." : "";
  const adv = boaAdvantages(l), con = boaConsider(l);
  return [`Why we recommend it: ${boaWhy(l)}`,
    adv.length ? `Advantages: ${join(adv)}` : "",
    con.length ? `Other things to consider: ${join(con)}` : "",
    "To complete: why it suits this client's objectives, risk profile and timeframe, how it fits with their existing investments, and the alternatives considered."].filter(Boolean).join("\n\n"); }

const boaText = l => l.boa_custom ? (l.boa || "") : draftBoa(l);
function renderBoa(pf){
  sel("boa-section").hidden = !pf.lines.length;
  if (document.activeElement !== sel("pnotes")) sel("pnotes").value = state.notes || ""; sel("pnotes").readOnly = state.readOnly;
  const a = document.activeElement; if (a && a.closest && a.closest("#boa")) return;   // never rebuild the list under someone's cursor
  sel("boa").innerHTML = pf.lines.map(l => `<div class="boa-item"><div class="boa-head"><b>${esc(l.name)} <span class="mono" style="font-weight:400;color:var(--faint);font-size:12px">${esc(l.ticker)}, ${fmtP(l.weight_pct, 1)}</span></b><span><span class="boa-state ${l.boa_ai ? "ai" : l.boa_custom ? "custom" : ""}">${l.boa_ai ? "AI draft in house style: check every fact, then edit" : l.boa_custom ? "Your words: kept and saved" : "Automatic draft: updates with the figures until you edit it"}</span>${l.boa_custom && !state.readOnly ? ` <button type="button" class="btn small" data-redraft="${esc(l.ticker)}">Back to the draft</button>` : ""}</span></div><textarea data-t="${esc(l.ticker)}" ${state.readOnly ? "readonly" : ""} aria-label="Basis of advice for ${esc(l.name)}">${esc(boaText(l))}</textarea></div>`).join("");
  sel("boa").querySelectorAll("textarea").forEach(ta => ta.oninput = () => { const l = state.lines.find(x => x.ticker === ta.dataset.t); if (!l) return; l.boa = ta.value; if (!l.boa_custom || l.boa_ai) { l.boa_custom = true; l.boa_ai = false; const st = ta.parentElement.querySelector(".boa-state"); st.textContent = "Your words: kept and saved"; st.classList.remove("ai"); st.classList.add("custom"); }
    state.dirty = true; updateSaveNote(); saveDraft(); trackSoon(); });
  sel("boa").querySelectorAll("button[data-redraft]").forEach(b => b.onclick = () => { const l = state.lines.find(x => x.ticker === b.dataset.redraft); if (!l) return; l.boa_custom = false; l.boa_ai = false; l.boa = ""; state.dirty = true; render(); toast("Back to the automatic draft. Undo restores your words."); }); }
// House style examples: this browser keeps the last ones used; a saved portfolio carries its own; config/boa_examples.md is the default.
(() => { try { HS.text = HS.text || localStorage.getItem("mpl-boa-examples") || DATA.boa_examples || ""; } catch(e) { HS.text = HS.text || DATA.boa_examples || ""; }
  const t = sel("hs-examples"); if (!t) return; t.value = HS.text; if (HS.text) sel("hs-wrap").open = false;
  t.oninput = () => { HS.text = t.value; try { localStorage.setItem("mpl-boa-examples", HS.text); } catch(e) {} state.dirty = true; updateSaveNote(); }; })();
// One background AI job (the review or the house style drafts): post it, then poll for the result.
async function runAiJob(payload, noteId, waitText, minutes = 4){
  const job = (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(16) + Math.random().toString(16).slice(2)).toLowerCase();
  sel(noteId).textContent = waitText;
  const { data } = await SB.auth.getSession(); const token = data.session && data.session.access_token;
  await fetch(FN + "/review-background", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job, token, payload }) });
  for (let i = 0; i < minutes * 24; i++) { await new Promise(r => setTimeout(r, 2500)); const r = await fetch(FN + "/review-status?job=" + job, { cache: "no-store" }); const j = await r.json().catch(() => ({}));
    if (j.status === "done" || j.status === "error") return j; if (j.of) sel(noteId).textContent = `${waitText.replace(/….*$/, "")}: ${j.done} of ${j.of} done…`; }
  return { status: "error", error: `No answer after ${minutes} minutes. Try again shortly.` }; }
sel("btn-boa-ai").onclick = async () => { if (AI.running) return; if (!SB) { toast("The AI drafts need accounts, which are not set up on this copy of the page"); return; }
  if (!user.session) { toast("Sign in to use the AI drafts"); openAuth("signin"); return; } if (!state.lines.length) { toast("Add some holdings first"); return; }
  if (!FN) { toast("The AI drafts run on the published site"); return; }
  const keep = sel("hs-keep").checked; const todo = state.lines.filter(l => !(keep && l.boa_custom && !l.boa_ai));
  if (!todo.length) { toast("Every holding already has your own words. Untick the box to redraft them."); return; }
  const pf = compute();
  const payload = { mode: "boa", examples: String(HS.text || "").slice(0, 15000),
    portfolio: { name: state.name || "Untitled", balance: pf.balance, compared_with: label(DATA.targets, state.ref) + " long-run target", rationale: state.notes || "", growth_pct: +pf.metrics.growth_pct.toFixed(1) },
    holdings: todo.map(l => { const r = R[l.ticker] || {}; const q = DATA.quality[l.ticker] || {}; const u = UMAP[l.ticker] || {};
      return { code: l.ticker, name: l.name, asset_class: label(CLASSES, l.asset_class), structure: VEHICLE_WORDS[l.vehicle] || l.vehicle, role_in_model: l.sleeve || "", exposure: exposureOf(l).text,
        management: isActive(l) ? "active" : l.vehicle === "etf" ? "index" : l.vehicle === "direct" ? "direct holding" : l.vehicle, weight_pct: +(l.weight_pct || 0).toFixed(2), dollars: Math.round(l.dollars || 0),
        fee_pct: l.mer_pct, yield_pct: l.yield_pct, franking_pct: l.franking_pct, sector: l.sector, region: l.region, currency: l.currency, listed: isListed(l), liquidity: l.liquidity || u.liquidity || "",
        analyst_consensus: r.consensus_label || "", quality_verdict: q.verdict || "", quality_note: q.note || "", description: String(r.summary || "").slice(0, 500), facts_draft: draftBoa(l) }; }) };
  AI.running = true; sel("btn-boa-ai").disabled = true;
  try { const res = await runAiJob(payload, "boa-ai-note", `Drafting ${todo.length} holding${todo.length === 1 ? "" : "s"} in your house style… this usually takes one to four minutes.`, 14);
    const drafts = (res.status === "done" && res.result && res.result.drafts) || [];
    if (!drafts.length) { sel("boa-ai-note").textContent = res.error || "The AI did not return any drafts. Try again shortly."; return; }
    clearTimeout(trackT); track(); let n = 0;
    for (const d of drafts) { const l = todo.find(x => x.ticker === d.code || x.ticker.replace(/\.(AX|XA)$/, "") === String(d.code || "").replace(/\.(AX|XA)$/, "")); if (!l || !d.text) continue; l.boa = String(d.text).trim(); l.boa_custom = true; l.boa_ai = true; n++; }
    state.dirty = true; render(); sel("boa-ai-note").textContent = `${n} draft${n === 1 ? "" : "s"} written in house style${res.remaining_today != null ? `; ${res.remaining_today} AI uses left today` : ""}. Check every fact before use; Undo puts the previous text back.${res.partial ? " Not every holding was drafted (" + res.partial + "); press the button again for the rest." : ""}`;
    toast("House style drafts ready"); }
  catch (e) { sel("boa-ai-note").textContent = "The AI drafts did not run: " + e.message; }
  finally { AI.running = false; sel("btn-boa-ai").disabled = false; } };
sel("pnotes").oninput = () => { state.notes = sel("pnotes").value; state.dirty = true; updateSaveNote(); saveDraft(); trackSoon(); };
function renderSheet(pf){
  const box = sel("sheet"); sel("holdings").querySelectorAll("tr.row").forEach(tr => tr.classList.toggle("active", tr.dataset.t===state.ticker));
  const l = pf.lines.find(x => x.ticker===state.ticker); if (!l) { box.hidden = true; box.innerHTML = ""; return; }
  const r = R[l.ticker] || {}; const col = cssColor(l.asset_class); const u = UMAP[l.ticker];
  const sentences = r.summary ? r.summary.split(". ") : []; const blurb = sentences.length ? sentences.slice(0,4).join(". ") + (sentences.length>4 ? "." : "") : (l.source === "live" ? "Added live from the price feed: no written description or analyst view until the daily build researches it." : "No description available from the data feed.");
  const ccy = r.price_currency && r.price_currency!=="AUD" ? ` (${r.price_currency})` : "";
  box.hidden = false; box.innerHTML = `<div class="sheet-head"><h3>${esc(l.name)} <span class="mono" style="font-weight:400;color:var(--faint);font-size:14px">${esc(l.ticker)}</span></h3>
      <div><span class="dot" style="background:${col}"></span>${label(CLASSES, l.asset_class)}, ${esc(l.sector||"")}, ${esc(l.region||"")}, ${fmtP(l.weight_pct,1)} (${fmtM(l.dollars)})</div></div>
    <div class="sheet-grid"><div>${DATA.quality[l.ticker] ? `<div class="note" style="background:var(--accent-soft);color:var(--text)"><b>Reviewed verdict: ${DATA.quality[l.ticker].verdict}.</b> ${esc(DATA.quality[l.ticker].note)} <span class="muted">(${DATA.quality[l.ticker].reviewed}; opinion, not advice)</span></div>` : ""}
      <p class="summary">${esc(blurb)}</p>${r.sparkline && r.sparkline.length ? `<div class="eyebrow">Last 12 months, dividends reinvested, rebased to 100</div>${spark(r.sparkline, col, 600, 120, true)}` : ""}</div>
      <dl class="kv"><dt>Analyst view</dt><dd>${consensusChip(r)}</dd><dt>1 year return</dt><dd>${fmtS(r.return_1y_pct)}</dd><dt>3 years, per year</dt><dd>${fmtS(r.return_3y_pct_pa)}</dd><dt>5 years, per year</dt><dd>${fmtS(r.return_5y_pct_pa)}</dd><dt>10 years, per year</dt><dd>${fmtS(r.return_10y_pct_pa)}</dd>
      ${r.history_years != null ? `<dt>History available</dt><dd>${r.history_years} years</dd>` : ""}<dt>Volatility (1y)</dt><dd>${fmtP(r.volatility_1y_pct)}</dd><dt>Worst fall in the last year</dt><dd>${fmtP(r.max_drawdown_1y_pct)}</dd>
      <dt>Dividend yield</dt><dd>${fmtP(l.yield_pct,2)}${l.yield_source === "asx" ? " (ASX)" : ""}</dd><dt>Franking${(asxFactsOf(l.ticker) || {}).franking_pct != null && Math.abs((asxFactsOf(l.ticker).franking_pct) - (l.franking_pct || 0)) < 1 ? " (ASX, last dividend)" : " (estimate)"}</dt><dd>${fmtP(l.franking_pct,0)}</dd><dt>Management cost</dt><dd>${fmtP(l.mer_pct,2)}</dd>
      ${r.market_cap!=null ? `<dt>${r.quote_type==="ETF"?"Fund size":"Market cap"}${ccy}</dt><dd>${r.market_cap >= 1e9 ? "$" + (r.market_cap/1e9).toFixed(1) + " bn" : fmtM(r.market_cap)}</dd>` : ""}
      <dt>Beta to ASX 200 (1y)</dt><dd>${(pf.metrics.holding_beta_asx200||{})[l.ticker] != null ? pf.metrics.holding_beta_asx200[l.ticker].toFixed(2) : "–"}</dd>
      <dt>Documents</dt><dd style="font-family:inherit">${docLink(l.ticker)}</dd><dt>Data</dt><dd style="font-family:inherit;color:var(--faint)">${esc(r.source||l.priced_from)}${r.fetched?", "+r.fetched:""}</dd></dl></div>${asxPanel(l)}`;
  const rb = sel("asx-refresh"); if (rb) rb.onclick = async e => { e.stopPropagation(); rb.disabled = true; rb.textContent = "Fetching…";
    try { await asxLookup(l.ticker); toast("Updated from the ASX"); renderSheet(compute()); } catch (err) { toast(err.message); rb.disabled = false; rb.textContent = "Get the latest from the ASX"; } };
  const ub = sel("asx-use"); if (ub) ub.onclick = e => { e.stopPropagation(); const f = asxFactsOf(l.ticker) || {}; const was = `${fmtP(l.yield_pct, 2)} yield, ${fmtP(l.franking_pct, 0)} franked`;
    if (f.franking_pct != null) l.franking_pct = +f.franking_pct; if (f.yield_pct) { l.yield_pct = +f.yield_pct; l.yield_source = "asx"; }
    state.dirty = true; render(); toast(`${l.ticker.replace(/\.(AX|XA)$/, "")}: now ${fmtP(l.yield_pct, 2)} yield, ${fmtP(l.franking_pct, 0)} franked from the ASX (was ${was}). Undo goes back.`); };
}
// ASX facts: kept by the daily build for every ASX holding (DATA.asx), or fetched live for any code (R[t].asx).
const asxFactsOf = t => (R[t] && R[t].asx) || (DATA.asx || {})[t] || null;
async function asxLookup(t){ const code = t.replace(/\.(AX|XA)$/, ""); const d = await api("/asx?code=" + encodeURIComponent(code));
  if (!d.facts || !Object.keys(d.facts).length) throw new Error("The ASX returned no details for " + code);
  R[t] = { ...(R[t] || { ticker: t, name: d.name, consensus_label: "no coverage", return_proxy: {} }), asx: d.facts }; return d; }
const fdate = d => { const x = new Date(d); return isNaN(x) ? String(d) : x.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" }); };
function asxPanel(l){ if (!/\.(AX|XA)$/.test(l.ticker)) return "";
  const f = asxFactsOf(l.ticker); const rows = [];
  if (f) { if (f.kind) rows.push(["Security", f.kind + (f.security && !/^ordinary fully paid$/i.test(f.security) ? ": " + f.security : "")]);
    if (f.last_dividend != null) rows.push(["Last dividend or distribution", `${f.dividend_currency && f.dividend_currency !== "AUD" ? f.dividend_currency + " " : "$"}${(+f.last_dividend).toFixed(4).replace(/0+$/, "").replace(/\.$/, "")}${f.franking_pct != null ? ", " + (+f.franking_pct).toFixed(0) + "% franked" : ""}`]);
    if (f.ex_date) rows.push(["Ex date, pay date", fdate(f.ex_date) + (f.pay_date ? ", " + fdate(f.pay_date) : "")]);
    if (f.yield_pct != null) rows.push(["Annual yield", fmtP(f.yield_pct, 2)]); if (f.pe != null) rows.push(["Price to earnings", (+f.pe).toFixed(1)]);
    if (f.low_52w != null && f.high_52w != null) rows.push(["52 week range", `$${f.low_52w} to $${f.high_52w}`]); if (f.sector) rows.push(["Sector", f.sector + (f.industry ? ", " + f.industry : "")]);
    if (f.listed) rows.push(["Listed", fdate(f.listed)]); }
  const differs = f && ((f.franking_pct != null && f.last_dividend != null && Math.abs((l.franking_pct || 0) - f.franking_pct) >= 1) || (f.yield_pct && Math.abs((l.yield_pct || 0) - f.yield_pct) >= 0.1));
  return `<div class="asxbox"><div class="eyebrow">From the ASX${f && f.fetched ? ", " + esc(f.fetched) : ""}</div>${f ? (f.description ? `<p class="summary" style="margin:4px 0 8px">${esc(f.description)}</p>` : "")
      + `<dl class="kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd style="font-family:inherit">${esc(v)}</dd>`).join("")}</dl>` : `<p class="muted" style="margin:4px 0">No ASX details on file for this holding yet.</p>`}
    <div class="acts no-print" style="margin-top:8px">${FN ? `<button type="button" class="btn small" id="asx-refresh">Get the latest from the ASX</button>` : ""}${differs && !state.readOnly ? ` <button type="button" class="btn small primary" id="asx-use">Use the ASX's yield and franking in this portfolio</button>` : ""}</div></div>`; }
function renderDiversification(pf){
  if (!pf.lines.length) { sel("divtiles").innerHTML = ""; ["secstack","regstack","seclegend","reglegend","divflags"].forEach(id => sel(id).innerHTML = ""); return; }
  const d = diversification(pf);
  sel("divtiles").innerHTML = [["Effective holdings", d.effective == null ? "–" : d.effective.toFixed(1), `${pf.lines.length} lines, counted as if equally weighted`],
    ["Largest holding", fmtP(d.top ? d.top.weight_pct : null, 1), d.top ? esc(d.top.name) : ""], ["Top five", fmtP(d.top5, 0), "share in the five largest lines"],
    ["Single companies", `${d.direct}`, `${fmtP(d.directShare, 0)} of the portfolio, ${d.directSectors} sector${d.directSectors === 1 ? "" : "s"}`]].map(([k,v,s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  const draw = (id, lid, items) => { sel(id).innerHTML = items.map(([k,v],i) => `<span style="width:${v}%;background:${SECTOR_COLORS[i % SECTOR_COLORS.length]}" data-l="${esc(k)}: ${fmtP(v)}"></span>`).join("");
    sel(id).querySelectorAll("span").forEach(el => { el.onmousemove = e => showTip(e, el.dataset.l); el.onmouseleave = hideTip; });
    sel(lid).innerHTML = items.map(([k,v],i) => `<span><i style="background:${SECTOR_COLORS[i % SECTOR_COLORS.length]}"></i>${esc(k)} <span class="mono">${fmtP(v)}</span></span>`).join(""); };
  draw("secstack", "seclegend", d.sector); draw("regstack", "reglegend", d.region);
  sel("divflags").innerHTML = d.flags.length ? d.flags.map(f => `<span class="flag">${esc(f)}</span>`).join("") : `<span class="chip good">No concentration flags against the engine's rules</span>`;
}
function seriesGrowth(key, bal){ const sr = (DATA.history.series||{})[key]; if (!sr) return null; let v = bal; return sr.map(r => v *= 1 + (r||0)); }
function renderBacktest(pf){
  const H = DATA.history; const bal = pf.balance; const bt = pf.lines.length ? computeBacktest(pf) : null;
  if (!bt) { sel("bttiles").innerHTML = ""; sel("btchart").innerHTML = `<div class="muted">Add holdings to see the backtest.</div>`; sel("btlegend").innerHTML = sel("btnote").innerHTML = ""; return; }
  sel("bt-title").textContent = `If ${fmtM(bal)} had been invested ${Math.round(bt.years)} years ago`;
  sel("bttiles").innerHTML = [["Worth today", fmtM(bt.end), `from ${fmtM(bal)} in ${H.months[0]}`], ["Per year", fmtS(bt.cagr*100), "compound annual growth, dividends reinvested, before fees and tax"],
    ["Worst fall", fmtP(bt.mdd*100,0), "largest peak-to-trough drop along the way"], ["Best 12 months", fmtS((bt.best||0)*100), "and worst: " + fmtS((bt.worst||0)*100)],
    ["On stand-ins", fmtP(bt.standShare,0), bt.standShare > 0 ? "share of the result from index ETFs standing in for younger holdings" : "every holding has its own full history"]].map(([k,v,s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  const asx = seriesGrowth("VAS.AX", bal), cash = seriesGrowth(H.class_proxy && H.class_proxy.cash, bal), world = seriesGrowth("VGS.AX", bal);
  const lines = [["This portfolio", bt.values, "var(--primary)", 2.4], ["Australian shares (VAS)", asx, cssColor("aus_equity"), 1.3], ["World shares (VGS)", world, cssColor("intl_equity"), 1.3], ["Cash ETF", cash, cssColor("cash"), 1.3]].filter(x => x[1]);
  const W = 900, Hh = 300, padL = 64, padR = 16, padT = 12, padB = 28, n = H.months.length;
  const all = lines.flatMap(x => x[1]); const lo = Math.min(bal, ...all) * 0.95, hi = Math.max(...all) * 1.03;
  const X = i => padL + i/(n-1)*(W-padL-padR), Y = v => padT + (1 - (v-lo)/(hi-lo))*(Hh-padT-padB);
  const raw = (hi-lo)/5, mag = Math.pow(10, Math.floor(Math.log10(raw))), step = [1,2,2.5,5,10].map(x => x*mag).find(x => x >= raw);
  let grid = ""; for (let v = Math.ceil(lo/step)*step; v <= hi; v += step) grid += `<line x1="${padL}" x2="${W-padR}" y1="${Y(v)}" y2="${Y(v)}" stroke="var(--line)" stroke-width="1"/><text x="${padL-6}" y="${Y(v)+4}" text-anchor="end" font-size="11" fill="var(--faint)">${fmtM(v)}</text>`;
  let xl = ""; for (let i = 0; i < n; i += 12) xl += `<text x="${X(i)}" y="${Hh-8}" text-anchor="middle" font-size="11" fill="var(--faint)">${H.months[i].slice(0,4)}</text>`;
  const paths = lines.map(([name, vals, col, sw]) => `<path d="${vals.map((v,i) => (i?"L":"M") + X(i).toFixed(1) + " " + Y(v).toFixed(1)).join(" ")}" fill="none" stroke="${col}" stroke-width="${sw}" stroke-linejoin="round"/>`).join("");
  sel("btchart").innerHTML = `<svg viewBox="0 0 ${W} ${Hh}" width="100%" role="img" aria-label="Growth of ${fmtM(bal)} over ${Math.round(bt.years)} years">${grid}${xl}${paths}</svg>`;
  sel("btlegend").innerHTML = lines.map(([name, vals, col]) => `<span><i style="background:${col}"></i>${name}: ${fmtM(vals[vals.length-1])}</span>`).join("");
  sel("btnote").innerHTML = (bt.standIns.length ? `Stand-ins: ${bt.standIns.map(x => `${esc(x.name)} used ${x.proxy} for ${x.months} of ${n} months`).join("; ")}. ` : "") + "The comparison lines put the same balance into a single ETF with no rebalancing.";
}
function renderRisk(pf){
  const m = pf.metrics; const dr = m.diversification_ratio, apc = m.avg_pairwise_correlation;
  sel("risktiles").innerHTML = [
    ["Beta to the ASX 200", m.beta_asx200 == null ? "–" : m.beta_asx200.toFixed(2), m.beta_asx200 == null ? "add holdings with price history" : `a 10% fall in Australian shares has meant about ${fmtP(Math.abs(m.beta_asx200)*10,0)} here`],
    ["Beta to world shares", m.beta_world == null ? "–" : m.beta_world.toFixed(2), "against the developed-world index ETF (VGS), unhedged"],
    ["Correlation to the ASX 200", m.correlation_asx200 == null ? "–" : m.correlation_asx200.toFixed(2), m.correlation_asx200 > 0.85 ? "moves almost in lock-step with the local market" : m.correlation_asx200 > 0.6 ? "tracks the local market fairly closely" : "only loosely tied to the local market"],
    ["Correlation of holdings", apc == null ? "–" : apc.toFixed(2), apc == null ? "" : apc > 0.5 ? "the holdings tend to rise and fall together" : apc > 0.25 ? "moderately related; some genuine diversification" : "largely independent of each other"],
    ["Diversification ratio", dr == null ? "–" : dr.toFixed(2), dr == null ? "" : `average holding volatility ${fmtP(m.weighted_avg_holding_vol_pct,0)} divided by the portfolio's ${fmtP(m.realised_volatility_pct,0)}`],
    ["Realised volatility", m.realised_volatility_pct == null ? "–" : "±" + fmtP(m.realised_volatility_pct,0), "one standard deviation of yearly moves, from daily prices"],
  ].map(([k,v,s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  const hb = m.holding_beta_asx200 || {}; const rows = pf.lines.filter(l => hb[l.ticker] != null).map(l => [l, hb[l.ticker]]).sort((a,b) => b[1] - a[1]); const maxB = Math.max(1, ...rows.map(r => Math.abs(r[1])));
  sel("betalist").innerHTML = rows.length ? rows.map(([l,b]) => `<div class="betarow"><span class="n">${esc(l.name)}</span><span class="bar"><i style="width:${Math.abs(b)/maxB*100}%;background:${b<0?"var(--good)":cssColor(l.asset_class)}"></i></span><span class="v mono">${b.toFixed(2)}</span></div>`).join("") : `<div class="muted">No price history yet.</div>`;
}

// ------------------------------------------------------------ search and filters
const filters = { cls: "", region: "", vehicle: "" };
function searchUniverse(q){
  const ql = q.toLowerCase();
  return U.filter(u => (!filters.cls || u.asset_class === filters.cls) && (!filters.region || u.region === filters.region) && (!filters.vehicle || (filters.vehicle === "direct" ? u.vehicle === "direct" : u.vehicle !== "direct")))
    .map(u => { const code = u.ticker.toLowerCase().replace(/\.(ax|xa)$/, ""), n = u.name.toLowerCase(), s = (u.sector||"").toLowerCase();
      const sc = !ql ? 1 : code === ql ? 100 : code.startsWith(ql) ? 80 : n.startsWith(ql) ? 70 : n.split(/\s+/).some(w => w.startsWith(ql)) ? 50 : (n.includes(ql) || s.includes(ql)) ? 30 : 0; return [sc, u]; })
    .filter(x => x[0] > 0).sort((a,b) => b[0] - a[0] || a[1].name.localeCompare(b[1].name)).map(x => x[1]);
}
function searchIndex(q){ const ql = q.toLowerCase(); const idx = DATA.search_index || []; const held = new Set(U.map(u => u.ticker));
  const score = i => { const s = i.s.toLowerCase(), n = i.n.toLowerCase(); const code = s.replace(/\.(ax|xa)$/, ""); if (code === ql) return 100; if (code.startsWith(ql)) return 80; if (n.startsWith(ql)) return 70; if (n.split(/\s+/).some(w => w.startsWith(ql))) return 50; if (n.includes(ql)) return 30; return 0; };
  return idx.filter(i => !held.has(i.s)).map(i => [score(i), i]).filter(x => x[0] > 0).sort((a,b) => b[0] - a[0]).slice(0, 8).map(([_, i]) => ({ symbol: i.s, name: i.n, exchange: i.e, type: i.t, sector: i.c })); }
let qTimer;
function renderResults(q){
  const held = new Set(state.lines.map(l => l.ticker)); const uni = searchUniverse(q).slice(0, q ? 12 : 40); const ext = q.length >= 2 ? searchIndex(q) : [];
  const row = (sym, name, d, cls, extra) => `<div class="result"><div><b>${esc(name)}</b> <span class="mono" style="color:var(--faint);font-size:12px">${esc(sym)}</span><div class="d">${d}</div></div><div>${held.has(sym) ? '<span class="chip neutral">in portfolio</span>' : `<button type="button" class="btn small primary" data-add="${esc(sym)}" data-cls="${cls}" ${extra?`data-type="${esc(extra.type||"")}" data-sector="${esc(extra.sector||"")}"`:""}>Add</button>`}</div></div>`;
  let html = uni.map(u => { const r = R[u.ticker] || {}; return row(u.ticker, u.name, `${label(CLASSES, u.asset_class)}, ${esc(u.sector)}, ${esc(u.region)}, ${u.vehicle}${u.twin ? ", unlisted, " + esc((u.liquidity||"").toLowerCase()) : ""}${u.status === "watchlist" ? ", watchlist" : ""}, yield ${fmtP(r.dividend_yield_pct != null ? r.dividend_yield_pct : u.yield,1)}, cost ${fmtP(u.mer,2)}, 1y ${fmtS(r.return_1y_pct)}, 5y ${fmtS(r.return_5y_pct_pa)} ${qualityChip(u.ticker)} ${consensusChip(r)}`, u.asset_class); }).join("");
  if (ext.length) html += `<div class="result" style="background:var(--surface-2)"><div class="d">Outside the engine's universe: fetched live when added</div></div>` + ext.map(x => row(x.symbol, x.name, `${esc(x.exchange)}, ${esc(x.type)}${x.sector ? ", " + esc(x.sector) : ""}`, guessClass(x.symbol, x.name, x.sector), x)).join("");
  if (!uni.length && !ext.length && q.length >= 2) html += `<div class="result"><div class="d">No match in the index. <button type="button" class="btn small" id="btn-yahoo">Search the price feed for "${esc(q)}"</button>${/^[A-Za-z0-9]{2,6}$/.test(q) ? ` <button type="button" class="btn small" id="btn-asxlook">Look up ${esc(q.toUpperCase())} on the ASX</button>` : ""}<br><span style="font-size:12px">Listed notes, hybrids and exchange-traded bonds are often only on the ASX: they are priced from it, with their asset class index standing in for history.</span></div></div>`;
  sel("results").innerHTML = html ? `<div class="results">${html}</div>` : "";
  sel("results").querySelectorAll("button[data-add]").forEach(b => b.onclick = () => addSymbol(b.dataset.add, b.dataset.cls, { type: b.dataset.type, sector: b.dataset.sector }));
  // ASX lookup: five-letter ASX codes are hybrids and notes; GSB codes are Commonwealth bonds.
  const ax = sel("btn-asxlook"); if (ax) ax.onclick = async () => { const code = q.toUpperCase(); if (state.lines.some(l => l.ticker === code + ".AX")) { toast(code + " is already in the portfolio"); return; }
    toast("Looking up " + code + " on the ASX…"); try { pushLine(await fetchAsxLine(code, /^GSB|^GTP|^TIB/.test(code) ? "fixed_income" : code.length === 5 ? "credit" : null)); } catch (e) { toast(e.message); } };
  const y = sel("btn-yahoo"); if (y) y.onclick = async () => { try { const d = await api("/search?q=" + encodeURIComponent(q)); const rs = d.results || []; if (!rs.length) { toast("Nothing found on the price feed"); return; }
      sel("results").innerHTML = `<div class="results">` + rs.map(x => row(x.symbol, x.name, `${esc(x.exchange)}, ${esc(x.type)}`, guessClass(x.symbol, x.name, ""), x)).join("") + `</div>`;
      sel("results").querySelectorAll("button[data-add]").forEach(b => b.onclick = () => addSymbol(b.dataset.add, b.dataset.cls, { type: b.dataset.type })); } catch(e) { toast(e.message); } };
}
function renderFilters(){
  const regions = [...new Set(U.map(u => u.region).filter(Boolean))].sort();
  const chip = (group, key, lbl) => `<button type="button" data-g="${group}" data-k="${esc(key)}" aria-pressed="${filters[group]===key}">${lbl}</button>`;
  sel("filters").innerHTML = chip("cls", "", "All classes") + CLASSES.map(c => chip("cls", c.key, c.label)).join("") + `<span style="width:100%"></span>` + chip("region", "", "All regions") + regions.map(r => chip("region", r, r)).join("") + `<span style="width:100%"></span>` + chip("vehicle", "", "Shares and funds") + chip("vehicle", "direct", "Single companies") + chip("vehicle", "fund", "Funds and ETFs");
  sel("filters").querySelectorAll("button").forEach(b => b.onclick = () => { filters[b.dataset.g] = b.dataset.k; renderFilters(); renderResults(sel("q").value.trim()); });
}
sel("q").oninput = () => { clearTimeout(qTimer); qTimer = setTimeout(() => renderResults(sel("q").value.trim()), 150); };
sel("q").onfocus = () => { if (!sel("results").innerHTML) renderResults(sel("q").value.trim()); };

// ------------------------------------------------------------ weight helpers and setup controls
sel("btn-norm").onclick = () => { const t = state.lines.reduce((s,l) => s + (l.weight_pct||0), 0); if (t <= 0) return; state.lines.forEach(l => l.weight_pct = +(l.weight_pct / t * 100).toFixed(2)); state.dirty = true; render(); };
sel("btn-equal").onclick = () => { if (!state.lines.length) return; const w = +(100 / state.lines.length).toFixed(2); state.lines.forEach(l => l.weight_pct = w); state.dirty = true; render(); };
sel("btn-cash").onclick = () => { const t = state.lines.filter(l => l.vehicle !== "cash").reduce((s,l) => s + (l.weight_pct||0), 0); let cash = state.lines.find(l => l.vehicle === "cash");
  if (!cash) { const u = U.find(x => x.vehicle === "cash"); cash = u ? lineFromUniverse(u) : { ticker: "CASH", name: "Cash account", asset_class: "cash", vehicle: "cash", role: "core", currency: "AUD", mer_pct: 0, yield_pct: 4.0, franking_pct: 0, sector: "Cash", region: "Australia", price_aud: 1, priced_from: "manual", weight_pct: 0, source: "universe" }; state.lines.push(cash); }
  cash.weight_pct = +Math.max(0, 100 - t).toFixed(2); state.dirty = true; render(); };
// Position sizes as the engine sets them (profiles.yaml sizing, from the house model): a single company about 2, a manager or LIC
// about 5, a core index ETF about 6, a satellite ETF or credit line 2.5, a term deposit about 9 beside 3.5 cash.
function sizeHint(l){ const z = DATA.sizing || {}; if (!z.enabled) { const u = UMAP[l.ticker]; return u ? Math.max(0.5, +u.weight_hint || 2) : 2; }
  if ((z.term_deposits || []).includes(l.ticker) || l.vehicle === "td") return +z.term_deposit_hint || 9;
  const h = l.vehicle === "etf" ? (["core", "fallback"].includes(l.role) ? +z.etf_core || 6 : +z.etf_satellite || 2.5) : +((z.hint_by_vehicle || {})[l.vehicle] || 2);
  return h * (String(state.ref).endsWith("@retirement") ? +((z.retirement_multiplier || {})[l.vehicle] || 1) : 1); }
sel("btn-rules").onclick = () => {
  // Engine-style weights: within each class, spread by weight hint, cap single companies, then scale classes to the reference target.
  const ref = DATA.saa[state.ref] || {}; const rules = DATA.diversification || {}; const byClass = {};
  state.lines.forEach(l => (byClass[l.asset_class] = byClass[l.asset_class] || []).push(l));
  const present = Object.keys(byClass); const refTot = present.reduce((s,c) => s + (ref[c]||0), 0) || 1;
  for (const c of present) { const ls = byClass[c]; const cwt = (ref[c]||0) / refTot * 100; const hints = ls.map(l => sizeHint(l)); const hs = hints.reduce((s,h) => s + h, 0);
    let w = hints.map(h => h / hs * cwt); const cap = ls.map(l => l.vehicle === "direct" ? Math.min(UMAP[l.ticker] ? +UMAP[l.ticker].max_weight || 6 : 6, rules.max_single_holding_pct || 10) : 100);
    for (let k = 0; k < 10; k++) { let ex = 0; const room = []; w.forEach((x, i) => { if (x > cap[i]) { ex += x - cap[i]; w[i] = cap[i]; } else room.push(i); }); if (ex < 1e-6 || !room.length) break; const rs = room.reduce((s,i) => s + w[i], 0) || 1; room.forEach(i => w[i] += ex * w[i] / rs); }
    ls.forEach((l, i) => l.weight_pct = +w[i].toFixed(2)); }
  const t = state.lines.reduce((s,l) => s + l.weight_pct, 0); if (t > 0) state.lines.forEach(l => l.weight_pct = +(l.weight_pct / t * 100).toFixed(2)); state.dirty = true; render(); toast("Weighted the way the engine would for the " + label(DATA.targets, state.ref).toLowerCase() + " target"); };
sel("pname").oninput = () => { state.name = sel("pname").value; state.dirty = true; sel("ptitle").textContent = state.name || "A new portfolio"; updateSaveNote(); saveDraft(); trackSoon(); };
sel("pbal").onchange = () => { const b = parseBalance(sel("pbal").value); if (!b) { toast("Enter a balance of at least $1,000"); return; } state.balance = b; sel("pbal").value = b.toLocaleString("en-AU"); state.dirty = true; render(); };
sel("pref").innerHTML = (DATA.targets || DATA.profiles).map(p => `<option value="${p.key}">${p.label} (${p.sub})</option>`).join(""); sel("pref").value = state.ref;
sel("pref").onchange = () => { state.ref = sel("pref").value; render(); };
// Base portfolios: the engine's model for a stage of life and a risk profile, at the balance tier the balance above falls in.
sel("bstage").innerHTML = (DATA.stages || []).map(x => `<option value="${x.key}">${esc(x.label)}${x.sub ? " (" + esc(x.sub) + ")" : ""}</option>`).join("");
sel("bprof").innerHTML = DATA.profiles.map(p => `<option value="${p.key}">${p.label} (${p.sub})</option>`).join("");
sel("bstage").value = (DATA.stages || []).some(x => x.key === "accumulation") ? "accumulation" : ((DATA.stages || [])[0] || {}).key; sel("bprof").value = "balanced";
const refFor = (profile, stage) => DATA.saa[profile + "@" + stage] ? profile + "@" + stage : profile;
function findModel(stage, prof, tier){ const ms = DATA.models || []; return ms.find(m => m.stage === stage && m.tier === tier && (m.requested || []).includes(prof)) || ms.find(m => m.stage === stage && m.tier === tier && m.profile === prof) || null; }
function updateBaseNote(){ const stage = sel("bstage").value, prof = sel("bprof").value, tier = tierFor(state.balance); const m = findModel(stage, prof, tier); const T = DATA.tiers.find(t => t.key === tier) || {};
  if (!m) { sel("bnote").textContent = "No base portfolio for this combination."; return; }
  let t = m.house ? `Loads the ${m.house.label} (${m.house.source}) for ${T.label || tier} balances (your ${fmtM(state.balance)} falls in that band): ${m.lines.length} holdings at the model's own weights, sized to your balance, with each holding's role in the model.`
    : `Loads the ${label(DATA.profiles, m.profile)} ${label(DATA.stages, stage).toLowerCase()} portfolio for ${T.label || tier} balances (your ${fmtM(state.balance)} falls in that band): ${m.lines.length} holdings, sized to your balance.`;
  if (m.profile !== prof) t += ` ${label(DATA.stages, stage)} caps the risk profile at ${label(DATA.profiles, m.profile)}, so that is the portfolio loaded.`;
  sel("bnote").textContent = t; }
sel("bstage").onchange = updateBaseNote; sel("bprof").onchange = updateBaseNote;
sel("btn-load").onclick = () => { const stage = sel("bstage").value, prof = sel("bprof").value; const mo = findModel(stage, prof, tierFor(state.balance)); if (!mo) { toast("No base portfolio for this combination"); return; }
  if (state.lines.length && !confirm("Replace the current holdings with this base portfolio? Undo will bring them back.")) return;
  state.lines = mo.lines.map(x => { const u = UMAP[x.ticker]; const l = u ? lineFromUniverse(u) : null; if (!l) return null; l.weight_pct = +x.weight_pct.toFixed(2); l.sleeve = x.sleeve || ""; return l; }).filter(Boolean);
  state.ref = refFor(mo.profile, mo.stage); sel("pref").value = state.ref; if (!state.name) { state.name = mo.label; sel("pname").value = state.name; } state.dirty = true; state.readOnly = false; render(); toast("Loaded " + mo.label + ". Change anything you like; Undo goes back."); };
sel("btn-new").onclick = () => { Object.assign(state, { id: null, name: "", lines: [], isPublic: false, readOnly: false, ownerId: null, ticker: null, dirty: false, notes: "" }); sel("pname").value = ""; sel("readonly").hidden = true; history.replaceState(null, "", location.pathname); render(); toast("New blank portfolio. Undo brings the previous one back."); };
sel("btn-print").onclick = () => window.print();
sel("btn-xlsx").onclick = () => { if (typeof XLSX === "undefined") { toast("The spreadsheet library did not load"); return; } clearTimeout(trackT); track(); const pf = compute(); const m = pf.metrics; const pc = m.platform; const wb = XLSX.utils.book_new();
  const summary = [["Model Portfolio Lab: your portfolio", state.name||""], ["Balance", pf.balance], ["Prices as of", DATA.as_of], ["Compared against", label(DATA.targets, state.ref) + " long-run target"], ["Growth %", m.growth_pct/100], ["Defensive %", m.defensive_pct/100], ["Holdings", m.holdings], ["Weighted MER", m.weighted_mer_pct/100], ["Investment fees p.a.", m.investment_fees_per_year],
    ["Platform", pc.label], ["Product", pc.product], ["Account type", pc.accountLabel || ""], ["Investment menu", pc.menuLabel], ["Platform administration fee p.a.", pc.admin], ["Other platform fees p.a.", pc.other], ["Total platform cost p.a.", pc.total], ["Platform rate card", (pc.as_of || "") + (pc.verified ? "" : " (not yet confirmed against a current fee document)")], ["Platform fee document", pc.source_url || pc.source || ""],
    ["Total ongoing cost %", m.total_ongoing_cost_pct/100], ["Initial brokerage", m.initial_brokerage], ["Cash yield", m.weighted_yield_pct/100], ["Income p.a.", m.income_per_year], ["Franking credits p.a.", m.franking_credits_per_year], ["Grossed-up yield", m.grossed_up_yield_pct/100],
    ["Weighted 3y return p.a.", m.weighted_return_3y_pct/100], ["Weighted 5y return p.a.", m.weighted_return_5y_pct/100], ["Weighted 10y return p.a.", m.weighted_return_10y_pct/100], ["Realised volatility (1y)", (m.realised_volatility_pct||0)/100], ["Trailing 1y return", (m.trailing_1y_return_pct||0)/100], ["Beta to ASX 200", m.beta_asx200 ?? ""], ["Beta to world shares", m.beta_world ?? ""], ["Average correlation between holdings", m.avg_pairwise_correlation ?? ""], ["Diversification ratio", m.diversification_ratio ?? ""], ["", ""],
    ["Portfolio rationale", state.notes || ""], ["", ""], ["Illustrative only; not financial advice. Returns are history, not forecasts. Analyst consensus is the Yahoo Finance aggregate, not licensee research.", ""]];
  const ws1 = XLSX.utils.aoa_to_sheet(summary); ws1["!cols"] = [{ wch: 38 }, { wch: 70 }]; XLSX.utils.book_append_sheet(wb, ws1, "Summary");
  const hold = [["Ticker", "Holding", "Asset class", "Vehicle", "Sector", "Region", "Role in the model", "Weight", "Dollars", "Units", "Price (AUD)", "MER", "Yield", "Franking", "Income p.a.", "1y", "3y pa", "5y pa", "10y pa", "Analyst view", "Analysts", "Verdict", "Source", "Basis of advice"]].concat(pf.lines.map(l => { const r = R[l.ticker]||{}; const q = DATA.quality[l.ticker]||{}; return [l.ticker, l.name, label(CLASSES, l.asset_class), l.vehicle, l.sector, l.region, l.sleeve || "", (l.weight_pct||0)/100, l.dollars, l.units, l.price_aud, (l.mer_pct||0)/100, (l.yield_pct||0)/100, (l.franking_pct||0)/100, (l.dollars||0)*(l.yield_pct||0)/100, r.return_1y_pct==null?null:r.return_1y_pct/100, r.return_3y_pct_pa==null?null:r.return_3y_pct_pa/100, r.return_5y_pct_pa==null?null:r.return_5y_pct_pa/100, r.return_10y_pct_pa==null?null:r.return_10y_pct_pa/100, r.consensus_label||"", r.analysts||"", q.verdict||"", l.source, boaText(l)]; }));
  const ws2 = XLSX.utils.aoa_to_sheet(hold); ws2["!cols"] = [{wch:10},{wch:34},{wch:22},{wch:8},{wch:18},{wch:16},{wch:26},{wch:8},{wch:12},{wch:9},{wch:10},{wch:7},{wch:7},{wch:8},{wch:11},{wch:7},{wch:7},{wch:7},{wch:7},{wch:14},{wch:8},{wch:14},{wch:9},{wch:90}]; XLSX.utils.book_append_sheet(wb, ws2, "Holdings");
  const boa = [["Basis of advice", state.name || ""], ["Portfolio rationale", state.notes || ""], ["", ""], ["Ticker", "Holding", "Asset class", "Weight", "Dollars", "Status", "Basis of advice"]]
    .concat(pf.lines.map(l => [l.ticker, l.name, label(CLASSES, l.asset_class), (l.weight_pct||0)/100, l.dollars, l.boa_ai ? "AI draft in house style: check before use" : l.boa_custom ? "Written" : "Automatic draft: complete before use", boaText(l)]));
  const ws3 = XLSX.utils.aoa_to_sheet(boa); ws3["!cols"] = [{wch:10},{wch:34},{wch:22},{wch:8},{wch:12},{wch:30},{wch:120}]; XLSX.utils.book_append_sheet(wb, ws3, "Basis of advice");
  const plat = [["Platform", "Product", "Account type", "Menu", "Administration p.a.", "Other platform fees p.a.", "Total p.a.", "% of balance", "Rate card", "Confirmed", "Fee document"]].concat(platformRows(pf).map(r => r.unpriced ? [r.label, r.product, r.accountLabel || "", r.menuLabel, null, null, null, null, r.as_of || "", "rate not published", r.source_url || ""] : [r.label, r.product, r.accountLabel || "", r.menuLabel, r.admin, r.other, r.total, r.total / pf.balance, r.as_of || "", r.verified ? "yes" : "to confirm", r.source_url || r.source || ""]));
  const chk = [["Severity", "Finding", "Why it matters"]].concat(checkPortfolio(pf).map(f => [f.sev, f.title, f.why]));
  const ws5 = XLSX.utils.aoa_to_sheet(chk); ws5["!cols"] = [{wch:10},{wch:60},{wch:110}]; XLSX.utils.book_append_sheet(wb, ws5, "Portfolio check");
  if (AI.result && AI.result.result) { const x = AI.result.result; const air = [["AI review", AI.at || ""], ["Model", AI.result.model || ""], ["General information, not advice", ""], [], ["Summary", x.summary || ""]].concat((x.strengths || []).map(s => ["Strength", s])).concat([[], ["Priority", "Suggestion", "Change", "Why", "Trade-off"]]).concat((x.suggestions || []).map(s => [s.priority, s.title, s.change, s.why, s.tradeoff])).concat([[]]).concat((x.questions || []).map(q => ["Ask the client", q]));
    const ws6 = XLSX.utils.aoa_to_sheet(air); ws6["!cols"] = [{wch:14},{wch:40},{wch:60},{wch:70},{wch:50}]; XLSX.utils.book_append_sheet(wb, ws6, "AI review"); }
  const ws4 = XLSX.utils.aoa_to_sheet(plat); ws4["!cols"] = [{wch:18},{wch:30},{wch:20},{wch:22},{wch:16},{wch:18},{wch:12},{wch:11},{wch:20},{wch:11},{wch:60}]; XLSX.utils.book_append_sheet(wb, ws4, "Platform comparison");
  XLSX.writeFile(wb, `my_portfolio_${(state.name||"portfolio").replace(/[^a-z0-9]+/gi, "_").toLowerCase()}.xlsx`); toast("Downloaded, with the basis of advice for every holding"); };

// ------------------------------------------------------------ import a model from Excel or CSV
// Reads any sheet with a column of codes and a column of weights, dollar values or units, including two or more portfolios
// set side by side (each with its own Code column, such as an accumulation and a pension model). Codes can be ASX codes,
// price-feed tickers, IRESS or Morningstar style codes with an exchange suffix (PANW.NAS, GTT.PAR, LUN.TSX, PRY.MTA,
// YLDX.CXA, VEU.ASX), prefixed codes (NASDAQ:PANW), Bloomberg codes (PANW US), APIR codes, HUB24 codes, CMA and TERM.
// Nothing is dropped silently: every row with a weight is imported or listed in the note.
const IMP = { wb: null, file: "", opts: [] };
const CLASS_WORDS = [[/australian\s*(equit|share)|aus(tralian)?\s+equit|domestic equit|australian direct|australian funds|australian listed/i, "aus_equity"], [/international|global|overseas|world|emerging/i, "intl_equity"],
  [/infrastructure|property|reit|real asset/i, "infrastructure"], [/alternative|gold|commodit|private/i, "alternatives"], [/fixed (income|interest)|\bbonds?\b/i, "fixed_income"], [/credit|hybrid/i, "credit"], [/\bcash\b|term deposit/i, "cash"]];
const classFromText = t => { for (const [re, k] of CLASS_WORDS) if (re.test(String(t || ""))) return k; return null; };
const DEFENSIVE_HEAD = /^(defensive|defensive assets|income assets|fixed interest and cash|cash and fixed interest|defensive income)\b/i;
// Within a "Defensive" section the row's own sleeve says what it is.
function defensiveClass(t){ t = String(t || "");
  if (/\bcash\b|term dep|^term\b|\btd\b|at call/i.test(t)) return "cash";
  if (/government|treasury|\bbonds?\b|fixed (income|interest)|absolute return|aggregate/i.test(t)) return "fixed_income";
  if (/hybrid|sub(ordinated)?\s*debt|credit|\bnotes?\b|\bmci\b|mutual capital|capital notes?|loan|private debt|high yield|floating|non.?bank/i.test(t)) return "credit";
  return null; }
const cellNum = v => { if (v == null || v === "") return null; if (typeof v === "number") return v; const s = String(v).replace(/[$,\s]/g, ""); const n = parseFloat(s.replace(/%$/, "")); return isFinite(n) ? n : null; };
// Exchange suffixes and Bloomberg exchange codes -> the price feed's suffix ("" is a US listing).
const EXCH = { ASX: ".AX", AX: ".AX", AU: ".AX", AT: ".AX", CXA: ".XA", CHA: ".XA", XA: ".XA", CBOE: ".XA",
  NAS: "", NSQ: "", NASDAQ: "", NMS: "", NYS: "", NYSE: "", NYQ: "", ARC: "", ARCA: "", AMEX: "", ASE: "", BATS: "", US: "", UN: "", UW: "", UQ: "", N: "", O: "",
  PAR: ".PA", EPA: ".PA", FP: ".PA", PA: ".PA", MTA: ".MI", MIL: ".MI", BIT: ".MI", IM: ".MI", MI: ".MI",
  TSX: ".TO", TOR: ".TO", TO: ".TO", CN: ".TO", CT: ".TO", TSXV: ".V", CVE: ".V", V: ".V",
  LSE: ".L", LON: ".L", LN: ".L", L: ".L", XETRA: ".DE", XET: ".DE", ETR: ".DE", GER: ".DE", GY: ".DE", DE: ".DE", FRA: ".F", F: ".F",
  AMS: ".AS", AEX: ".AS", NA: ".AS", AS: ".AS", SWX: ".SW", VTX: ".SW", SIX: ".SW", SW: ".SW", NZX: ".NZ", NZE: ".NZ", NZ: ".NZ",
  HKG: ".HK", HKEX: ".HK", HK: ".HK", TYO: ".T", TSE: ".T", JPX: ".T", JP: ".T", JT: ".T", T: ".T", SGX: ".SI", SES: ".SI", SP: ".SI", SI: ".SI",
  TWSE: ".TW", TAI: ".TW", TPE: ".TW", TT: ".TW", TW: ".TW", MCE: ".MC", BME: ".MC", SM: ".MC", MC: ".MC",
  STO: ".ST", ST: ".ST", CPH: ".CO", DC: ".CO", CO: ".CO", OSL: ".OL", OL: ".OL", HEL: ".HE", FH: ".HE", HE: ".HE", BRU: ".BR", BB: ".BR", BR: ".BR",
  LIS: ".LS", LS: ".LS", VIE: ".VI", AV: ".VI", VI: ".VI", KRX: ".KS", KS: ".KS" };
// A code in any of the forms above -> { kind: listed | apir | cash | td, code, exch, cands: price-feed symbols to try in order }.
function normCode(raw){
  let s = String(raw ?? "").trim().toUpperCase().replace(/\s+(EQUITY|ETF)$/, "").replace(/\s+/g, " ");
  if (!s || s.length > 24) return null;
  if (/^(CMA|CASH|CASH ACCOUNT|HUB24 CASH|CASH AT CALL|PLATFORM CASH)$/.test(s)) return { kind: "cash", code: "CMA", exch: null, cands: ["CMA"] };
  if (/^(TERM|TD|TERM DEPOSIT|TD\d{1,2}|TERM DEP\w*)$/.test(s)) return { kind: "td", code: s, exch: null, cands: ["TD12"] };
  if (/^[A-Z]{3}\d{4}[A-Z]{2}$/.test(s)) return { kind: "apir", code: s, exch: null, cands: [s] };
  let base = null, ex = null, m;
  if ((m = s.match(/^([A-Z]{1,6}):\s*([A-Z0-9\-]{1,7})$/))) { ex = m[1]; base = m[2]; }          // ASX:BHP, NASDAQ:PANW
  else if ((m = s.match(/^([A-Z0-9\-]{1,7})\.([A-Z]{1,6})$/))) { base = m[1]; ex = m[2]; }      // PANW.NAS, VEU.ASX, GTT.PA
  else if ((m = s.match(/^([A-Z0-9\-]{1,7}) ([A-Z]{2})$/))) { base = m[1]; ex = m[2]; }         // Bloomberg: PANW US, BHP AU
  else if (/^[A-Z0-9]{1,7}$/.test(s) && /[A-Z]/.test(s) || /^\d{4}$/.test(s)) base = s;
  else return null;
  if (ex != null && !(ex in EXCH)) return null;
  const suf = ex == null ? null : EXCH[ex];
  if (suf == null) return { kind: "listed", code: base, exch: null, cands: [base + ".AX", base + ".XA", base] };
  return { kind: "listed", code: base, exch: suf, cands: suf === ".AX" ? [base + ".AX", base + ".XA"] : suf === ".XA" ? [base + ".XA", base + ".AX"] : [base + suf] };
}
const looksCode = v => !!normCode(v);
const IMP_HEAD = { code: /^(asx\s*)?(code|ticker|symbol|security code|stock code|asx code|apir( code)?|investment code|holding code|hub24 code|ticker code)$/i,
  name: /^(name|description|security( name)?|investment( name)?|holding( name)?|fund( name)?|company|company\s*\/\s*fund|company name|stock|issuer)$/i,
  w: /(alloc|weight|target %|proportion|model\s*%|% of (portfolio|total)|portfolio %|^%$|^% ?alloc)/i, v: /(market value|^value|amount|balance|\$ ?value|allocation \$|\$$)/i,
  u: /^(units|quantity|qty|no\.? of (units|shares)|shares held|holding units)$/i, cls: /(asset class|^class$|category)/i,
  sleeve: /(sleeve|^sector|segment|theme|^role)/i, veh: /^(type|vehicle|structure|security type|instrument|investment type)$/i,
  yld: /yield/i, mer: /\b(mer|icr|management (fee|cost)|fees? %|expense)\b/i };
// Every block of holdings on a sheet: one per Code column in the header row, running from just after the previous block's
// headers to the next block. Each block reads its own columns, section headings, label (text above the header) and FUM.
function findBlocks(rows){
  for (let i = 0; i < Math.min(rows.length, 40); i++) { const r = (rows[i] || []).map(c => String(c ?? "").trim());
    const codes = r.map((h, j) => IMP_HEAD.code.test(h) ? j : -1).filter(j => j >= 0); if (!codes.length) continue;
    const width = Math.max(r.length, ...rows.slice(i, i + 200).map(x => (x || []).length));
    const los = codes.map((c, k) => { if (k === 0) return 0; let lo = c; for (let j = c - 1; j > codes[k - 1]; j--) if (!r[j]) { lo = j + 1; break; } return lo; });
    return codes.map((c, k) => { const lo = los[k], hi = k + 1 < codes.length ? los[k + 1] - 1 : width - 1;
      const f = (re, not) => { for (let j = lo; j <= hi; j++) if (j !== c && re.test(r[j]) && !(not && not.test(r[j]))) return j; return -1; };
      const b = { header: i, lo, hi, code: c, name: f(IMP_HEAD.name), w: f(IMP_HEAD.w, /\$|price|income|yield|growth|return|tsr/i), v: (() => { const strong = f(/(market value|^value|current value|holding value|allocation \$|amount|balance)/i, /%|income|mer|fee|price|cost|unit|target|nav/i); return strong >= 0 ? strong : f(IMP_HEAD.v, /%|income|mer|fee|price|cost|unit|target|nav|cap/i); })(), u: f(IMP_HEAD.u), cls: f(IMP_HEAD.cls),
        sleeve: f(IMP_HEAD.sleeve), veh: f(IMP_HEAD.veh), yld: f(IMP_HEAD.yld, /\$|income/i), mer: f(IMP_HEAD.mer, /\$/), label: "", fum: null };
      const words = []; let last = -1;
      for (let y = 0; y < i; y++) { const row = rows[y] || []; for (let j = lo; j <= hi; j++) if (row[j] != null && row[j] !== "") last = y; }
      if (last >= 0) { const t = []; for (let j = lo; j <= hi; j++) { const v = (rows[last] || [])[j]; if (v != null && v !== "" && cellNum(v) == null) t.push(String(v).trim()); }
        const head = t.join(" "); if (t.length === 1 && head.length < 40) b.section0 = DEFENSIVE_HEAD.test(head) ? "defensive" : (/^(australian|international|global|overseas|domestic|property|infrastructure|fixed|credit|cash|alternative|hybrid|real asset)/i.test(head) && /equit|share|propert|infrastructure|interest|income|credit|cash|alternative|hybrid|asset|bond/i.test(head) ? classFromText(head) : null) || null; if (!b.section0) delete b.section0; }
      for (let y = 0; y < i; y++) { const row = rows[y] || []; for (let j = lo; j <= hi; j++) { const v = row[j]; if (v == null || v === "") continue;
        if (typeof v === "string" && /^(fum|balance|portfolio (value|balance)|amount( invested)?|total( value)?|investment amount|account balance|value)$/i.test(v.trim())) {
          for (let x = j + 1; x <= hi; x++) { const n = cellNum(row[x]); if (n != null && n > 1000) { b.fum = n; break; } } continue; }
        if (typeof v === "string" && v.trim().length > 1 && cellNum(v) == null) { const t = v.trim();
          if (y === last && b.section0) continue;   // the section heading just above the header row, not part of the label
          if (!words.includes(t)) words.push(t); } } }
      b.label = words.join(", "); return b; }); }
  // No header row: the code column is the one with most code-like cells; the weight column is the numeric one summing nearest 100 or 1.
  const width = Math.max(0, ...rows.slice(0, 200).map(r => (r || []).length)); let code = -1, best = 0;
  for (let j = 0; j < width; j++) { const n = rows.filter(r => r && looksCode(r[j]) && /[A-Z]/i.test(String(r[j]))).length; if (n > best) { best = n; code = j; } }
  if (code < 0 || best < 2) return [];
  let w = -1, gap = Infinity;
  for (let j = 0; j < width; j++) { if (j === code) continue; const vals = rows.filter(r => r && looksCode(r[code])).map(r => cellNum(r[j])).filter(v => v != null); if (vals.length < best * 0.6) continue; const sum = vals.reduce((a, b) => a + b, 0); const g = Math.min(Math.abs(sum - 100), Math.abs(sum - 1) * 100); if (g < gap) { gap = g; w = j; } }
  return [{ header: -1, lo: 0, hi: width - 1, code, name: -1, w, v: -1, u: -1, cls: -1, sleeve: -1, veh: -1, yld: -1, mer: -1, label: "", fum: null }]; }
function parseBlock(rows, b){
  const items = [], unread = [], noweight = []; let section = b.section0 || null;
  const textIn = r => { const t = []; for (let j = b.lo; j <= Math.min(b.hi, r.length - 1); j++) { const x = r[j]; if (x != null && String(x).trim() !== "") t.push(String(x).trim()); } return t; };
  for (let i = b.header + 1; i < rows.length; i++) { const r = rows[i] || []; const raw = String(r[b.code] ?? "").trim();
    const nums = [b.w, b.v, b.u].map(j => j >= 0 ? cellNum(r[j]) : null); const hasNum = nums.some(x => x != null && x !== 0);
    const n = raw ? normCode(raw) : null;
    if (!raw || !n || (!hasNum && (classFromText(raw) || DEFENSIVE_HEAD.test(raw)))) {   // a section heading such as "Australian equities", "Defensive" or "Cash"
      const text = textIn(r); const t = text.filter(x => cellNum(x) == null).join(" ");
      if (text.length && text.length <= 3 && t) { if (DEFENSIVE_HEAD.test(t)) { section = "defensive"; continue; } const k = classFromText(t); if (k) { section = k; continue; } }
      if (raw && hasNum && !/^total/i.test(raw)) unread.push(raw);
      continue; }
    if (/^total/i.test(raw)) continue;
    if (!hasNum && n.kind !== "cash" && n.kind !== "td") { if (!/^(code|ticker|symbol)$/i.test(raw)) noweight.push(raw); continue; }
    const name = b.name >= 0 ? String(r[b.name] ?? "").trim() : ""; const sleeve = b.sleeve >= 0 ? String(r[b.sleeve] ?? "").trim() : "";
    let cls = b.cls >= 0 ? classFromText(r[b.cls]) : null;
    if (!cls) cls = section === "defensive" ? (defensiveClass(sleeve) || defensiveClass(name)) : (section || defensiveClass(sleeve));
    items.push({ raw, n, name, sleeve, w: nums[0], v: nums[1], u: nums[2], cls, yld: b.yld >= 0 ? cellNum(r[b.yld]) : null, mer: b.mer >= 0 ? cellNum(r[b.mer]) : null, veh: b.veh >= 0 ? String(r[b.veh] ?? "").trim() : "" }); }
  // Yields and fees written as fractions (0.0535) become percentages; a whole column is one or the other.
  // A fee column of fractions tops out near 0.03 (3%) and a yield column near 0.2 (20%); in percentage points they are larger.
  for (const [k, lim] of [["yld", 0.2], ["mer", 0.03]]) { const vals = items.map(it => it[k]).filter(v => v != null && v !== 0); if (vals.length && Math.max(...vals.map(Math.abs)) <= lim) items.forEach(it => { if (it[k] != null) it[k] = +(it[k] * 100).toFixed(4); }); }
  return { items, unread, noweight }; }
function matchCode(n, it = {}){
  if (!n) return null;
  const raw = String(it.raw || "").toUpperCase();
  const h = U.find(u => { const hc = String(u.hub24_code || "").toUpperCase(); return hc && (hc === raw || hc === n.code && n.exch == null && n.kind !== "listed"); }); if (h) return { ticker: h.ticker, src: "universe" };
  // A bare code in an international section is tried as an overseas listing first; otherwise as an ASX code first.
  const cands = n.kind === "listed" && n.exch == null && it.cls === "intl_equity" ? [n.code, n.code + ".AX", n.code + ".XA"] : n.cands;
  for (const t of cands) if (UMAP[t]) return { ticker: t, src: "universe" };
  const idx = DATA.search_index || []; for (const t of cands) { const x = idx.find(i => i.s.toUpperCase() === t); if (x) return { ticker: x.s, src: "index", meta: { type: x.t, sector: x.c } }; }
  return null; }
const titleCase = s => String(s || "").toLowerCase().replace(/\b([a-z])/g, c => c.toUpperCase()).replace(/\b(Ltd|Limited|Plc|Inc)\.?$/i, m => m.charAt(0).toUpperCase() + m.slice(1).toLowerCase()).replace(/\.$/, "");
function vehicleFromText(t, cls){ t = String(t || "").toLowerCase();
  if (/^etf/.test(t)) return "etf"; if (/^lic|listed investment/.test(t)) return "lic"; if (/^fund|managed fund|unlisted/.test(t)) return "fund"; if (/^cma|^cash/.test(t)) return "cash";
  if (/^direct|^share|^equity|^stock/.test(t)) return cls === "credit" ? "hybrid" : cls === "fixed_income" ? "bond" : "direct"; return null; }
// An ASX listing the price feed has no history for (listed notes, exchange-traded bonds, some hybrids): today's price from the
// ASX, with the asset class index standing in for risk and history.
async function fetchAsxLine(code, cls, meta = {}){
  const c = String(code).replace(/\.(AX|XA)$/i, "").toUpperCase();
  const d = await api("/asx?code=" + encodeURIComponent(c)); const price = d.header && d.header.priceLast;
  if (!price) throw new Error("The ASX has no price for " + c);
  const f = d.facts || {}; const sym = c + ".AX"; const name = meta.name || titleCase(d.name || c);
  const k = cls || meta.cls || ({ PR: "credit", FLC: "credit", FRG: "fixed_income" })[f.issue_type] || guessClass(sym, name, "");
  R[sym] = { ticker: sym, name, consensus_label: "no coverage", return_proxy: {}, price, price_currency: "AUD", asx: f,
    summary: [f.description, f.security && !/^ordinary fully paid$/i.test(f.security) ? "Security: " + f.security + "." : ""].filter(Boolean).join(" "),
    source: "ASX (price and facts; no price history, so the asset class index stands in)", fetched: new Date().toISOString().slice(0, 10) };
  const vehicle = vehicleFromText(meta.veh, k) || ({ ETF: "etf", PR: "hybrid", FLC: "hybrid", FRG: "bond" })[f.issue_type] || (/listed investment/i.test(f.description || "") ? "lic" : null) || (k === "credit" ? "hybrid" : k === "fixed_income" ? "bond" : "direct");
  const yld = meta.yld ?? f.yield_pct ?? null;
  return { ticker: sym, name, asset_class: k, vehicle, role: "satellite", currency: "AUD", mer_pct: meta.mer ?? 0, yield_pct: yld ?? 0, yield_source: meta.yld != null ? "sheet" : f.yield_pct != null ? "asx" : "none",
    franking_pct: f.franking_pct ?? 0, sector: meta.sleeve || f.sector || (k === "credit" ? "Hybrids and notes" : k === "fixed_income" ? "Bonds" : ""), region: "Australia", price_aud: price, priced_from: "asx", weight_pct: 0, source: "asx", sleeve: meta.sleeve || "", boa: "", boa_custom: false }; }
// A holding with no price feed at all (an unlisted fund outside the universe, a term deposit, an unpriceable listing): kept at
// the sheet's weight with the sheet's yield and fee so the portfolio still adds up, and labelled as such.
function manualLine(it, kind){
  const code = it.n ? (it.n.kind === "listed" && it.n.exch ? it.n.cands[0] : it.n.code) : String(it.raw).toUpperCase();
  const cls = it.cls || (kind === "td" || kind === "cash" ? "cash" : kind === "apir" ? "aus_equity" : "aus_equity");
  const vehicle = vehicleFromText(it.veh, cls) || (kind === "cash" ? "cash" : kind === "td" ? "td" : kind === "apir" ? "fund" : cls === "credit" ? "hybrid" : cls === "fixed_income" ? "bond" : "direct");
  return { ticker: code, name: it.name || code, asset_class: cls, vehicle, role: "satellite", currency: "AUD", mer_pct: it.mer ?? 0, yield_pct: it.yld ?? 0, yield_source: "sheet", franking_pct: 0,
    sector: it.sleeve || (vehicle === "fund" ? "Diversified fund" : vehicle === "td" || vehicle === "cash" ? "Cash" : ""), region: /\.(AX|XA)$/.test(code) || kind !== "listed" || (it.n && it.n.exch == null && it.cls !== "intl_equity") ? "Australia" : guessRegion(code, it.name),
    price_aud: kind === "td" || kind === "cash" ? 1 : null, priced_from: "manual", listed: kind === "listed", weight_pct: 0, source: "sheet", sleeve: it.sleeve || "", boa: "", boa_custom: false }; }
async function resolveItem(it){
  const n = it.n;
  if (n.kind === "cash") { const u = UMAP.CMA || U.find(x => x.vehicle === "cash"); return u ? { line: lineFromUniverse(u), how: "universe" } : { line: manualLine(it, "cash"), how: "sheet" }; }
  if (n.kind === "td") { const u = UMAP.TD12; const l = u ? lineFromUniverse(u) : manualLine(it, "td"); if (u && it.yld != null) { l.yield_pct = it.yld; l.yield_source = "sheet"; } return { line: l, how: u ? "universe" : "sheet" }; }
  const m = matchCode(n, it);
  if (m && m.src === "universe") return { line: lineFromUniverse(UMAP[m.ticker]), how: "universe" };
  if (n.kind === "apir") return { line: manualLine(it, "apir"), how: "sheet" };
  const sym = m ? m.ticker : (it.cls === "intl_equity" && n.exch == null ? n.code : n.cands[0]);
  try { return { line: await fetchLiveLine(sym, it.cls, m ? m.meta : null), how: "live" }; } catch (e) { /* no history: try the ASX, then keep the sheet's figures */ }
  if (n.exch === ".AX" || n.exch === ".XA" || (n.exch == null && /^[A-Z0-9]{2,6}$/.test(n.code))) {
    try { return { line: await fetchAsxLine(n.code, it.cls, { name: it.name, mer: it.mer, yld: it.yld, sleeve: it.sleeve, veh: it.veh }), how: "asx" }; } catch (e) { /* not on the ASX either */ } }
  return { line: manualLine(it, "listed"), how: "sheet" }; }
function readSheet(name){ return XLSX.utils.sheet_to_json(IMP.wb.Sheets[name], { header: 1, raw: true, blankrows: true, defval: null }); }
sel("impfile").onchange = async () => { const f = sel("impfile").files[0]; if (!f) return; if (typeof XLSX === "undefined") { toast("The spreadsheet library did not load"); return; }
  try { IMP.wb = XLSX.read(await f.arrayBuffer(), { type: "array" }); IMP.file = f.name.replace(/\.[^.]+$/, ""); } catch (e) { toast("Could not read that file: " + e.message); return; }
  // One option per portfolio block on each sheet, ranked by how many codes it recognises.
  IMP.opts = [];
  for (const sheet of IMP.wb.SheetNames) { const rows = readSheet(sheet); const blocks = findBlocks(rows);
    blocks.forEach((b, k) => { const p = parseBlock(rows, b); if (!p.items.length) return;
      const known = p.items.filter(it => it.n && (it.n.kind !== "listed" || matchCode(it.n, it))).length;
      const what = [b.label, b.fum ? fmtM(b.fum) : ""].filter(Boolean).join(", ");
      IMP.opts.push({ key: sheet + "|" + k, sheet, block: b, items: p.items.length, known, text: `${sheet}${blocks.length > 1 || what ? ": " + (what || "portfolio " + (k + 1)) : ""} (${p.items.length} holdings, ${known} recognised)` }); }); }
  if (!IMP.opts.length) { sel("impnote").textContent = "No holdings found in that file. The sheet needs a column headed Code, Ticker or ASX code, or a column of codes."; sel("impsheet").innerHTML = "<option>Nothing to import</option>"; sel("impsheet").disabled = true; sel("btn-import").disabled = true; return; }
  const ranked = [...IMP.opts].sort((a, b) => b.known - a.known);
  sel("impsheet").innerHTML = IMP.opts.map(o => `<option value="${esc(o.key)}">${esc(o.text)}</option>`).join(""); sel("impsheet").value = ranked[0].key; sel("impsheet").disabled = false; sel("btn-import").disabled = false;
  const multi = IMP.opts.length > IMP.wb.SheetNames.length;
  sel("impnote").textContent = `${f.name}: ${IMP.opts.length} portfolio${IMP.opts.length === 1 ? "" : "s"} found${multi ? " (more than one on a sheet, side by side)" : ""}. Choose one and press Import.`; };
sel("btn-import").onclick = async () => { if (!IMP.wb) return; const opt = IMP.opts.find(o => o.key === sel("impsheet").value); if (!opt) return;
  const rows = readSheet(opt.sheet); const b = opt.block; const p = parseBlock(rows, b);
  if (!p.items.length) { sel("impnote").textContent = "No holdings found in that portfolio."; return; }
  if (state.lines.length && !confirm(`Replace the current ${state.lines.length} holdings with the ${p.items.length} rows from "${opt.text}"? Undo will bring them back.`)) return;
  sel("btn-import").disabled = true; sel("impnote").textContent = "Importing…";
  const lines = [], how = { universe: [], live: [], asx: [], sheet: [] }; const seen = new Set(); const dupes = [];
  for (const it of p.items) { const { line: l, how: h } = await resolveItem(it);
    if (seen.has(l.ticker)) { dupes.push(it.raw); const prev = lines.find(x => x.ticker === l.ticker); if (prev) { prev._w = (prev._w || 0) + (it.w || 0); prev._v = (prev._v || 0) + (it.v || 0); } continue; } seen.add(l.ticker);
    if (it.cls && CLASSES.some(c => c.key === it.cls) && l.vehicle !== "cash") l.asset_class = it.cls;
    if (it.sleeve) l.sleeve = it.sleeve; if (!l.name || l.name === l.ticker) l.name = it.name || l.name;
    l._w = it.w; l._v = it.v; l._u = it.u; lines.push(l); how[h].push(it.raw); }
  // Weights: the weight column if there is one (fractions become percentages), otherwise dollar values, otherwise units at today's prices.
  const has = k => lines.filter(l => l[k] != null).length >= Math.max(1, lines.length * 0.6); let basis = "";
  if (has("_w")) { const sum = lines.reduce((s, l) => s + (l._w || 0), 0); const k = sum > 0 && sum <= 1.5 ? 100 : 1; lines.forEach(l => l.weight_pct = +((l._w || 0) * k).toFixed(3)); basis = "the sheet's weights"; }
  else { const val = l => l._v != null ? l._v : (l._u != null && l.price_aud ? l._u * l.price_aud : 0); const sum = lines.reduce((s, l) => s + val(l), 0);
    lines.forEach(l => l.weight_pct = sum ? +(val(l) / sum * 100).toFixed(3) : 0); basis = has("_v") ? "the sheet's dollar values" : "units at today's prices";
    if (sum > 1000 && !b.fum) { state.balance = Math.round(sum); sel("pbal").value = state.balance.toLocaleString("en-AU"); } }
  if (b.fum) { state.balance = Math.round(b.fum); sel("pbal").value = state.balance.toLocaleString("en-AU"); }
  lines.forEach(l => { delete l._w; delete l._v; delete l._u; });
  state.lines = lines; state.ticker = null; state.dirty = true;
  // The label decides the comparison target when it names a profile and a stage ("Balanced ... Pension").
  const lab = (b.label || "") + " " + opt.sheet; const prof = [...(DATA.profiles || [])].sort((x, y) => y.label.length - x.label.length).find(x => new RegExp("\\b" + x.label.replace(/ /g, "\\s*") + "\\b", "i").test(lab));
  if (prof) { const stage = /pension|retire|drawdown/i.test(lab) ? "retirement" : "accumulation"; state.ref = refFor(prof.key, stage); sel("pref").value = state.ref; }
  const nm = [IMP.file, b.label].filter(Boolean).join(", "); if (!state.name || confirm(`Name the portfolio "${nm}"?`)) { state.name = nm; sel("pname").value = state.name; }
  render(); sel("btn-import").disabled = false;
  const list = a => a.map(x => esc(x)).join(", ");
  const parts = [`Imported ${lines.length} holding${lines.length === 1 ? "" : "s"} from "${esc(opt.text.replace(/ \(\d+ holdings.*$/, ""))}", weighted by ${basis}${b.fum ? `, at the sheet's balance of ${fmtM(b.fum)}` : ""}.`];
  if (how.live.length) parts.push(`${how.live.length} fetched from the price feed (${list(how.live)}).`);
  if (how.asx.length) parts.push(`<b>${how.asx.length} priced from the ASX</b> because the price feed has no history for them (${list(how.asx)}); their asset class index stands in for risk and history.`);
  if (how.sheet.length) parts.push(`<b>${how.sheet.length} kept at the sheet's own figures</b> because no price feed carries them (${list(how.sheet)}): weight, yield and fee from the sheet, no units or history.`);
  if (p.unread.length) parts.push(`<b>Not read as codes: ${list(p.unread)}</b>. Add them by searching below.`);
  if (p.noweight.length) parts.push(`Skipped because they have no weight, value or units: ${list(p.noweight)}.`);
  if (dupes.length) parts.push(`Listed twice and combined: ${list(dupes)}.`);
  if (!how.asx.length && !how.sheet.length && !p.unread.length) parts.push("Every row was matched.");
  parts.push("Prices are today's.");
  sel("impnote").innerHTML = parts.join(" ");
  toast(`Imported ${lines.length} holdings. Undo goes back.`); };

// ------------------------------------------------------------ portfolio check (rules)
const SEV_ORDER = { high: 0, medium: 1, low: 2 };
function bestCandidate(cls, opts = {}){ const held = new Set(state.lines.map(l => l.ticker)); const q = t => (DATA.quality[t] || {}).verdict || "";
  const rank = u => (q(u.ticker) === "core" ? 0 : q(u.ticker) === "satellite" ? 1 : 2) * 10 + (u.vehicle === "etf" ? 0 : 1) * 3 + (+u.mer || 0);
  return U.filter(u => u.asset_class === cls && u.status !== "watchlist" && !held.has(u.ticker) && u.price_aud != null && !["speculative", "not recommended"].includes(q(u.ticker)) && (!opts.region || u.region === opts.region) && (!opts.maxMer || +u.mer < opts.maxMer) && (!opts.vehicle || u.vehicle === opts.vehicle)
    && !(R[u.ticker] && /Sell|Underperform/.test(R[u.ticker].consensus_label || ""))).sort((a, b) => rank(a) - rank(b))[0] || null; }
function swapLine(oldT, newT){ const i = state.lines.findIndex(l => l.ticker === oldT); if (i < 0 || !UMAP[newT]) return; const w = state.lines[i].weight_pct; const l = lineFromUniverse(UMAP[newT]); l.weight_pct = w; state.lines.splice(i, 1, l); state.dirty = true; render(); toast(`Swapped ${oldT} for ${newT}. Undo goes back.`); }
function addAt(t, w){ if (!UMAP[t] || state.lines.some(l => l.ticker === t)) return; const l = lineFromUniverse(UMAP[t]); l.weight_pct = +w.toFixed(2); state.lines.push(l); state.dirty = true; render(); toast(`Added ${t} at ${w.toFixed(1)}%. Use "Scale to 100%" to rebalance; Undo goes back.`); }
function setWeight(t, w){ const l = state.lines.find(x => x.ticker === t); if (!l) return; l.weight_pct = +w.toFixed(2); state.dirty = true; render(); }
// What part of the market a holding gives: asset class, region and segment. Used so the check and the AI only ever compare like
// with like (a small companies fund with a small companies fund, never with a broad index fund).
const GROWTH_SEGMENTS = [[/mid.?cap|ex.?20\b|ex.?50\b/i, "mid caps"], [/small|micro/i, "small companies"], [/long.?short|alpha|market neutral/i, "long/short"], [/activist|catalyst|concentrated|special situation/i, "concentrated"],
  [/emerging|asia|china|india/i, "emerging markets"], [/income|dividend|high yield|equity yield/i, "income"], [/propert|reit|real estate/i, "property"], [/infrastructure|utilit/i, "infrastructure"],
  [/tech|nasdaq|cyber|robot|semiconductor|cloud/i, "technology"], [/health|biotech|pharma/i, "healthcare"], [/gold|resource|mining|commodit/i, "resources"], [/esg|ethical|sustainab/i, "ethical"], [/quality/i, "quality"], [/hedged/i, "currency hedged"]];
const DEFENSIVE_SEGMENTS = [[/govern|treasury|commonwealth/i, "government bonds"], [/high yield/i, "high yield credit"], [/sub(ordinated)? ?debt|hybrid|capital notes?|\bmci\b|mutual capital/i, "subordinated debt and hybrids"],
  [/absolute return|unconstrained|complex|alpha/i, "absolute return"], [/floating|frn/i, "floating rate credit"], [/private (debt|credit)|loan/i, "private debt"], [/inflation/i, "inflation-linked bonds"], [/global|international/i, "global bonds"]];
function exposureOf(x){ const t = [x.name, x.sector, x.sleeve].filter(Boolean).join(" "); const growth = (CLASSES.find(c => c.key === x.asset_class) || {}).kind === "growth";
  let seg = growth ? "broad market" : "broad"; for (const [re, k] of (growth ? GROWTH_SEGMENTS : DEFENSIVE_SEGMENTS)) if (re.test(t)) { seg = k; break; }
  const cls = label(CLASSES, x.asset_class).toLowerCase().replace(/^australian/, "Australian"); const region = x.region && x.region !== "Australia" && x.asset_class !== "aus_equity" ? ", " + x.region : "";
  return { segment: seg, region: x.region || "", text: `${seg === "broad market" || seg === "broad" ? "broad " : seg + ", "}${cls}${region}` }; }
function likeForLike(l, ex){ const held = new Set(state.lines.map(x => x.ticker)); const q = t => (DATA.quality[t] || {}).verdict || "";
  return U.filter(u => u.asset_class === l.asset_class && u.vehicle === "etf" && u.status !== "watchlist" && !held.has(u.ticker) && u.price_aud != null && +u.mer < (l.mer_pct || 0) * 0.7
      && !["speculative", "not recommended"].includes(q(u.ticker)) && !(R[u.ticker] && /Sell|Underperform/.test(R[u.ticker].consensus_label || "")))
    .filter(u => { const e = exposureOf(u); return e.segment === ex.segment && (e.region === ex.region || (!e.region && !ex.region)); })
    .sort((a, b) => (+a.mer) - (+b.mer))[0] || null; }
function checkPortfolio(pf){
  const F = []; const m = pf.metrics; const bal = pf.balance; const lines = pf.lines.filter(l => (l.weight_pct || 0) > 0); if (!lines.length) return F;
  const add = (sev, title, why, actions = []) => F.push({ sev, title, why, actions });
  if (Math.abs(pf.total - 100) > 0.05) add("high", `Weights add up to ${fmtP(pf.total, 1)}`, "Every other figure assumes the weights as entered, so costs, income and risk are overstated or understated until they add to 100%.", [["Scale to 100%", () => sel("btn-norm").click()], ["Fill the gap with cash", () => sel("btn-cash").click()]]);
  // allocation against the target
  const ref = DATA.saa[state.ref] || {}; const refLabel = label(DATA.targets, state.ref);
  const refG = CLASSES.filter(c => c.kind === "growth").reduce((s, c) => s + (ref[c.key] || 0), 0);
  if (Math.abs(m.growth_pct - refG) > 10) add("high", `${fmtP(m.growth_pct, 0)} growth assets against the ${refLabel} target of ${fmtP(refG, 0)}`, `A gap this size changes the risk the portfolio carries: in a bad year for shares it would fall roughly ${m.growth_pct > refG ? "more" : "less"} than a ${refLabel.toLowerCase()} investor has agreed to. Either the target profile is wrong for this client or the mix needs moving.`);
  for (const c of CLASSES) { const d = (pf.class_weights[c.key] || 0) - (ref[c.key] || 0); if (Math.abs(d) <= 5) continue;
    if (d < 0) { const cand = bestCandidate(c.key); add("medium", `${label(CLASSES, c.key)} is ${fmtP(-d, 1)} under the target`, `The ${refLabel} target holds ${fmtP(ref[c.key] || 0, 0)} here; this portfolio holds ${fmtP(pf.class_weights[c.key] || 0, 1)}. Under-weighting a whole asset class is a large active bet and gives up the diversification that class brings.`,
      cand ? [[`Add ${cand.ticker.replace(/\.AX$/, "")} at ${(-d).toFixed(1)}%`, () => addAt(cand.ticker, -d)]] : []); }
    else { const big = lines.filter(l => l.asset_class === c.key).sort((a, b) => b.weight_pct - a.weight_pct)[0]; add("medium", `${label(CLASSES, c.key)} is ${fmtP(d, 1)} over the target`, `The ${refLabel} target holds ${fmtP(ref[c.key] || 0, 0)}; this portfolio holds ${fmtP(pf.class_weights[c.key] || 0, 1)}. Trim the largest holdings in the class, or record why the overweight is intended.`,
      big ? [[`Trim ${big.ticker.replace(/\.AX$/, "")} by ${Math.min(d, big.weight_pct).toFixed(1)}%`, () => setWeight(big.ticker, big.weight_pct - Math.min(d, big.weight_pct))]] : []); } }
  // concentration
  const d = diversification(pf);
  lines.filter(l => l.vehicle === "direct" && l.weight_pct > (DATA.diversification.max_single_holding_pct || 10)).forEach(l => add("high", `${l.name} is ${fmtP(l.weight_pct, 1)} of the portfolio`, `One company's bad news (a profit warning, a regulator, a takeover that fails) would move the whole portfolio. The engine caps a single company at ${DATA.diversification.max_single_holding_pct || 10}%.`, [[`Cut to ${DATA.diversification.max_single_holding_pct || 10}%`, () => setWeight(l.ticker, DATA.diversification.max_single_holding_pct || 10)]]));
  if (d.effective != null && d.effective < 8 && lines.length >= 3) add("medium", `Effectively ${d.effective.toFixed(1)} holdings`, "A few large lines dominate, so the portfolio behaves like a handful of bets rather than a spread. Diversified funds count as one line here, so this matters most when the large lines are single companies.");
  d.flags.filter(f => !/fewer than five/.test(f)).forEach(f => add("medium", f.charAt(0).toUpperCase() + f.slice(1), "Concentration in one sector or country ties the result to one set of risks (commodity prices, interest rates, one economy)."));
  // analyst and quality warnings
  lines.forEach(l => { const r = R[l.ticker] || {}; const q = (DATA.quality[l.ticker] || {}).verdict;
    if (/Sell|Underperform/.test(r.consensus_label || "")) { const c = bestCandidate(l.asset_class, { region: l.region }); add("high", `${l.name}: analyst consensus ${r.consensus_label}`, `${r.analysts} covering analysts lean negative. That is a prompt to re-check the reason for holding it against current research (Morgans or FNArena), not an automatic sell.`, c ? [[`Swap for ${c.ticker.replace(/\.AX$/, "")}`, () => swapLine(l.ticker, c.ticker)]] : []); }
    if (q === "not recommended") add("high", `${l.name}: quality review says not recommended`, (DATA.quality[l.ticker] || {}).note || "");
    if (q === "speculative" && l.weight_pct > 3) add("medium", `${l.name} is speculative at ${fmtP(l.weight_pct, 1)}`, "Speculative holdings belong in small positions so a total loss is survivable. Above 3% one failure is felt across the portfolio.", [["Cut to 3%", () => setWeight(l.ticker, 3)]]); });
  // cost
  // Cost, like for like only: a cheaper fund is suggested only when it gives the same exposure (asset class, region and segment:
  // small companies, income, property, infrastructure, a sector or theme, emerging markets, or the broad market). A broad index fund
  // is never offered in place of a specialist one: swapping a small companies fund for A200 changes what the portfolio owns, not just
  // what it costs. Long/short, activist and concentrated funds have no index equivalent, and listed investment companies are left out
  // because their price, franking and structure make a fee comparison with an ETF misleading.
  lines.filter(l => ["etf", "fund"].includes(l.vehicle) && (l.mer_pct || 0) >= 0.35).forEach(l => {
    const ex = exposureOf(l); if (["long/short", "concentrated", "absolute return"].includes(ex.segment)) return;
    const c = likeForLike(l, ex); if (!c) return;
    const save = ((l.mer_pct || 0) - (+c.mer || 0)) / 100 * (l.dollars || 0); if (save < 100) return;
    add("low", `Like for like: ${c.name} gives the same exposure (${ex.text}) for ${fmtP(+c.mer, 2)} a year`,
      `${l.name} costs ${fmtP(l.mer_pct, 2)}, ${fmtM(save)} a year more at this weight, for the same part of the market. ${isActive(l) ? "An active manager has to beat that market by the difference, after fees, to earn its place: keep it if there is a reason to expect it will, and record the reason in the basis of advice." : "Where two funds track the same market, the cheaper one is the better default."}`,
      [[`Swap for ${c.ticker.replace(/\.(AX|XA)$/, "")}`, () => swapLine(l.ticker, c.ticker)]]); });

  const rows = platformRows(pf).filter(r => !r.unpriced); const cur = rows.find(r => r.key === state.platform.key); const cheap = rows[0];
  if (cur && cheap && cheap.key !== cur.key && cur.total - cheap.total > 250) add("low", `${cheap.label} would cost ${fmtM(cur.total - cheap.total)} a year less than ${cur.label}`, "At this balance and with these holdings. Platform choice also depends on the investment menu, reporting, the licensee's approved product list and family group discounts, so treat this as a question to ask, not an answer.", [[`Try ${cheap.label}`, () => { state.platform = { ...state.platform, key: cheap.key, menu: "auto" }; state.dirty = true; render(); }]]);
  // overlap between index funds
  const groups = {}; lines.filter(l => l.vehicle === "etf" && l.role === "core").forEach(l => { const k = l.asset_class + "|" + l.region; (groups[k] = groups[k] || []).push(l); });
  Object.values(groups).filter(g => g.length >= 2).forEach(g => add("low", `${g.map(l => l.ticker.replace(/\.AX$/, "")).join(" and ")} overlap`, `Core index funds in the same asset class and region hold largely the same companies. Two or more add cost and complexity without adding diversification; one is usually enough.`));
  // cash, income, risk
  const cash = pf.class_weights.cash || 0; if (cash > 12 && !["conservative"].includes(state.ref.split("@")[0])) add("low", `${fmtP(cash, 0)} in cash`, "Cash above what is needed for fees, pension payments and rebalancing is a drag on long-run growth. Keep it if it is a deliberate buffer for known spending.");
  const volHint = 2 + 0.13 * refG; if (m.realised_volatility_pct != null && m.realised_volatility_pct > volHint * 1.35) add("medium", `Moves more than a typical ${refLabel.toLowerCase()} portfolio`, `Realised volatility of ±${fmtP(m.realised_volatility_pct, 0)} against roughly ±${fmtP(volHint, 0)} for a ${refLabel.toLowerCase()} mix. Concentrated or high-beta holdings usually explain it.`);
  if (m.avg_pairwise_correlation != null && m.avg_pairwise_correlation > 0.6 && lines.length >= 5) add("low", "The holdings rise and fall together", `Average correlation of ${m.avg_pairwise_correlation.toFixed(2)} between holdings: they are mostly the same bet, so the diversification on paper is less real than it looks.`);
  if (["conservative", "moderate"].includes(state.ref.split("@")[0]) && m.grossed_up_yield_pct < 3) add("low", `Grossed-up yield of ${fmtP(m.grossed_up_yield_pct, 1)}`, "For a cautious or income-focused investor, a low yield means drawing on capital to fund spending. Fully franked Australian income lifts the grossed-up yield for low-tax and pension accounts.");
  const tier = DATA.tiers.find(t => t.key === pf.tier) || {}; const tiny = lines.filter(l => l.vehicle !== "cash" && (l.dollars || 0) < (tier.min_holding || 0));
  if (tiny.length) add("medium", `${tiny.length} holding${tiny.length === 1 ? "" : "s"} under ${fmtM(tier.min_holding)}`, `${tiny.map(l => l.ticker.replace(/\.AX$/, "")).join(", ")}: at this size brokerage and admin effort outweigh the diversification each adds. Combine them or raise their weight.`);
  const drafts = pf.lines.filter(l => !l.boa_custom || l.boa_ai).length; if (drafts) add("low", `${drafts} basis of advice draft${drafts === 1 ? "" : "s"} not yet written or checked`, "Automatic and AI drafts describe the holding, not why it suits the client, and an AI draft can be wrong. Check and complete each one before the portfolio is used for advice.", [["Go to the basis of advice", () => sel("boa-section").scrollIntoView({ behavior: "smooth" })]]);
  return F.sort((a, b) => SEV_ORDER[a.sev] - SEV_ORDER[b.sev]); }
let CHECK = [];
function renderCheck(pf){ sel("check").hidden = !pf.lines.length; if (!pf.lines.length) return; CHECK = checkPortfolio(pf);
  const words = { high: "Fix", medium: "Review", low: "Consider" };
  sel("checklist").innerHTML = CHECK.length ? CHECK.map((f, i) => `<div class="find"><span class="sev ${f.sev}">${words[f.sev]}</span><div><b>${esc(f.title)}</b><div class="why">${esc(f.why)}</div>${f.actions.length && !state.readOnly ? `<div class="acts">${f.actions.map((a, j) => `<button type="button" class="btn small" data-f="${i}" data-a="${j}">${esc(a[0])}</button>`).join("")}</div>` : ""}</div></div>`).join("")
    : `<div class="find"><span class="sev good">Clear</span><div><b>No issues found by the rules</b><div class="why">Allocation is within 5 points of the target in every class, nothing is concentrated, costs are reasonable and there are no analyst or quality warnings.</div></div></div>`;
  sel("checklist").querySelectorAll("button[data-f]").forEach(b => b.onclick = () => CHECK[+b.dataset.f].actions[+b.dataset.a][1]());
  sel("ainote").textContent = !SB ? "" : user.session ? "Uses the site's AI credit; limited per account each day." : "Sign in to use the AI review."; }

// ------------------------------------------------------------ AI review
const AI = { result: null, at: null, running: false };
function aiPayload(){ const pf = compute(); const m = pf.metrics; const d = diversification(pf); const ref = DATA.saa[state.ref] || {};
  const q = t => (DATA.quality[t] || {}).verdict || "";
  return { portfolio: { name: state.name || "Untitled", balance: pf.balance, compare_against: label(DATA.targets, state.ref) + " long-run target", target_allocation_pct: ref,
      actual_allocation_pct: Object.fromEntries(CLASSES.map(c => [c.key, +(pf.class_weights[c.key] || 0).toFixed(2)])), asset_class_names: Object.fromEntries(CLASSES.map(c => [c.key, c.label])),
      platform: { name: m.platform.label, menu: m.platform.menuLabel, cost_per_year: Math.round(m.platform.total) },
      metrics: { growth_pct: +m.growth_pct.toFixed(1), defensive_pct: +m.defensive_pct.toFixed(1), weighted_fund_fee_pct: +m.weighted_mer_pct.toFixed(3), total_cost_pct: +m.total_ongoing_cost_pct.toFixed(3), cash_yield_pct: +m.weighted_yield_pct.toFixed(2), grossed_up_yield_pct: +m.grossed_up_yield_pct.toFixed(2),
        realised_volatility_pct: m.realised_volatility_pct == null ? null : +m.realised_volatility_pct.toFixed(1), beta_asx200: m.beta_asx200 == null ? null : +m.beta_asx200.toFixed(2), average_correlation: m.avg_pairwise_correlation == null ? null : +m.avg_pairwise_correlation.toFixed(2),
        effective_holdings: d.effective == null ? null : +d.effective.toFixed(1), top_five_pct: +d.top5.toFixed(1), single_companies: d.direct, sectors: d.sector.slice(0, 8), regions: d.region.slice(0, 6) },
      holdings: pf.lines.map(l => { const r = R[l.ticker] || {}; return { code: l.ticker, name: l.name, asset_class: l.asset_class, vehicle: l.vehicle, role: l.role, role_in_model: l.sleeve || "", exposure: exposureOf(l).text,
        management: isActive(l) ? "active" : l.vehicle === "etf" ? "index" : l.vehicle === "direct" ? "direct holding" : l.vehicle, advisers_reason: l.boa_custom ? String(l.boa || "").slice(0, 400) : "", weight_pct: +(l.weight_pct || 0).toFixed(2), dollars: Math.round(l.dollars || 0), fee_pct: l.mer_pct, yield_pct: l.yield_pct, franking_pct: l.franking_pct, sector: l.sector, region: l.region,
        analyst_consensus: r.consensus_label || "no coverage", analysts: r.analysts || 0, quality_verdict: q(l.ticker), volatility_1y_pct: r.volatility_1y_pct ?? null }; }),
      rule_check: CHECK.map(f => ({ severity: f.sev, finding: f.title, detail: f.why })) },
    universe_candidates: U.filter(u => u.status !== "watchlist" && u.price_aud != null && ["core", "satellite"].includes(q(u.ticker)) && !state.lines.some(l => l.ticker === u.ticker))
      .sort((a, b) => a.asset_class.localeCompare(b.asset_class) || (+a.mer - +b.mer)).slice(0, 160)
      .map(u => [u.ticker, u.name, u.asset_class, u.vehicle, +(+u.mer).toFixed(2), +(((R[u.ticker] || {}).dividend_yield_pct ?? +u.yield) || 0).toFixed(2), q(u.ticker), (R[u.ticker] || {}).consensus_label || "", exposureOf(u).text]),
    universe_candidate_columns: ["code", "name", "asset_class", "vehicle", "fee_pct", "yield_pct", "quality_verdict", "analyst_consensus", "exposure"] }; }
function renderAI(){ const box = sel("airesult"); if (!AI.result) { box.innerHTML = ""; return; } const r = AI.result;
  if (r.error) { box.innerHTML = `<div class="ai"><b>The AI review did not run.</b> ${esc(r.error)}</div>`; return; }
  const x = r.result; const pr = { high: "high", medium: "medium", low: "low" };
  box.innerHTML = `<div class="ai"><h3>AI review</h3><div class="muted" style="font-size:12px;margin-bottom:8px">${esc(r.model || "")}, ${AI.at ? new Date(AI.at).toLocaleString("en-AU") : ""}${r.remaining_today != null ? `, ${r.remaining_today} reviews left today` : ""}. General information for checking and learning, not advice; check every suggestion before acting on it.</div>` +
    (x ? `<p>${esc(x.summary || "")}</p>${(x.strengths || []).length ? `<div class="lbl">Strengths</div><ul>${x.strengths.map(s => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}<div class="lbl" style="display:block;margin-top:10px">Suggestions</div>` +
      (x.suggestions || []).map(s => `<div class="sg"><span class="sev ${pr[s.priority] || "low"}" style="font-size:11.5px;font-weight:600;padding:3px 9px;border-radius:999px">${esc(s.priority || "")}</span> <b>${esc(s.title || "")}</b><div style="margin-top:4px"><span class="lbl">Change</span>${esc(s.change || "")}</div><div><span class="lbl">Why</span>${esc(s.why || "")}</div>${s.tradeoff ? `<div class="muted"><span class="lbl">Trade-off</span>${esc(s.tradeoff)}</div>` : ""}</div>`).join("") +
      ((x.questions || []).length ? `<div class="lbl" style="display:block;margin-top:10px">Ask the client first</div><ul>${x.questions.map(q => `<li>${esc(q)}</li>`).join("")}</ul>` : "")
     : `<pre style="white-space:pre-wrap;font:inherit">${esc(r.text || "")}</pre>`) + `</div>`; }
sel("btn-ai").onclick = async () => { if (AI.running) return; if (!SB) { toast("The AI review needs accounts, which are not set up on this copy of the page"); return; }
  if (!user.session) { toast("Sign in to use the AI review"); openAuth("signin"); return; } if (!state.lines.length) { toast("Add some holdings first"); return; }
  if (!FN) { toast("The AI review runs on the published site"); return; }
  AI.running = true; sel("btn-ai").disabled = true;
  try { const res = await runAiJob(aiPayload(), "ainote", "Reviewing… this usually takes 20 to 60 seconds.");
    AI.result = res; AI.at = new Date().toISOString(); renderAI();
    if (res && res.status === "done") { toast("AI review ready"); sel("airesult").scrollIntoView({ behavior: "smooth", block: "start" }); }
  } catch (e) { AI.result = { error: e.message }; renderAI(); }
  finally { AI.running = false; sel("btn-ai").disabled = false; sel("ainote").textContent = "Uses the site's AI credit; limited per account each day."; } };

// ------------------------------------------------------------ accounts (Supabase)
const SB = (DATA.supabase && DATA.supabase.url && DATA.supabase.key && window.supabase) ? window.supabase.createClient(DATA.supabase.url, DATA.supabase.key) : null;
function serialise(){ return { version: 2, ai_review: AI.result && !AI.result.error ? { ...AI.result, at: AI.at } : null, name: state.name, balance: state.balance, ref: state.ref, platform: state.platform, notes: state.notes, lines: state.lines.map(l => ({ ...l, boa: boaText(l) })), house_style: HS.text || "", extra: Object.fromEntries(state.lines.filter(l => EXTRA[l.ticker]).map(l => [l.ticker, EXTRA[l.ticker]])), research: Object.fromEntries(state.lines.filter(l => l.source === "live" && R[l.ticker]).map(l => [l.ticker, R[l.ticker]])), saved_as_of: DATA.as_of }; }
function hydrate(d, { readOnly=false, id=null, ownerId=null, isPublic=false } = {}){
  Object.assign(EXTRA, d.extra || {}); Object.assign(R, d.research || {}); if (d.house_style) { HS.text = d.house_style; if (sel("hs-examples")) sel("hs-examples").value = HS.text; }
  state.lines = (d.lines || []).map(l => { const u = UMAP[l.ticker]; if (u && l.source !== "live") { const f = lineFromUniverse(u); f.weight_pct = l.weight_pct; f.asset_class = l.asset_class || f.asset_class; f.boa = l.boa || ""; f.boa_custom = !!l.boa_custom; f.boa_ai = !!l.boa_ai; f.sleeve = l.sleeve || ""; return f; } return { boa: "", boa_custom: false, ...l }; });
  state.name = d.name || ""; state.balance = d.balance || 250000; state.ref = d.ref || "balanced"; state.id = id; state.readOnly = readOnly; state.ownerId = ownerId; state.isPublic = isPublic; state.dirty = false; state.ticker = null;
  state.platform = { ...DEFAULT_PLATFORM(), ...(d.platform || {}) }; state.notes = d.notes || ""; AI.result = d.ai_review || null; AI.at = d.ai_review ? d.ai_review.at : null; renderAI();
  sel("pname").value = state.name; sel("pbal").value = state.balance.toLocaleString("en-AU"); sel("pref").value = state.ref; sel("pnotes").value = state.notes;
  sel("readonly").hidden = !readOnly; if (readOnly) sel("readonly").innerHTML = `This is a shared, read-only portfolio. Sign in and click <b>Save as a copy</b> to edit your own version.`;
  render();
}
const AUTH = { mode: "signin" };
const authDlg = sel("authdlg"), resetDlg = sel("resetdlg");
function authMsg(kind, text){ const m = sel("au-msg"); m.className = "auth-msg" + (kind ? " " + kind : ""); m.textContent = text || ""; }
function openAuth(mode){ if (!SB) { toast("Accounts are not set up on this copy of the page"); return; } AUTH.mode = mode || "signin"; authMsg("", ""); renderAuthDialog(); if (!authDlg.open) authDlg.showModal(); setTimeout(() => sel("au-email").focus(), 50); }
function renderAuthDialog(){
  const m = AUTH.mode; const T = { signin: "Sign in", signup: "Create your account", link: "Sign in with an emailed link", forgot: "Reset your password" };
  sel("auth-title").textContent = T[m]; sel("auth-tabs").hidden = m === "forgot";
  sel("auth-tabs").querySelectorAll("button").forEach(b => b.setAttribute("aria-selected", String(b.dataset.mode === m)));
  sel("au-pw-wrap").hidden = (m === "link" || m === "forgot"); sel("au-pw").autocomplete = m === "signup" ? "new-password" : "current-password";
  sel("au-submit").textContent = { signin: "Sign in", signup: "Create account", link: "Send me a link", forgot: "Send reset email" }[m];
  sel("au-foot").innerHTML = m === "signin" ? `<button type="button" data-go="forgot">Forgotten your password?</button>, No account yet? <button type="button" data-go="signup">Create one</button>`
    : m === "signup" ? `Your portfolios are saved to this account only. We email you a confirmation link first. Already have an account? <button type="button" data-go="signin">Sign in</button>`
    : m === "link" ? `No password needed: we email you a link that signs you in on this device. <button type="button" data-go="signin">Use a password instead</button>`
    : `Enter your email and we will send a link to choose a new password. <button type="button" data-go="signin">Back to sign in</button>`;
  sel("au-foot").querySelectorAll("button[data-go]").forEach(b => b.onclick = () => { AUTH.mode = b.dataset.go; authMsg("", ""); renderAuthDialog(); });
}
sel("auth-tabs").querySelectorAll("button").forEach(b => b.onclick = () => { AUTH.mode = b.dataset.mode; authMsg("", ""); renderAuthDialog(); });
sel("auth-close").onclick = () => authDlg.close(); sel("reset-close").onclick = () => resetDlg.close();
sel("au-show").onclick = () => { const i = sel("au-pw"); i.type = i.type === "password" ? "text" : "password"; sel("au-show").textContent = i.type === "password" ? "Show" : "Hide"; };
sel("rs-show").onclick = () => { const i = sel("rs-pw"); i.type = i.type === "password" ? "text" : "password"; sel("rs-show").textContent = i.type === "password" ? "Show" : "Hide"; };
function friendly(err){ const t = String(err && err.message || err || ""); if (/invalid login credentials/i.test(t)) return "That email and password do not match. Check both, or use \"Forgotten your password?\"."; if (/email not confirmed/i.test(t)) return "Your email is not confirmed yet. Open the confirmation link we sent you, then sign in."; if (/already registered|already been registered/i.test(t)) return "There is already an account for that email. Sign in instead, or reset the password."; if (/rate limit|too many/i.test(t)) return "Too many attempts for now. Wait a minute and try again."; if (/password should be at least|weak/i.test(t)) return "Choose a longer password: at least 8 characters."; if (/valid email/i.test(t)) return "That does not look like an email address."; return t || "Something went wrong. Try again."; }
sel("auth-form").onsubmit = async (e) => {
  e.preventDefault(); const email = sel("au-email").value.trim(), pw = sel("au-pw").value; const btn = sel("au-submit");
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { authMsg("err", "Enter a valid email address."); return; }
  if ((AUTH.mode === "signin" || AUTH.mode === "signup") && pw.length < 8) { authMsg("err", "Your password needs at least 8 characters."); return; }
  btn.disabled = true; authMsg("info", "One moment…");
  try {
    if (AUTH.mode === "signin") { const { error } = await SB.auth.signInWithPassword({ email, password: pw }); if (error) throw error; authDlg.close(); toast("Signed in as " + email); }
    else if (AUTH.mode === "signup") { const { data, error } = await SB.auth.signUp({ email, password: pw, options: { emailRedirectTo: location.origin + "/builder.html" } }); if (error) throw error;
      if (data.session) { authDlg.close(); toast("Account created"); } else if (data.user && data.user.identities && data.user.identities.length === 0) { authMsg("err", "There is already an account for that email. Sign in instead, or reset the password."); }
      else authMsg("ok", `Almost there. We sent a confirmation link to ${email}. Open it (check spam if it has not arrived in a minute), then come back here and sign in.`); }
    else if (AUTH.mode === "link") { const { error } = await SB.auth.signInWithOtp({ email, options: { emailRedirectTo: location.origin + "/builder.html", shouldCreateUser: true } }); if (error) throw error; authMsg("ok", `Check ${email} for your sign-in link. It opens this page already signed in.`); }
    else if (AUTH.mode === "forgot") { const { error } = await SB.auth.resetPasswordForEmail(email, { redirectTo: location.origin + "/builder.html" }); if (error) throw error; authMsg("ok", `If there is an account for ${email}, a reset link is on its way.`); }
  } catch (err) { authMsg("err", friendly(err)); } finally { btn.disabled = false; }
};
sel("reset-form").onsubmit = async (e) => { e.preventDefault(); const pw = sel("rs-pw").value; const m = sel("rs-msg"); if (pw.length < 8) { m.className = "auth-msg err"; m.textContent = "At least 8 characters."; return; }
  const { error } = await SB.auth.updateUser({ password: pw }); if (error) { m.className = "auth-msg err"; m.textContent = friendly(error); return; } resetDlg.close(); toast("Password saved. You are signed in."); };
function renderAccount(){
  renderLocal();
  const a = sel("acct");
  if (!SB) { a.innerHTML = `<span class="muted">Accounts are not set up on this copy of the page, so Save keeps portfolios in this browser (until you clear your browsing data).</span>`; sel("mine").innerHTML = ""; return; }
  const s = user.session;
  if (!s) { a.innerHTML = `<button class="btn primary" id="btn-open-signin" type="button">Sign in</button><button class="btn" id="btn-open-signup" type="button">Create account</button><span class="muted">Sign in to save portfolios to your account, reopen them on any device and share them. Without an account, Save keeps them in this browser.</span>`;
    sel("btn-open-signin").onclick = () => openAuth("signin"); sel("btn-open-signup").onclick = () => openAuth("signup"); sel("mine").innerHTML = ""; return; }
  const initial = (s.user.email || "?").slice(0, 1).toUpperCase();
  a.innerHTML = `<div class="signed"><span class="avatar">${initial}</span><span>Signed in as <b>${esc(s.user.email)}</b></span><span class="muted" id="minecount"></span><button class="btn small" id="btn-signout" type="button">Sign out</button></div>`;
  sel("btn-signout").onclick = async () => { await SB.auth.signOut(); toast("Signed out"); };
  listMine();
}
async function listMine(){
  if (!SB || !user.session) return; const { data, error } = await SB.from("portfolios").select("id,name,is_public,updated_at,data").eq("user_id", user.session.user.id).order("updated_at", { ascending: false });
  if (error) { sel("mine").innerHTML = `<div class="note">Could not load your portfolios: ${esc(error.message)}. If this is a new project, the database table may not be set up yet.</div>`; return; }
  sel("minecount").textContent = data.length ? `${data.length} saved portfolio${data.length === 1 ? "" : "s"}` : "No saved portfolios yet";
  sel("mine").innerHTML = data.map(p => `<div class="pend"><span><b>${esc(p.name || "Untitled")}</b> <span class="mono" style="color:var(--faint);font-size:12px">${(p.data && p.data.lines ? p.data.lines.length : 0)} holdings, ${fmtM(p.data && p.data.balance)}, ${new Date(p.updated_at).toLocaleDateString("en-AU")}${p.is_public ? ", shared" : ""}</span></span><button class="btn small" data-open="${p.id}" type="button">Open</button><button class="btn small" data-dup="${p.id}" type="button">Duplicate</button><button class="btn small danger" data-del="${p.id}" type="button">Delete</button></div>`).join("");
  sel("mine").querySelectorAll("button[data-open]").forEach(b => b.onclick = () => { const p = data.find(x => x.id === b.dataset.open); if (state.dirty && state.lines.length && !confirm("Discard unsaved changes?")) return; hydrate(p.data, { id: p.id, ownerId: user.session.user.id, isPublic: p.is_public }); history.replaceState(null, "", "?p=" + p.id); toast("Opened " + (p.name || "portfolio")); });
  sel("mine").querySelectorAll("button[data-dup]").forEach(b => b.onclick = async () => { const p = data.find(x => x.id === b.dataset.dup); const { error } = await SB.from("portfolios").insert({ user_id: user.session.user.id, name: (p.name || "Untitled") + " (copy)", data: p.data, is_public: false }); toast(error ? error.message : "Duplicated"); listMine(); });
  sel("mine").querySelectorAll("button[data-del]").forEach(b => b.onclick = async () => { if (!confirm("Delete this portfolio? This cannot be undone.")) return; const { error } = await SB.from("portfolios").delete().eq("id", b.dataset.del); if (error) { toast(error.message); return; } if (state.id === b.dataset.del) { state.id = null; history.replaceState(null, "", location.pathname); } toast("Deleted"); listMine(); render(); });
}
// Portfolios saved in this browser: used when nobody is signed in, or when the account cannot be reached, so Save always works.
const LOCAL_KEY = "mpl-builder-saved";
function localList(){ try { return JSON.parse(localStorage.getItem(LOCAL_KEY) || "[]"); } catch(e) { return []; } }
function localWrite(list){ try { localStorage.setItem(LOCAL_KEY, JSON.stringify(list)); return true; } catch(e) { return false; } }
function isLocalId(id){ return !!id && String(id).startsWith("local-"); }
function saveLocal(asCopy){ const list = localList(); const id = (!asCopy && isLocalId(state.id)) ? state.id : "local-" + Date.now().toString(36);
  const rec = { id, name: (asCopy && isLocalId(state.id) ? state.name + " (copy)" : state.name) || "Untitled", data: serialise(), updated_at: new Date().toISOString() };
  const i = list.findIndex(x => x.id === id); if (i >= 0) list[i] = rec; else list.unshift(rec);
  if (!localWrite(list)) return false; state.id = id; state.ownerId = "local"; state.readOnly = false; state.dirty = false; sel("readonly").hidden = true; history.replaceState(null, "", location.pathname); return true; }
function renderLocal(){ const list = localList(); const box = sel("localmine"); if (!list.length) { box.innerHTML = ""; return; }
  const signed = SB && user.session;
  box.innerHTML = `<div class="eyebrow" style="margin-top:6px">Saved in this browser (${list.length})</div>` + list.map(p => `<div class="pend"><span><b>${esc(p.name || "Untitled")}</b> <span class="mono" style="color:var(--faint);font-size:12px">${(p.data && p.data.lines ? p.data.lines.length : 0)} holdings, ${fmtM(p.data && p.data.balance)}, ${new Date(p.updated_at).toLocaleDateString("en-AU")}</span></span><button class="btn small" data-lopen="${p.id}" type="button">Open</button>${signed ? `<button class="btn small" data-lmove="${p.id}" type="button">Move to my account</button>` : `<span></span>`}<button class="btn small danger" data-ldel="${p.id}" type="button">Delete</button></div>`).join("");
  box.querySelectorAll("button[data-lopen]").forEach(b => b.onclick = () => { const p = localList().find(x => x.id === b.dataset.lopen); if (!p) return; hydrate(p.data, { id: p.id, ownerId: "local" }); history.replaceState(null, "", location.pathname); toast("Opened " + (p.name || "portfolio") + " from this browser"); });
  box.querySelectorAll("button[data-ldel]").forEach(b => b.onclick = () => { if (!confirm("Delete this portfolio from this browser?")) return; localWrite(localList().filter(x => x.id !== b.dataset.ldel)); if (state.id === b.dataset.ldel) state.id = null; renderLocal(); render(); toast("Deleted from this browser"); });
  box.querySelectorAll("button[data-lmove]").forEach(b => b.onclick = async () => { const p = localList().find(x => x.id === b.dataset.lmove); if (!p || !user.session) return;
    const { error } = await SB.from("portfolios").insert({ user_id: user.session.user.id, name: p.name || "Untitled", data: p.data, is_public: false });
    if (error) { toast("Your account did not accept it: " + error.message); return; } localWrite(localList().filter(x => x.id !== p.id)); if (state.id === p.id) state.id = null; toast("Moved to your account"); renderLocal(); listMine(); render(); }); }
async function save(asCopy){
  if (state.readOnly && !asCopy) { toast("This is someone else's shared portfolio. Use \"Save as a copy\" to keep your own version."); return; }
  if (!state.lines.length) { toast("Add some holdings first"); return; }
  clearTimeout(trackT); track();
  if (!state.name) { state.name = prompt("Name this portfolio", "My portfolio") || ""; if (!state.name) return; sel("pname").value = state.name; }
  if (!SB || !user.session) {
    if (saveLocal(asCopy)) { toast(SB ? "Saved in this browser. Sign in to keep it in your account and open it on any device." : "Saved in this browser"); renderLocal(); render(); }
    else toast("Not saved: this browser's storage is full or turned off");
    return; }
  const wasLocal = isLocalId(state.id) ? state.id : null;
  const payload = { user_id: user.session.user.id, name: state.name, data: serialise(), updated_at: new Date().toISOString() };
  const own = state.id && state.ownerId === user.session.user.id && !state.readOnly;
  let res;
  try {
    if (own && !asCopy) res = await SB.from("portfolios").update(payload).eq("id", state.id).select("id,is_public").single();
    else res = await SB.from("portfolios").insert({ ...payload, name: asCopy && own ? state.name + " (copy)" : state.name, is_public: false }).select("id,is_public").single();
  } catch (e) { res = { error: e }; }
  if (res.error) { const ok = saveLocal(asCopy); toast("Your account did not accept the save (" + (res.error.message || res.error) + ")." + (ok ? " A copy is saved in this browser instead." : "")); renderLocal(); render(); return; }
  if (wasLocal) localWrite(localList().filter(x => x.id !== wasLocal));
  state.id = res.data.id; state.ownerId = user.session.user.id; state.readOnly = false; state.isPublic = res.data.is_public; state.dirty = false; sel("readonly").hidden = true;
  history.replaceState(null, "", "?p=" + state.id); toast("Saved to your account"); listMine(); renderLocal(); render();
}
sel("btn-save").onclick = () => save(false);
sel("btn-saveas").onclick = () => { if (state.name && !state.name.endsWith("(copy)")) { /* keep name; insert as new */ } save(true); };
sel("btn-share").onclick = async () => {
  if (SB && !user.session) { openAuth("signin"); return; }
  if (!SB || !state.id || isLocalId(state.id) || state.ownerId !== user.session.user.id) { toast("Save the portfolio to your account first (sign in, then Save)"); return; }
  if (state.dirty) { toast("Save your changes first so the link shows them"); return; }
  const makePublic = !state.isPublic; const { error } = await SB.from("portfolios").update({ is_public: makePublic }).eq("id", state.id); if (error) { toast(error.message); return; }
  state.isPublic = makePublic; const link = location.origin + location.pathname + "?p=" + state.id;
  if (makePublic) { try { await navigator.clipboard.writeText(link); toast("Sharing on. Link copied: " + link); } catch(e) { prompt("Sharing on. Copy this link:", link); } } else toast("Sharing off: the link no longer works for others");
  listMine();
};
async function openShared(id){
  if (!SB) return false; const { data, error } = await SB.from("portfolios").select("id,user_id,name,is_public,data").eq("id", id).maybeSingle();
  if (error || !data) { toast("That portfolio is not available (deleted, or sharing was turned off)"); return false; }
  const mine = user.session && user.session.user.id === data.user_id; hydrate(data.data, { readOnly: !mine, id: data.id, ownerId: data.user_id, isPublic: data.is_public }); return true;
}

// ------------------------------------------------------------ start
sel("meta").textContent = DATA.meta; sel("ucount").textContent = U.length;
if (DATA.banner) { sel("banner").querySelector(".wrap").textContent = DATA.banner; sel("banner").hidden = false; }
renderFilters();
(async () => {
  const params = new URLSearchParams(location.search); const shared = params.get("p");
  if (SB) { const { data } = await SB.auth.getSession(); user.session = data.session;
    SB.auth.onAuthStateChange((event, s) => { user.session = s; renderAccount(); if (event === "PASSWORD_RECOVERY") { sel("rs-msg").className = "auth-msg"; resetDlg.showModal(); }
      if (event === "SIGNED_IN" && location.hash.includes("access_token")) { history.replaceState(null, "", location.pathname + location.search); toast("Email confirmed: you are signed in"); }
      if (shared && !state.id) openShared(shared); }); }
  renderAccount();
  if (shared && await openShared(shared)) { resetHistory(); return; }
  // Opened from the Model portfolios page: load that model at the balance shown there, then go to the check.
  const fromModel = params.get("model");
  if (fromModel) { const mo = (DATA.models || []).find(x => x.id === fromModel);
    if (mo) { const bal = parseBalance(params.get("balance") || "") || mo.balance; state.balance = bal; sel("pbal").value = bal.toLocaleString("en-AU");
      state.lines = mo.lines.map(x => { const u = UMAP[x.ticker]; const l = u ? lineFromUniverse(u) : null; if (!l) return null; l.weight_pct = +x.weight_pct.toFixed(2); l.sleeve = x.sleeve || ""; return l; }).filter(Boolean);
      state.ref = refFor(mo.profile, mo.stage); sel("pref").value = state.ref; state.name = mo.label; sel("pname").value = mo.label; state.id = null; state.dirty = true;
      history.replaceState(null, "", location.pathname); render(); resetHistory(); toast("Loaded " + mo.label + " from the model portfolios");
      setTimeout(() => sel("check").scrollIntoView({ behavior: "smooth", block: "start" }), 300); return; }
    toast("That model is a managed portfolio or ESG version, which the builder cannot open"); }
  // Opened from the Daily brief's ASX lookup (?add=CODE): add that holding to the current draft at 0%.
  const addCode = (params.get("add") || "").trim().toUpperCase().replace(/\.(AX|XA)$/, "");
  const addAfter = () => { if (!/^[A-Z0-9]{2,6}$/.test(addCode)) return; history.replaceState(null, "", location.pathname);
    const sym = [addCode + ".AX", addCode + ".XA", addCode].find(t => UMAP[t]);
    if (state.lines.some(l => l.ticker === sym || l.ticker === addCode + ".AX")) { toast(addCode + " is already in this portfolio"); return; }
    if (sym) addSymbol(sym); else { toast("Fetching " + addCode + " from the ASX…"); fetchAsxLine(addCode).then(l => pushLine(l)).catch(e => toast(e.message)); }
    setTimeout(() => sel("holdings-section").scrollIntoView({ behavior: "smooth", block: "start" }), 400); };
  try { const d = JSON.parse(localStorage.getItem("mpl-builder-draft") || "null"); if (d && d.lines && d.lines.length) { hydrate(d, { id: d.id || null, ownerId: isLocalId(d.id) ? "local" : (user.session ? user.session.user.id : null) }); state.dirty = !!d.id; updateSaveNote(); resetHistory(); toast("Restored your last draft from this browser"); addAfter(); return; } } catch(e) {}
  render(); resetHistory(); addAfter();
})();
</script>
</body>
</html>
"""


def _platforms_from_settings(cfg: dict | None) -> dict:
    """Fallback when config/platforms.yaml is missing: the HUB24 rate card from settings.yaml in the platforms shape."""
    if not cfg or not cfg.get("menus"):
        return {}
    menus = {}
    for k, m in cfg["menus"].items():
        menus[k] = {"label": m.get("label", k), "tiering": "marginal", "bands": m.get("bands", []), "min_admin_fee": m.get("min_admin_fee", 0),
                    "max_admin_fee": m.get("max_admin_fee"), "fixed_fees": [{"label": "Account keeping fee", "amount": m.get("account_keeping_fee", 0)}],
                    "percent_fees": [{"label": "Expense recovery", "rate": m.get("expense_recovery_rate", 0), "cap": m.get("expense_recovery_cap")}],
                    "allows_listed": k == "choice", "max_balance": cfg.get("discover_max_balance") if k == "discover" else None}
    return {"hub24": {"label": "HUB24", "accounts": {"super": {"label": "Super or pension", "product": cfg.get("name", "HUB24 Super"), "as_of": cfg.get("rate_card_date", ""), "menus": menus}}}}


def _model_lines(pf: Portfolio) -> list[dict]:
    """A base portfolio for the builder. A house model loads at the model's own weights (the page sizes them to the user's
    balance); a weight the engine could not price today is held in cash, as on the dashboard."""
    house = pf.house or {}
    sleeves = house.get("sleeves") or {}
    if not house.get("weights"):
        return [{"ticker": l.ticker, "weight_pct": round(l.weight_pct, 3), "sleeve": sleeves.get(l.ticker, "")} for l in pf.lines]
    held = {l.ticker for l in pf.lines}
    w = {t: float(v) for t, v in house["weights"].items() if t in held}
    spare = sum(float(v) for t, v in house["weights"].items() if t not in held)
    cash = next((l.ticker for l in pf.lines if l.ticker == "CMA"), None) or next((l.ticker for l in pf.lines if l.asset_class == "cash"), None)
    if cash:
        w[cash] = w.get(cash, 0.0) + spare
    return [{"ticker": l.ticker, "weight_pct": round(w.get(l.ticker, l.weight_pct), 3), "sleeve": sleeves.get(l.ticker, "")} for l in pf.lines]


def _boa_examples() -> str:
    """House-style basis of advice examples shipped with the site (config/boa_examples.md, lines starting with # are notes)."""
    from ..config import PROJECT_ROOT
    p = PROJECT_ROOT / "config" / "boa_examples.md"
    if not p.exists():
        return ""
    return "\n".join(l for l in p.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#")).strip()


def _css() -> str:
    m = re.search(r"<style>(.*?)</style>", dash.TEMPLATE, re.S)
    return m.group(1) if m else ""


STAGE_NOUN = {"early_accumulation": "early accumulator", "accumulation": "accumulator", "retirement": "retiree"}


def write_builder(path: Path, portfolios: list[Portfolio], profiles: Profiles, md: MarketData, universe: pd.DataFrame,
                  research: dict | None, prices: dict[str, float], *, settings_site_url: str = "", quality: dict | None = None,
                  platform_cfg: dict | None = None, pds: dict | None = None, history: dict | None = None, esg: dict | None = None,
                  supabase: dict | None = None, as_of: str = "", platforms: dict | None = None, asx: dict | None = None) -> Path:
    classes = [{"key": k, "label": v["label"], "kind": v["kind"]} for k, v in profiles.asset_classes.items()]
    colors = {c["key"]: f"--series-{i + 1}" for i, c in enumerate(classes)}
    light_vars = " ".join(f"--series-{i + 1}:{dash.PALETTE_LIGHT[i % len(dash.PALETTE_LIGHT)]};" for i in range(len(classes)))
    dark_vars = " ".join(f"--series-{i + 1}:{dash.PALETTE_DARK[i % len(dash.PALETTE_DARK)]};" for i in range(len(classes)))
    uni = fill_sector_region(universe, research)
    uni = uni[uni["status"].isin(["active", "watchlist"])] if "status" in uni.columns else uni
    universe_rows = []
    for _, r in uni.iterrows():
        universe_rows.append({"ticker": r["ticker"], "name": r["name"], "asset_class": r["asset_class"], "vehicle": r["vehicle"], "role": r["role"], "currency": r["currency"],
                              "mer": float(r["mer"]), "yield": float(r["yield"]), "franking": float(r["franking"]), "sector": r["sector"], "region": r["region"],
                              "status": r.get("status", "active"), "price_aud": prices.get(r["ticker"]), "max_weight": float(r["max_weight"]), "weight_hint": float(r["weight_hint"]),
                              "twin": r.get("twin", "") or "", "liquidity": r.get("liquidity", "") or "", "style": r.get("style", "") or "",
                              "hub24_code": str(r.get("hub24_code", "") or "").strip(), "manual": str(r.get("source", "")) == "unlisted_fund" or r["vehicle"] in ("td", "cash")})
    tiers = sorted(profiles.balance_tiers.items(), key=lambda kv: kv[1]["order"])

    def split(lbl: str) -> tuple[str, str]:
        return (lbl.split(" (")[0], lbl.split(" (")[1].rstrip(")")) if " (" in lbl else (lbl, "")

    stage_label = {k: split(v["label"])[0] for k, v in profiles.life_stages.items()}
    tier_label = {k: split(v["label"])[0] for k, v in profiles.balance_tiers.items()}
    # Base portfolios: one per stage, profile and tier. A stage that caps the profile (retirement) builds the same
    # portfolio for several requested profiles, so each model records every profile it answers for.
    models, by_id = [], {}
    for pf in sorted(portfolios, key=lambda p: (profiles.profile_order(p.profile_used), profiles.life_stages[p.life_stage]["order"], profiles.tier_order(p.tier))):
        if pf.implementation != "direct" or (pf.esg or {}).get("screened"):
            continue
        if pf.id in by_id:
            req = by_id[pf.id]["requested"]
            if pf.profile_requested not in req:
                req.append(pf.profile_requested)
            continue
        house = pf.house or {}
        by_id[pf.id] = {"id": pf.id, "profile": pf.profile_used, "stage": pf.life_stage, "tier": pf.tier, "balance": pf.balance, "requested": [pf.profile_requested],
                        "label": (f"{house['label']}, {tier_label[pf.tier].lower()} tier" if house else
                                  f"{profiles.risk_profiles[pf.profile_used]['label']} {STAGE_NOUN.get(pf.life_stage, stage_label[pf.life_stage].lower())}, {tier_label[pf.tier].lower()} tier"),
                        "house": {"label": house.get("label", ""), "source": house.get("source", ""), "model_balance": house.get("model_balance")} if house else None,
                        "lines": _model_lines(pf)}
        models.append(by_id[pf.id])
    growth = profiles.growth_classes
    data = {
        "meta": f"Built {datetime.now():%d %B %Y %H:%M}. Prices as of {md.as_of.date()}; AUD/USD {1 / md.fx_aud_per_usd:.4f}. Rebuilt automatically each weekday evening.",
        "banner": "SYNTHETIC DATA: this page was built in offline test mode. Every number is a placeholder." if md.synthetic else "",
        "as_of": as_of or str(md.as_of.date()),
        "classes": classes, "colors": colors,
        "profiles": [{"key": k, "label": v["label"], "sub": f"{sum(v['saa'][c] for c in growth):.0f}% growth"} for k, v in sorted(profiles.risk_profiles.items(), key=lambda kv: kv[1]["order"])],
        "stages": [{"key": k, "label": split(v["label"])[0], "sub": split(v["label"])[1]} for k, v in sorted(profiles.life_stages.items(), key=lambda kv: kv[1]["order"])],
        "saa": {**{k: {c: float(w) for c, w in v["saa"].items()} for k, v in profiles.risk_profiles.items()},
                **{f"{k}@{st}": {c: float(w) for c, w in sv.items()} for k, v in profiles.risk_profiles.items() for st, sv in (v.get("saa_by_stage") or {}).items()}},
        # Comparison targets: each profile's long-run target, plus its pension-phase target where it has one.
        "targets": [t for k, v in sorted(profiles.risk_profiles.items(), key=lambda kv: kv[1]["order"])
                    for t in ([{"key": k, "label": v["label"], "sub": f"{sum(v['saa'][c] for c in growth):.0f}% growth"}]
                              + [{"key": f"{k}@{st}", "label": f"{v['label']} ({STAGE_NOUN.get(st, st)})", "sub": f"{sum(sv[c] for c in growth):.0f}% growth"}
                                 for st, sv in (v.get("saa_by_stage") or {}).items()])],
        "boa_examples": _boa_examples(),
        "asx": asx or {},
        "sizing": getattr(profiles, "sizing", {}) or {},
        "tiers": [{"key": k, "label": split(v["label"])[0], "min_balance": v["min_balance"], "max_holdings": v["max_holdings"], "min_holding": v["min_holding_dollars"], "brokerage": v["brokerage_dollars"]} for k, v in tiers],
        "platform": platform_cfg or {}, "pds": pds or {}, "quality": quality or {},
        "platforms": (platforms or {}).get("platforms") or _platforms_from_settings(platform_cfg), "default_platform": (platforms or {}).get("default", "hub24"),
        "diversification": getattr(profiles, "diversification", {}) or {},
        "research": {t: dict(r.__dict__) for t, r in (research or {}).items()},
        "universe": universe_rows, "models": models,
        "returns": dash._daily_returns(md, uni, profiles), "history": history or {},
        "fx_aud_per": md.fx_aud_per, "site_url": settings_site_url or "",
        "search_index": dash._load_search_index(),
        "supabase": {"url": (supabase or {}).get("url", ""), "key": (supabase or {}).get("anon_key", "")},
    }
    html = (TEMPLATE.replace("__CSS__", _css().replace("__LIGHT_VARS__", light_vars).replace("__DARK_VARS__", dark_vars))
            .replace("__DATA__", json.dumps(dash._clean(data), default=str)))
    path.parent.mkdir(parents=True, exist_ok=True)
    from .motion import inject
    path.write_text(inject(html), encoding="utf-8")
    return path
