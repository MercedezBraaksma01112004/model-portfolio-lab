// Nasdaq's public quote API: the fallback for United States listings when Yahoo Finance refuses the site's servers.
// Prices are daily closes; dividends come from the dividend history, so total returns are rebuilt by reinvesting each
// dividend on its ex-date. Monthly returns are converted to Australian dollars with the month-end exchange rates the
// daily build publishes at /data/fx_monthly.json.
const H = { "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
  "Accept": "application/json, text/plain, */*", "Accept-Language": "en-AU,en;q=0.9", "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/" };
const money = v => { const n = parseFloat(String(v ?? "").replace(/[$,]/g, "")); return isFinite(n) ? n : null; };
const usDate = s => { const m = String(s || "").match(/^(\d{2})\/(\d{2})\/(\d{4})$/); return m ? `${m[3]}-${m[1]}-${m[2]}` : null; };

async function get(path) {
  const r = await fetch("https://api.nasdaq.com/api/" + path, { headers: H });
  if (!r.ok) throw new Error(`Nasdaq returned ${r.status}`);
  const j = await r.json();
  if (!j || !j.data) throw new Error("Nasdaq has no data");
  return j.data;
}

export const isUsSymbol = s => /^[A-Z]{1,5}([.-][A-Z])?$/.test(s) && !/\.(AX|XA|L|TO|V|PA|MI|DE|AS|MC|BR|SW|NZ|HK|T|SI|TW|ST|CO|OL|HE|LS|VI|KS|F)$/.test(s);

export async function nasdaqSearch(q) {
  const d = await get(`autocomplete/slookup/10?search=${encodeURIComponent(q)}`);
  return (Array.isArray(d) ? d : []).filter(x => x.symbol && ["STOCKS", "ETF"].includes(String(x.asset || "").toUpperCase()))
    .map(x => ({ symbol: x.symbol.replace("/", "-"), name: x.name, exchange: x.exchange || "US", type: String(x.asset).toUpperCase() === "ETF" ? "ETF" : "EQUITY" }));
}

// Daily closes (ascending), dividends by ex-date, name and type for one US symbol.
export async function nasdaqSeries(sym) {
  let last = null;
  for (const ac of ["stocks", "etf"]) {
    try {
      const info = await get(`quote/${encodeURIComponent(sym)}/info?assetclass=${ac}`);
      if (!info.companyName) continue;
      const to = new Date(), from = new Date(Date.now() - 10.4 * 365.25 * 86400e3);
      const h = await get(`quote/${encodeURIComponent(sym)}/historical?assetclass=${ac}&fromdate=${from.toISOString().slice(0, 10)}&todate=${to.toISOString().slice(0, 10)}&limit=9999`);
      const rows = ((h.tradesTable || {}).rows || []).map(r => ({ d: usDate(r.date), c: money(r.close) })).filter(r => r.d && r.c != null).reverse();
      if (rows.length < 30) throw new Error("too little history");
      const divs = {};
      try { const dv = await get(`quote/${encodeURIComponent(sym)}/dividends?assetclass=${ac}`);
        for (const r of ((dv.dividends || {}).rows || [])) { const d = usDate(r.exOrEffDate), a = money(r.amount); if (d && a) divs[d] = (divs[d] || 0) + a; } } catch { /* no dividends */ }
      return { name: info.companyName.replace(/ (Common Stock|Class [A-Z] Common Stock|Ordinary Shares)$/i, ""), type: ac === "etf" ? "ETF" : "EQUITY", exchange: info.exchange || "US", currency: "USD", rows, divs };
    } catch (e) { last = e; }
  }
  throw last || new Error("Nasdaq has no history for " + sym);
}

// The same shape history.mjs returns from Yahoo: AUD monthly total returns, native daily returns, trailing figures.
export async function nasdaqHistory(sym, origin) {
  const s = await nasdaqSeries(sym);
  // Total-return index: each dividend reinvested on its ex-date.
  const lvl = [1]; for (let i = 1; i < s.rows.length; i++) lvl.push(lvl[i - 1] * (s.rows[i].c + (s.divs[s.rows[i].d] || 0)) / s.rows[i - 1].c);
  const monthEnd = {}; s.rows.forEach((r, i) => { monthEnd[r.d.slice(0, 7)] = lvl[i]; });
  let fx = null; try { const r = await fetch(origin + "/data/fx_monthly.json"); if (r.ok) fx = (await r.json()).aud_per || null; } catch { /* no conversion available */ }
  const usd = fx && fx.USD ? fx.USD : null;
  const months = Object.keys(monthEnd).sort().filter(m => !usd || usd[m] != null);
  const levels = months.map(m => usd ? monthEnd[m] * usd[m] : monthEnd[m]);
  const monthly = []; for (let i = 1; i < levels.length; i++) monthly.push(+(levels[i] / levels[i - 1] - 1).toFixed(5));
  const ann = n => levels.length > n ? +((Math.pow(levels[levels.length - 1] / levels[levels.length - 1 - n], 12 / n) - 1) * 100).toFixed(2) : null;
  const yr = s.rows.slice(-253), yl = lvl.slice(-253);
  const daily = [], dates = []; for (let i = 1; i < yr.length; i++) { dates.push(yr[i].d); daily.push(+(yl[i] / yl[i - 1] - 1).toFixed(5)); }
  const vol = daily.length > 20 ? +(Math.sqrt(daily.reduce((a, r) => a + r * r, 0) / daily.length - Math.pow(daily.reduce((a, r) => a + r, 0) / daily.length, 2)) * Math.sqrt(252) * 100).toFixed(2) : null;
  let peak = -Infinity, mdd = 0, v = 1; for (const r of daily) { v *= 1 + r; peak = Math.max(peak, v); mdd = Math.min(mdd, v / peak - 1); }
  const price = s.rows[s.rows.length - 1].c;
  const yearAgo = new Date(Date.now() - 365.25 * 86400e3).toISOString().slice(0, 10);
  const divs12 = Object.entries(s.divs).filter(([d]) => d >= yearAgo).reduce((a, [, x]) => a + x, 0);
  return {
    symbol: sym, name: s.name, currency: "USD", price, exchange: s.exchange, type: s.type, yield_pct: price ? +(divs12 / price * 100).toFixed(2) : 0,
    return_1y_pct: yl.length > 1 ? +((yl[yl.length - 1] / yl[0] - 1) * 100).toFixed(2) : null,
    return_3y_pct_pa: ann(36), return_5y_pct_pa: ann(60), return_10y_pct_pa: ann(120), history_years: +(levels.length / 12).toFixed(1),
    volatility_1y_pct: vol, max_drawdown_1y_pct: +(mdd * 100).toFixed(2),
    spark: yr.filter((_, i) => i % Math.max(1, Math.floor(yr.length / 60)) === 0).map(r => +(r.c / yr[0].c * 100).toFixed(2)),
    monthly: { months: months.slice(1), returns: monthly }, daily: { dates, returns: daily },
    source: usd ? "Nasdaq (prices and dividends; monthly figures in AUD)" : "Nasdaq (prices and dividends; monthly figures in USD, no exchange rates available)",
  };
}
