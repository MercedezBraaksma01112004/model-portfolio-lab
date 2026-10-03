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
<title>Build your own portfolio · Model Portfolio Lab</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
__CSS__
.acct { display:flex; flex-wrap:wrap; gap:8px 12px; align-items:center; font-size:13.5px; }
.acct input { font:inherit; padding:7px 10px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); min-width:180px; }
.acct select { font:inherit; padding:7px 10px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); max-width:260px; }
.wrow input.w { width:84px; font:inherit; font-size:15px; padding:9px 9px; border:1.5px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); text-align:right; font-family:"IBM Plex Mono", ui-monospace, monospace; min-height:40px; }
.wrow input.w:focus { outline:2px solid var(--accent); outline-offset:1px; border-color:transparent; }
.wrow input.w.bad { border-color:var(--critical); }
.setup { display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:14px; }
.setup label { display:block; font-size:12.5px; color:var(--muted); margin-bottom:4px; }
.setup input, .setup select { width:100%; font:inherit; font-size:15px; padding:11px 12px; border:1.5px solid var(--line); border-radius:10px; background:var(--bg); color:var(--text); min-height:46px; }
.setup input:focus, .setup select:focus { outline:2px solid var(--accent); outline-offset:1px; border-color:transparent; }
.total { font-family:"IBM Plex Mono", ui-monospace, monospace; font-weight:500; }
.total.bad { color:var(--critical); }
.chips { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0; }
.chips button { border:1.5px solid var(--line); background:var(--surface); color:var(--text); padding:7px 13px; border-radius:999px; font-size:13px; min-height:36px; }
.chips button:hover { border-color:var(--accent); }
.chips button[aria-pressed="true"] { background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }
.result { grid-template-columns: 1fr auto; }
.result .d { font-size:12px; color:var(--faint); }
.toast { position:fixed; bottom:18px; left:50%; transform:translateX(-50%); background:var(--text); color:var(--bg); padding:10px 16px; border-radius:10px; font-size:13.5px; display:none; z-index:20; max-width:90vw; }
.empty { padding:22px; text-align:center; color:var(--faint); border:1px dashed var(--line); border-radius:10px; }
.readonly { background:var(--accent-soft); padding:10px 14px; border-radius:10px; font-size:13.5px; margin-top:10px; }
.mine { display:grid; gap:6px; margin-top:8px; }
dialog.auth { border:1px solid var(--line); border-radius:14px; padding:0; width:min(440px, 92vw); background:var(--surface); color:var(--text); box-shadow:0 20px 60px rgba(0,0,0,.25); }
dialog.auth::backdrop { background:rgba(10,12,11,.45); }
.auth-head { display:flex; justify-content:space-between; align-items:center; padding:16px 20px 0; }
.auth-head h3 { margin:0; font-family:"IBM Plex Serif", Georgia, serif; font-size:19px; font-weight:600; }
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
</style>
</head>
<body>
<header><div class="wrap">
  <nav class="nav no-print"><a href="/">Model portfolios</a><a href="/builder.html" aria-current="page">Build your own portfolio</a><a href="/quality.html">Holdings quality review</a></nav>
  <h1>Build your own portfolio</h1>
  <p class="lede">Choose any listed share, ETF or fund, set the weights, and watch the cost, income, risk, diversification and a ten-year backtest
  recalculate as you go. Start blank, or from one of the engine's model portfolios and change what you disagree with.</p>
  <div class="meta" id="meta"></div>
  <div class="meta">Personal learning project. Illustrative only: not financial advice and not a recommendation to buy or sell anything. Past returns are history, not forecasts.</div>
</div></header>
<div class="banner" id="banner" hidden><div class="wrap"></div></div>
<main class="wrap">

<section id="account" class="no-print">
  <div class="eyebrow">Your account</div>
  <div class="acct" id="acct"></div>
  <div class="mine" id="mine"></div>
</section>

<section id="setup">
  <div class="eyebrow">Start here</div>
  <h2 id="ptitle">A new portfolio</h2>
  <div id="readonly" class="readonly" hidden></div>
  <div class="setup" style="margin-top:12px">
    <div><label for="pname">Portfolio name</label><input id="pname" type="text" placeholder="e.g. Growth with a franked income tilt" maxlength="80"></div>
    <div><label for="pbal">Balance invested ($)</label><input id="pbal" type="text" inputmode="numeric" value="250,000"></div>
    <div><label for="pref">Compare against the long-run target for</label><select id="pref"></select></div>
    <div><label for="pstart">Start from a model portfolio</label><select id="pstart"><option value="">Blank</option></select></div>
  </div>
  <div class="toolbar">
    <button class="btn primary" id="btn-save" type="button">Save</button>
    <button class="btn" id="btn-saveas" type="button">Save as a copy</button>
    <button class="btn" id="btn-share" type="button">Share link</button>
    <button class="btn" id="btn-new" type="button">New blank portfolio</button>
    <button class="btn" id="btn-xlsx" type="button">Download as Excel</button>
    <button class="btn" id="btn-print" type="button">Print</button>
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
  <div class="tscroll"><table id="htable" hidden><thead><tr><th>Holding</th><th>Asset class</th><th>Sector · region</th><th class="num">Weight %</th><th class="num">Dollars</th><th class="num">Units</th><th class="num">Price (AUD)</th><th>Last 12 months</th><th class="num">1y</th><th class="num">3y pa</th><th class="num">5y pa</th><th class="num">10y pa</th><th class="num">Yield</th><th class="num">Cost</th><th>Analyst view</th><th class="no-print"></th></tr></thead><tbody id="holdings"></tbody></table></div>
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
  <p class="muted" style="font-size:12.5px;margin:8px 0 0">Weighted returns are the weight-times-return average of the holdings, the way a model spreadsheet does it. A holding younger than the period uses its asset class index ETF as a stand-in (marked †). Fees use the HUB24 rate card for the menu this mix would sit on.</p>
  <div id="warnings" style="margin-top:10px"></div>
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

