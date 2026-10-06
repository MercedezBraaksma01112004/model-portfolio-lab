import { yfetch, json } from "./_yahoo.mjs";
import { nasdaqHistory, isUsSymbol } from "./_nasdaq.mjs";
// GET /.netlify/functions/history?symbol=BHP.AX
// Everything the builder page needs to treat a holding it has never seen like one from the engine's universe:
// name, currency, latest price, trailing dividend yield, ten years of month-end total returns (dividends
// reinvested) converted to AUD, and the last year of daily returns in the holding's own currency.
const FX = { USD: "AUDUSD=X", EUR: "EURAUD=X", CAD: "CADAUD=X", GBP: "GBPAUD=X", NZD: "NZDAUD=X", CHF: "CHFAUD=X", JPY: "JPYAUD=X", HKD: "HKDAUD=X", SGD: "SGDAUD=X", TWD: "TWDAUD=X" };
const chart = (s, range, interval) => yfetch(`https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(s)}?range=${range}&interval=${interval}&events=div`);
const closes = r => (r.indicators?.adjclose?.[0]?.adjclose || r.indicators?.quote?.[0]?.close || []);
const monthKey = ts => { const d = new Date(ts * 1000); return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`; };

async function fxSeries(currency, range, interval) {
  const t = FX[currency];
  if (!t) return null;
  const r = (await chart(t, range, interval)).chart?.result?.[0];
  if (!r) return null;
  const map = {};
  closes(r).forEach((v, i) => { if (v != null) map[interval === "1mo" ? monthKey(r.timestamp[i]) : r.timestamp[i]] = v; });
  return { map, invert: t.startsWith("AUD") };   // AUDUSD=X is USD per AUD; the others are AUD per unit
}

export default async (req) => {
  const s = new URL(req.url).searchParams.get("symbol")?.trim().toUpperCase();
  if (!s) return json({ error: "symbol required" }, 400);
  let yahooError = "";
  try { return await fromYahoo(s); } catch (e) { yahooError = String(e.message || e); }
  // Yahoo refuses data-centre addresses at times. United States listings fall back to Nasdaq; anything else is left for the
  // cloud build, which can reach Yahoo (the page queues it through the fetchq function).
  if (isUsSymbol(s)) {
    try { return json(await nasdaqHistory(s, new URL(req.url).origin), 200, 3600); } catch (e) { yahooError += `; Nasdaq: ${e.message || e}`; }
  }
  return json({ error: yahooError || "no data", queue: true }, 502);
};

async function fromYahoo(s) {
  {
    const [m, d] = await Promise.all([chart(s, "10y", "1mo"), chart(s, "1y", "1d")]);
    const rm = m.chart?.result?.[0], rd = d.chart?.result?.[0];
    if (!rm || !rd) throw new Error("no data");
    const meta = rd.meta || rm.meta || {};
    const currency = (meta.currency || "AUD").toUpperCase();
    // Month-end closes, AUD converted (the engine does the same for its own history)
    const mc = closes(rm), mt = rm.timestamp || [];
    const fx = currency === "AUD" ? null : await fxSeries(currency, "10y", "1mo");
    const months = [], levels = [];
    for (let i = 0; i < mc.length; i++) {
      if (mc[i] == null) continue;
      const k = monthKey(mt[i]);
      let v = mc[i];
      if (fx) { const f = fx.map[k]; if (f == null) continue; v = fx.invert ? v / f : v * f; }
      if (months.length && months[months.length - 1] === k) { levels[levels.length - 1] = v; continue; }
      months.push(k); levels.push(v);
    }
    const monthly = []; for (let i = 1; i < levels.length; i++) monthly.push(+(levels[i] / levels[i - 1] - 1).toFixed(5));
    const mmonths = months.slice(1);
    const ann = (n) => levels.length > n ? +((Math.pow(levels[levels.length - 1] / levels[levels.length - 1 - n], 12 / n) - 1) * 100).toFixed(2) : null;
    // Daily returns in native currency, last year
    const dc = closes(rd), dt = rd.timestamp || [];
    const dates = [], daily = []; let prev = null;
    for (let i = 0; i < dc.length; i++) { if (dc[i] == null) continue; if (prev != null) { dates.push(new Date(dt[i] * 1000).toISOString().slice(0, 10)); daily.push(+(dc[i] / prev - 1).toFixed(5)); } prev = dc[i]; }
    const raw = (rd.indicators?.quote?.[0]?.close || []).filter(v => v != null);
    const last = meta.regularMarketPrice ?? raw[raw.length - 1];
    const divs = Object.values(rd.events?.dividends || {}).reduce((t, x) => t + (x.amount || 0), 0);
    const vol = daily.length > 20 ? +(Math.sqrt(daily.reduce((s, r) => s + r * r, 0) / daily.length - Math.pow(daily.reduce((s, r) => s + r, 0) / daily.length, 2)) * Math.sqrt(252) * 100).toFixed(2) : null;
    let peak = -Infinity, mdd = 0, lvl = 1; for (const r of daily) { lvl *= 1 + r; peak = Math.max(peak, lvl); mdd = Math.min(mdd, lvl / peak - 1); }
    const first = dc.find(v => v != null), lastAdj = [...dc].reverse().find(v => v != null);
    return json({
      symbol: s, name: meta.longName || meta.shortName || s, currency, price: last, exchange: meta.exchangeName, type: meta.instrumentType,
      yield_pct: last && divs ? +((divs / last) * 100).toFixed(2) : 0,
      return_1y_pct: first && lastAdj ? +((lastAdj / first - 1) * 100).toFixed(2) : null,
      return_3y_pct_pa: ann(36), return_5y_pct_pa: ann(60), return_10y_pct_pa: ann(120), history_years: +(levels.length / 12).toFixed(1),
      volatility_1y_pct: vol, max_drawdown_1y_pct: +(mdd * 100).toFixed(2),
      spark: dc.filter((v, i) => v != null && i % Math.max(1, Math.floor(dc.length / 60)) === 0).map(v => +(v / first * 100).toFixed(2)),
      monthly: { months: mmonths, returns: monthly }, daily: { dates, returns: daily },
    }, 200, 3600);
  }
}