<section id="glossary" class="no-print">
  <div class="eyebrow">Reading the page</div>
  <h2>How the figures are worked out</h2>
  <details><summary>Where the data comes from</summary><p>Holdings in the engine's universe use the daily build's prices, dividend-adjusted returns and Yahoo Finance analyst consensus. Anything you add from outside it is fetched from the same price feed when you add it, converted to Australian dollars at today's rate for the price and at each month's rate for the history. Unlisted managed funds and term deposits are not in the feed and cannot be added here.</p></details>
  <details><summary>Fees</summary><p>The cost per year is the weighted management cost of the funds plus the HUB24 administration fee from the rate card: Choice menu for anything holding shares or ETFs. Brokerage is not included in the running cost.</p></details>
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
const state = { id: null, name: "", balance: 250000, ref: "balanced", lines: [], isPublic: false, readOnly: false, ownerId: null, ticker: null, dirty: false };
const user = { session: null };
const EXTRA = {};   // ticker -> {daily:{dates,returns}, monthly:{months,returns}} fetched live for holdings outside the universe

function lineFromUniverse(u){
  const r = R[u.ticker] || {};
  return { ticker: u.ticker, name: u.name, asset_class: u.asset_class, vehicle: u.vehicle, role: u.role, currency: u.currency, mer_pct: +u.mer || 0,
    yield_pct: r.dividend_yield_pct != null ? r.dividend_yield_pct : (+u.yield || 0), yield_source: r.dividend_yield_pct != null ? "live" : "config",
    franking_pct: +u.franking || 0, sector: u.sector || "", region: u.region || "", price_aud: u.price_aud, priced_from: u.price_aud == null ? "unpriced" : "feed",
    weight_pct: 0, source: "universe" };
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
  let h = null;
  // Pre-computed by the daily build for every listing in the search index; the live function is the fallback.
  try { const r = await fetch("/data/listings/" + encodeURIComponent(symbol) + ".json", { cache: "no-cache" }); if (r.ok) h = await r.json(); } catch(e) {}
  if (!h) { try { h = await api("/history?symbol=" + encodeURIComponent(symbol)); } catch(e) { toast("No data for " + symbol + ": " + e.message + ". Only listings in the search index are available offline."); return; } }
  const fx = DATA.fx_aud_per || {}; const rate = h.currency === "AUD" ? 1 : (fx[h.currency] || null);
  if (rate == null) { toast("No exchange rate for " + h.currency + "; cannot price " + symbol); return; }
  const vehicle = (h.type === "ETF" || (meta && meta.type === "ETF")) ? "etf" : "direct";
  const sector = vehicle === "etf" ? "Diversified fund" : (h.sector_group || sectorFromIndex((meta && meta.sector) || h.sector, h.type));
  R[symbol] = { ticker: symbol, name: h.name, sparkline: h.spark || [], return_1y_pct: h.return_1y_pct, return_3y_pct_pa: h.return_3y_pct_pa, return_5y_pct_pa: h.return_5y_pct_pa, return_10y_pct_pa: h.return_10y_pct_pa,
    history_years: h.history_years, dividend_yield_pct: h.yield_pct, price: h.price, price_currency: h.currency, volatility_1y_pct: h.volatility_1y_pct, max_drawdown_1y_pct: h.max_drawdown_1y_pct,
    source: h.built ? "price feed (daily build)" : "price feed (live)", consensus_label: "no coverage", return_proxy: {}, sector: (meta && meta.sector) || h.sector || "", fetched: h.built || new Date().toISOString().slice(0,10) };
  EXTRA[symbol] = { daily: h.daily, monthly: h.monthly };
  pushLine({ ticker: symbol, name: h.name, asset_class: cls || guessClass(symbol, h.name, meta && meta.sector), vehicle, role: "satellite", currency: h.currency, mer_pct: vehicle === "etf" ? 0.2 : 0,
    yield_pct: h.yield_pct || 0, yield_source: "live", franking_pct: 0, sector, region: guessRegion(symbol, h.name), price_aud: h.price * rate, priced_from: "live", weight_pct: 0, source: "live" });
}
function pushLine(l){ state.lines.push(l); state.ticker = l.ticker; state.dirty = true; sel("q").value = ""; sel("results").innerHTML = ""; render(); toast(l.name + " added at 0%: set its weight in the table"); }
function removeLine(t){ state.lines = state.lines.filter(l => l.ticker !== t); if (state.ticker === t) state.ticker = null; state.dirty = true; render(); }

// ------------------------------------------------------------ calculations
function tierFor(bal){ let t = DATA.tiers[0].key; for (const x of DATA.tiers) if (bal >= x.min_balance) t = x.key; return t; }
function menuFor(bal, hasListed){ const c = DATA.platform; if (!c || !c.menus) return "choice"; if (!hasListed) return (c.menus.discover && bal < (c.discover_max_balance||0)) ? "discover" : "core"; return "choice"; }
function menuLabel(key){ const c = DATA.platform; return (c && c.menus && c.menus[key] && c.menus[key].label) || key; }
function platformFee(bal, menu){ let c = DATA.platform; if (!c) return 0; if (c.menus) c = c.menus[menu] || c.menus.choice; if (!c || !c.bands) return 0; let fee = 0, lower = 0;
  for (const b of c.bands) { const upper = b.up_to == null ? Infinity : b.up_to; fee += Math.max(0, Math.min(bal, upper) - lower) * b.rate; lower = upper; if (bal <= upper) break; }
  fee = Math.min(Math.max(fee, c.min_admin_fee||0), c.max_admin_fee||Infinity); fee += c.account_keeping_fee||0; fee += Math.min(bal*(c.expense_recovery_rate||0), c.expense_recovery_cap||0); return fee; }
function dailySeries(l){
  const R0 = DATA.returns || {}; if (l.vehicle === "cash" || l.priced_from === "manual") return null;
  if (R0.series && R0.series[l.ticker]) return R0.series[l.ticker];
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
  const hasListed = lines.some(l => l.vehicle !== "cash"); m.platform_menu = menuFor(bal, hasListed);
  m.investment_fees_per_year = m.weighted_mer_pct / 100 * bal; m.platform_admin_fee_per_year = platformFee(bal, m.platform_menu);
  m.total_ongoing_cost_pct = m.weighted_mer_pct + m.platform_admin_fee_per_year / bal * 100; m.initial_brokerage = lines.filter(l => l.vehicle !== "cash").length * (T.brokerage||0);
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
const SECTOR_COLORS = ["#2a78d6","#eb6834","#1baf7a","#eda100","#e87ba4","#008300","#4a3aa7","#0e9aa7","#8a5a2b","#c2185b","#5c6bc0","#7cb342","#f4511e","#00897b","#6d4c41","#9e9d24"];
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
  return `<span class="chip ${cls}" title="${r.analysts} analysts, mean ${(r.consensus_mean||0).toFixed(1)} on a 1 to 5 scale">${r.consensus_label} · ${r.analysts}</span>`; }
function retCell(r, key, period){ if (!r || r[key]==null) return "–"; const px = r.return_proxy && r.return_proxy[period]; return `<span title="${px ? "index stand-in: " + px : ""}">${fmtS(r[key])}${px ? "†" : ""}</span>`; }
function docLink(t){ const d = DATA.pds[t]; return d ? `<a href="${d.url}" target="_blank" rel="noopener">${esc(d.label)}</a>` : '<span class="muted">no link on file</span>'; }
function parseBalance(v){ const n = parseFloat(String(v).replace(/[^0-9.]/g, "")); return isFinite(n) && n >= 1000 ? n : null; }

function render(){
  const pf = compute(); const m = pf.metrics; const bal = pf.balance; const bad = Math.abs(pf.total - 100) > 0.05;
  sel("ptitle").textContent = state.name || (state.id ? "Untitled portfolio" : "A new portfolio");
  sel("total").textContent = fmtP(pf.total, 1); sel("total").classList.toggle("bad", bad);
  sel("title").textContent = (state.name || "Your portfolio") + ` · ${fmtM(bal)}`;
  sel("htable").hidden = !pf.lines.length; sel("holdings-empty").hidden = !!pf.lines.length;
  const maxW = Math.max(1, ...pf.lines.map(l => l.weight_pct || 0));
  sel("holdings").innerHTML = pf.lines.map(l => { const r = R[l.ticker] || {}; const col = cssColor(l.asset_class) || "var(--accent)";
    return `<tr class="row wrow ${state.ticker===l.ticker?"active":""}" data-t="${esc(l.ticker)}"><td><b>${esc(l.name)}</b><br><span class="mono" style="font-size:11.5px;color:var(--faint)">${esc(l.ticker)} · ${l.vehicle}${l.source==="live" ? " · live" : ""}</span> ${qualityChip(l.ticker)}</td>
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
    ["Cost per year", fmtM(m.investment_fees_per_year + m.platform_admin_fee_per_year), `${fmtP(m.weighted_mer_pct,2)} in funds + ${fmtM(m.platform_admin_fee_per_year)} platform (${menuLabel(m.platform_menu)}); ${fmtP(m.total_ongoing_cost_pct,2)} all-in`],
    ["Income per year", fmtM(m.income_per_year), `${fmtP(m.weighted_yield_pct,2)} cash yield` + (m.franking_credits_per_year > 0.5 ? ` + ${fmtM(m.franking_credits_per_year)} franking credits (${fmtP(m.grossed_up_yield_pct,2)} grossed up)` : "")],
    ["A typical year moved", m.realised_volatility_pct == null ? "–" : "±" + fmtP(m.realised_volatility_pct,0), "realised volatility over the last year"],
    ["Last 12 months", fmtS(m.trailing_1y_return_pct), "what this mix returned; history, not a forecast"],
  ];
  sel("tiles").innerHTML = tiles.map(([k,v,s]) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
  sel("rtiles").innerHTML = [["3y","Weighted 3 year return p.a."],["5y","Weighted 5 year return p.a."],["10y","Weighted 10 year return p.a."]].map(([p,k]) => { const px = m["weighted_return_"+p+"_proxy_share_pct"]||0;
    return `<div class="tile"><div class="k">${k}</div><div class="v">${fmtS(m["weighted_return_"+p+"_pct"])}</div><div class="s">${px > 0.5 ? px.toFixed(0) + "% of the weight rests on index stand-ins" : "average of the holdings' own returns"}</div></div>`; }).join("") +
    `<div class="tile"><div class="k">Brokerage to buy it all</div><div class="v">${fmtM(m.initial_brokerage)}</div><div class="s">one-off, at the tier's per-trade rate</div></div>`;
  const warn = [];
  if (pf.lines.length && bad) warn.push(`Weights add up to ${fmtP(pf.total,1)}, not 100%. Use "Scale to 100%" or "Fill the gap with cash" above; the dollar figures assume the weights as entered.`);
  const unpriced = pf.lines.filter(l => l.price_aud == null); if (unpriced.length) warn.push("No price for " + unpriced.map(l => l.ticker).join(", ") + "; shown without units.");
  const T = DATA.tiers.find(t => t.key === pf.tier) || {}; const small = pf.lines.filter(l => l.weight_pct > 0 && l.dollars < (T.min_holding||0) && l.vehicle !== "cash");
  if (small.length) warn.push(`${small.length} holding(s) are under the ${fmtM(T.min_holding)} minimum the engine uses at this balance (${small.map(l => l.ticker).join(", ")}): brokerage will eat into them.`);
  sel("warnings").innerHTML = warn.map(w => `<div class="note">${w}</div>`).join("");
  // allocation
  const cw = pf.class_weights; const ref = DATA.saa[state.ref] || {};
  sel("stack").innerHTML = CLASSES.filter(c => (cw[c.key]||0) > 0).map(c => `<span style="width:${cw[c.key]}%;background:${cssColor(c.key)}" data-l="${c.label}: ${fmtP(cw[c.key])}"></span>`).join("");
  sel("stack").querySelectorAll("span").forEach(el => { el.onmousemove = e => showTip(e, el.dataset.l); el.onmouseleave = hideTip; });
  sel("legend").innerHTML = CLASSES.map(c => `<span><i style="background:${cssColor(c.key)}"></i>${c.label} <span class="mono">${fmtP(cw[c.key]||0)}</span></span>`).join("");
  sel("alloc").innerHTML = CLASSES.map(c => { const d = (cw[c.key]||0) - (ref[c.key]||0); return `<tr><td><span class="dot" style="background:${cssColor(c.key)}"></span>${c.label}</td><td class="num">${fmtP(cw[c.key]||0)}</td><td class="num">${fmtP(ref[c.key]||0)}</td><td class="num ${Math.abs(d)>5?"neg":""}">${(d>=0?"+":"")+d.toFixed(1)} pp</td><td class="num">${fmtM((cw[c.key]||0)/100*bal)}</td></tr>`; }).join("");
  const refG = CLASSES.filter(c => c.kind==="growth").reduce((s,c) => s + (ref[c.key]||0), 0);
  sel("allocnote").textContent = `The ${label(DATA.profiles, state.ref)} long-run target is ${refG.toFixed(0)}% growth assets; yours is ${fmtP(m.growth_pct,0)}. Differences over 5 points are marked.`;
  renderDiversification(pf); renderBacktest(pf); renderRisk(pf);
  sel("savenote").textContent = state.readOnly ? "Read-only shared portfolio. Sign in and use \"Save as a copy\" to make it yours." : state.id ? (state.dirty ? "Unsaved changes" : "Saved") : (state.lines.length ? "Not saved yet" : "");
  try { if (!state.readOnly) localStorage.setItem("mpl-builder-draft", JSON.stringify({ name: state.name, balance: state.balance, ref: state.ref, lines: state.lines, id: state.id, extra: EXTRA, research: Object.fromEntries(state.lines.filter(l => l.source === "live").map(l => [l.ticker, R[l.ticker]])) })); } catch(e) {}
}
function renderSheet(pf){
  const box = sel("sheet"); sel("holdings").querySelectorAll("tr.row").forEach(tr => tr.classList.toggle("active", tr.dataset.t===state.ticker));
  const l = pf.lines.find(x => x.ticker===state.ticker); if (!l) { box.hidden = true; box.innerHTML = ""; return; }
  const r = R[l.ticker] || {}; const col = cssColor(l.asset_class); const u = UMAP[l.ticker];
  const sentences = r.summary ? r.summary.split(". ") : []; const blurb = sentences.length ? sentences.slice(0,4).join(". ") + (sentences.length>4 ? "." : "") : (l.source === "live" ? "Added live from the price feed: no written description or analyst view until the daily build researches it." : "No description available from the data feed.");
  const ccy = r.price_currency && r.price_currency!=="AUD" ? ` (${r.price_currency})` : "";
  box.hidden = false; box.innerHTML = `<div class="sheet-head"><h3>${esc(l.name)} <span class="mono" style="font-weight:400;color:var(--faint);font-size:14px">${esc(l.ticker)}</span></h3>
      <div><span class="dot" style="background:${col}"></span>${label(CLASSES, l.asset_class)} · ${esc(l.sector||"")} · ${esc(l.region||"")} · ${fmtP(l.weight_pct,1)} (${fmtM(l.dollars)})</div></div>
    <div class="sheet-grid"><div>${DATA.quality[l.ticker] ? `<div class="note" style="background:var(--accent-soft);color:var(--text)"><b>Reviewed verdict: ${DATA.quality[l.ticker].verdict}.</b> ${esc(DATA.quality[l.ticker].note)} <span class="muted">(${DATA.quality[l.ticker].reviewed}; opinion, not advice)</span></div>` : ""}
      <p class="summary">${esc(blurb)}</p>${r.sparkline && r.sparkline.length ? `<div class="eyebrow">Last 12 months, dividends reinvested, rebased to 100</div>${spark(r.sparkline, col, 600, 120, true)}` : ""}</div>
      <dl class="kv"><dt>Analyst view</dt><dd>${consensusChip(r)}</dd><dt>1 year return</dt><dd>${fmtS(r.return_1y_pct)}</dd><dt>3 years, per year</dt><dd>${fmtS(r.return_3y_pct_pa)}</dd><dt>5 years, per year</dt><dd>${fmtS(r.return_5y_pct_pa)}</dd><dt>10 years, per year</dt><dd>${fmtS(r.return_10y_pct_pa)}</dd>
      ${r.history_years != null ? `<dt>History available</dt><dd>${r.history_years} years</dd>` : ""}<dt>Volatility (1y)</dt><dd>${fmtP(r.volatility_1y_pct)}</dd><dt>Worst fall in the last year</dt><dd>${fmtP(r.max_drawdown_1y_pct)}</dd>
      <dt>Dividend yield</dt><dd>${fmtP(l.yield_pct,2)}</dd><dt>Franking (estimate)</dt><dd>${fmtP(l.franking_pct,0)}</dd><dt>Management cost</dt><dd>${fmtP(l.mer_pct,2)}</dd>
      ${r.market_cap!=null ? `<dt>${r.quote_type==="ETF"?"Fund size":"Market cap"}${ccy}</dt><dd>${r.market_cap >= 1e9 ? "$" + (r.market_cap/1e9).toFixed(1) + " bn" : fmtM(r.market_cap)}</dd>` : ""}
      <dt>Beta to ASX 200 (1y)</dt><dd>${(pf.metrics.holding_beta_asx200||{})[l.ticker] != null ? pf.metrics.holding_beta_asx200[l.ticker].toFixed(2) : "–"}</dd>
      <dt>Documents</dt><dd style="font-family:inherit">${docLink(l.ticker)}</dd><dt>Data</dt><dd style="font-family:inherit;color:var(--faint)">${esc(r.source||l.priced_from)}${r.fetched?" · "+r.fetched:""}</dd></dl></div>`;
}
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
  const lines = [["This portfolio", bt.values, "var(--accent)", 2.4], ["Australian shares (VAS)", asx, cssColor("aus_equity"), 1.3], ["World shares (VGS)", world, cssColor("intl_equity"), 1.3], ["Cash ETF", cash, cssColor("cash"), 1.3]].filter(x => x[1]);
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
    ["Correlation between holdings", apc == null ? "–" : apc.toFixed(2), apc == null ? "" : apc > 0.5 ? "the holdings tend to rise and fall together" : apc > 0.25 ? "moderately related; some genuine diversification" : "largely independent of each other"],
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
  let html = uni.map(u => { const r = R[u.ticker] || {}; return row(u.ticker, u.name, `${label(CLASSES, u.asset_class)} · ${esc(u.sector)} · ${esc(u.region)} · ${u.vehicle}${u.status === "watchlist" ? " · watchlist" : ""} · yield ${fmtP(r.dividend_yield_pct != null ? r.dividend_yield_pct : u.yield,1)} · cost ${fmtP(u.mer,2)} · 1y ${fmtS(r.return_1y_pct)} · 5y ${fmtS(r.return_5y_pct_pa)} ${qualityChip(u.ticker)} ${consensusChip(r)}`, u.asset_class); }).join("");
  if (ext.length) html += `<div class="result" style="background:var(--surface-2)"><div class="d">Outside the engine's universe: fetched live when added</div></div>` + ext.map(x => row(x.symbol, x.name, `${esc(x.exchange)} · ${esc(x.type)}${x.sector ? " · " + esc(x.sector) : ""}`, guessClass(x.symbol, x.name, x.sector), x)).join("");
  if (!uni.length && !ext.length && q.length >= 2) html += `<div class="result"><div class="d">No match in the index. <button type="button" class="btn small" id="btn-yahoo">Search the price feed for "${esc(q)}"</button></div></div>`;
  sel("results").innerHTML = html ? `<div class="results">${html}</div>` : "";
  sel("results").querySelectorAll("button[data-add]").forEach(b => b.onclick = () => addSymbol(b.dataset.add, b.dataset.cls, { type: b.dataset.type, sector: b.dataset.sector }));
  const y = sel("btn-yahoo"); if (y) y.onclick = async () => { try { const d = await api("/search?q=" + encodeURIComponent(q)); const rs = d.results || []; if (!rs.length) { toast("Nothing found on the price feed"); return; }
      sel("results").innerHTML = `<div class="results">` + rs.map(x => row(x.symbol, x.name, `${esc(x.exchange)} · ${esc(x.type)}`, guessClass(x.symbol, x.name, ""), x)).join("") + `</div>`;
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
sel("btn-rules").onclick = () => {
  // Engine-style weights: within each class, spread by weight hint, cap single companies, then scale classes to the reference target.
  const ref = DATA.saa[state.ref] || {}; const rules = DATA.diversification || {}; const byClass = {};
  state.lines.forEach(l => (byClass[l.asset_class] = byClass[l.asset_class] || []).push(l));
  const present = Object.keys(byClass); const refTot = present.reduce((s,c) => s + (ref[c]||0), 0) || 1;
  for (const c of present) { const ls = byClass[c]; const cwt = (ref[c]||0) / refTot * 100; const hints = ls.map(l => { const u = UMAP[l.ticker]; return u ? Math.max(0.5, +u.weight_hint || 2) : 2; }); const hs = hints.reduce((s,h) => s + h, 0);
    let w = hints.map(h => h / hs * cwt); const cap = ls.map(l => l.vehicle === "direct" ? Math.min(UMAP[l.ticker] ? +UMAP[l.ticker].max_weight || 6 : 6, rules.max_single_holding_pct || 10) : 100);
    for (let k = 0; k < 10; k++) { let ex = 0; const room = []; w.forEach((x, i) => { if (x > cap[i]) { ex += x - cap[i]; w[i] = cap[i]; } else room.push(i); }); if (ex < 1e-6 || !room.length) break; const rs = room.reduce((s,i) => s + w[i], 0) || 1; room.forEach(i => w[i] += ex * w[i] / rs); }
    ls.forEach((l, i) => l.weight_pct = +w[i].toFixed(2)); }
  const t = state.lines.reduce((s,l) => s + l.weight_pct, 0); if (t > 0) state.lines.forEach(l => l.weight_pct = +(l.weight_pct / t * 100).toFixed(2)); state.dirty = true; render(); toast("Weighted the way the engine would for the " + label(DATA.profiles, state.ref).toLowerCase() + " target"); };
sel("pname").oninput = () => { state.name = sel("pname").value; state.dirty = true; sel("ptitle").textContent = state.name || "A new portfolio"; };
sel("pbal").onchange = () => { const b = parseBalance(sel("pbal").value); if (!b) { toast("Enter a balance of at least $1,000"); return; } state.balance = b; sel("pbal").value = b.toLocaleString("en-AU"); state.dirty = true; render(); };
sel("pref").innerHTML = DATA.profiles.map(p => `<option value="${p.key}">${p.label} (${p.sub})</option>`).join(""); sel("pref").value = state.ref;
sel("pref").onchange = () => { state.ref = sel("pref").value; render(); };
sel("pstart").innerHTML += DATA.models.map(mo => `<option value="${mo.id}">${mo.label}</option>`).join("");
sel("pstart").onchange = () => { const mo = DATA.models.find(x => x.id === sel("pstart").value); if (!mo) return;
  if (state.lines.length && !confirm("Replace the current holdings with this model portfolio?")) { sel("pstart").value = ""; return; }
  state.lines = mo.lines.map(x => { const u = UMAP[x.ticker]; const l = u ? lineFromUniverse(u) : null; if (!l) return null; l.weight_pct = +x.weight_pct.toFixed(2); return l; }).filter(Boolean);
  state.ref = mo.profile; sel("pref").value = mo.profile; if (!state.name) { state.name = mo.label; sel("pname").value = state.name; } state.dirty = true; state.readOnly = false; sel("pstart").value = ""; render(); toast("Loaded " + mo.label + ". Change anything you like."); };
sel("btn-new").onclick = () => { if (state.lines.length && state.dirty && !confirm("Discard the current portfolio?")) return; Object.assign(state, { id: null, name: "", lines: [], isPublic: false, readOnly: false, ownerId: null, ticker: null, dirty: false }); sel("pname").value = ""; sel("readonly").hidden = true; history.replaceState(null, "", location.pathname); render(); };
sel("btn-print").onclick = () => window.print();
sel("btn-xlsx").onclick = () => { if (typeof XLSX === "undefined") { toast("The spreadsheet library did not load"); return; } const pf = compute(); const m = pf.metrics; const wb = XLSX.utils.book_new();
  const summary = [["Model Portfolio Lab: your portfolio", state.name||""], ["Balance", pf.balance], ["Prices as of", DATA.as_of], ["Growth %", m.growth_pct/100], ["Defensive %", m.defensive_pct/100], ["Holdings", m.holdings], ["Weighted MER", m.weighted_mer_pct/100], ["Investment fees p.a.", m.investment_fees_per_year], ["Platform menu", menuLabel(m.platform_menu)], ["Platform fee p.a.", m.platform_admin_fee_per_year], ["Total ongoing cost %", m.total_ongoing_cost_pct/100], ["Cash yield", m.weighted_yield_pct/100], ["Income p.a.", m.income_per_year], ["Franking credits p.a.", m.franking_credits_per_year], ["Grossed-up yield", m.grossed_up_yield_pct/100],
    ["Weighted 3y return p.a.", m.weighted_return_3y_pct/100], ["Weighted 5y return p.a.", m.weighted_return_5y_pct/100], ["Weighted 10y return p.a.", m.weighted_return_10y_pct/100], ["Realised volatility (1y)", (m.realised_volatility_pct||0)/100], ["Trailing 1y return", (m.trailing_1y_return_pct||0)/100], ["Beta to ASX 200", m.beta_asx200 ?? ""], ["Beta to world shares", m.beta_world ?? ""], ["Average correlation between holdings", m.avg_pairwise_correlation ?? ""], ["Diversification ratio", m.diversification_ratio ?? ""], ["", ""], ["Illustrative only; not financial advice. Returns are history, not forecasts.", ""]];
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(summary), "Summary");
  const hold = [["Ticker", "Holding", "Asset class", "Vehicle", "Sector", "Region", "Weight", "Dollars", "Units", "Price (AUD)", "MER", "Yield", "Franking", "Income p.a.", "1y", "3y pa", "5y pa", "10y pa", "Analyst view", "Verdict", "Source"]].concat(pf.lines.map(l => { const r = R[l.ticker]||{}; const q = DATA.quality[l.ticker]||{}; return [l.ticker, l.name, label(CLASSES, l.asset_class), l.vehicle, l.sector, l.region, (l.weight_pct||0)/100, l.dollars, l.units, l.price_aud, (l.mer_pct||0)/100, (l.yield_pct||0)/100, (l.franking_pct||0)/100, (l.dollars||0)*(l.yield_pct||0)/100, r.return_1y_pct==null?null:r.return_1y_pct/100, r.return_3y_pct_pa==null?null:r.return_3y_pct_pa/100, r.return_5y_pct_pa==null?null:r.return_5y_pct_pa/100, r.return_10y_pct_pa==null?null:r.return_10y_pct_pa/100, r.consensus_label||"", q.verdict||"", l.source]; }));
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(hold), "Holdings");
  XLSX.writeFile(wb, `my_portfolio_${(state.name||"portfolio").replace(/[^a-z0-9]+/gi, "_").toLowerCase()}.xlsx`); };

// ------------------------------------------------------------ accounts (Supabase)
const SB = (DATA.supabase && DATA.supabase.url && DATA.supabase.key && window.supabase) ? window.supabase.createClient(DATA.supabase.url, DATA.supabase.key) : null;
function serialise(){ return { version: 1, name: state.name, balance: state.balance, ref: state.ref, lines: state.lines.map(l => ({...l})), extra: Object.fromEntries(state.lines.filter(l => EXTRA[l.ticker]).map(l => [l.ticker, EXTRA[l.ticker]])), research: Object.fromEntries(state.lines.filter(l => l.source === "live" && R[l.ticker]).map(l => [l.ticker, R[l.ticker]])), saved_as_of: DATA.as_of }; }
function hydrate(d, { readOnly=false, id=null, ownerId=null, isPublic=false } = {}){
  Object.assign(EXTRA, d.extra || {}); Object.assign(R, d.research || {});
  state.lines = (d.lines || []).map(l => { const u = UMAP[l.ticker]; if (u && l.source !== "live") { const f = lineFromUniverse(u); f.weight_pct = l.weight_pct; f.asset_class = l.asset_class || f.asset_class; return f; } return {...l}; });
  state.name = d.name || ""; state.balance = d.balance || 250000; state.ref = d.ref || "balanced"; state.id = id; state.readOnly = readOnly; state.ownerId = ownerId; state.isPublic = isPublic; state.dirty = false; state.ticker = null;
  sel("pname").value = state.name; sel("pbal").value = state.balance.toLocaleString("en-AU"); sel("pref").value = state.ref;
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
  sel("au-foot").innerHTML = m === "signin" ? `<button type="button" data-go="forgot">Forgotten your password?</button> · No account yet? <button type="button" data-go="signup">Create one</button>`
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
  const a = sel("acct");
  if (!SB) { a.innerHTML = `<span class="muted">Accounts are not set up on this copy of the page, so portfolios stay in this browser only (kept as a draft until you clear your browsing data).</span>`; sel("mine").innerHTML = ""; return; }
  const s = user.session;
  if (!s) { a.innerHTML = `<button class="btn primary" id="btn-open-signin" type="button">Sign in</button><button class="btn" id="btn-open-signup" type="button">Create account</button><span class="muted">Sign in to save portfolios, reopen them on any device and share them. Experimenting below needs no account.</span>`;
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
  sel("mine").innerHTML = data.map(p => `<div class="pend"><span><b>${esc(p.name || "Untitled")}</b> <span class="mono" style="color:var(--faint);font-size:12px">${(p.data && p.data.lines ? p.data.lines.length : 0)} holdings · ${fmtM(p.data && p.data.balance)} · ${new Date(p.updated_at).toLocaleDateString("en-AU")}${p.is_public ? " · shared" : ""}</span></span><button class="btn small" data-open="${p.id}" type="button">Open</button><button class="btn small" data-dup="${p.id}" type="button">Duplicate</button><button class="btn small danger" data-del="${p.id}" type="button">Delete</button></div>`).join("");
  sel("mine").querySelectorAll("button[data-open]").forEach(b => b.onclick = () => { const p = data.find(x => x.id === b.dataset.open); if (state.dirty && state.lines.length && !confirm("Discard unsaved changes?")) return; hydrate(p.data, { id: p.id, ownerId: user.session.user.id, isPublic: p.is_public }); history.replaceState(null, "", "?p=" + p.id); toast("Opened " + (p.name || "portfolio")); });
  sel("mine").querySelectorAll("button[data-dup]").forEach(b => b.onclick = async () => { const p = data.find(x => x.id === b.dataset.dup); const { error } = await SB.from("portfolios").insert({ user_id: user.session.user.id, name: (p.name || "Untitled") + " (copy)", data: p.data, is_public: false }); toast(error ? error.message : "Duplicated"); listMine(); });
  sel("mine").querySelectorAll("button[data-del]").forEach(b => b.onclick = async () => { if (!confirm("Delete this portfolio? This cannot be undone.")) return; const { error } = await SB.from("portfolios").delete().eq("id", b.dataset.del); if (error) { toast(error.message); return; } if (state.id === b.dataset.del) { state.id = null; history.replaceState(null, "", location.pathname); } toast("Deleted"); listMine(); render(); });
}
async function save(asCopy){
  if (!SB) { toast("Accounts are not set up yet; your draft stays in this browser"); return; }
  if (!user.session) { toast("Sign in or create an account to save"); openAuth("signin"); return; }
  if (!state.lines.length) { toast("Add some holdings first"); return; }
  if (!state.name) { state.name = prompt("Name this portfolio", "My portfolio") || ""; if (!state.name) return; sel("pname").value = state.name; }
  const payload = { user_id: user.session.user.id, name: state.name, data: serialise(), updated_at: new Date().toISOString() };
  const own = state.id && state.ownerId === user.session.user.id && !state.readOnly;
  let res;
  if (own && !asCopy) res = await SB.from("portfolios").update(payload).eq("id", state.id).select("id,is_public").single();
  else res = await SB.from("portfolios").insert({ ...payload, name: asCopy && own ? state.name + " (copy)" : state.name, is_public: false }).select("id,is_public").single();
  if (res.error) { toast("Not saved: " + res.error.message); return; }
  state.id = res.data.id; state.ownerId = user.session.user.id; state.readOnly = false; state.isPublic = res.data.is_public; state.dirty = false; sel("readonly").hidden = true;
  history.replaceState(null, "", "?p=" + state.id); toast("Saved"); listMine(); render();
}
sel("btn-save").onclick = () => save(false);
sel("btn-saveas").onclick = () => { if (state.name && !state.name.endsWith("(copy)")) { /* keep name; insert as new */ } save(true); };
sel("btn-share").onclick = async () => {
  if (SB && !user.session) { openAuth("signin"); return; }
  if (!SB || !state.id || state.ownerId !== user.session.user.id) { toast("Save the portfolio to your account first"); return; }
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
  if (shared && await openShared(shared)) return;
  try { const d = JSON.parse(localStorage.getItem("mpl-builder-draft") || "null"); if (d && d.lines && d.lines.length) { hydrate(d, { id: d.id || null }); state.dirty = !!d.id; toast("Restored your last draft from this browser"); return; } } catch(e) {}
  render();
})();
</script>
</body>
</html>
"""


def _css() -> str:
    m = re.search(r"<style>(.*?)</style>", dash.TEMPLATE, re.S)
    return m.group(1) if m else ""


def write_builder(path: Path, portfolios: list[Portfolio], profiles: Profiles, md: MarketData, universe: pd.DataFrame,
                  research: dict | None, prices: dict[str, float], *, settings_site_url: str = "", quality: dict | None = None,
                  platform_cfg: dict | None = None, pds: dict | None = None, history: dict | None = None, esg: dict | None = None,
                  supabase: dict | None = None, as_of: str = "") -> Path:
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
                              "status": r.get("status", "active"), "price_aud": prices.get(r["ticker"]), "max_weight": float(r["max_weight"]), "weight_hint": float(r["weight_hint"])})
    tiers = sorted(profiles.balance_tiers.items(), key=lambda kv: kv[1]["order"])

    def split(lbl: str) -> tuple[str, str]:
        return (lbl.split(" (")[0], lbl.split(" (")[1].rstrip(")")) if " (" in lbl else (lbl, "")

    stage_label = {k: split(v["label"])[0] for k, v in profiles.life_stages.items()}
    tier_label = {k: split(v["label"])[0] for k, v in profiles.balance_tiers.items()}
    models, seen = [], set()
    for pf in sorted(portfolios, key=lambda p: (profiles.profile_order(p.profile_used), profiles.life_stages[p.life_stage]["order"], profiles.tier_order(p.tier))):
        if pf.implementation != "direct" or (pf.esg or {}).get("screened") or pf.id in seen:
            continue
        seen.add(pf.id)
        models.append({"id": pf.id, "profile": pf.profile_used, "balance": pf.balance,
                       "label": f"{profiles.risk_profiles[pf.profile_used]['label']} · {stage_label[pf.life_stage]} · {tier_label[pf.tier]}",
                       "lines": [{"ticker": l.ticker, "weight_pct": round(l.weight_pct, 3)} for l in pf.lines]})
    growth = profiles.growth_classes
    data = {
        "meta": f"Built {datetime.now():%d %B %Y %H:%M}. Prices as of {md.as_of.date()}; AUD/USD {1 / md.fx_aud_per_usd:.4f}. Rebuilt automatically each weekday evening.",
        "banner": "SYNTHETIC DATA: this page was built in offline test mode. Every number is a placeholder." if md.synthetic else "",
        "as_of": as_of or str(md.as_of.date()),
        "classes": classes, "colors": colors,
        "profiles": [{"key": k, "label": v["label"], "sub": f"{sum(v['saa'][c] for c in growth):.0f}% growth"} for k, v in sorted(profiles.risk_profiles.items(), key=lambda kv: kv[1]["order"])],
        "saa": {k: {c: float(w) for c, w in v["saa"].items()} for k, v in profiles.risk_profiles.items()},
        "tiers": [{"key": k, "label": split(v["label"])[0], "min_balance": v["min_balance"], "max_holdings": v["max_holdings"], "min_holding": v["min_holding_dollars"], "brokerage": v["brokerage_dollars"]} for k, v in tiers],
        "platform": platform_cfg or {}, "pds": pds or {}, "quality": quality or {},
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
    path.write_text(html, encoding="utf-8")
    return path
